"""events — introspection & control over the interpreter's event bus."""
from ..values import NativeModule, builtin


def list_events(interp):
    out = {}
    for name, handlers in interp.events.items():
        out[name] = len(handlers)
    return out


def off(interp, name=None):
    """Remove handlers: off("x") removes one event, off() removes all."""
    if name is None:
        n = sum(len(v) for v in interp.events.values())
        interp.events.clear()
        return n
    return len(interp.events.pop(name, []))


async def emit(interp, name, payload=None):
    await interp.emit_event(name, payload)
    return True


def build():
    return NativeModule("events", {
        "list": builtin("list", needs_interp=True)(list_events),
        "off": builtin("off", needs_interp=True)(off),
        "emit": builtin("emit", needs_interp=True)(emit),
    })
