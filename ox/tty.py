"""Tiny terminal styling helper. Respects NO_COLOR and non-tty streams."""
import os
import sys

_ENABLED = None

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
GRAY = "\x1b[90m"


def enabled():
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = (
            os.environ.get("NO_COLOR", "") == ""
            and sys.stdout is not None
            and hasattr(sys.stdout, "isatty")
            and sys.stdout.isatty()
        )
    return _ENABLED


def paint(text, *codes):
    if not enabled() or not codes:
        return text
    return "".join(codes) + text + RESET


def bold(t):    return paint(t, BOLD)
def dim(t):     return paint(t, DIM)
def red(t):     return paint(t, RED)
def green(t):   return paint(t, GREEN)
def yellow(t):  return paint(t, YELLOW)
def blue(t):    return paint(t, BLUE)
def magenta(t): return paint(t, MAGENTA)
def cyan(t):    return paint(t, CYAN)
def gray(t):    return paint(t, GRAY)


def colorize(level):
    return {"error": red, "warn": yellow, "info": cyan, "ok": green,
            "debug": gray, "trace": magenta}.get(level, str)
