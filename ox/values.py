"""Value model & runtime semantics for ox.

Everything that defines "how ox values behave" lives here so the interpreter
and the transpiled-code runtime share exactly the same semantics:
  * type_name / truthy / ox_str / ox_repr / ox_eq
  * operator helpers (ox_add, ox_sub, ... comparisons)
  * OxFunction / BuiltinFunction / NativeModule / OxModule / Range /
    Duration / OxErrorValue / BoundMethod
  * call_value / call_method / get_attr_value / method tables
  * to_ox_error — mapping foreign python exceptions to ox errors
"""
import asyncio
import inspect

from .errors import OxThrow

# ---------------------------------------------------------------------------
# core value classes
# ---------------------------------------------------------------------------


class OxErrorValue:
    """An ox error value: created by error(...), thrown by `throw`."""

    def __init__(self, msg, code=0, data=None, kind="error", pos=None, trace=None):
        self.msg = str(msg)
        self.code = code
        self.data = data
        self.kind = kind  # "error" | "verify"
        self.pos = pos    # (file, line, col) or None
        self.trace = trace or []

    def to_dict(self):
        return {"msg": self.msg, "code": self.code, "data": self.data,
                "kind": self.kind}

    def __str__(self):
        return self.msg + (" (code %s)" % self.code if self.code else "")


class Duration(float):
    """A number of seconds with pretty printing (100ms + 2s == 2.1)."""

    def __new__(cls, seconds):
        return super().__new__(cls, seconds)

    def __str__(self):
        v = float(self)
        for unit, secs in (("d", 86400), ("h", 3600), ("m", 60)):
            if v >= secs and v % secs == 0:
                return "%g%s" % (v // secs, unit)
        if v > 0 and v < 1:
            ms = v * 1000
            if ms == int(ms):
                return "%gms" % ms
        return "%gs" % v

    def __repr__(self):
        return str(self)


class Range:
    """Lazy integer range: 0..5 inclusive, 0..<5 exclusive."""

    def __init__(self, start, end, exclusive=False, step=1):
        self.start = start
        self.end = end
        self.exclusive = exclusive
        self.step = step

    def py_range(self):
        last = self.end - (1 if self.exclusive else 0)
        return range(self.start, last + 1, self.step)

    def __iter__(self):
        return iter(self.py_range())

    def __len__(self):
        return len(self.py_range())

    def to_list(self):
        return list(self.py_range())

    def __str__(self):
        return "%s..%s%s" % (self.start, "<" if self.exclusive else "", self.end)


class NO_DEFAULT:
    """Sentinel distinguishing 'parameter has no default' from a default
    whose value is null. Stored in OxFunction.defaults; never escapes to
    ox code (binding either consumes it or raises 'missing argument')."""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "<no default>"


NO_DEFAULT = NO_DEFAULT()


class OxFunction:
    __slots__ = ("name", "params", "defaults", "vararg", "body", "env")

    def __init__(self, name, params, defaults, vararg, body, env):
        self.name = name or "<anonymous>"
        self.params = params
        self.defaults = defaults      # list aligned with params (values)
        self.vararg = vararg
        self.body = body              # Block node
        self.env = env

    def __str__(self):
        return "<fn %s>" % self.name


class BuiltinArgError(Exception):
    pass


class BuiltinFunction:
    """Wraps a python callable so it can be called from ox with ox calling
    conventions (keyword args, arity errors, optional interpreter/env access)."""

    def __init__(self, name, fn, needs_interp=False, wants_env=False):
        self.name = name
        self.fn = fn
        self.needs_interp = needs_interp
        self.wants_env = wants_env
        self.params = []
        self.defaults = {}
        self.vararg = None
        skip = (1 if needs_interp else 0) + (1 if wants_env else 0)
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return
        for i, p in enumerate(sig.parameters.values()):
            if i < skip:
                continue
            pname = p.name
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD,
                          p.KEYWORD_ONLY):
                self.params.append(pname)
                if p.default is not inspect.Signature.empty:
                    self.defaults[pname] = p.default
            elif p.kind == p.VAR_POSITIONAL:
                self.vararg = pname

    def bind(self, args, kwargs):
        pos = {}
        var = []
        for i, a in enumerate(args):
            if i < len(self.params):
                pos[self.params[i]] = a
            elif self.vararg is not None:
                var.append(a)
            else:
                raise BuiltinArgError(
                    "%s() takes at most %d argument%s, got %d" %
                    (self.name, len(self.params),
                     "" if len(self.params) == 1 else "s", len(args) + len(kwargs)))
        for k, v in (kwargs or {}).items():
            if self.vararg is not None or k not in self.params:
                raise BuiltinArgError(
                    "%s() got an unexpected keyword argument '%s'" % (self.name, k))
            if k in pos:
                raise BuiltinArgError(
                    "%s() got duplicate value for '%s'" % (self.name, k))
            pos[k] = v
        ordered = []
        for i, p in enumerate(self.params):
            if p in pos:
                ordered.append(pos[p])
            elif p in self.defaults:
                ordered.append(self.defaults[p])
            else:
                raise BuiltinArgError(
                    "%s() missing required argument '%s'" % (self.name, p))
        return ordered, var

    def __str__(self):
        return "<builtin %s>" % self.name


class NativeModule:
    __slots__ = ("name", "members")

    def __init__(self, name, members):
        self.name = name
        self.members = members

    def __str__(self):
        return "<module %s>" % self.name


class OxModule:
    __slots__ = ("name", "members", "path")

    def __init__(self, name, members, path=None):
        self.name = name
        self.members = members
        self.path = path

    def __str__(self):
        return "<module %s>" % self.name


class BoundMethod:
    __slots__ = ("obj", "name")

    def __init__(self, obj, name):
        self.obj = obj
        self.name = name

    def __str__(self):
        return "<method %s>" % self.name


def builtin(name=None, needs_interp=False, wants_env=False, module=None):
    """Decorator turning a python function into a BuiltinFunction."""
    def deco(fn):
        return BuiltinFunction(name or fn.__name__, fn,
                               needs_interp=needs_interp, wants_env=wants_env)
    return deco


# ---------------------------------------------------------------------------
# type names, truthiness, printing, equality
# ---------------------------------------------------------------------------

def type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, Duration):
        return "duration"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, (OxFunction, BuiltinFunction, BoundMethod)):
        return "fn"
    if isinstance(v, (NativeModule, OxModule)):
        return "module"
    if isinstance(v, Range):
        return "range"
    if isinstance(v, OxErrorValue):
        return "error"
    if isinstance(v, asyncio.Task):
        return "task"
    if isinstance(v, asyncio.Future):
        return "task"
    return type(v).__name__.lower()


def truthy(v):
    if v is None or v is False:
        return False
    if v is True:
        return True
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, (str, list, dict)):
        return len(v) > 0
    if isinstance(v, Range):
        return len(v) > 0
    return True


def _fmt_num(v):
    if isinstance(v, Duration):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    f = repr(float(v))
    return f


def ox_repr(v, depth=0):
    if depth > 8:
        return "..."
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, bool) or v is None:
        return "true" if v is True else ("false" if v is False else "null")
    if isinstance(v, (int, float)):
        return _fmt_num(v)
    if isinstance(v, list):
        return "[" + ", ".join(ox_repr(x, depth + 1) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (ox_repr(k, depth + 1), ox_repr(x, depth + 1))
                               for k, x in v.items()) + "}"
    if isinstance(v, Range):
        return str(v)
    if isinstance(v, OxErrorValue):
        return "error(%s)" % ox_repr(v.msg)
    if isinstance(v, (OxFunction, BuiltinFunction, BoundMethod)):
        return str(v)
    if isinstance(v, (NativeModule, OxModule)):
        return str(v)
    if isinstance(v, asyncio.Task):
        return "<task %s>" % ("done" if v.done() else "pending")
    if isinstance(v, bytes):
        return "bytes(%d)" % len(v)
    return str(v)


def ox_str(v):
    if isinstance(v, str):
        return v
    if isinstance(v, bool) or v is None:
        return "true" if v is True else ("false" if v is False else "null")
    if isinstance(v, (int, float)):
        return _fmt_num(v)
    if isinstance(v, OxErrorValue):
        return str(v)
    return ox_repr(v)


def ox_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if type(a) is not type(b):
        if isinstance(a, Range) and isinstance(b, Range):
            pass
        elif not (isinstance(a, str) and isinstance(b, str)):
            # allow list==list / dict==dict below, others must match types
            if not (isinstance(a, list) and isinstance(b, list)) and \
               not (isinstance(a, dict) and isinstance(b, dict)):
                return False
    if isinstance(a, str):
        return a == b
    if a is None:
        return b is None
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(ox_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a.keys()) == set(b.keys()) and all(ox_eq(a[k], b[k]) for k in a)
    if isinstance(a, Range) and isinstance(b, Range):
        return (a.start, a.end, a.exclusive, a.step) == \
               (b.start, b.end, b.exclusive, b.step)
    return a is b


def ox_cmp(a, b, op):
    if isinstance(a, bool) or isinstance(b, bool):
        raise TypeError("cannot compare %s and %s" % (type_name(a), type_name(b)))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return op(a, b)
    if isinstance(a, str) and isinstance(b, str):
        return op(a, b)
    raise TypeError("cannot compare %s and %s" % (type_name(a), type_name(b)))


# ---------------------------------------------------------------------------
# operator helpers (shared by interpreter & transpiled runtime)
# ---------------------------------------------------------------------------

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _dur(v):
    return isinstance(v, Duration)


def _mk(res, dur):
    return Duration(res) if dur else res


def ox_add(a, b):
    if isinstance(a, str):
        return a + ox_str(b)
    if isinstance(b, str):
        raise TypeError("cannot add %s and str (put the string first to "
                        "concatenate)" % type_name(a))
    if _num(a) and _num(b):
        return _mk(a + b, _dur(a) or _dur(b))
    if isinstance(a, list) and isinstance(b, list):
        return a + b
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        out.update(b)
        return out
    raise TypeError("cannot add %s and %s" % (type_name(a), type_name(b)))


def ox_sub(a, b):
    if _num(a) and _num(b):
        return _mk(a - b, _dur(a) or _dur(b))
    raise TypeError("cannot subtract %s from %s" % (type_name(b), type_name(a)))


def ox_mul(a, b):
    if _num(a) and _num(b):
        return _mk(a * b, _dur(a) or _dur(b))
    if isinstance(a, str) and _num(b):
        return a * int(b)
    if isinstance(a, list) and _num(b):
        return a * int(b)
    raise TypeError("cannot multiply %s and %s" % (type_name(a), type_name(b)))


def ox_div(a, b):
    if _num(a) and _num(b):
        if b == 0:
            raise ZeroDivisionError("division by zero")
        return _mk(a / b, _dur(a) or _dur(b))
    raise TypeError("cannot divide %s by %s" % (type_name(a), type_name(b)))


def ox_floordiv(a, b):
    if _num(a) and _num(b):
        if b == 0:
            raise ZeroDivisionError("integer division by zero")
        return _mk(a // b, _dur(a) or _dur(b))
    raise TypeError("cannot divide %s by %s" % (type_name(a), type_name(b)))


def ox_mod(a, b):
    if _num(a) and _num(b):
        if b == 0:
            raise ZeroDivisionError("modulo by zero")
        return _mk(a % b, _dur(a) or _dur(b))
    raise TypeError("cannot take %s modulo %s" % (type_name(a), type_name(b)))


def ox_pow(a, b):
    if _num(a) and _num(b):
        return _mk(a ** b, _dur(a) or _dur(b))
    raise TypeError("cannot raise %s to %s" % (type_name(a), type_name(b)))


def ox_neg(a):
    if _num(a):
        return _mk(-a, _dur(a))
    raise TypeError("cannot negate %s" % type_name(a))


def to_ox_error(exc):
    """Map a foreign python exception to an OxErrorValue."""
    if isinstance(exc, OxErrorValue):
        return exc
    if isinstance(exc, OxThrow):
        return exc.value
    if isinstance(exc, RecursionError):
        return OxErrorValue("stack overflow: recursion too deep")
    if isinstance(exc, ZeroDivisionError):
        return OxErrorValue(str(exc) or "division by zero")
    if isinstance(exc, asyncio.TimeoutError):
        return OxErrorValue("operation timed out")
    if isinstance(exc, asyncio.CancelledError):
        return OxErrorValue("task cancelled")
    if isinstance(exc, FileNotFoundError):
        return OxErrorValue("no such file or directory: %s" % exc.filename or exc)
    if isinstance(exc, PermissionError):
        return OxErrorValue("permission denied: %s" % exc.filename or exc)
    if isinstance(exc, IsADirectoryError):
        return OxErrorValue("is a directory: %s" % exc.filename or exc)
    if isinstance(exc, OSError):
        return OxErrorValue("io error: %s" % exc)
    if isinstance(exc, (TypeError, ValueError, KeyError, IndexError, AttributeError)):
        return OxErrorValue("%s: %s" % (type(exc).__name__.lower(), exc))
    return OxErrorValue("%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------
# method call machinery
# ---------------------------------------------------------------------------

def method_table(v):
    if isinstance(v, dict):
        return DICT_METHODS
    if isinstance(v, list):
        return LIST_METHODS
    if isinstance(v, str):
        return STR_METHODS
    if isinstance(v, bool):
        return BOOL_METHODS
    if isinstance(v, (int, float)):
        return NUM_METHODS
    if isinstance(v, Range):
        return RANGE_METHODS
    return None


def get_attr_value(obj, name):
    """Attribute READ: d.k / mod.fn / "s".upper (bound method) / py bridge."""
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        if name in DICT_METHODS:
            return BoundMethod(obj, name)
        raise KeyError("dict has no key '%s'" % name)
    if isinstance(obj, (NativeModule, OxModule)):
        if name in obj.members:
            return obj.members[name]
        raise KeyError("module '%s' has no function '%s'" % (obj.name, name))
    if isinstance(obj, OxErrorValue):
        fields = {"msg": obj.msg, "code": obj.code, "data": obj.data, "kind": obj.kind}
        if name in fields:
            return fields[name]
        raise KeyError("error has no field '%s'" % name)
    if isinstance(obj, Range):
        fields = {"start": obj.start, "end": obj.end, "exclusive": obj.exclusive,
                  "step": obj.step}
        if name in fields:
            return fields[name]
        if name in RANGE_METHODS:
            return BoundMethod(obj, name)
        raise KeyError("range has no field '%s'" % name)
    table = method_table(obj)
    if table is not None and name in table:
        return BoundMethod(obj, name)
    # generic python object (py bridge, server handles, ws connections ...)
    if name.startswith("_"):
        raise KeyError("private attribute '%s'" % name)
    if hasattr(obj, name):
        return getattr(obj, name)
    raise KeyError("%s has no attribute '%s'" % (type_name(obj), name))


def set_attr_value(obj, name, value):
    if isinstance(obj, dict):
        obj[name] = value
        return
    if name.startswith("_"):
        raise KeyError("private attribute '%s'" % name)
    if hasattr(obj, "__dict__") or hasattr(obj, name):
        try:
            setattr(obj, name, value)
            return
        except (AttributeError, TypeError):
            pass
    raise TypeError("cannot set '%s' on %s" % (name, type_name(obj)))


def getitem(obj, index):
    if isinstance(obj, list):
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("list index must be int, got %s" % type_name(index))
        if -len(obj) <= index < len(obj):
            return obj[index]
        raise IndexError("list index %s out of range (len %s)" % (index, len(obj)))
    if isinstance(obj, str):
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("string index must be int, got %s" % type_name(index))
        if -len(obj) <= index < len(obj):
            return obj[index]
        raise IndexError("string index %s out of range (len %s)" % (index, len(obj)))
    if isinstance(obj, dict):
        if isinstance(obj, dict) and index in obj:
            return obj[index]
        raise KeyError("dict has no key %s" % ox_repr(index))
    raise TypeError("cannot index %s" % type_name(obj))


def setitem(obj, index, value):
    if isinstance(obj, list):
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("list index must be int, got %s" % type_name(index))
        if not (-len(obj) <= index < len(obj)):
            raise IndexError("list index %s out of range (len %s)" % (index, len(obj)))
        obj[index] = value
        return
    if isinstance(obj, dict):
        try:
            obj[index] = value
            return
        except TypeError:
            raise TypeError("unhashable dict key of type %s" % type_name(index))
    raise TypeError("cannot assign into %s" % type_name(obj))


async def call_value(interp, fn, args, kwargs=None, env=None):
    """Call any ox-callable value with ox calling conventions."""
    kwargs = kwargs or {}
    if isinstance(fn, OxFunction):
        return await interp.call_function(fn, args, kwargs)
    if isinstance(fn, BuiltinFunction):
        pre = []
        if fn.needs_interp:
            pre.append(interp)
        if fn.wants_env:
            pre.append(env if env is not None else interp.globals)
        pos, var = fn.bind(args, kwargs)
        try:
            result = fn.fn(*pre, *pos, *var)
        except BuiltinArgError as e:
            raise OxThrow(OxErrorValue(str(e)))
        if inspect.isawaitable(result):
            result = await result
        return result
    if isinstance(fn, BoundMethod):
        return await call_method(interp, fn.obj, fn.name, args, kwargs)
    if isinstance(fn, (NativeModule, OxModule)):
        raise OxThrow(OxErrorValue("module '%s' is not callable" % fn.name))
    if callable(fn):  # python bridge value
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    raise OxThrow(OxErrorValue("value of type %s is not callable" % type_name(fn)))


async def call_method(interp, obj, name, args, kwargs=None):
    kwargs = kwargs or {}
    if isinstance(obj, (NativeModule, OxModule)):
        # module member call: fs.exists(...) == call(fs.exists)
        if name in obj.members:
            return await call_value(interp, obj.members[name], args, kwargs)
        raise OxThrow(OxErrorValue("module '%s' has no function '%s'"
                                   % (obj.name, name)))
    table = method_table(obj)
    if table is not None and name in table:
        try:
            result = table[name](interp, obj, *args, **kwargs)
        except BuiltinArgError as e:
            raise OxThrow(OxErrorValue(str(e)))
        except TypeError as e:
            msg = str(e)
            if "positional argument" in msg or "keyword argument" in msg or \
               "argument" in msg:
                raise OxThrow(OxErrorValue("%s.%s: %s" % (type_name(obj), name, msg)))
            raise
        if inspect.isawaitable(result):
            result = await result
        return result
    if isinstance(obj, asyncio.Task):
        if name == "result":
            raise OxThrow(OxErrorValue(
                "task.result() would block — use 'await task' instead"))
        if name == "done":
            return obj.done()
        if name == "cancel":
            obj.cancel()
            return True
        if name == "id":
            return id(obj)
    if isinstance(obj, OxErrorValue):
        if name == "to_dict":
            return obj.to_dict()
    # generic python object method (bridged)
    if hasattr(obj, name):
        attr = getattr(obj, name)
        if callable(attr):
            if name.startswith("_"):
                raise OxThrow(OxErrorValue("private method '%s'" % name))
            result = attr(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        if not args and not kwargs:
            return attr
        raise OxThrow(OxErrorValue("'%s' is a property, not a method" % name))
    raise OxThrow(OxErrorValue("%s has no method '%s'" % (type_name(obj), name)))


# ---------------------------------------------------------------------------
# built-in method tables
# ---------------------------------------------------------------------------

def m(fn):
    fn._ox_method = True
    return fn


def _unique(o):
    seen = []
    out = []
    for x in o:
        if not any(ox_eq(x, s) for s in seen):
            seen.append(x)
            out.append(x)
    return out


def _flatten(o, deep):
    out = []
    for x in o:
        if isinstance(x, list):
            out.extend(_flatten(x, True) if deep else x)
        else:
            out.append(x)
    return out


def _sort_key_fn(key, interp=None):
    if key is None:
        return None
    if isinstance(key, str):
        return lambda item: getitem(item, key) if isinstance(item, dict) else item
    if isinstance(key, (OxFunction, BuiltinFunction)):
        # ox functions are not python-callable; route them through
        # call_value (returns a coroutine that _list_sort awaits)
        if interp is None:
            raise TypeError("sort key function has no interpreter context")
        return lambda item: call_value(interp, key, [item])
    if callable(key):
        return key
    raise TypeError("sort key must be a function or a dict-key string")


async def _list_map(interp, o, fn):
    return [await call_value(interp, fn, [x]) for x in o]


async def _list_filter(interp, o, fn):
    return [x for x in o if truthy(await call_value(interp, fn, [x]))]


async def _list_each(interp, o, fn):
    for x in o:
        await call_value(interp, fn, [x])
    return o


async def _list_find(interp, o, fn):
    for x in o:
        if truthy(await call_value(interp, fn, [x])):
            return x
    return None


async def _list_find_index(interp, o, fn):
    for k, x in enumerate(o):
        if truthy(await call_value(interp, fn, [x])):
            return k
    return -1


async def _list_any(interp, o, fn):
    return any(truthy(await call_value(interp, fn, [x])) for x in o)


async def _list_all(interp, o, fn):
    return all(truthy(await call_value(interp, fn, [x])) for x in o)


async def _list_reduce(interp, o, fn, init=None):
    if not o and init is None:
        return None
    if init is None:
        acc, rest = o[0], o[1:]
    else:
        acc, rest = init, list(o)
    for x in rest:
        acc = await call_value(interp, fn, [acc, x])
    return acc


async def _list_sort(interp, o, key=None, reverse=False):
    kf = _sort_key_fn(key, interp)
    if kf is None:
        pairs = [(x, x) for x in o]
    else:
        pairs = []
        for x in o:
            k = kf(x)
            if inspect.isawaitable(k):
                k = await k
            pairs.append((k, x))
    pairs.sort(key=lambda p: p[0], reverse=reverse)
    return [x for _, x in pairs]


async def _list_sort_by(interp, o, key, reverse=False):
    return await _list_sort(interp, o, key=key, reverse=reverse)


LIST_METHODS = {
    "len":        m(lambda i, o: len(o)),
    "empty":      m(lambda i, o: len(o) == 0),
    "push":       m(lambda i, o, v: (o.append(v), o)[1]),
    "push_all":   m(lambda i, o, src: (o.extend(list(src)), o)[1]),
    "pop":        m(lambda i, o: o.pop() if o else None),
    "shift":      m(lambda i, o: o.pop(0) if o else None),
    "unshift":    m(lambda i, o, v: (o.insert(0, v), o)[1]),
    "insert":     m(lambda i, o, idx, v: (o.insert(idx, v), o)[1]),
    "remove":     m(lambda i, o, v: _list_remove(o, v)),
    "remove_at":  m(lambda i, o, idx: o.pop(idx)),
    "index":      m(lambda i, o, v: o.index(v) if _contains_eq(o, v) else -1),
    "has":        m(lambda i, o, v: _contains_eq(o, v)),
    "contains":   m(lambda i, o, v: _contains_eq(o, v)),
    "count":      m(lambda i, o, v: sum(1 for x in o if ox_eq(x, v))),
    "join":       m(lambda i, o, sep=", ": sep.join(ox_str(x) for x in o)),
    "concat":     m(lambda i, o, other: o + list(other)),
    "first":      m(lambda i, o: o[0] if o else None),
    "last":       m(lambda i, o: o[-1] if o else None),
    "slice":      m(lambda i, o, a, b=None: o[a:b]),
    "reverse":    m(lambda i, o: list(reversed(o))),
    "unique":     m(lambda i, o: _unique(o)),
    "flatten":    m(lambda i, o, deep=False: _flatten(o, deep)),
    "clone":      m(lambda i, o: list(o)),
    "sum":        m(lambda i, o: sum(x for x in o if _num(x))),
    "min":        m(lambda i, o: min(o) if o else None),
    "max":        m(lambda i, o: max(o) if o else None),
    "avg":        m(lambda i, o: sum(o) / len(o) if o else None),
    "zip":        m(lambda i, o, other: [[a, b] for a, b in zip(o, other)]),
    "indexes":    m(lambda i, o: list(range(len(o)))),
    "map":        m(_list_map),
    "filter":     m(_list_filter),
    "each":       m(_list_each),
    "find":       m(_list_find),
    "find_index": m(_list_find_index),
    "any":        m(_list_any),
    "all":        m(_list_all),
    "reduce":     m(_list_reduce),
    "sort":       m(_list_sort),
    "sort_by":    m(_list_sort_by),
}


def _contains_eq(o, v):
    return any(ox_eq(x, v) for x in o)


def _list_remove(o, v):
    for k, x in enumerate(o):
        if ox_eq(x, v):
            del o[k]
            return True
    return False


# ---- string ----------------------------------------------------------------

STR_METHODS = {
    "len":        m(lambda i, o: len(o)),
    "empty":      m(lambda i, o: len(o) == 0),
    "upper":      m(lambda i, o: o.upper()),
    "lower":      m(lambda i, o: o.lower()),
    "trim":       m(lambda i, o: o.strip()),
    "trim_left":  m(lambda i, o: o.lstrip()),
    "trim_right": m(lambda i, o: o.rstrip()),
    "split":      m(lambda i, o, sep=None: o.split(sep) if sep else o.split()),
    "split_lines": m(lambda i, o: o.splitlines()),
    "replace":    m(lambda i, o, a, b: o.replace(a, b)),
    "startswith": m(lambda i, o, s: o.startswith(s)),
    "endswith":   m(lambda i, o, s: o.endswith(s)),
    "has":        m(lambda i, o, s: s in o),
    "contains":   m(lambda i, o, s: s in o),
    "index":      m(lambda i, o, s: o.find(s)),
    "slice":      m(lambda i, o, a, b=None: o[a:b]),
    "repeat":     m(lambda i, o, n: o * int(n)),
    "pad_left":   m(lambda i, o, n, ch=" ": o.rjust(int(n), ch)),
    "pad_right":  m(lambda i, o, n, ch=" ": o.ljust(int(n), ch)),
    "chars":      m(lambda i, o: list(o)),
    "reverse":    m(lambda i, o: o[::-1]),
    "first":      m(lambda i, o: o[0] if o else None),
    "last":       m(lambda i, o: o[-1] if o else None),
    "capitalize": m(lambda i, o: o.capitalize()),
    "title":      m(lambda i, o: o.title()),
    "swapcase":   m(lambda i, o: o.swapcase()),
}


# ---- dict ------------------------------------------------------------------

async def _dict_map_values(interp, o, fn):
    out = {}
    for k, v in o.items():
        out[k] = await call_value(interp, fn, [v, k])
    return out


async def _dict_filter(interp, o, fn):
    out = {}
    for k, v in o.items():
        if truthy(await call_value(interp, fn, [v, k])):
            out[k] = v
    return out


def _deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


DICT_METHODS = {
    "len":        m(lambda i, o: len(o)),
    "empty":      m(lambda i, o: len(o) == 0),
    "keys":       m(lambda i, o: list(o.keys())),
    "values":     m(lambda i, o: list(o.values())),
    "items":      m(lambda i, o: [[k, v] for k, v in o.items()]),
    "has":        m(lambda i, o, k: k in o),
    "contains":   m(lambda i, o, k: k in o),
    "get":        m(lambda i, o, k, default=None: o.get(k, default)),
    "set":        m(lambda i, o, k, v: (o.__setitem__(k, v), o)[1]),
    "del":        m(lambda i, o, k: o.pop(k, None)),
    "merge":      m(lambda i, o, other, deep=False:
                     _deep_merge(o, other) if deep else {**o, **other}),
    "update":     m(lambda i, o, other: (o.update(other), o)[1]),
    "pick":       m(lambda i, o, keys: {k: o[k] for k in keys if k in o}),
    "omit":       m(lambda i, o, keys: {k: v for k, v in o.items() if k not in keys}),
    "clone":      m(lambda i, o: dict(o)),
    "sort_keys":  m(lambda i, o: {k: o[k] for k in sorted(o.keys(), key=ox_str)}),
    "map_values": m(_dict_map_values),
    "filter":     m(_dict_filter),
    "first":      m(lambda i, o: [[k, v] for k, v in o.items()][0] if o else None),
}


# ---- numbers ---------------------------------------------------------------

async def _num_times(interp, o, fn):
    for k in range(int(o)):
        await call_value(interp, fn, [k])
    return o


NUM_METHODS = {
    "abs":   m(lambda i, o: abs(o)),
    "floor": m(lambda i, o: _mk(int(o // 1), _dur(o))),
    "ceil":  m(lambda i, o: _mk(int(-(-o // 1)), _dur(o))),
    "round": m(lambda i, o, n=0: _mk(round(o, int(n)), _dur(o))),
    "clamp": m(lambda i, o, lo, hi: max(lo, min(hi, o))),
    "times": m(_num_times),
}


BOOL_METHODS = {
    "to_int": m(lambda i, o: 1 if o else 0),
}


# ---- range -----------------------------------------------------------------

RANGE_METHODS = {
    "len":     m(lambda i, o: len(o)),
    "to_list": m(lambda i, o: o.to_list()),
    "empty":   m(lambda i, o: len(o) == 0),
}
