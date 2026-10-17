"""co — concurrency: sleeps, timeouts, periodic monitors, task helpers,
cron schedules.

(The module is named `co` because `async` is a keyword in ox.)
"""
import asyncio
import time as _time

from ..errors import OxThrow
from ..values import NativeModule, OxErrorValue, builtin


def _secs(d):
    return float(d)


# ---- cron ------------------------------------------------------------------

CRON_ALIASES = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

_MONTH_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_DOW_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5,
              "sat": 6}
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field_values(part, lo, hi, names, field):
    """Parse one cron field ("*", "*/5", "1-6/2", "mon,wed") into a set."""
    out = set()
    for chunk in part.split(","):
        chunk = chunk.strip().lower()
        if not chunk:
            raise OxThrow(OxErrorValue(
                "cron: empty item in '%s' field" % field))
        step = 1
        if "/" in chunk:
            chunk, step_s = chunk.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                raise OxThrow(OxErrorValue(
                    "cron: bad step '/%s'" % step_s))
            if step < 1:
                raise OxThrow(OxErrorValue("cron: step must be >= 1"))
        if chunk == "*" or chunk == "":
            start, end = lo, hi
        elif "-" in chunk and not chunk.startswith("-"):
            a, b = chunk.split("-", 1)
            start = names.get(a, None) if names else None
            end = names.get(b, None) if names else None
            if start is None:
                try:
                    start = int(a)
                except ValueError:
                    raise OxThrow(OxErrorValue(
                        "cron: bad range start '%s'" % a))
            if end is None:
                try:
                    end = int(b)
                except ValueError:
                    raise OxThrow(OxErrorValue(
                        "cron: bad range end '%s'" % b))
        else:
            v = names.get(chunk, None) if names else None
            if v is None:
                try:
                    v = int(chunk)
                except ValueError:
                    raise OxThrow(OxErrorValue(
                        "cron: bad value '%s' in %s field" % (chunk, field)))
            start = end = v
        if start < lo or end > hi or start > end:
            raise OxThrow(OxErrorValue(
                "cron: value out of range in %s field ('%s')"
                % (field, part)))
        out.update(range(start, end + 1, step))
    return out


def _parse_cron(expr):
    """Parse a 5-field cron expression into (mins, hours, doms, months, dows).
    Classic semantics: day-of-week 0 and 7 both mean Sunday; when both
    day-of-month and day-of-week are restricted, either may match."""
    expr = ox_str_cron(expr)
    expr = CRON_ALIASES.get(expr.strip().lower(), expr)
    fields = expr.split()
    if len(fields) != 5:
        raise OxThrow(OxErrorValue(
            "cron: expected 5 fields (min hour day month weekday), got %d"
            % len(fields)))
    names = (None, None, None, _MONTH_NAMES, _DOW_NAMES)
    labels = ("minute", "hour", "day-of-month", "month", "weekday")
    sets = []
    for i, part in enumerate(fields):
        lo, hi = _FIELD_RANGES[i]
        sets.append(_field_values(part, lo, hi, names[i], labels[i]))
    mins, hours, doms, months, dows = sets
    if 7 in dows:
        dows.add(0)
    dom_any = fields[2] == "*"
    dow_any = fields[4] == "*"
    return mins, hours, doms, months, dows, dom_any, dow_any


def ox_str_cron(expr):
    if not isinstance(expr, str):
        raise OxThrow(OxErrorValue("cron: expected an expression string"))
    return expr


def cron_next(expr, after=None):
    """Next epoch second matching the cron expression (local time).
    Returns null if nothing matches within five years."""
    mins, hours, doms, months, dows, dom_any, dow_any = _parse_cron(expr)
    if after is None:
        after = _time.time()
    t = int(after) + 60 - (int(after) % 60)  # next whole minute
    limit = int(after) + 5 * 366 * 86400
    while t <= limit:
        st = _time.localtime(t)
        if st.tm_min not in mins or st.tm_hour not in hours \
                or st.tm_mon not in months:
            t += 60
            continue
        dom_ok = st.tm_mday in doms
        cron_dow = (st.tm_wday + 1) % 7  # python: mon=0..sun=6; cron: sun=0..sat=6
        dow_ok = cron_dow in dows
        if dom_any and dow_any:
            day_ok = True
        elif dom_any:
            day_ok = dow_ok
        elif dow_any:
            day_ok = dom_ok
        else:
            day_ok = dom_ok or dow_ok
        if day_ok:
            return t
        t += 60
    return None


class CronHandle:
    def __init__(self, task, state, expr):
        self._task = task
        self._state = state
        self._expr = expr

    def stop(self):
        self._state["stop"] = True
        if self._task and not self._task.done():
            self._task.cancel()

    def stopped(self):
        return self._state["stop"]

    def next(self):
        """Next scheduled fire time (epoch seconds), or null."""
        return cron_next(self._expr)

    def __repr__(self):
        return "<co.cron %r>" % self._expr


async def cron(interp, expr, fn):
    """Run fn() on a cron schedule; returns a handle with stop() and next()."""
    _parse_cron(expr)  # validate early, before first fire
    state = {"stop": False}

    async def loop():
        while not state["stop"]:
            nxt = cron_next(expr)
            if nxt is None:
                return
            delay = nxt - _time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            if state["stop"]:
                return
            try:
                await call_value(interp, fn, [], {})
            except OxThrow as t:
                from . import logmod
                logmod.log_error("co.cron task failed: %s" % t.value.msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — cron tasks must not die
                from . import logmod
                logmod.log_error("co.cron task failed: %s" % e)

    task = asyncio.get_running_loop().create_task(loop())
    return CronHandle(task, state, expr)


async def sleep(d):
    await asyncio.sleep(_secs(d))


async def all_of(tasks):
    out = []
    for t in tasks:
        if asyncio.isfuture(t) or isinstance(t, asyncio.Task):
            out.append(await t)
        else:
            out.append(t)
    return out


async def any_of(tasks):
    real = [t for t in tasks if asyncio.isfuture(t) or isinstance(t, asyncio.Task)]
    if not real:
        return tasks[0] if tasks else None
    done, _pending = await asyncio.wait(real, return_when=asyncio.FIRST_COMPLETED)
    for t in done:
        return t.result()
    return None


async def timeout(d, fn):
    from ..values import call_value

    async def runner():
        return await call_value(_interp_holder[0], fn, [], {})

    try:
        return await asyncio.wait_for(runner(), timeout=_secs(d))
    except asyncio.TimeoutError:
        raise OxThrow(OxErrorValue("operation timed out after %ss" % _secs(d),
                                   kind="timeout"))


_interp_holder = [None]


def _with_interp(interp):
    _interp_holder[0] = interp


class Handle:
    def __init__(self, task, state):
        self._task = task
        self._state = state

    def stop(self):
        self._state["stop"] = True
        if self._task and not self._task.done():
            self._task.cancel()

    def stopped(self):
        return self._state["stop"]

    def __repr__(self):
        return "<co.handle>"


async def every(interval, fn, delay=0):
    """Run fn() every interval; returns a handle with stop()."""
    from ..values import call_value
    interp = _interp_holder[0]
    state = {"stop": False}

    async def loop():
        await asyncio.sleep(_secs(delay))
        while not state["stop"]:
            try:
                await call_value(interp, fn, [], {})
            except OxThrow as t:
                from . import logmod
                logmod.log_error("co.every task failed: %s" % t.value.msg)
            await asyncio.sleep(_secs(interval))

    task = asyncio.get_running_loop().create_task(loop())
    return Handle(task, state)


async def after(d, fn):
    """Run fn() once after a delay; returns a handle with stop()."""
    from ..values import call_value
    interp = _interp_holder[0]
    state = {"stop": False}

    async def loop():
        try:
            await asyncio.sleep(_secs(d))
            if not state["stop"]:
                await call_value(interp, fn, [], {})
        except asyncio.CancelledError:
            pass

    task = asyncio.get_running_loop().create_task(loop())
    return Handle(task, state)


def pending():
    n = 0
    for t in asyncio.all_tasks():
        if not t.done() and t is not asyncio.current_task():
            n += 1
    return n


def build():
    m = NativeModule("co", {
        "sleep": builtin("sleep")(sleep),
        "all": builtin("all")(all_of),
        "any": builtin("any")(any_of),
        "timeout": builtin("timeout", needs_interp=True)(_timeout_entry),
        "every": builtin("every", needs_interp=True)(_every_entry),
        "after": builtin("after", needs_interp=True)(_after_entry),
        "cron": builtin("cron", needs_interp=True)(_cron_entry),
        "cron_next": builtin("cron_next")(cron_next),
        "pending": builtin("pending")(pending),
    })
    return m


async def _cron_entry(interp, expr, fn):
    _interp_holder[0] = interp
    return await cron(interp, expr, fn)


async def _timeout_entry(interp, d, fn):
    _interp_holder[0] = interp
    return await timeout(d, fn)


async def _every_entry(interp, interval, fn, delay=0):
    _interp_holder[0] = interp
    return await every(interval, fn, delay=delay)


async def _after_entry(interp, d, fn):
    _interp_holder[0] = interp
    return await after(d, fn)
