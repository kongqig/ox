#!/usr/bin/env python3
"""Probe actual ox 0.3.1 behavior for the 7 syntax claims from the external review.

Each probe runs the real CLI (`python -m ox run`) in a subprocess and reports
stdout / exit code, so we can judge each claim on facts, not on the review's
guesses.
"""
import subprocess
import sys
import tempfile
import os
import textwrap

OX = sys.executable
PROBES = []


def probe(name, src):
    PROBES.append((name, textwrap.dedent(src)))


# 1. interpolation landmine
probe("interp-css", """
    let css = "body { color: red }"
    print(css)
""")
probe("interp-literal-ok", """
    let s = 'body { color: red }'
    print(s)
""")

# 2. await semantics
probe("await-sync-fn", """
    fn quick() { 1 }
    let a = quick()
    let b = await quick()
    print(a, b)
""")
probe("await-no-await-async-call", """
    import co
    let t = co.sleep(10ms)
    print(t)
""")
probe("await-builtin-direct", """
    import co
    print(co.sleep(10ms))
""")

# 3. match bare identifier
probe("match-bare-bind", """
    let x = 5
    match 5 {
      x => print("bound", x)
      _ => print("no")
    }
""")

# 4. fn(x) without space
probe("fn-no-space", """
    let d = fn(x) { x * 2 }
    print(d(3))
""")

# 5. contextual keywords inside workflow
probe("ctx-kw-desc-as-var", """
    workflow "w" {
      let desc = "my description"
      step "s" { verify true }
      print(desc)
    }
""")

# 6. pipe with bare function name
probe("pipe-sort", """
    let r = [3, 1, 2] |> sort
    print(r)
""")
probe("pipe-str-upper", """
    let r = "abc" |> upper
    print(r)
""")

# 7. for unpacking: dict vs list-of-pairs
probe("for-dict-unpack", """
    for k, v in {name: "ox", n: 2} { print(k, "=", v) }
""")
probe("for-list-pairs", """
    for a, b in [["x", 1], ["y", 2]] { print(a, b) }
""")

# extras: unicode, deep recursion
probe("unicode-emoji", """
    let s = "你好 🚀 café"
    print(s.len(), s.upper(), s)
""")
probe("deep-recursion", """
    fn fib(n) { if n < 2 { n } else { fib(n - 1) + fib(n - 2) } }
    print(fib(24))
""")


def main():
    results = []
    for name, src in PROBES:
        with tempfile.NamedTemporaryFile("w", suffix=".ox", delete=False,
                                         dir="/home/z/my-project/ox") as f:
            f.write(src)
            path = f.name
        try:
            p = subprocess.run([OX, "-m", "ox", "run", path],
                               capture_output=True, text=True, timeout=30,
                               cwd="/home/z/my-project/ox")
            out = (p.stdout + p.stderr).strip()
            results.append((name, p.returncode, out))
        except subprocess.TimeoutExpired:
            results.append((name, -1, "TIMEOUT"))
        finally:
            os.unlink(path)
    for name, code, out in results:
        status = "OK  " if code == 0 else "FAIL"
        print(f"[{status}] {name} (exit={code})")
        for line in out.splitlines()[:6]:
            print(f"       {line}")
        print()
    fails = sum(1 for _, c, _ in results if c != 0)
    print(f"== {len(results) - fails}/{len(results)} probes exited 0")


if __name__ == "__main__":
    main()
