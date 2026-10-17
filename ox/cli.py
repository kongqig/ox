"""ox — command line interface.

    ox run <file|dir> [--check] [-- args...]   run a program
    ox test [file|dir] [--json]                run tests
    ox build <file|dir> [-o out] [--emit py]   static-check + compile
    ox check <file|dir>                        static analysis only
    ox repl                                    interactive session
    ox init [name]                             scaffold a project
    ox version / ox help
"""
import argparse
import asyncio
import json
import os
import sys

from . import __version__, tty
from .errors import (AnalyzeWarning, LexError, OxToolError, OxExit, OxThrow,
                     ParseError, render_source_line)

MANIFEST = "ox.proj.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read_source(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        print(tty.red("⨯ cannot read %s: %s" % (path, e.strerror or e)),
              file=sys.stderr)
        raise SystemExit(2)


def parse_source(src, file):
    from .lexer import Lexer
    from .parser import Parser
    tokens = Lexer(src, file).tokenize()
    return Parser(tokens, file).parse_program()


def resolve_target(target):
    """Returns (entry file, manifest dict or None)."""
    if target is None:
        if os.path.isfile(MANIFEST):
            return resolve_manifest(os.getcwd())
        for cand in ("main.ox", "app.ox", "index.ox"):
            if os.path.isfile(cand):
                return cand, None
        print(tty.red("⨯ no target given and no %s / main.ox found" % MANIFEST),
              file=sys.stderr)
        raise SystemExit(2)
    if os.path.isdir(target):
        return resolve_manifest(target)
    if not os.path.isfile(target):
        print(tty.red("⨯ no such file or directory: %s" % target), file=sys.stderr)
        raise SystemExit(2)
    return target, None


def resolve_manifest(directory):
    mpath = os.path.join(directory, MANIFEST)
    manifest = None
    if os.path.isfile(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError) as e:
            print(tty.red("⨯ invalid %s: %s" % (MANIFEST, e)), file=sys.stderr)
            raise SystemExit(2)
    entry = (manifest or {}).get("entry") or "main.ox"
    path = os.path.join(directory, entry)
    if not os.path.isfile(path):
        print(tty.red("⨯ entry file not found: %s" % path), file=sys.stderr)
        raise SystemExit(2)
    return path, manifest


def print_tool_error(e, sources=None):
    label = {LexError: "lex", ParseError: "parse"}.get(type(e), "error")
    print(tty.red("⨯ %s error · %s" % (label, e.where())), file=sys.stderr)
    print(render_source_line(e.file, e.line, e.col, e.message, "error",
                             sources or {}), file=sys.stderr)


def print_throw(interp, exc):
    err = exc.value
    kind = "verify" if err.kind == "verify" else "runtime"
    print(tty.red("⨯ %s error · %s" % (kind, err.msg or "verification failed")),
          file=sys.stderr)
    if err.code:
        print(tty.yellow("  code: %s" % err.code), file=sys.stderr)
    if err.pos:
        f, line, col = err.pos
        if f in interp.sources and interp.sources[f]:
            print(render_source_line(f, line, col, err.msg, "error",
                                     interp.sources), file=sys.stderr)
        else:
            print(tty.gray("  at %s:%s:%s" % (f, line, col)), file=sys.stderr)
    if err.trace:
        print(tty.gray("  trace:"), file=sys.stderr)
        for frame in err.trace[-8:]:
            print(tty.gray("    at %s (%s:%s)" % (frame[0], frame[1], frame[2])),
                  file=sys.stderr)


async def run_program_async(interp, program):
    await interp.run_program(program)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_run(args):
    entry, _manifest = resolve_target(args.target)
    src = read_source(entry)
    try:
        program = parse_source(src, entry)
    except OxToolError as e:
        interp_sources = {entry: src}
        print_tool_error(e, interp_sources)
        return 2
    if args.check:
        from .analyzer import analyze
        errors, warnings = analyze(program)
        for w in warnings:
            print(render_source_line(w.file, w.line, w.col, w.message,
                                     "warning", {entry: src}))
        for e in errors:
            print(render_source_line(e.file, e.line, e.col, e.message,
                                     "error", {entry: src}))
        if errors:
            return 2
    from .interpreter import Interpreter
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    interp = Interpreter(file=entry, argv=args.script_args)
    interp.sources[entry] = src
    try:
        return runtime_run(run_program_async(interp, program), interp)
    finally:
        pending_note(interp)


def runtime_run(coro, interp):
    from .runtime import run
    try:
        return run(coro)
    except OxThrow as t:
        print_throw(interp, t)
        return 1
    except OxExit as e:
        return e.code


def pending_note(interp):  # placeholder for future use
    return None


def cmd_test(args):
    from .testing import run_tests
    return run_tests(args.target, json_report=args.json)


def cmd_build(args):
    from .builder import build
    return build(args.target, output=args.output, emit=args.emit,
                 binary=args.binary)


def cmd_check(args):
    from .analyzer import analyze
    entry, _ = resolve_target(args.target)
    src = read_source(entry)
    try:
        program = parse_source(src, entry)
    except OxToolError as e:
        print_tool_error(e, {entry: src})
        return 2
    errors, warnings = analyze(program)
    n_err = 0
    for w in warnings:
        print(render_source_line(w.file, w.line, w.col, w.message, "warning",
                                 {entry: src}))
        n_err += 1 if args.strict else 0
    for e in errors:
        print(render_source_line(e.file, e.line, e.col, e.message, "error",
                                 {entry: src}))
        n_err += 1
    total = len(errors) + len(warnings)
    if total == 0:
        print(tty.green("✓ %s: no issues found" % entry))
        return 0
    print("")
    print("%s: %d error%s, %d warning%s" %
          (tty.red("⨯") if errors else tty.yellow("!"),
           len(errors), "" if len(errors) == 1 else "s",
           len(warnings), "" if len(warnings) == 1 else "s"))
    return 1 if (errors or args.strict) else 0


def cmd_repl(args):
    from .repl import repl
    return repl()


def cmd_fmt(args):
    from .fmt import format_file
    import glob as _glob
    import os

    targets = args.targets or ["."]
    files = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
        elif os.path.isdir(t):
            for dirpath, dirnames, filenames in os.walk(t):
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and d not in
                               ("node_modules", "__pycache__", "build",
                                "download", "docs", "skills", "ox")]
                for f in sorted(filenames):
                    if f.endswith(".ox"):
                        files.append(os.path.join(dirpath, f))
        else:
            files.extend(sorted(_glob.glob(t)))
    if not files:
        print(tty.yellow("! no .ox files found"))
        return 0
    changed = []
    for path in files:
        try:
            did, _text = format_file(path, check=args.check)
        except Exception as e:  # noqa: BLE001 — one bad file must not stop fmt
            print(tty.red("⨯ %s: %s" % (path, e)))
            return 1
        if did:
            changed.append(path)
    if args.check:
        for path in changed:
            print(tty.yellow("would reformat: %s" % path))
        if changed:
            print("%d file%s would be reformatted" %
                  (len(changed), "" if len(changed) == 1 else "s"))
            return 1
        print(tty.green("✓ %d file%s already formatted" %
                        (len(files), "" if len(files) == 1 else "s")))
        return 0
    for path in changed:
        print(tty.green("formatted: %s" % path))
    print("%d file%s formatted, %d left unchanged" %
          (len(changed), "" if len(changed) == 1 else "s",
           len(files) - len(changed)))
    return 0


def cmd_init(args):
    from .scaffold import init_project
    return init_project(args.name, force=args.force)


def cmd_version(args):
    py = sys.version.split()[0]
    print(tty.bold("ox %s" % __version__) + tty.gray(" · python %s · %s"
                                                     % (py, sys.platform)))
    return 0


def cmd_help(args):
    print(HELP)
    return 0


HELP = """%(bold)sOX%(reset)s — a sturdy little language for automation & tooling (v%(version)s)

%(bold)sUsage:%(reset)s ox %(cyan)s<command>%(reset)s [options]

  %(cyan)srun%(reset)s     <file|dir>   Run a program (interpreted)
                        --check        statically check first
                        -- <args...>   pass args to the script (os.args())
  %(cyan)stest%(reset)s    [file|dir]   Run test files (*.test.ox)
                        --json         write a machine-readable report
  %(cyan)sbuild%(reset)s   <file|dir>   Compile: check + translate + package
                        -o <path>      output path (default build/<name>.pyz)
                        --emit py      emit readable Python instead of a zipapp
                        --binary       freeze into a standalone executable
                                       (needs pyinstaller; runs without python)
  %(cyan)scheck%(reset)s   <file|dir>   Static analysis only
                        --strict       treat warnings as errors
  %(cyan)sfmt%(reset)s     [files|dirs]  Format source in place (2-space indent,
                        --check        normalised spacing, comments kept)
                                       exit 1 if anything would change
  %(cyan)srepl%(reset)s                 Interactive session (Ctrl+D to exit)
  %(cyan)sinit%(reset)s    [name]       Scaffold a new project
                        --force        overwrite existing files
  %(cyan)sversion%(reset)s              Show version info
  %(cyan)shelp%(reset)s                 Show this help

%(bold)sExamples:%(reset)s
  ox run deploy.ox
  ox run . -- --env prod
  ox test
  ox build backup.ox -o backup
  ox repl

%(dim)sDocs: docs/LANGUAGE.md · docs/STDLIB.md · docs/CLI.md%(reset)s
""" % {"bold": tty.BOLD or "", "reset": tty.RESET or "", "cyan": tty.CYAN or "",
       "dim": tty.DIM or "", "version": __version__}


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def split_script_args(argv):
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def build_argparser():
    ap = argparse.ArgumentParser(prog="ox", add_help=False)
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--version", action="store_true")
    sub = ap.add_subparsers(dest="command")

    p = sub.add_parser("run", add_help=False)
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("--check", action="store_true")

    p = sub.add_parser("test", add_help=False)
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("build", add_help=False)
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--emit", default="app", choices=["app", "py"])
    p.add_argument("--binary", action="store_true")

    p = sub.add_parser("check", add_help=False)
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("--strict", action="store_true")

    p = sub.add_parser("fmt", add_help=False)
    p.add_argument("targets", nargs="*", default=None)
    p.add_argument("--check", action="store_true")

    sub.add_parser("repl", add_help=False)
    p = sub.add_parser("init", add_help=False)
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--force", action="store_true")

    sub.add_parser("version", add_help=False)
    sub.add_parser("help", add_help=False)
    return ap


def main(argv=None):
    import os
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.name == "nt":
        from . import tty as _tty
        print(_tty.yellow(
            "warning: ox targets Linux/macOS (POSIX). Windows is unsupported: "
            "fs.lock, os.start and other POSIX-only features will fail."))
    if argv and argv[0] in ("version", "--version", "-v"):
        return cmd_version(None)
    if argv and argv[0] in ("help", "--help", "-h"):
        return cmd_help(None)
    if not argv:
        return cmd_help(None)

    main_args, script_args = split_script_args(argv)
    ap = build_argparser()
    args = ap.parse_args(main_args)
    args.script_args = script_args
    if args.no_color:
        import os
        os.environ["NO_COLOR"] = "1"

    handlers = {"run": cmd_run, "test": cmd_test, "build": cmd_build,
                "check": cmd_check, "fmt": cmd_fmt, "repl": cmd_repl,
                "init": cmd_init, "version": cmd_version, "help": cmd_help}
    handler = handlers.get(args.command)
    if handler is None:
        cmd_help(None)
        return 2
    try:
        return handler(args) or 0
    except OxToolError as e:
        print_tool_error(e)
        return 2
    except KeyboardInterrupt:
        print("")
        return 130
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
