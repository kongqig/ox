"""Standard library registry.

`MODULES` maps module names to NativeModule instances; `make_globals()`
builds the global builtin environment every interpreter starts with.
Modules that need interpreter/context access declare it via the
`needs_interp` / `wants_env` flags (see values.builtin).
"""
from ..values import (BuiltinFunction, Duration, OxErrorValue, Range,
                      builtin, ox_repr, ox_str, truthy, type_name)
from . import asyncmod, cbridge, cryptomod, datamod, eventmod, fsmod, logmod, mathmod, netmod, osmod, pybridge, servermod, taskmod, timemod, verifymod


def _g_print(*args, sep=" "):
    print(sep.join(ox_str(a) for a in args), flush=True)


def _g_len(x):
    if isinstance(x, bool) or x is None:
        raise OxErrorValue("len() expects a string, list, dict or range, got %s"
                           % type_name(x))
    try:
        return len(x)
    except TypeError:
        raise OxErrorValue("len() expects a string, list, dict or range, got %s"
                           % type_name(x))


def _g_type(x):
    return type_name(x)


_NO_ARG = object()  # distinguishes str() from str(null)


def _g_str(x=_NO_ARG):
    # str() with no argument is ""; str(null) is "null" — matching
    # interpolation ("{x}") and repr, which both render null as "null"
    if x is _NO_ARG:
        return ""
    return ox_str(x)


def _g_repr(x=_NO_ARG):
    if x is _NO_ARG:
        return "null"
    return ox_repr(x)


def _g_int(x, base=10):
    if isinstance(x, bool):
        return 1 if x else 0
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        try:
            if s.lower().startswith("0x"):
                return int(s, 16)
            return int(s, base)
        except ValueError:
            raise OxErrorValue("cannot convert %r to int" % x)
    raise OxErrorValue("cannot convert %s to int" % type_name(x))


def _g_float(x):
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.strip())
        except ValueError:
            raise OxErrorValue("cannot convert %r to float" % x)
    raise OxErrorValue("cannot convert %s to float" % type_name(x))


def _g_bool(x=None):
    return truthy(x)


def _g_range(start, end=None, step=1):
    if end is None:
        start, end = 0, start
    for v in (start, end, step):
        if isinstance(v, bool) or not isinstance(v, int):
            raise OxErrorValue("range() bounds must be integers, got %s"
                               % type_name(v))
    if step == 0:
        raise OxErrorValue("range() step cannot be zero")
    return Range(start, end, exclusive=True, step=step)


def _g_error(msg, code=0, data=None):
    return OxErrorValue(ox_str(msg), code=code, data=data)


def _g_exit(code=0):
    from ..errors import OxExit
    raise OxExit(int(code))


async def _g_input(prompt=""):
    import asyncio
    return await asyncio.to_thread(input, prompt)


async def _g_sleep(d):
    import asyncio
    await asyncio.sleep(_seconds(d))


def _seconds(d):
    if isinstance(d, Duration):
        return float(d)
    if isinstance(d, bool) or not isinstance(d, (int, float)):
        raise OxErrorValue("expected a duration (like 2s or 150ms) or number "
                           "of seconds, got %s" % type_name(d))
    return float(d)


async def _g_run(interp, name, only=None, skip=None, dry=False, resume=False):
    from . import taskmod
    return await taskmod.run_workflow(interp, name, only=only, skip=skip,
                                      dry=dry, resume=resume)


async def _g_eval(interp, env, src):
    if not isinstance(src, str):
        raise OxErrorValue("eval() expects source text")
    return await interp.eval_source(src, env)


def _g_compile(src):
    try:
        from ..transpiler import transpile_source
    except ImportError:  # pragma: no cover
        raise OxErrorValue("compiler backend unavailable in this build")
    if not isinstance(src, str):
        raise OxErrorValue("compile() expects source text")
    return transpile_source(src)


def make_globals():
    g = {
        "print": builtin("print")(_g_print),
        "len": builtin("len")(_g_len),
        "type": builtin("type")(_g_type),
        "str": builtin("str")(_g_str),
        "repr": builtin("repr")(_g_repr),
        "int": builtin("int")(_g_int),
        "float": builtin("float")(_g_float),
        "bool": builtin("bool")(_g_bool),
        "range": builtin("range")(_g_range),
        "error": builtin("error")(_g_error),
        "exit": builtin("exit")(_g_exit),
        "input": builtin("input")(_g_input),
        "sh": builtin("sh")(osmod.sh_run),
        "sleep": builtin("sleep")(_g_sleep),
        "run": builtin("run", needs_interp=True)(_g_run),
        "eval": builtin("eval", needs_interp=True, wants_env=True)(_g_eval),
        "compile": builtin("compile")(_g_compile),
    }
    return g


MODULES = {}

MODULES["fs"] = fsmod.build()
MODULES["os"] = osmod.build()
MODULES["env"] = osmod.build_env()
MODULES["log"] = logmod.build()
MODULES["time"] = timemod.build()
MODULES["math"] = mathmod.build()
MODULES["crypto"] = cryptomod.build()
MODULES["verify"] = verifymod.build()
MODULES["data"] = datamod.build()
MODULES["json"] = datamod.build_json()
MODULES["net"] = netmod.build()
MODULES["http"] = netmod.build_http_alias()
MODULES["server"] = servermod.build()
MODULES["wf"] = taskmod.build()
MODULES["co"] = asyncmod.build()
MODULES["events"] = eventmod.build()
MODULES["py"] = pybridge.build()
MODULES["c"] = cbridge.build()
