"""ox test — the built-in test runner.

Test files are `*.test.ox`; each may contain any number of:

    test "name" { verify ... }
    test "slow thing", timeout=2s { ... }

Top-level statements in a test file run first (imports, helpers, fixtures) —
an error there fails the whole file. Each `test` block then runs against the
module environment. Failures (thrown errors, failed `verify`) are reported
per test with file/line info.
"""
import asyncio
import json
import os
import sys
import time as _time

from . import tty
from .errors import OxThrow, OxToolError, SkipTest, render_source_line
from .interpreter import Interpreter
from .lexer import Lexer
from .parser import Parser

SKIP_DIRS = {".git", ".ox", "node_modules", "__pycache__", "build", ".venv",
             "download", "docs", "examples", "skills"}


def discover(target):
    if target and os.path.isfile(target):
        return [target]
    root = target or ("tests" if os.path.isdir("tests") else ".")
    out = []
    if os.path.isfile(root):
        return [root]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not d.startswith(".")]
        for f in sorted(filenames):
            if f.endswith(".test.ox"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


async def _run_file(path, results):
    file_rec = {"file": path, "tests": [], "error": None}
    results.append(file_rec)
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        file_rec["error"] = "cannot read: %s" % e
        return
    interp = Interpreter(file=path)
    interp.sources[path] = src
    try:
        program = Parser(Lexer(src, path).tokenize(), path).parse_program()
    except OxToolError as e:
        file_rec["error"] = "parse error: %s" % e.message
        return
    try:
        await interp.run_program(program)
    except OxThrow as t:
        file_rec["error"] = "top-level error: %s" % t.value.msg
        return
    except Exception as e:  # noqa: BLE001
        file_rec["error"] = "top-level error: %s" % e
        return

    for test in interp.tests:
        rec = {"name": test.name, "ok": True, "ms": 0, "error": None,
               "where": None}
        file_rec["tests"].append(rec)
        t0 = _time.monotonic()
        try:
            from .environment import Env
            coro = interp.exec_block(test.body, Env(test.env))
            if test.timeout is not None:
                await asyncio.wait_for(coro, timeout=float(test.timeout))
            else:
                await coro
        except asyncio.TimeoutError:
            rec["ok"] = False
            rec["error"] = "timed out after %s" % test.timeout
        except SkipTest as s:
            rec["ok"] = True
            rec["skipped"] = True
            rec["error"] = s.msg
        except OxThrow as t:
            err = t.value
            rec["ok"] = False
            rec["error"] = err.msg or "verification failed"
            if err.pos:
                rec["where"] = "%s:%s:%s" % err.pos
            elif err.trace:
                f = err.trace[-1]
                rec["where"] = "%s:%s:%s" % (f[1], f[2], f[3])
        except Exception as e:  # noqa: BLE001
            rec["ok"] = False
            rec["error"] = str(e)
        rec["ms"] = round((_time.monotonic() - t0) * 1000)

    # background procs started in this file must not outlive it
    try:
        from .builtins import osmod
        await osmod.kill_live_procs()
    except Exception:  # noqa: BLE001 — cleanup must never fail a file
        pass


def run_tests(target=None, json_report=False):
    files = discover(target)
    if not files:
        print(tty.yellow("! no test files found (looked for *.test.ox)"))
        return 0
    results = []
    t0 = _time.monotonic()

    async def run_all():
        for f in files:
            await _run_file(f, results)

    asyncio.run(run_all())
    elapsed = round((_time.monotonic() - t0) * 1000)

    n_pass = n_fail = n_skip = 0
    for fr in results:
        rel = fr["file"]
        print(tty.bold(rel))
        if fr["error"]:
            print("  " + tty.red("✗ file") + " — " + fr["error"])
            n_fail += 1
        for tr in fr["tests"]:
            if tr.get("skipped"):
                n_skip += 1
                print("  " + tty.yellow("−") + " %s " % tr["name"] +
                      tty.gray("(skipped: %s)" % (tr["error"] or "skipped")))
            elif tr["ok"]:
                n_pass += 1
                print("  " + tty.green("✓") + " %s " % tr["name"] +
                      tty.gray("(%dms)" % tr["ms"]))
            else:
                n_fail += 1
                print("  " + tty.red("✗") + " %s — " % tr["name"] +
                      tty.red(tr["error"] or "failed"))
                if tr["where"]:
                    print("      " + tty.gray(tr["where"]))
        if not fr["error"] and not fr["tests"]:
            print(tty.gray("  (no tests registered)"))
        print("")

    total = n_pass + n_fail
    summary = "%d file%s · %d test%s · %s passed · %s failed" % (
        len(results), "" if len(results) == 1 else "s",
        total, "" if total == 1 else "s",
        tty.green(str(n_pass)) if n_pass else "0",
        tty.red(str(n_fail)) if n_fail else "0")
    if n_skip:
        summary += tty.yellow(" · %d skipped" % n_skip)
    summary += " · %dms" % elapsed
    print(summary if n_fail == 0 else tty.bold(summary))

    if json_report:
        report = {"files": results,
                  "summary": {"files": len(results), "tests": total,
                              "passed": n_pass, "failed": n_fail,
                              "skipped": n_skip, "ms": elapsed}}
        with open("ox-test-report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(tty.gray("report written to ox-test-report.json"))

    return 1 if n_fail else 0
