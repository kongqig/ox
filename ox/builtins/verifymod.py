"""verify — test-friendly assertions (the `verify` statement is the core)."""
from ..errors import OxThrow, SkipTest
from ..values import NativeModule, OxErrorValue, builtin, ox_eq, ox_repr, truthy


def _fail(msg):
    raise OxThrow(OxErrorValue(msg, kind="verify"))


def v_skip(msg=None):
    """Mark the current test as skipped (e.g. tooling unavailable)."""
    raise SkipTest(ox_repr(msg) if msg is not None else "skipped")


def v_eq(a, b, msg=None):
    if not ox_eq(a, b):
        _fail(msg or ("expected %s == %s" % (ox_repr(a), ox_repr(b))))


def v_ne(a, b, msg=None):
    if ox_eq(a, b):
        _fail(msg or ("expected %s != %s" % (ox_repr(a), ox_repr(b))))


def v_true(x, msg=None):
    if not truthy(x):
        _fail(msg or ("expected truthy value, got %s" % ox_repr(x)))


def v_false(x, msg=None):
    if truthy(x):
        _fail(msg or ("expected falsy value, got %s" % ox_repr(x)))


def v_has(coll, v, msg=None):
    if isinstance(coll, dict):
        ok = v in coll
    elif isinstance(coll, (list, str)):
        ok = any(ox_eq(x, v) for x in coll)
    else:
        _fail("has() expects a list, dict or string")
        return
    if not ok:
        _fail(msg or ("expected collection to contain %s" % ox_repr(v)))


def v_approx(a, b, eps=1e-9, msg=None):
    try:
        ok = abs(float(a) - float(b)) <= eps
    except (TypeError, ValueError):
        _fail("approx() expects numbers, got %s and %s" % (ox_repr(a), ox_repr(b)))
        return
    if not ok:
        _fail(msg or ("expected %s ~= %s (eps %s)" % (ox_repr(a), ox_repr(b),
                                                      ox_repr(eps))))


async def v_throws(interp, fn, msg=None):
    from ..values import call_value
    try:
        await call_value(interp, fn, [], {})
    except OxThrow as t:
        return t.value
    _fail(msg or "expected an error to be thrown, but nothing was raised")


def build():
    return NativeModule("verify", {
        "eq": builtin("eq")(v_eq),
        "ne": builtin("ne")(v_ne),
        "true": builtin("true")(v_true),
        "false": builtin("false")(v_false),
        "has": builtin("has")(v_has),
        "approx": builtin("approx")(v_approx),
        "throws": builtin("throws", needs_interp=True)(v_throws),
        "skip": builtin("skip")(v_skip),
    })
