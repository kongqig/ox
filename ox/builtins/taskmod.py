"""wf — the workflow engine: steps, retries, rollback, persisted state.

    workflow "backup" {
      desc "Nightly backup"

      step "dump" {
        sh("pg_dump app > dump.sql")
      } retry 3 backoff 2s

      step "upload" {
        net.post("https://backups.example.com", data=fs.read("dump.sql"))
      } rollback {
        sh("rm dump.sql")
      }

      step "verify" {
        verify fs.size("dump.sql") > 0, "dump must not be empty"
      }

      on fail { log.error("backup failed") }
      on done { emit "backup.ok" }
    }

    let r = run("backup")     # -> {ok, steps, run, ms, ...}
    run("backup", dry=true)   # show what would run
    run("backup", resume=true)  # redo only unfinished steps of the last failed run

State is persisted under .ox/state/<name>.json: every run (with per-step
status, attempts, duration, error) is appended, forming a versioned history
you can inspect with wf.status / wf.history.

A run is written to disk as status "running" *before* its first step
executes and finalized as "ok"/"failed" when it ends — so a process that
dies mid-run leaves a visible "running" record that `run(..., resume=true)`
treats as crashed and recovers from. Only one live run per workflow is
allowed (advisory flock on <name>.lock); a second concurrent run fails
with a clear error instead of silently clobbering state. Corrupt state
files (truncated, garbage, wrong shape) are backed up to <name>.json.corrupt
and the workflow starts from fresh state — never a traceback.
"""
import asyncio
import json as _json
import os
import re
import time as _time

from .. import tty
from ..errors import OxThrow
from ..values import NativeModule, OxErrorValue, builtin, ox_str
from . import logmod

MAX_RUNS_KEPT = 20


class Step:
    def __init__(self, name, body, retry=1, backoff=0.0, rollback=None):
        self.name = name
        self.body = body          # async callable () -> value
        self.retry = max(1, int(retry))
        self.backoff = float(backoff)
        self.rollback = rollback  # async callable | None


class Workflow:
    def __init__(self, name, desc=""):
        self.name = name
        self.desc = desc
        self.steps = []
        self.hooks = {"fail": [], "done": []}

    def step_names(self):
        return [s.name for s in self.steps]


def state_dir():
    return os.environ.get("OX_STATE_DIR") or os.path.join(os.getcwd(), ".ox",
                                                          "state")


def _slug(name):
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)[:80]


def _state_path(name):
    return os.path.join(state_dir(), _slug(name) + ".json")


def _valid_run(rec):
    """A run record is usable if it has a steps list of step dicts."""
    return (isinstance(rec, dict)
            and isinstance(rec.get("steps"), list)
            and all(isinstance(s, dict) and isinstance(s.get("name"), str)
                    and isinstance(s.get("status"), str)
                    for s in rec["steps"]))


def _backup_corrupt(path, reason, name):
    """Preserve a corrupt state file, then let the caller start fresh."""
    bak = path + ".corrupt"
    n = 0
    while os.path.exists(bak):
        n += 1
        bak = "%s.corrupt-%d" % (path, n)
    kept = None
    try:
        os.replace(path, bak)
        kept = bak
    except OSError:
        pass
    print(tty.yellow("! state file for workflow '%s' is corrupt (%s)"
                     % (name, reason)))
    if kept:
        print(tty.gray("  backed up to %s — starting from fresh state" % kept))
    else:
        print(tty.gray("  could not back it up — starting from fresh state"))


def load_state(name):
    path = _state_path(name)
    if not os.path.isfile(path):
        return {"name": name, "runs": []}
    try:
        with open(path, encoding="utf-8") as f:
            state = _json.load(f)
    except (OSError, ValueError) as e:
        _backup_corrupt(path, str(e), name)
        return {"name": name, "runs": []}
    if not isinstance(state, dict) or not isinstance(state.get("runs"), list):
        _backup_corrupt(path, "not a valid state document", name)
        return {"name": name, "runs": []}
    good = [r for r in state["runs"] if _valid_run(r)]
    dropped = len(state["runs"]) - len(good)
    if dropped:
        _backup_corrupt(path, "%d malformed run record(s)" % dropped, name)
        state["runs"] = good
    return state


def _acquire_run_lock(name):
    """One live run per workflow — advisory flock, cross-process."""
    try:
        import fcntl
    except ImportError:  # non-POSIX platform: degraded, no guard
        return None
    path = os.path.join(state_dir(), _slug(name) + ".lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise OxThrow(OxErrorValue(
            "workflow '%s' is already running in another process "
            "(lock held: %s)" % (name, path)))
    return fd


def _release_run_lock(fd):
    if fd is None:
        return
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def save_state(name, state):
    path = _state_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state["runs"] = state["runs"][-MAX_RUNS_KEPT:]
    state["updated"] = _time.time()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(state, f, indent=2, ensure_ascii=False, default=ox_str)
    os.replace(tmp, path)


async def define_workflow(interp, stmt, env):
    """Interpreted `workflow "name" { ... }` — executes the body to collect."""
    from ..environment import Env
    entries = []
    interp.collectors.append(entries)
    try:
        await interp.exec_block(stmt.body, Env(env) if env else interp.globals)
    finally:
        interp.collectors.pop()
    register_workflow(interp, stmt.name, entries)


def register_workflow(interp, name, entries):
    wf = Workflow(name)
    for entry in entries:
        kind = entry[0]
        if kind == "step":
            d = entry[1]
            wf.steps.append(Step(d["name"], d["body"], d["retry"],
                                 d["backoff"], d["rollback"]))
        elif kind == "hook":
            _, hook_kind, fn = entry
            wf.hooks.setdefault(hook_kind, []).append(fn)
        elif kind == "desc":
            wf.desc = entry[1]
    if not wf.steps:
        raise OxThrow(OxErrorValue("workflow '%s' has no steps" % name))
    interp.workflows[name] = wf
    return wf


async def _call(fn, *args):
    from ..errors import ReturnSignal
    try:
        r = fn(*args)
        if asyncio.iscoroutine(r):
            r = await r
        return r
    except ReturnSignal as rs:
        return rs.value  # `return` inside a step body = the step's value


async def _run_hooks(wf, kind):
    for fn in wf.hooks.get(kind, []):
        try:
            await _call(fn)
        except Exception as e:  # noqa: BLE001 — hook errors are logged
            logmod.log_error("workflow '%s' %s-hook failed: %s"
                             % (wf.name, kind, e))


async def run_workflow(interp, name, only=None, skip=None, dry=False,
                       resume=False):
    wf = interp.workflows.get(name)
    if wf is None:
        available = ", ".join(sorted(interp.workflows)) or "(none defined)"
        raise OxThrow(OxErrorValue("no workflow named '%s' — defined: %s"
                                   % (name, available)))
    lock_fd = None if dry else _acquire_run_lock(name)
    try:
        return await _run_locked(interp, wf, name, only, skip, dry, resume)
    finally:
        _release_run_lock(lock_fd)


async def _run_locked(interp, wf, name, only, skip, dry, resume):
    state = load_state(name)
    t0 = _time.monotonic()

    steps = wf.steps
    filtered = False
    if only:
        only = [ox_str(s) for s in only]
        steps = [s for s in steps if s.name in only]
        filtered = True
    if skip:
        skip = [ox_str(s) for s in skip]
        steps = [s for s in steps if s.name not in skip]
        filtered = True

    resume_done = set()
    if resume:
        last = None
        for run in reversed(state["runs"]):
            # "running" here means the previous process died mid-run:
            # we hold the run lock, so it cannot be live anymore.
            if run.get("status") in ("failed", "crashed", "running"):
                last = run
                break
        if last is not None:
            resume_done = {s["name"] for s in last["steps"]
                           if s["status"] == "ok"}

    run_record = {"id": len(state["runs"]) + 1,
                  "started": _time.time(),
                  "status": "running",
                  "mode": "dry" if dry else ("resume" if resume else "normal"),
                  "ms": 0,
                  "steps": []}
    if not dry:
        # persisted up-front: a crash mid-run leaves a visible "running"
        # record that a later `resume=true` recovers from
        state["runs"].append(run_record)
        state["name"] = name
        state["desc"] = wf.desc
        save_state(name, state)

    banner = tty.bold("▶ workflow %s" % name)
    if wf.desc:
        banner += tty.gray(" — %s" % wf.desc)
    print(banner)
    succeeded = []
    failed_step = None
    for step in steps:
        srec = {"name": step.name, "status": "pending", "attempts": 0,
                "ms": 0, "error": None}
        run_record["steps"].append(srec)
        if dry:
            srec["status"] = "dry"
            print("  " + tty.cyan("[dry] ") + step.name)
            continue
        if step.name in resume_done:
            srec["status"] = "skipped (resume)"
            print("  " + tty.gray("[skip] ") + step.name +
                  tty.gray(" (already ok in last run)"))
            succeeded.append(step)
            continue

        st0 = _time.monotonic()
        attempts = 0
        err = None
        while attempts < step.retry:
            attempts += 1
            try:
                result = await _call(step.body)
                err = None
                break
            except Exception as e:  # noqa: BLE001 — step failure is data
                from ..values import to_ox_error
                err = to_ox_error(e)
                if attempts < step.retry:
                    delay = step.backoff * attempts
                    print("  " + tty.yellow("[retry] ") + step.name +
                          tty.gray(" attempt %d/%d failed (%s), %s"
                                   % (attempts, step.retry, err.msg,
                                      ("in %.2fs" % delay) if delay
                                      else "retrying")))
                    if delay:
                        await asyncio.sleep(delay)
        srec["attempts"] = attempts
        srec["ms"] = round((_time.monotonic() - st0) * 1000)
        if err is None:
            srec["status"] = "ok"
            detail = _fmt_result(result) if attempts == 1 else ""
            print("  " + tty.green("✓ ") + step.name +
                  tty.gray(" (%dms%s)" % (srec["ms"], detail)))
            succeeded.append(step)
        else:
            srec["status"] = "failed"
            srec["error"] = err.msg
            failed_step = step
            print("  " + tty.red("✗ ") + step.name +
                  tty.gray(" (%dms) — %s" % (srec["ms"], err.msg)))
            break

    if failed_step is None and not dry:
        run_record["status"] = "ok"
        run_record["ended"] = _time.time()
        run_record["ms"] = round((_time.monotonic() - t0) * 1000)
        state["name"] = name
        state["desc"] = wf.desc
        save_state(name, state)
        if not filtered:
            await _run_hooks(wf, "done")
        print(tty.green("✓ workflow '%s' ok (%dms)" % (name, run_record["ms"])))
        return _result(wf, run_record, True)

    if failed_step is not None:
        run_record["status"] = "failed"
        run_record["ended"] = _time.time()
        run_record["ms"] = round((_time.monotonic() - t0) * 1000)
        state["name"] = name
        state["desc"] = wf.desc
        save_state(name, state)
        # rollbacks: the failed step's own rollback first (partial-work
        # cleanup), then succeeded steps' rollbacks in reverse order
        rolled = []
        undo_chain = ([failed_step] if failed_step.rollback is not None else []) \
            + [s for s in reversed(succeeded) if s.rollback is not None]
        for step in undo_chain:
            try:
                await _call(step.rollback)
                rolled.append(step.name)
                print("  " + tty.magenta("↩ rollback ") + step.name)
            except Exception as e:  # noqa: BLE001
                logmod.log_error("rollback of '%s' failed: %s"
                                 % (step.name, e))
        if not filtered:
            await _run_hooks(wf, "fail")
        print(tty.red("✗ workflow '%s' failed at step '%s'"
                      % (name, failed_step.name)))
        return _result(wf, run_record, False, rolled)

    # dry run
    run_record["status"] = "dry"
    run_record["ended"] = _time.time()
    run_record["ms"] = 0
    print(tty.yellow("■ dry run complete — nothing was executed"))
    return _result(wf, run_record, True)


def _fmt_result(result):
    if result is None:
        return ""
    s = ox_str(result)
    if len(s) > 40:
        s = s[:37] + "..."
    return " — " + s


def _result(wf, run_record, ok, rolled=None):
    return {"ok": ok, "workflow": wf.name, "run": run_record["id"],
            "status": run_record["status"], "mode": run_record["mode"],
            "ms": run_record["ms"],
            "steps": [{"name": s["name"], "status": s["status"],
                       "attempts": s["attempts"], "ms": s["ms"],
                       "error": s["error"]} for s in run_record["steps"]],
            "rolled_back": rolled or []}


def wf_list(interp):
    out = []
    for name in sorted(interp.workflows):
        wf = interp.workflows[name]
        out.append({"name": name, "desc": wf.desc,
                    "steps": len(wf.steps)})
    return out


def wf_steps(interp, name):
    wf = interp.workflows.get(name)
    if wf is None:
        raise OxThrow(OxErrorValue("no workflow named '%s'" % name))
    return wf.step_names()


def wf_status(interp, name):
    state = load_state(name)
    last = state["runs"][-1] if state["runs"] else None
    if last is None:
        return {"name": name, "runs": 0, "last": None}
    return {"name": name, "runs": len(state["runs"]), "last": {
        "id": last.get("id", 0), "status": last.get("status", "?"),
        "mode": last.get("mode", ""),
        "started": last.get("started", 0), "ms": last.get("ms", 0),
        "steps": [{"name": s.get("name", "?"), "status": s.get("status", "?")}
                  for s in last["steps"]]}}


def wf_history(interp, name, n=5):
    state = load_state(name)
    runs = state["runs"][-int(n):]
    return [{"id": r.get("id", 0), "status": r.get("status", "?"),
             "mode": r.get("mode", ""),
             "started": r.get("started", 0), "ms": r.get("ms", 0),
             "failed_step": next((s["name"] for s in r["steps"]
                                  if s.get("status") == "failed"), None)}
            for r in runs]


def wf_state_dir(path=None):
    if path is None:
        return state_dir()
    os.environ["OX_STATE_DIR"] = ox_str(path)
    return ox_str(path)


async def wf_run(interp, name, **kw):
    return await run_workflow(interp, name, **kw)


def build():
    return NativeModule("wf", {
        "run": builtin("run", needs_interp=True)(wf_run),
        "list": builtin("list", needs_interp=True)(wf_list),
        "steps": builtin("steps", needs_interp=True)(wf_steps),
        "status": builtin("status", needs_interp=True)(wf_status),
        "history": builtin("history", needs_interp=True)(wf_history),
        "state_dir": builtin("state_dir")(wf_state_dir),
    })
