"""ox repl — interactive session."""
import asyncio

from . import __version__, tty
from .errors import OxExit, OxThrow, OxToolError
from .interpreter import Interpreter

BANNER = """%(bold)sox%(reset)s %(version)s — a sturdy little language for automation
Type ox statements; Ctrl+D or .exit to leave, .help for tips.
""" % {"bold": tty.BOLD or "", "reset": tty.RESET or "",
       "version": __version__}

TIPS = """  .exit / .quit      leave the repl
  let x = 5           variables persist between inputs
  fn f(n) { n * 2 }   functions too
  spawn { work() }    concurrency works here as well
  import fs           stdlib is one import away
  1 + 2               expression results are printed
"""


def _is_incomplete_error(exc):
    msg = str(exc)
    return "end of file" in msg


def repl():
    print(BANNER)
    interp = Interpreter(file="<repl>")
    loop = asyncio.new_event_loop()
    buffer = []
    try:
        while True:
            try:
                prompt = "ox> " if not buffer else "...> "
                line = loop.run_until_complete(
                    asyncio.to_thread(input, prompt))
            except EOFError:
                print("")
                break
            except KeyboardInterrupt:
                print("")
                buffer = []
                continue
            stripped = line.strip()
            if not buffer:
                if stripped in (".exit", ".quit", "exit", "quit"):
                    break
                if stripped == ".help":
                    print(TIPS)
                    continue
                if stripped == "":
                    continue
            buffer.append(line)
            src = "\n".join(buffer)
            try:
                result = loop.run_until_complete(
                    interp.eval_source(src, interp.globals))
                if result is not None:
                    from .values import ox_repr
                    print(tty.cyan(ox_repr(result)))
                buffer = []
            except OxToolError as e:
                if _is_incomplete_error(e):
                    continue  # keep reading multiline input
                from .errors import render_source_line
                print(render_source_line("<repl>", e.line, e.col, e.message,
                                         "error", {"<repl>": src}))
                buffer = []
            except OxThrow as t:
                _print_error(t.value, src)
                buffer = []
            except OxExit:
                print(tty.gray("bye"))
                break
            except KeyboardInterrupt:
                print(tty.yellow("(interrupted)"))
                buffer = []
            except Exception as e:  # noqa: BLE001
                print(tty.red("error: %s" % e))
                buffer = []
    finally:
        loop.close()
    return 0


def _print_error(err, src):
    print(tty.red("⨯ %s" % (err.msg or "error")))
    if err.pos:
        from .errors import render_source_line
        f, line, col = err.pos
        print(render_source_line(f, line, col, err.msg, "error",
                                 {"<repl>": src}))
