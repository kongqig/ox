#!/usr/bin/env python3
"""Performance baseline for ox 0.4 (review priority #3).

Measures order-of-magnitude numbers so users know what to expect:
  1. interpreter vs compiled artifact (CPU-bound fib)
  2. 1k concurrent tasks
  3. large file write/read (10 MB)
  4. large JSON parse/dump (10k objects)
  5. string / list method throughput

Prints a markdown table; results go into docs/PERF.md.
Run:  python scripts/bench_ox.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = "/home/z/my-project/ox"
OX = sys.executable
RESULTS = []


def run_ox(src, timeout=120):
    d = tempfile.mkdtemp(prefix="ox-bench-")
    p = os.path.join(d, "b.ox")
    with open(p, "w") as f:
        f.write(src)
    t0 = time.perf_counter()
    r = subprocess.run([OX, "-m", "ox", "run", p], capture_output=True,
                       text=True, timeout=timeout, cwd=ROOT)
    dt = time.perf_counter() - t0
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("bench program failed")
    os.unlink(p)
    os.rmdir(d)
    return dt


def bench(name, src, note=""):
    dt = run_ox(src)
    RESULTS.append((name, dt, note))
    print(f"{name:44s} {dt * 1000:9.1f} ms   {note}")


FIB = """
fn fib(n) { if n < 2 { n } else { fib(n - 1) + fib(n - 2) } }
print("fib26", fib(26))
"""

CONC = """
import co
fn work(i) { i * i }
let fns = []
for i in 1..1000 { fns.push(fn () { work(i) }) }
let handles = []
for f in fns { handles.push(spawn f()) }
co.all(handles)
print("1k tasks done")
"""

BIGFILE = """
import fs
let d = fs.temp_dir("ox-bench")
let p = d + "/big.bin"
let blob = "x".repeat(1024 * 1024)
for i in 1..10 { fs.append(p, blob) }
let back = fs.read(p)
print("size", back.len())
fs.remove(p)
fs.remove(d)
"""

BIGJSON = """
import json
let items = []
for i in 1..10000 {
  items.push({id: i, name: "item", tags: ["a", "b"], score: i * 0.5})
}
let text = json.dump(items)
let back = json.parse(text)
print("json", back.len(), text.len())
"""

STRINGS = """
let parts = []
for i in 1..20000 { parts.push(f"row-{i}") }
let joined = parts.join(",")
let up = joined.upper()
print("strings", up.len())
"""

LISTOPS = """
let xs = []
for i in 1..20000 { xs.push(i) }
let ys = xs.map(fn (x) { x * 2 }).filter(fn (x) { x > 10000 })
print("listops", ys.len(), xs.len())
"""


def main():
    print("== ox 0.4 performance baseline (CPython 3.12, this machine) ==\n")

    bench("startup (empty program)", 'print("hi")\n',
          "process spawn + runtime init")
    bench("fib(26) — interpreter", FIB, "tree-walking evaluator")
    bench("fib(26) — cold cache second run", FIB,
          "same, pycache warm (delta vs above is OS noise)")

    # compiled artifact timing
    d = tempfile.mkdtemp(prefix="ox-benchb-")
    src = os.path.join(d, "main.ox")
    with open(src, "w") as f:
        f.write(FIB)
    b = subprocess.run([OX, "-m", "ox", "build", src], capture_output=True,
                       text=True, cwd=d,
                       env={**os.environ, "PYTHONPATH": ROOT})
    if b.returncode == 0:
        art = os.path.join(d, "build", "main")
        t0 = time.perf_counter()
        r = subprocess.run([OX, art], capture_output=True, text=True,
                           timeout=120)
        dt = time.perf_counter() - t0
        assert r.returncode == 0, r.stderr
        RESULTS.append(("fib(26) — compiled zipapp", dt, "transpiled python"))
        print(f"{'fib(26) — compiled zipapp':44s} {dt * 1000:9.1f} ms   "
              "transpiled python")

    bench("1k concurrent spawn tasks", CONC, "asyncio tasks")
    bench("10 MB file write+read", BIGFILE, "fs layer")
    bench("10k-object JSON roundtrip", BIGJSON, "json parse+dump")
    bench("20k f-strings + join + upper", STRINGS, "string layer")
    bench("20k push/map/filter", LISTOPS, "list layer")

    print("\n| benchmark | time | note |")
    print("|---|---|---|")
    for name, dt, note in RESULTS:
        print(f"| {name} | {dt * 1000:.0f} ms | {note} |")


if __name__ == "__main__":
    main()
