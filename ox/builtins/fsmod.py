"""fs — files & directories: read/write/query/delete/move/copy/verify/watch,
plus zip/tar archives."""
import asyncio
import glob as _glob
import hashlib
import json as _json
import os
import shutil
import tarfile
import tempfile
import time as _time
import zipfile

from ..errors import OxThrow
from ..values import NativeModule, OxErrorValue, builtin, ox_str


def _p(path):
    return ox_str(path)


def read(path, encoding="utf-8"):
    with open(_p(path), encoding=encoding) as f:
        return f.read()


def read_bytes(path):
    with open(_p(path), "rb") as f:
        return f.read()


def read_lines(path, encoding="utf-8"):
    with open(_p(path), encoding=encoding) as f:
        return [line.rstrip("\n").rstrip("\r") for line in f]


def write(path, data, append=False):
    data = data if isinstance(data, str) else ox_str(data)
    mode = "a" if append else "w"
    with open(_p(path), mode, encoding="utf-8") as f:
        f.write(data)
    return len(data)


def write_bytes(path, data):
    with open(_p(path), "wb") as f:
        f.write(data)
    return len(data)


def append(path, data):
    return write(path, data, append=True)


def write_lines(path, lines):
    with open(_p(path), "w", encoding="utf-8") as f:
        for line in lines:
            f.write(ox_str(line) + "\n")
    return len(lines)


def exists(path):
    return os.path.exists(_p(path))


def is_file(path):
    return os.path.isfile(_p(path))


def is_dir(path):
    return os.path.isdir(_p(path))


def size(path):
    return os.path.getsize(_p(path))


def mtime(path):
    return os.path.getmtime(_p(path))


def empty(path):
    return size(_p(path)) == 0


def touch(path):
    p = _p(path)
    if os.path.exists(p):
        os.utime(p)
    else:
        open(p, "a").close()
    return True


def mkdir(path):
    os.mkdir(_p(path))
    return True


def mkdirs(path):
    os.makedirs(_p(path), exist_ok=True)
    return True


def list_dir(path="."):
    p = _p(path)
    try:
        names = sorted(os.listdir(p))
    except OSError:
        return []
    out = []
    for n in names:
        out.append({"name": n,
                    "type": "dir" if os.path.isdir(os.path.join(p, n)) else "file",
                    "size": os.path.getsize(os.path.join(p, n))
                    if os.path.isfile(os.path.join(p, n)) else 0})
    return out


def files(path="."):
    return [e["name"] for e in list_dir(path) if e["type"] == "file"]


def dirs(path="."):
    return [e["name"] for e in list_dir(path) if e["type"] == "dir"]


def walk(path=".", pattern=None):
    out = []
    for root, _dnames, fnames in os.walk(_p(path)):
        for f in fnames:
            out.append(os.path.join(root, f))
    if pattern:
        out = [f for f in out if _glob.fnmatch.fnmatch(os.path.basename(f),
                                                       pattern)]
    return sorted(out)


def glob(pattern, path=None):
    if path:
        pattern = os.path.join(_p(path), pattern)
    return sorted(_glob.glob(pattern))


def copy(src, dst):
    src, dst = _p(src), _p(dst)
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True


def copytree(src, dst):
    shutil.copytree(_p(src), _p(dst))
    return True


def move(src, dst):
    shutil.move(_p(src), _p(dst))
    return True


rename = move


def remove(path):
    p = _p(path)
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)
    return True


def delete(path):
    return remove(path)


def remove_tree(path):
    # rm -rf semantics: a missing directory is not an error
    p = _p(path)
    if os.path.isdir(p):
        shutil.rmtree(p)
    return True


def rmdir(path):
    os.rmdir(_p(path))
    return True


def chmod(path, mode):
    os.chmod(_p(path), int(str(mode), 8) if isinstance(mode, str) else int(mode))
    return True


def chdir(path):
    os.chdir(_p(path))
    return True


def cwd():
    return os.getcwd()


def home():
    return os.path.expanduser("~")


def abs(path):
    return os.path.abspath(_p(path))


def join(*parts):
    return os.path.join(*[_p(x) for x in parts])


def split(path):
    p = _p(path)
    return [os.path.dirname(p), os.path.basename(p)]


def ext(path):
    return os.path.splitext(_p(path))[1]


def stem(path):
    return os.path.splitext(os.path.basename(_p(path)))[0]


def norm(path):
    return os.path.normpath(_p(path))


def rel(path, base="."):
    return os.path.relpath(_p(path), _p(base))


def temp_dir(prefix="ox-"):
    return tempfile.mkdtemp(prefix=prefix)


def temp_file(suffix=".tmp", prefix="ox-"):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
    os.close(fd)
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(_p(path), "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def md5(path):
    h = hashlib.md5()
    with open(_p(path), "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- archives --------------------------------------------------------------

def _as_path_list(paths):
    if isinstance(paths, str):
        return [_p(paths)]
    return [_p(p) for p in paths]


def _norm_entry(name):
    """Normalise an archive entry name to forward slashes."""
    return name.replace(os.sep, "/").lstrip("/")


def _iter_entries(paths, base):
    """Yield (abs_path, entry_name) pairs for the given top-level paths.

    Without `base`, a top-level directory keeps its own name inside the
    archive (`fs.zip("dist", "d.zip")` stores `dist/...` entries); with a
    `base`, entry names are relative to that directory instead.
    """
    for p in paths:
        ap = os.path.abspath(p)
        if not os.path.exists(ap):
            raise OxThrow(OxErrorValue("no such file or directory: %s" % p))
        if base is not None:
            root = os.path.abspath(base)
            top = os.path.relpath(ap, root)
            if top == ".." or top.startswith(".." + os.sep):
                raise OxThrow(OxErrorValue(
                    "cannot archive '%s': outside of base '%s'" % (p, base)))
        else:
            root = os.path.dirname(ap)
            top = os.path.basename(ap.rstrip(os.sep)) or os.path.basename(ap)
        if os.path.isdir(ap):
            for f in walk(ap):
                yield f, _norm_entry(os.path.relpath(f, root))
        else:
            yield ap, _norm_entry(top)


def _safe_member(dest, name):
    """Resolve an archive member inside dest; reject escapes (zip-slip)."""
    root = os.path.realpath(dest)
    target = os.path.realpath(os.path.join(root, _norm_entry(name)))
    if target != root and not target.startswith(root + os.sep):
        raise OxThrow(OxErrorValue(
            "unsafe archive entry '%s' escapes destination" % name,
            kind="security"))
    return target


def make_zip(paths, dest, base=None):
    """Create a zip from files/directories; returns the entry count."""
    dest = _p(dest)
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for src, name in _iter_entries(_as_path_list(paths), base):
            z.write(src, name)
            n += 1
    return n


def unzip(archive, dest):
    """Extract a zip into dest; returns the file count. Path-traversal
    entries (zip-slip) are rejected with an error."""
    archive, dest = _p(archive), _p(dest)
    os.makedirs(dest, exist_ok=True)
    n = 0
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = _safe_member(dest, info.filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
    return n


def make_tar_gz(paths, dest, base=None):
    """Create a gzipped tarball; returns the entry count."""
    dest = _p(dest)
    n = 0
    with tarfile.open(dest, "w:gz") as t:
        for src, name in _iter_entries(_as_path_list(paths), base):
            t.add(src, arcname=name)
            n += 1
    return n


def untar_gz(archive, dest):
    """Extract a gzipped tarball into dest; returns the file count.
    Symlinks/devices and path-traversal entries are rejected."""
    archive, dest = _p(archive), _p(dest)
    os.makedirs(dest, exist_ok=True)
    n = 0
    with tarfile.open(archive, "r:gz") as t:
        for info in t:
            if not info.isfile():
                continue
            target = _safe_member(dest, info.name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            f = t.extractfile(info)
            if f is None:
                continue
            with open(target, "wb") as out:
                shutil.copyfileobj(f, out)
            n += 1
    return n


def read_json(path):
    with open(_p(path), encoding="utf-8") as f:
        return _json.load(f)


def write_json(path, value, pretty=True):
    with open(_p(path), "w", encoding="utf-8") as f:
        _json.dump(value, f, indent=2 if pretty else None, ensure_ascii=False,
                   default=ox_str)
    return True


def replace_in(path, old, new, count=-1):
    """Text replacement inside a file; returns number of replacements."""
    data = read(path)
    occurrences = data.count(old)
    if occurrences == 0:
        return 0
    write(path, data.replace(old, new, count if count > 0 else -1))
    return occurrences


def grep(path, pattern, regex=False):
    """Lines of a file containing `pattern` (substring or regex)."""
    import re as _re
    rx = _re.compile(pattern) if regex else None
    out = []
    for line in read_lines(path):
        if (rx and rx.search(line)) or (not rx and pattern in line):
            out.append(line)
    return out


async def watch(interp, path, fn, interval=0.5):
    """Watch a file/directory for changes; calls fn({path, kind}) each change.

    Returns a handle with a stop() method. Runs until stopped or the
    program exits.
    """
    from ..values import call_value
    p = _p(path)
    state = {}

    def snapshot():
        snap = {}
        for root, _d, fnames in os.walk(p):
            for f in fnames:
                fp = os.path.join(root, f)
                try:
                    snap[fp] = os.stat(fp).st_mtime
                except OSError:
                    pass
        return snap

    state["snap"] = snapshot()
    state["stop"] = False

    async def loop():
        while not state["stop"]:
            await asyncio.sleep(float(interval))
            if state["stop"]:
                break
            new = await asyncio.to_thread(snapshot)
            old = state["snap"]
            for fp, mtime in new.items():
                if fp not in old:
                    await _fire(fp, "created")
                elif old[fp] != mtime:
                    await _fire(fp, "modified")
            for fp in old:
                if fp not in new:
                    await _fire(fp, "deleted")
            state["snap"] = new

    async def _fire(fp, kind):
        try:
            await call_value(interp, fn, [{"path": fp, "kind": kind}])
        except Exception as e:  # noqa: BLE001 — watchers must not die
            from . import logmod
            logmod.log_error("watch handler failed: %s" % e)

    task = asyncio.get_running_loop().create_task(loop())

    class Handle:
        def stop(self):
            state["stop"] = True
            task.cancel()

        def stopped(self):
            return state["stop"]

    return Handle()


# ---- advisory file locks ---------------------------------------------------

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover — windows
    _fcntl = None


class LockHandle:
    """An advisory exclusive lock on a file, acquired via fs.lock()/try_lock().

    Fields: `path`. Method: `release()`. The lock is held until release() or
    process exit; it excludes other processes AND other lock attempts in
    this process (flock is per file description).
    """

    def __init__(self, path, fd):
        self._path = path
        self._fd = fd

    @property
    def path(self):
        return self._path

    @property
    def held(self):
        return self._fd is not None

    def release(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            finally:
                os.close(fd)
        return True

    def __repr__(self):
        return "<lock %s%s>" % (self._path,
                                "" if self._fd is not None else " (released)")


def _acquire_nb(path):
    """One non-blocking acquire attempt; returns fd or None."""
    fd = os.open(_p(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


async def try_lock(path):
    """Try to take an exclusive lock once; returns a handle or null."""
    if _fcntl is None:
        raise OxThrow(OxErrorValue(
            "file locks are not supported on this platform"))
    fd = await asyncio.to_thread(_acquire_nb, _p(path))
    if fd is None:
        return None
    return LockHandle(_p(path), fd)


async def lock(path, timeout=None):
    """Take an exclusive lock, waiting up to `timeout` (forever if null)."""
    if _fcntl is None:
        raise OxThrow(OxErrorValue(
            "file locks are not supported on this platform"))
    p = _p(path)
    deadline = None if timeout is None else _time.monotonic() + float(timeout)
    while True:
        fd = await asyncio.to_thread(_acquire_nb, p)
        if fd is not None:
            return LockHandle(p, fd)
        if deadline is not None and _time.monotonic() >= deadline:
            raise OxThrow(OxErrorValue(
                "timed out waiting for lock on '%s'" % p, kind="timeout"))
        await asyncio.sleep(0.05)


async def with_lock(interp, path, fn, timeout=None):
    """Run fn() while holding the lock; always releases afterwards."""
    handle = await lock(path, timeout=timeout)
    try:
        from ..values import call_value
        return await call_value(interp, fn, [], {})
    finally:
        handle.release()


def build():
    return NativeModule("fs", {
        "read": builtin("read")(read),
        "read_bytes": builtin("read_bytes")(read_bytes),
        "read_lines": builtin("read_lines")(read_lines),
        "write": builtin("write")(write),
        "write_bytes": builtin("write_bytes")(write_bytes),
        "write_lines": builtin("write_lines")(write_lines),
        "append": builtin("append")(append),
        "exists": builtin("exists")(exists),
        "is_file": builtin("is_file")(is_file),
        "is_dir": builtin("is_dir")(is_dir),
        "size": builtin("size")(size),
        "mtime": builtin("mtime")(mtime),
        "empty": builtin("empty")(empty),
        "touch": builtin("touch")(touch),
        "mkdir": builtin("mkdir")(mkdir),
        "mkdirs": builtin("mkdirs")(mkdirs),
        "list": builtin("list")(list_dir),
        "files": builtin("files")(files),
        "dirs": builtin("dirs")(dirs),
        "walk": builtin("walk")(walk),
        "glob": builtin("glob")(glob),
        "copy": builtin("copy")(copy),
        "copytree": builtin("copytree")(copytree),
        "move": builtin("move")(move),
        "rename": builtin("rename")(rename),
        "remove": builtin("remove")(remove),
        "delete": builtin("delete")(delete),
        "remove_tree": builtin("remove_tree")(remove_tree),
        "rmdir": builtin("rmdir")(rmdir),
        "chmod": builtin("chmod")(chmod),
        "chdir": builtin("chdir")(chdir),
        "cwd": builtin("cwd")(cwd),
        "home": builtin("home")(home),
        "abs": builtin("abs")(abs),
        "join": builtin("join")(join),
        "split": builtin("split")(split),
        "ext": builtin("ext")(ext),
        "stem": builtin("stem")(stem),
        "norm": builtin("norm")(norm),
        "rel": builtin("rel")(rel),
        "temp_dir": builtin("temp_dir")(temp_dir),
        "temp_file": builtin("temp_file")(temp_file),
        "sha256": builtin("sha256")(sha256),
        "md5": builtin("md5")(md5),
        "read_json": builtin("read_json")(read_json),
        "write_json": builtin("write_json")(write_json),
        "replace": builtin("replace_in")(replace_in),
        "grep": builtin("grep")(grep),
        "zip": builtin("zip")(make_zip),
        "unzip": builtin("unzip")(unzip),
        "tar_gz": builtin("tar_gz")(make_tar_gz),
        "untar_gz": builtin("untar_gz")(untar_gz),
        "lock": builtin("lock")(lock),
        "try_lock": builtin("try_lock")(try_lock),
        "with_lock": builtin("with_lock", needs_interp=True)(with_lock),
        "watch": builtin("watch", needs_interp=True)(watch),
    })
