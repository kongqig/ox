"""c — FFI bridge to dynamic C libraries via ctypes.

    import c
    let libm = c.lib("m")
    let pow = libm.fn("pow", [c.double, c.double], c.double)
    print(pow(2.0, 10.0))          # 1024.0

    let libc = c.lib("c")
    let strlen = libc.fn("strlen", [c.char_p], c.size_t)
    print(strlen("hello"))         # 5
"""
import ctypes
import ctypes.util

from ..values import NativeModule, builtin, ox_str


class CType:
    def __init__(self, name, pytype, is_str=False):
        self.name = name
        self.pytype = pytype
        self.is_str = is_str

    def __repr__(self):
        return "<c.%s>" % self.name


TYPES = {
    "int": CType("int", ctypes.c_int),
    "uint": CType("uint", ctypes.c_uint),
    "long": CType("long", ctypes.c_long),
    "ulong": CType("ulong", ctypes.c_ulong),
    "float": CType("float", ctypes.c_float),
    "double": CType("double", ctypes.c_double),
    "bool": CType("bool", ctypes.c_bool),
    "char_p": CType("char_p", ctypes.c_char_p, is_str=True),
    "void_p": CType("void_p", ctypes.c_void_p),
    "size_t": CType("size_t", ctypes.c_size_t),
    "int8": CType("int8", ctypes.c_int8),
    "int16": CType("int16", ctypes.c_int16),
    "int32": CType("int32", ctypes.c_int32),
    "int64": CType("int64", ctypes.c_int64),
    "uint8": CType("uint8", ctypes.c_uint8),
    "uint16": CType("uint16", ctypes.c_uint16),
    "uint32": CType("uint32", ctypes.c_uint32),
    "uint64": CType("uint64", ctypes.c_uint64),
}


class LibObj:
    def __init__(self, lib, name):
        self._lib = lib
        self.name = name

    def fn(self, fname, arg_types=None, ret=None):
        try:
            func = getattr(self._lib, ox_str(fname))
        except AttributeError:
            raise ValueError("symbol '%s' not found in library '%s'"
                             % (fname, self.name))
        if arg_types:
            types = [_resolve(t) for t in arg_types]
            func.argtypes = [t.pytype for t in types]
        else:
            types = []
        if ret is not None:
            rt = _resolve(ret)
            func.restype = rt.pytype
        else:
            rt = CType("int", ctypes.c_int)

        def wrapper(*args):
            conv = []
            for t, a in zip(types, args):
                conv.append(_convert(t, a))
            try:
                out = func(*conv)
            except ctypes.ArgumentError as e:
                raise ValueError("%s(%s): %s" % (fname, ", ".join(
                    _short(a) for a in args), e))
            return _unconvert(rt, out)

        wrapper.__name__ = ox_str(fname)
        wrapper._ox_ffi_name = fname
        return wrapper

    def __repr__(self):
        return "<c.lib %s>" % self.name


def _short(a):
    s = ox_str(a)
    return s if len(s) < 20 else s[:17] + "..."


def _resolve(t):
    if isinstance(t, CType):
        return t
    if isinstance(t, str) and t in TYPES:
        return TYPES[t]
    raise ValueError("unknown C type %r (use c.int, c.double, c.char_p, ...)"
                     % (t,))


def _convert(t, a):
    if t.is_str:
        if isinstance(a, str):
            return a.encode("utf-8")
        if isinstance(a, bytes):
            return a
    if isinstance(a, bool):
        return int(a)
    if isinstance(a, (int, float)):
        return a
    raise ValueError("cannot pass %r as %s" % (a, t.name))


def _unconvert(t, out):
    if t.is_str and isinstance(out, bytes):
        return out.decode("utf-8", errors="replace")
    if isinstance(out, (int, float, bool)):
        return out
    if out is None:
        return None
    return out


def load_lib(name):
    name = ox_str(name)
    path = None
    if "/" in name or name.endswith(".so") or name.endswith(".dylib") or \
            name.endswith(".dll"):
        path = name
    else:
        path = ctypes.util.find_library(name)
    if path is None:
        # try the raw name (works when LD_LIBRARY_PATH is set)
        path = name
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        raise ValueError("cannot load C library '%s': %s" % (name, e))
    return LibObj(lib, name)


def build():
    members = {k: v for k, v in TYPES.items()}
    members["lib"] = builtin("lib")(load_lib)
    return NativeModule("c", members)
