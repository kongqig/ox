#!/usr/bin/env python3
"""Round 2: does an un-awaited async call actually run to completion?
Plus deep recursion, cyclic refs, eval error paths, res.file traversal."""
import subprocess
import sys
import tempfile
import os
import textwrap

OX = sys.executable
PROBES = []


def probe(name, src):
    PROBES.append((name, textwrap.dedent(src)))


# --- the await question: does co.sleep(200ms) actually sleep without await? ---
probe("unawaited-sleep-timing", """
    import co
    import time
    let t0 = time.now()
    co.sleep(200ms)
    let dt = time.now() - t0
    print("elapsed:", dt)
""")
probe("unawaited-side-effect", """
    import co
    var x = 0
    co.every(50ms) { x = x + 1 }
    co.sleep(300ms)
    print("x =", x)
""")
probe("await-in-arith", """
    import co
    let a = co.timeout(1s, fn() { 42 })
    print(a + 1)
""")

# --- deep recursion: clean error or crash? ---
probe("deep-recursion-5k", """
    fn down(n) { if n == 0 { "done" } else { down(n - 1) } }
    print(down(5000))
""")
probe("deep-recursion-100k", """
    fn down(n) { if n == 0 { "done" } else { down(n - 1) } }
    print(down(100000))
""")

# --- cyclic references ---
probe("cyclic-repr", """
    let a = {name: "a"}
    a.self = a
    print(a)
""")
probe("cyclic-json", """
    import json
    let a = {name: "a"}
    a.self = a
    print(json.encode(a))
""")

# --- eval error paths ---
probe("eval-parse-error", """
    import sys
    let r = eval("let = = 3")
    print(r)
""")
probe("eval-runtime-error", """
    try {
      eval("1 / 0")
    } catch e {
      print("caught:", e)
    }
""")

# --- str/repr consistency for edge types ---
probe("nan-inf-display", """
    print(0/0 == 0/0, 1/0)
""")
probe("bool-is-num", """
    print(true + 1, false == 0, true == 1)
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
            results.append((name, p.returncode, (p.stdout + p.stderr).strip()))
        except subprocess.TimeoutExpired:
            results.append((name, -1, "TIMEOUT"))
        finally:
            os.unlink(path)
    for name, code, out in results:
        status = "OK  " if code == 0 else "FAIL"
        print(f"[{status}] {name} (exit={code})")
        for line in out.splitlines()[:8]:
            print(f"       {line}")
        print()
    fails = sum(1 for _, c, _ in results if c != 0)
    print(f"== {len(results) - fails}/{len(results)} probes exited 0")


if __name__ == "__main__":
    main()
