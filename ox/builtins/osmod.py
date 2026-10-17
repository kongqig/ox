"""os — shell commands, environment, process & device info."""
import asyncio
import os
import platform as _pyplat
import shutil
import socket
import subprocess
import sys
import time as _time

from .. import __version__
from ..values import NativeModule, builtin, ox_str
from . import logmod

_SHELL_TIMEOUT_DEFAULT = None


def _timeout_secs(t):
    if t is None:
        return None
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return float(t)
    return None


async def sh_run(cmd, cwd=None, env=None, timeout=None, input=None):
    """Run a shell command; returns {ok, code, out, err, cmd}."""
    if not isinstance(cmd, str):
        raise TypeError("sh() expects a command string")
    merged = None
    if env:
        merged = dict(os.environ)
        for k, v in env.items():
            merged[ox_str(k)] = ox_str(v)

    def work():
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=cwd, env=merged, timeout=_timeout_secs(timeout),
                input=input)
            return {"ok": r.returncode == 0, "code": r.returncode,
                    "out": r.stdout, "err": r.stderr, "cmd": cmd}
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": -1, "out": "",
                    "err": "command timed out after %ss" % _timeout_secs(timeout),
                    "cmd": cmd}
        except FileNotFoundError as e:
            return {"ok": False, "code": 127, "out": "", "err": str(e), "cmd": cmd}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "code": -1, "out": "", "err": str(e), "cmd": cmd}

    return await asyncio.to_thread(work)


async def sh_ok(cmd, **kw):
    return (await sh_run(cmd, **kw))["ok"]


async def sh_lines(cmd, **kw):
    r = await sh_run(cmd, **kw)
    out = r["out"].rstrip("\n")
    return out.split("\n") if out else []


# ---- background processes --------------------------------------------------

_LIVE_PROCS = []

_SIG_TERM = 15
_SIG_KILL = 9
try:  # prefer named constants when the signal module is available
    import signal as _pysignal
    _SIG_TERM = _pysignal.SIGTERM
    _SIG_KILL = _pysignal.SIGKILL
except ImportError:  # pragma: no cover
    pass


def _killpg(pid, sig):
    """Signal a whole process group; fall back to the bare pid."""
    try:
        os.killpg(os.getpgid(pid), sig)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, OSError):
        pass


class ProcHandle:
    """Background process started via os.start().

    Fields: `pid`, `cmd`, `running`. Methods: `wait(timeout=null)`,
    `kill()`, `out()`, `err()`. Output is captured continuously, so
    `out()`/`err()` can be read while the process runs.

    The command runs in its own session, so kill() reliably takes down the
    whole process tree (shell + children), and terminal Ctrl+C is not
    forwarded — use kill() instead.
    """

    def __init__(self, proc, cmd, detach=False):
        self._proc = proc
        self._cmd = cmd
        self._detach = detach is True
        self._out = []
        self._err = []
        loop = asyncio.get_running_loop()
        self._pump_out = loop.create_task(self._pump(proc.stdout, self._out))
        self._pump_err = loop.create_task(self._pump(proc.stderr, self._err))
        _LIVE_PROCS.append(self)

    @property
    def cmd(self):
        return self._cmd

    @property
    def pid(self):
        return self._proc.pid

    @property
    def running(self):
        return self._proc.returncode is None

    def out(self):
        return "".join(self._out)

    def err(self):
        return "".join(self._err)

    async def _pump(self, stream, buf):
        if stream is None:
            return
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                return
            buf.append(chunk.decode("utf-8", "replace"))

    async def _wait_exit(self, secs):
        """Wait until returncode is set. Polls instead of awaiting
        proc.wait(), which can stall after the process was signalled."""
        if secs is not None:
            deadline = _time.monotonic() + secs
        while self._proc.returncode is None:
            if secs is not None and _time.monotonic() >= deadline:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.02)
        return self._proc.returncode

    def _close(self):
        """Close the subprocess transport so nothing warns at exit."""
        try:
            self._proc._transport.close()  # noqa: SLF001
        except Exception:  # noqa: BLE001 — best effort
            pass

    async def _drop_pipes(self):
        """Stop capturing output and close the pipes (process keeps running)."""
        tasks = [t for t in (self._pump_out, self._pump_err) if t and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._close()

    def _result(self, code, timed_out):
        return {"ok": code == 0 and not timed_out, "code": code,
                "out": self.out(), "err": self.err(), "cmd": self._cmd,
                "timed_out": timed_out}

    async def wait(self, timeout=None):
        """Wait for exit; returns {ok, code, out, err, cmd, timed_out}.
        On timeout the process keeps running and `timed_out` is true."""
        try:
            code = await self._wait_exit(None if timeout is None
                                         else _timeout_secs(timeout))
        except asyncio.TimeoutError:
            return self._result(-1, True)
        # flush output pumps (bounded: grandchildren may hold the pipes open)
        try:
            await asyncio.wait_for(
                asyncio.gather(self._pump_out, self._pump_err,
                               return_exceptions=True), timeout=2)
        except asyncio.TimeoutError:
            pass
        if not self.running:
            self._close()
        return self._result(code, False)

    async def kill(self):
        """Terminate the whole process group: TERM first, KILL after a
        grace period. Returns true."""
        if self._proc.returncode is None:
            _killpg(self._proc.pid, _SIG_TERM)
            try:
                await self._wait_exit(5)
            except asyncio.TimeoutError:
                _killpg(self._proc.pid, _SIG_KILL)
                try:
                    await self._wait_exit(2)
                except asyncio.TimeoutError:
                    pass
            try:
                await asyncio.wait_for(
                    asyncio.gather(self._pump_out, self._pump_err,
                                   return_exceptions=True), timeout=1)
            except asyncio.TimeoutError:
                pass
            self._close()
        return True

    def __repr__(self):
        state = "running" if self.running else "exited"
        return "<proc %s (%s, pid %s)>" % (self._cmd, state, self._proc.pid)


async def start(cmd, cwd=None, env=None, detach=False):
    """Start a background shell command; returns a ProcHandle.

    POSIX only: the child runs in its own process group so kill() reaches
    the whole tree. Unless `detach=true`, the process is terminated
    automatically when the script exits.
    """
    if os.name != "posix":
        raise OxThrow(OxErrorValue(
            "os.start requires POSIX process groups and is not supported "
            "on this platform (see docs: platform support)"))
    if not isinstance(cmd, str):
        raise TypeError("os.start() expects a command string")
    merged = None
    if env:
        merged = dict(os.environ)
        for k, v in env.items():
            merged[ox_str(k)] = ox_str(v)
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd, env=merged, start_new_session=True)
    return ProcHandle(proc, cmd, detach=detach)


async def kill_live_procs():
    """At program exit: terminate background procs started with os.start().
    Detached procs keep running, but their pipe handles are dropped cleanly."""
    victims = [h for h in _LIVE_PROCS if not h._detach and h.running]
    detached = [h for h in _LIVE_PROCS if h._detach]
    _LIVE_PROCS.clear()
    for h in victims:
        _killpg(h._proc.pid, _SIG_TERM)
    if victims:
        await asyncio.sleep(0.3)
        for h in victims:
            if h._proc.returncode is None:
                _killpg(h._proc.pid, _SIG_KILL)
        for h in victims:
            try:
                await h._wait_exit(1)
            except asyncio.TimeoutError:
                pass
            h._close()
    for h in detached:
        await h._drop_pipes()


def _args(interp):
    return list(interp.argv)


def _cwd():
    return os.getcwd()


def _chdir(path):
    os.chdir(path)


def _home():
    return os.path.expanduser("~")


def _hostname():
    return socket.gethostname()


def _user():
    return os.environ.get("USER") or os.environ.get("USERNAME") or ""


def _pid():
    return os.getpid()


def _platform():
    return {
        "system": _pyplat.system(),
        "release": _pyplat.release(),
        "version": _pyplat.version(),
        "machine": _pyplat.machine(),
        "python": sys.version.split()[0],
        "ox": __version__,
    }


def _cpu():
    load = None
    if hasattr(os, "getloadavg"):
        try:
            load = list(os.getloadavg())
        except OSError:
            load = None
    return {"count": os.cpu_count() or 1, "load": load}


def _mem():
    """Best-effort memory info (linux reads /proc/meminfo)."""
    try:
        info = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    info[parts[0]] = int(parts[1].strip().split()[0]) * 1024
        total = info.get("MemTotal")
        avail = info.get("MemAvailable", info.get("MemFree"))
        if total:
            return {"total": total, "available": avail,
                    "used": total - (avail or 0)}
    except (OSError, ValueError):
        pass
    return None


def _disk(path="."):
    try:
        u = shutil.disk_usage(path)
        return {"total": u.total, "free": u.free, "used": u.used}
    except OSError:
        return None


def _net_ifaces():
    names = []
    base = "/sys/class/net"
    if os.path.isdir(base):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            names = []
    out = []
    for n in names:
        out.append({"name": n})
    return out


def _local_ip():
    """The IP this machine would use to reach the internet (no packets sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def _which(cmd):
    return shutil.which(cmd)


def _device():
    return {
        "hostname": _hostname(),
        "platform": _platform(),
        "cpu": _cpu(),
        "mem": _mem(),
        "disk": _disk(),
        "ifaces": _net_ifaces(),
        "local_ip": _local_ip(),
    }


def _sleep_note():  # pragma: no cover
    logmod.log_info("tip: use the global sleep(2s) or co.sleep(2s)")


# ---- env module -------------------------------------------------------------

def _env_get(name, default=None):
    v = os.environ.get(name)
    return v if v is not None else default


def _env_set(name, value):
    os.environ[ox_str(name)] = ox_str(value)


def _env_has(name):
    return name in os.environ


def _env_del(name):
    os.environ.pop(name, None)


def _env_all():
    return dict(os.environ)


def build():
    return NativeModule("os", {
        "sh": builtin("sh")(sh_run),
        "sh_ok": builtin("sh_ok")(sh_ok),
        "sh_lines": builtin("sh_lines")(sh_lines),
        "exec": builtin("exec")(sh_run),
        "start": builtin("start")(start),
        "args": builtin("args", needs_interp=True)(_args),
        "cwd": builtin("cwd")(_cwd),
        "chdir": builtin("chdir")(_chdir),
        "home": builtin("home")(_home),
        "hostname": builtin("hostname")(_hostname),
        "user": builtin("user")(_user),
        "pid": builtin("pid")(_pid),
        "platform": builtin("platform")(_platform),
        "device": builtin("device")(_device),
        "cpu": builtin("cpu")(_cpu),
        "mem": builtin("mem")(_mem),
        "disk": builtin("disk")(_disk),
        "net_ifaces": builtin("net_ifaces")(_net_ifaces),
        "local_ip": builtin("local_ip")(_local_ip),
        "which": builtin("which")(_which),
    })


def build_env():
    return NativeModule("env", {
        "get": builtin("get")(_env_get),
        "set": builtin("set")(_env_set),
        "has": builtin("has")(_env_has),
        "del": builtin("del")(_env_del),
        "all": builtin("all")(_env_all),
    })
