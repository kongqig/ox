"""log — leveled, colored logging with optional file tee + table printing."""
import datetime
import json as _json
import os
import sys

from .. import tty
from ..values import NativeModule, builtin, ox_repr, ox_str

LEVELS = {"debug": 10, "info": 20, "ok": 25, "success": 25, "warn": 30,
          "warning": 30, "error": 40}
_TAGS = {"debug": tty.gray, "info": tty.cyan, "ok": tty.green,
         "success": tty.green, "warn": tty.yellow, "warning": tty.yellow,
         "error": tty.red}
_state = {"min": 20, "quiet": False, "file": None}


def _emit(level, msg):
    if _state["quiet"]:
        return
    if LEVELS.get(level, 20) < _state["min"]:
        return
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = "[%s] %-7s %s" % (ts, level, ox_str(msg))
    if _state["file"]:
        try:
            with open(_state["file"], "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    print(_TAGS.get(level, str)(line), flush=True)


def log_debug(msg):
    _emit("debug", msg)


def log_info(msg):
    _emit("info", msg)


def log_ok(msg):
    _emit("ok", msg)


def log_warn(msg):
    _emit("warn", msg)


def log_error(msg):
    _emit("error", msg)


def _set_level(level):
    level = ox_str(level).lower()
    if level not in LEVELS:
        raise ValueError("unknown log level '%s' (use debug/info/ok/warn/error)"
                         % level)
    _state["min"] = LEVELS[level]


def _quiet(q=True):
    _state["quiet"] = bool(q)


def _file(path, append=True):
    _state["file"] = path
    if path and not append:
        try:
            open(path, "w").close()
        except OSError:
            pass


def _table(rows, cols=None):
    if not rows:
        print("(empty)", flush=True)
        return
    dicts = [r for r in rows if isinstance(r, dict)]
    if cols is None:
        if dicts and len(dicts) == len(rows):
            seen = []
            for r in rows:
                for k in r.keys():
                    if k not in seen:
                        seen.append(k)
            cols = seen
        else:
            cols = ["value"]
            rows = [{"value": r} for r in rows]
    if not isinstance(cols, list):
        cols = [cols]
    widths = [len(ox_str(c)) for c in cols]
    text_rows = []
    for r in rows:
        vals = []
        for i, c in enumerate(cols):
            v = r.get(c, "") if isinstance(r, dict) else ""
            s = ox_str(v)
            if len(s) > 60:
                s = s[:57] + "..."
            vals.append(s)
            widths[i] = max(widths[i], len(s))
        text_rows.append(vals)
    header = "  ".join(ox_str(c).ljust(widths[i]) for i, c in enumerate(cols))
    print(tty.bold(header), flush=True)
    print(tty.gray("-" * len(header)), flush=True)
    for vals in text_rows:
        print("  ".join(v.ljust(widths[i]) for i, v in enumerate(vals)),
              flush=True)


def _json_print(obj, pretty=True):
    try:
        s = _json.dumps(obj, indent=2 if pretty else None,
                        ensure_ascii=False, default=ox_str)
    except (TypeError, ValueError):
        s = ox_repr(obj)
    print(s, flush=True)


def _line(ch="-", n=60):
    print(ox_str(ch)[0] * int(n), flush=True)


def build():
    return NativeModule("log", {
        "debug": builtin("debug")(log_debug),
        "info": builtin("info")(log_info),
        "ok": builtin("ok")(log_ok),
        "success": builtin("success")(log_ok),
        "warn": builtin("warn")(log_warn),
        "warning": builtin("warning")(log_warn),
        "error": builtin("error")(log_error),
        "level": builtin("level")(_set_level),
        "quiet": builtin("quiet")(_quiet),
        "file": builtin("file")(_file),
        "table": builtin("table")(_table),
        "json": builtin("json")(_json_print),
        "line": builtin("line")(_line),
    })
