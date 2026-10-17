"""Error types for the ox toolchain (python-side errors + runtime signals)."""
from . import tty


class OxToolError(Exception):
    """Base class for toolchain errors (lex/parse/analyze) — never user-thrown."""

    def __init__(self, message, line=None, col=None, file=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.file = file

    def where(self):
        if self.line is None:
            return self.file or "<ox>"
        loc = "%s:%s:%s" % (self.file or "<ox>", self.line, self.col or 0)
        return loc


class LexError(OxToolError):
    pass


class ParseError(OxToolError):
    pass


class AnalyzeError(OxToolError):
    """Static-analysis error (severe)."""

    def __init__(self, message, line=None, col=None, file=None, severity="error"):
        super().__init__(message, line, col, file)
        self.severity = severity


class AnalyzeWarning(OxToolError):
    def __init__(self, message, line=None, col=None, file=None):
        super().__init__(message, line, col, file)
        self.severity = "warning"


def render_source_line(file, line, col, message, severity="error", source_map=None):
    """Pretty `path:line:col: severity: message` with a caret under the token."""
    kind = {"error": "error", "warning": "warning"}[severity]
    color = tty.red if severity == "error" else tty.yellow
    head = color("%s: %s:" % (kind, (file or "<ox>")))
    if line is not None:
        head = color("%s:%s:%s:" % (kind, (file or "<ox>"), line))
        if col:
            head += "%s:" % col
    out = ["  " + head + " " + message]
    src = (source_map or {}).get(file)
    if src is not None and line is not None:
        lines = src.splitlines()
        if 1 <= line <= len(lines):
            text = lines[line - 1]
            out.append("  " + tty.gray("%s | " % line) + text)
            pad = " " * (len("%s | " % line) + max(0, (col or 1) - 1))
            out.append("  " + pad + color("^"))
    return "\n".join(out)


class OxThrow(Exception):
    """Runtime exception carrying an OxErrorValue (thrown by `throw`, verify,
    runtime type errors, IO errors ...)."""

    def __init__(self, value):
        super().__init__(getattr(value, "msg", str(value)))
        self.value = value


class OxExit(Exception):
    """Raised by the builtin exit(); unwinds cleanly through finally blocks."""

    def __init__(self, code=0):
        super().__init__("exit(%d)" % code)
        self.code = code


class SkipTest(Exception):
    """Raised by verify.skip(); the test runner reports it as skipped."""

    def __init__(self, msg=""):
        super().__init__(msg or "skipped")
        self.msg = msg or "skipped"


class BreakSignal(Exception):
    def __init__(self, pos=None):
        super().__init__("break")
        self.pos = pos  # (file, line, col) of the 'break' statement


class ContinueSignal(Exception):
    def __init__(self, pos=None):
        super().__init__("continue")
        self.pos = pos  # (file, line, col) of the 'continue' statement


class ReturnSignal(Exception):
    def __init__(self, value):
        super().__init__("return")
        self.value = value
