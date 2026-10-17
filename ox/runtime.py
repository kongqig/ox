"""Shared runtime for interpreted and compiled ox programs.

Transpiled ox code (`ox build`) emits calls to the helpers in this module,
so compiled programs behave exactly like interpreted ones. The interpreter
itself also routes DSL features (workflows, servers, events) through here.
"""
import asyncio
import functools

from .errors import (BreakSignal, ContinueSignal, OxExit, OxThrow)
from .values import (BoundMethod, BuiltinFunction, Duration, OxErrorValue,
                     OxFunction, Range, call_method, call_value, get_attr_value,
                     method_table, ox_add, ox_cmp, ox_div, ox_eq, ox_floordiv,
                     ox_mod, ox_mul, ox_neg, ox_pow, ox_repr, ox_str, ox_sub,
                     set_attr_value, setitem, to_ox_error, truthy, type_name,
                     getitem)

get_attr = get_attr_value
to_error = to_ox_error

_DUR_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}

_interp = None


def get_interp():
    """The process-wide interpreter used by compiled ox programs."""
    global _interp
    if _interp is None:
        from .interpreter import Interpreter
        _interp = Interpreter(file="<compiled>")
    return _interp


def set_interp(interp):
    global _interp
    _interp = interp


def get_module(name):
    from .builtins import MODULES
    if name not in MODULES:
        raise OxThrow(OxErrorValue("no module named '%s'" % name))
    return MODULES[name]


def _escaped_signal_error(exc):
    """A break/continue that no loop caught -> a clean ox error."""
    word = "'break'" if isinstance(exc, BreakSignal) else "'continue'"
    err = OxErrorValue("%s outside of a loop" % word)
    pos = getattr(exc, "pos", None)
    if pos:
        err.pos = pos
    return OxThrow(err)


def run(coro):
    """asyncio.run with graceful Ctrl+C handling; returns an exit code."""
    try:
        result = asyncio.run(_run_wrapped(coro))
        return result
    except KeyboardInterrupt:
        print("")
        return 130
    except (BreakSignal, ContinueSignal) as e:
        raise _escaped_signal_error(e)


async def _run_wrapped(coro):
    try:
        return await coro
    except (BreakSignal, ContinueSignal) as e:
        raise _escaped_signal_error(e)
    finally:
        pending = [t for t in asyncio.all_tasks() if not t.done()
                   and t is not asyncio.current_task()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # terminate background processes started with os.start()
        try:
            from .builtins import osmod
            await osmod.kill_live_procs()
        except Exception:  # noqa: BLE001 — cleanup must never mask a result
            pass


# ---- operator helpers (compiled code calls these) ------------------------------

add = ox_add
sub = ox_sub
mul = ox_mul
div = ox_div
floordiv = ox_floordiv
mod = ox_mod
pow_ = ox_pow
neg = ox_neg
eq = ox_eq


# ---- match patterns ------------------------------------------------------------

def match_pattern(pat, value):
    """Match a compiled pattern structure against a value.

    pat is a tuple tree:
      ("wild",)                    always matches
      ("lit", v)                   compare by value
      ("bind", name)               bind, always matches
      ("expr", v_or_thunk)         compare by value (thunk resolved here)
      ("list", (sub...), rest)     exact length unless rest; rest: None|""|name
      ("dict", ((key, sub)...), rest)  partial match; rest: None|""|name

    Returns a dict of bindings, or None when the value does not match.
    Shared by the interpreter and compiled code so both stay identical.
    """
    kind = pat[0]
    if kind == "wild":
        return {}
    if kind == "bind":
        return {pat[1]: value}
    if kind == "lit" or kind == "expr":
        v = pat[1]
        if callable(v):
            v = v()
        return {} if ox_eq(v, value) else None
    if kind == "range":
        # containment: 5 matches 1..5, not 1..<5
        lo, hi, excl = pat[1], pat[2], pat[3]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if excl:
            return {} if lo <= value < hi else None
        return {} if lo <= value <= hi else None
    if kind == "list":
        items, rest = pat[1], pat[2]
        if not isinstance(value, list) or len(value) < len(items):
            return None
        if rest is None and len(value) != len(items):
            return None
        out = {}
        for sub, v in zip(items, value):
            b = match_pattern(sub, v)
            if b is None:
                return None
            out.update(b)
        if rest:
            if rest != "":
                out[rest] = list(value[len(items):])
        return out
    if kind == "dict":
        pairs, rest = pat[1], pat[2]
        if not isinstance(value, dict):
            return None
        out = {}
        for key, sub in pairs:
            if key not in value:
                return None
            b = match_pattern(sub, value[key])
            if b is None:
                return None
            out.update(b)
        if rest and rest != "":
            keys = set()
            for key, _sub in pairs:
                keys.add(key)
            out[rest] = {k: v for k, v in value.items() if k not in keys}
        return out
    raise ValueError("bad pattern node %r" % (pat,))


def ne(a, b):
    return not ox_eq(a, b)


def lt(a, b):
    return ox_cmp(a, b, lambda x, y: x < y)


def le(a, b):
    return ox_cmp(a, b, lambda x, y: x <= y)


def gt(a, b):
    return ox_cmp(a, b, lambda x, y: x > y)


def ge(a, b):
    return ox_cmp(a, b, lambda x, y: x >= y)


def dur(n, unit):
    return Duration(float(n) * _DUR_UNITS[unit])


def range_lit(a, b, exclusive):
    return Range(a, b, exclusive)


def interp_parts(parts):
    """String interpolation: parts are ("s", text) or ("e", value)."""
    out = []
    for kind, p in parts:
        out.append(p if kind == "s" else ox_str(p))
    return "".join(out)


async def call(f, args=None, kwargs=None):
    """Unified call entry for compiled code. `f` may be a python callable or
    a *name string*: names resolve against ox builtins and fall back to
    pipe-style method dispatch on the first argument (sort(xs) == xs.sort())."""
    args = args or []
    kwargs = kwargs or {}
    if isinstance(f, str):
        interp = get_interp()
        if f in interp.globals.values:
            f = interp.globals.values[f]
        else:
            if args:
                table = method_table(args[0])
                if table is not None and f in table:
                    return await call_method(interp, args[0], f, args[1:],
                                             kwargs)
            raise OxThrow(OxErrorValue("undefined variable '%s'" % f))
    return await call_value(get_interp(), f, args, kwargs)


async def mcall(obj, name, args=None, kwargs=None):
    """Method call for compiled code: x.name(args)."""
    return await call_method(get_interp(), obj, name, args or [], kwargs or {})


def iter_pairs(seq):
    """Two-variable for loops: dicts yield [k, v]; lists pass through."""
    if isinstance(seq, dict):
        return [[k, v] for k, v in seq.items()]
    if isinstance(seq, list):
        return seq
    raise OxThrow(OxErrorValue(
        "cannot unpack %s into two loop variables" % type_name(seq)))


async def unwrap(v):
    """`await` in compiled code: task / list-of-tasks / plain value."""
    if asyncio.isfuture(v) or isinstance(v, asyncio.Task):
        return await v
    if isinstance(v, list):
        out = []
        for x in v:
            out.append(await unwrap(x))
        return out
    return v


async def _spawn_runner(fn):
    v = await call(fn)
    if isinstance(v, (OxFunction, BuiltinFunction, BoundMethod)) or \
            (callable(v) and not isinstance(v, (str, list, dict, int, float))):
        v = await call(v)
    return v


def spawn(fn):
    return asyncio.get_running_loop().create_task(_spawn_runner(fn))


def throw(v):
    if isinstance(v, OxErrorValue):
        raise OxThrow(v)
    raise OxThrow(OxErrorValue(ox_str(v)))


def verify(cond, msg=None):
    if not truthy(cond):
        raise OxThrow(OxErrorValue(msg or "verification failed", kind="verify"))


def error(msg, code=0, data=None):
    return OxErrorValue(ox_str(msg), code=code, data=data)


def set_attr(obj, name, value):
    set_attr_value(obj, name, value)


def setitem_add(obj, key, value, op="+"):
    """Compound assignment on dict-key targets (d.k += v)."""
    cur = get_attr_value(obj, key) if not isinstance(obj, list) else obj[key]
    new = {"+": ox_add, "-": ox_sub, "*": ox_mul, "/": ox_div,
           "//": ox_floordiv, "%": ox_mod}[op](cur, value)
    if isinstance(obj, dict):
        obj[key] = new
    else:
        setitem(obj, key, new)
    return new


# ---- DSL registration helpers (compiled code) ----------------------------------

async def _workflow(name, body):
    from .builtins import taskmod
    interp = get_interp()
    interp.collectors.append([])
    try:
        await call(body)
    finally:
        entries = interp.collectors.pop()
    taskmod.register_workflow(interp, name, entries)


def _step(name, body, retry=1, backoff=0.0, rollback=None):
    interp = get_interp()
    if not interp.collectors:
        raise OxThrow(OxErrorValue("'step' can only be used inside a workflow"))
    interp.collectors[-1].append(
        ("step", {"name": name, "body": body, "retry": int(retry),
                  "backoff": float(_secs(backoff)), "rollback": rollback}))


def _hook(kind, body):
    interp = get_interp()
    if not interp.collectors:
        raise OxThrow(OxErrorValue("'on %s' can only be used inside a workflow"
                                   % kind))
    interp.collectors[-1].append(("hook", kind, body))


def _desc(text):
    interp = get_interp()
    if not interp.collectors:
        raise OxThrow(OxErrorValue("'desc' can only be used inside a workflow"))
    interp.collectors[-1].append(("desc", text))


async def _serve(port, options, router):
    from .builtins import servermod
    return await servermod.serve(get_interp(), port, options or {}, router,
                                 None)


def _route(method, path, handler):
    interp = get_interp()
    if not interp.route_collectors:
        raise OxThrow(OxErrorValue("routes can only be declared inside serve"))
    interp.route_collectors[-1].append(("route", method.upper(), path, handler))


def _static(prefix, directory):
    interp = get_interp()
    if not interp.route_collectors:
        raise OxThrow(OxErrorValue("'static' can only be used inside serve"))
    interp.route_collectors[-1].append(("static", prefix, directory))


def _ws(path, handler):
    interp = get_interp()
    if not interp.route_collectors:
        raise OxThrow(OxErrorValue("'ws' can only be used inside serve"))
    interp.route_collectors[-1].append(("ws", path, handler))


def _test(name, timeout, body):  # registered but not auto-run in built apps
    interp = get_interp()
    interp.py_tests.append({"name": name, "timeout": timeout, "fn": body})


def _on(name, handler):
    interp = get_interp()
    interp.events.setdefault(name, []).append(handler)


async def _emit(name, payload=None):
    await get_interp().emit_event(name, payload)


def _secs(v):
    if isinstance(v, Duration):
        return float(v)
    return float(v)


async def load_ox_module(path):
    """Import an .ox module from compiled code (runs it interpreted)."""
    return await get_interp().load_ox_module(path)


def run_compiled(main_fn):
    """Entry point used by zipapps built with `ox build`."""
    import sys
    interp = get_interp()
    try:
        code = asyncio.run(_run_wrapped(main_fn()))
    except OxThrow as t:
        _print_throw(interp, t)
        return 1
    except OxExit as e:
        return e.code
    except KeyboardInterrupt:
        print("")
        return 130
    return code or 0


def _print_throw(interp, exc):
    import sys
    from . import tty
    err = exc.value
    print(tty.red("⨯ error: %s%s" % (err.msg,
                                     " (code %s)" % err.code if err.code else "")),
          file=sys.stderr)
    if err.kind == "verify":
        print(tty.yellow("  (a verify statement failed)"), file=sys.stderr)
    if err.pos:
        f, line, col = err.pos
        from .errors import render_source_line
        print(render_source_line(f, line, col, err.msg, "error",
                                 interp.sources), file=sys.stderr)
    for frame in err.trace[-6:]:
        print(tty.gray("  at %s (%s:%s)" % (frame[0], frame[1], frame[2])),
              file=sys.stderr)
