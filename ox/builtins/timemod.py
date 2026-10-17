"""time — clocks, formatting and parsing."""
import datetime
import time as _time

from ..values import NativeModule, builtin

_DEFAULT_FMT = "%Y-%m-%d %H:%M:%S"


def _now():
    return _time.time()


def _epoch():
    return int(_time.time())


def _now_str(fmt=None):
    return datetime.datetime.now().strftime(fmt or _DEFAULT_FMT)


def _format(ts, fmt=None):
    return datetime.datetime.fromtimestamp(float(ts)).strftime(fmt or _DEFAULT_FMT)


def _parse(s, fmt=None):
    if fmt is None:
        for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S",
                  "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.datetime.strptime(s, f).timestamp()
            except ValueError:
                continue
        raise ValueError("cannot parse %r as a date (pass a format like "
                         "'%%Y-%%m-%%d')" % s)
    return datetime.datetime.strptime(s, fmt).timestamp()


def _iso(ts=None):
    if ts is None:
        return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
    return datetime.datetime.fromtimestamp(float(ts)).isoformat(sep=" ",
                                                                timespec="seconds")


def _utc_iso(ts=None):
    if ts is None:
        return datetime.datetime.utcnow().isoformat(sep=" ", timespec="seconds") + "Z"
    return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc)\
        .isoformat(sep=" ", timespec="seconds")


def _parts(ts=None):
    d = datetime.datetime.fromtimestamp(ts if ts is not None else _time.time())
    return {"year": d.year, "month": d.month, "day": d.day,
            "hour": d.hour, "minute": d.minute, "second": d.second,
            "weekday": d.strftime("%A"), "date": d.strftime("%Y-%m-%d"),
            "time": d.strftime("%H:%M:%S")}


def build():
    return NativeModule("time", {
        "now": builtin("now")(_now),
        "epoch": builtin("epoch")(_epoch),
        "now_str": builtin("now_str")(_now_str),
        "format": builtin("format")(_format),
        "parse": builtin("parse")(_parse),
        "iso": builtin("iso")(_iso),
        "utc": builtin("utc")(_utc_iso),
        "parts": builtin("parts")(_parts),
    })
