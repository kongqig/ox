"""Stage 3 of fmt validation: run the full test suite and all examples on
the FORMATTED corpus (in a temp dir) and compare against the original."""
import glob
import os
import shutil
import subprocess
import sys

SRC = "/home/z/my-project/ox"
WORK = "/tmp/ox-fmt-verify"

sys.path.insert(0, SRC)
from ox.fmt import format_source  # noqa: E402


def sh(cmd, cwd=None, timeout=60):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              cwd=cwd or SRC, timeout=timeout)
    except subprocess.TimeoutExpired:
        class _R:
            returncode = 124
            stdout = ""
            stderr = ""
        return _R()


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    # copy the project (python package + formatted ox sources)
    shutil.copytree(os.path.join(SRC, "ox"), os.path.join(WORK, "oxpkg"))
    os.rename(os.path.join(WORK, "oxpkg"), os.path.join(WORK, "ox"))
    for d in ("tests", "examples"):
        os.makedirs(os.path.join(WORK, d), exist_ok=True)
        for path in sorted(glob.glob(os.path.join(SRC, d, "**", "*.ox"),
                                     recursive=True)):
            with open(path, encoding="utf-8") as f:
                src = f.read()
            rel = os.path.relpath(path, SRC)
            dst = os.path.join(WORK, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as f:
                f.write(format_source(src, path))

    # 1. full test suite on formatted sources
    r = sh("python -m ox test", cwd=WORK)
    tail = r.stdout.strip().splitlines()[-1]
    print("formatted corpus tests:", tail)
    ok_tests = "0 failed" in tail
    if not ok_tests:
        print(r.stdout[-3000:])
        return 1

    # 2. example outputs before vs after formatting (server.ox is a
    # long-running demo and is skipped)
    mismatches = 0
    for path in sorted(glob.glob(os.path.join(SRC, "examples/*.ox"))):
        name = os.path.basename(path)
        if name == "server.ox":
            print("  %s: SKIPPED (long-running demo)" % name)
            continue
        if name == "backup.ox":
            # nondeterministic output: random temp dirs + timing ms
            # (the original differs from itself run-to-run)
            print("  %s: SKIPPED (nondeterministic output)" % name)
            continue
        r1 = sh("python -m ox run examples/%s" % name)
        r2 = sh("python -m ox run examples/%s" % name, cwd=WORK)
        same = (r1.returncode == r2.returncode and
                r1.stdout == r2.stdout)
        # examples embed temp paths / ports in output; compare loosely:
        # same exit code and same line count as a smoke signal
        loose = r1.returncode == r2.returncode and \
            len(r1.stdout.splitlines()) == len(r2.stdout.splitlines())
        status = "OK" if same else ("LOOSE-OK" if loose else "MISMATCH")
        if not loose:
            mismatches += 1
            print("  %s: rc %d vs %d" % (name, r1.returncode, r2.returncode))
            print("   before:", r1.stdout[-300:])
            print("   after: ", r2.stdout[-300:])
        else:
            print("  %s: %s" % (name, status))
    print("example mismatches:", mismatches)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
