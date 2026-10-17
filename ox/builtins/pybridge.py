"""py — direct access to the Python ecosystem.

    import py
    let math = py.import("math")
    print(math.sqrt(2))
    print(py.eval("sorted([3, 1, 2])"))
    py.pip("install requests")        # manage packages for scripts
"""
import asyncio
import importlib
import subprocess
import sys

from ..values import NativeModule, builtin, ox_str


def py_import(name):
    name = ox_str(name)
    try:
        return importlib.import_module(name)
    except ImportError:
        pass
    # attribute-path import, e.g. "datetime.datetime" (a class)
    if "." in name:
        head, _, rest = name.partition(".")
        try:
            obj = importlib.import_module(head)
        except ImportError as e:
            raise ValueError("cannot import python module '%s': %s" % (head, e))
        try:
            for part in rest.split("."):
                obj = getattr(obj, part)
        except AttributeError:
            raise ValueError("'%s' has no attribute '%s'" % (head, rest))
        return obj
    raise ValueError("cannot import python module '%s'" % name)


_NS = {"__builtins__": __builtins__}


def py_eval(src):
    try:
        return eval(ox_str(src), _NS)
    except Exception as e:  # noqa: BLE001 — surface as ox error
        raise ValueError("py.eval failed: %s: %s" % (type(e).__name__, e))


def py_exec(src):
    try:
        exec(ox_str(src), _NS)
        return True
    except Exception as e:  # noqa: BLE001
        raise ValueError("py.exec failed: %s: %s" % (type(e).__name__, e))


def py_exec_file(path):
    try:
        with open(ox_str(path), encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, ox_str(path), "exec"), _NS)
        return True
    except OSError as e:
        raise ValueError("cannot read %s: %s" % (path, e))
    except Exception as e:  # noqa: BLE001
        raise ValueError("py.exec_file failed: %s: %s" % (type(e).__name__, e))


def py_version():
    return sys.version.split()[0]


async def py_pip(args):
    """Run `python -m pip <args>`; returns an sh-style result dict."""
    if isinstance(args, list):
        cmd = " ".join(ox_str(a) for a in args)
    else:
        cmd = ox_str(args)

    def work():
        try:
            r = subprocess.run([sys.executable, "-m", "pip"] + cmd.split(),
                               capture_output=True, text=True, timeout=600)
            return {"ok": r.returncode == 0, "code": r.returncode,
                    "out": r.stdout, "err": r.stderr, "cmd": "pip " + cmd}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "code": -1, "out": "", "err": str(e),
                    "cmd": "pip " + cmd}

    return await asyncio.to_thread(work)


def py_callable(v):
    return callable(v)


def build():
    return NativeModule("py", {
        "import": builtin("import")(py_import),
        "eval": builtin("eval")(py_eval),
        "exec": builtin("exec")(py_exec),
        "exec_file": builtin("exec_file")(py_exec_file),
        "pip": builtin("pip")(py_pip),
        "version": builtin("version")(py_version),
        "callable": builtin("callable")(py_callable),
    })
