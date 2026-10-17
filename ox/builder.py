"""ox build — static analysis + transpilation + packaging.

    ox build app.ox                 # -> build/app (executable zipapp)
    ox build app.ox -o dist/app     # -> dist/app
    ox build app.ox --emit py       # -> build/app.py (readable python)
    ox build app.ox --binary        # -> build/app.bin (standalone,
                                    #    needs PyInstaller, no python needed)

The zipapp embeds the transpiled program AND the ox runtime package, so the
output runs anywhere with python3.9+ (`./app` or `python3 app`). The
--binary mode additionally freezes it with PyInstaller into a single
executable that runs without any python installed.
"""
import os
import shutil
import subprocess
import sys
import zipfile
import zipapp

from . import __version__, tty
from .analyzer import analyze
from .cli import read_source, resolve_target
from .errors import OxToolError, render_source_line
from .parser import Parser
from .lexer import Lexer


def build(target, output=None, emit="app", binary=False):
    entry, manifest = resolve_target(target)
    src = read_source(entry)
    try:
        program = Parser(Lexer(src, entry).tokenize(), entry).parse_program()
    except OxToolError as e:
        print(tty.red("⨯ parse error · %s" % e.where()), file=sys.stderr)
        print(render_source_line(e.file, e.line, e.col, e.message, "error",
                                 {entry: src}), file=sys.stderr)
        return 2

    # ---- stage 1: static analysis -----------------------------------------
    errors, warnings = analyze(program)
    for w in warnings:
        print(render_source_line(w.file, w.line, w.col, w.message, "warning",
                                 {entry: src}))
    for e in errors:
        print(render_source_line(e.file, e.line, e.col, e.message, "error",
                                 {entry: src}))
    name = manifest.get("name") if manifest else None
    stem = name or os.path.splitext(os.path.basename(entry))[0]
    stem = os.path.basename(stem) or "app"  # never let paths leak into names
    stem = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in stem)
    if errors:
        print("")
        print(tty.red("⨯ build failed: %d static error%s (fix and rebuild)"
                      % (len(errors), "" if len(errors) == 1 else "s")))
        return 1

    # ---- stage 2: transpile -------------------------------------------------
    from .transpiler import transpile
    py_source = transpile(program)
    try:
        compile(py_source, entry + ".py", "exec")  # syntax sanity check
    except SyntaxError as e:  # pragma: no cover — transpiler bug guard
        print(tty.red("⨯ transpiler produced invalid python: %s" % e),
              file=sys.stderr)
        return 1

    if emit == "py":
        out = output or os.path.join("build", stem + ".py")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(py_source)
        print(tty.green("✓ compiled") + " %s -> %s (%s lines of python, "
                         "requires ox package on PYTHONPATH)"
              % (tty.bold(entry), tty.bold(out), len(py_source.splitlines())))
        return 0

    if binary:
        return _build_binary(entry, stem, py_source, output)

    # ---- stage 3: package zipapp ----------------------------------------------
    out = output or os.path.join("build", stem if output else stem)
    if not out.endswith(".pyz") and os.path.splitext(out)[1] == "":
        out = out  # executable name without extension is fine for zipapp
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    ox_pkg = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(ox_pkg)
    license_file = os.path.join(project_root, "LICENSE")

    main_py = (
        "# ox app '%s' — built by ox %s from %s\n"
        "import sys\n"
        "import ox.runtime as _rt\n"
        "import oxapp\n"
        "sys.exit(_rt.run_compiled(oxapp._ox_main))\n"
        % (stem, __version__, entry)
    )

    tmp_zip = out + ".tmp"
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("__main__.py", main_py)
        z.writestr("oxapp.py", py_source)
        if os.path.isfile(license_file):
            z.write(license_file, "LICENSE")
        for root, dirs, files in os.walk(ox_pkg):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", "tests", "examples")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, project_root)
                z.write(full, rel)
    with open(out, "wb") as f:
        f.write(b"#!/usr/bin/env python3\n")
        with open(tmp_zip, "rb") as zf:
            shutil.copyfileobj(zf, f)
    os.remove(tmp_zip)
    os.chmod(out, 0o755)

    size = os.path.getsize(out)
    print(tty.green("✓ built") + " %s -> %s (%s, self-contained zipapp, "
          "runs on python3.9+)" % (tty.bold(entry), tty.bold(out),
                                   _fmt_size(size)))
    print(tty.gray("  run it with: ./%s  (or: python3 %s)" % (out, out)))
    if warnings:
        print(tty.gray("  note: %d warning%s emitted during analysis"
                       % (len(warnings), "" if len(warnings) == 1 else "s")))
    return 0


def _build_binary(entry, stem, py_source, output):
    """Freeze the transpiled program + ox runtime into a standalone
    executable with PyInstaller. No python is needed to run the result."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(tty.red("⨯ --binary needs PyInstaller") + " — install it with:")
        print(tty.gray("  python3 -m pip install pyinstaller"))
        return 1

    out = output or os.path.join("build", stem + ".bin")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    out = os.path.abspath(out)

    ox_pkg = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(ox_pkg)  # contains the ox package
    workdir = os.path.join(os.path.dirname(out), stem + "-freeze")
    os.makedirs(workdir, exist_ok=True)
    entry_py = os.path.join(workdir, "ox_entry.py")
    app_py = os.path.join(workdir, "oxapp.py")
    with open(entry_py, "w", encoding="utf-8") as f:
        f.write(
            "# ox binary entry — built by ox %s from %s\n"
            "import sys\n"
            "import ox.runtime as _rt\n"
            "import oxapp\n"
            "sys.exit(_rt.run_compiled(oxapp._ox_main))\n"
            % (__version__, entry))
    with open(app_py, "w", encoding="utf-8") as f:
        f.write(py_source)

    dist_dir = os.path.join(workdir, "dist")
    build_dir = os.path.join(workdir, "build")
    name = os.path.basename(out)
    cmd = [sys.executable, "-m", "PyInstaller",
           "--onefile", "--clean", "--strip",
           "--distpath", dist_dir, "--workpath", build_dir,
           "--specpath", workdir,
           "--name", name,
           entry_py]
    print(tty.gray("freezing with PyInstaller (this can take a minute)..."))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir,
                       env=dict(os.environ, PYTHONPATH=project_root))
    produced = os.path.join(dist_dir, name)
    if r.returncode != 0 or not os.path.exists(produced):
        print(tty.red("⨯ PyInstaller failed:"), file=sys.stderr)
        tail = "\n".join((r.stderr or r.stdout).splitlines()[-25:])
        print(tty.gray(tail), file=sys.stderr)
        return 1
    if os.path.exists(out):
        os.remove(out)
    shutil.move(produced, out)
    shutil.rmtree(workdir, ignore_errors=True)
    os.chmod(out, 0o755)
    size = os.path.getsize(out)
    print(tty.green("✓ built") + " %s -> %s (%s, standalone binary — "
          "no python required)" % (tty.bold(entry), tty.bold(out),
                                    _fmt_size(size)))
    print(tty.gray("  run it with: ./%s" % out))
    return 0


def _fmt_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024)
    return "%.1f MB" % (n / (1024 * 1024))
