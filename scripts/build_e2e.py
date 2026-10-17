#!/usr/bin/env python3
"""End-to-end smoke test for `ox build` artifacts (review priority #2).

Compiles one program that exercises fs / net / workflow / match / closures /
f-strings / co concurrency, runs the zipapp artifact, and byte-compares its
output with the interpreter's output. Exits non-zero on any mismatch.
"""
import os
import subprocess
import sys
import tempfile

ROOT = "/home/z/my-project/ox"
PROG = r'''
import fs
import net
import co
import time

# f-strings + match destructuring + closures
let label = "build-e2e"
fn describe(evt) {
  match evt {
    {kind: "deploy", host} => f"deploy on {host}"
    [x, y] => f"pair {x},{y}"
    _ => "other"
  }
}
var count = 0
fn bump() { count = count + 1 }
for _ in 1..5 { bump() }
print(f"[{label}] match: {describe({kind: "deploy", host: "h1"})}",
      describe([1, 2]), f"count={count}")

# fs roundtrip
let d = fs.temp_dir("ox-build-e2e")
fs.write(d + "/data.txt", "hello artifact")
let back = fs.read(d + "/data.txt")
print(f"[{label}] fs: {back} ({fs.size(d + "/data.txt")} bytes)")
fs.remove(d)

# concurrency
let t0 = time.now()
let results = co.all([spawn fn() { "a" }, spawn fn() { "b" }, spawn fn() { "c" }])
print(f"[{label}] co: {results.sort()} in {(time.now() - t0).round(3)}s")

# serve + net self-request
let h = serve 0, daemon=true {
  get "/ping" {
    res.json({pong: true})
  }
}
let r = net.get(f"http://127.0.0.1:{h.port}/ping")
print(f"[{label}] http: {r.json.pong} {r.status}")
h.stop()

# workflow with retry
workflow "e2e-flow" {
  step "one" {
    verify true
  }
}
print(f"[{label}] workflow ok")

# 0.4.1: keyword-named kwargs, soft-keyword params, null defaults,
# sort_by with a user function — all must compile to the same behavior
fn kw_probe(a, verify=null, on=null) {
  return [a, verify, on]
}
print(f"[{label}] kwargs: {kw_probe(1, verify=false, on=2)}")
print(f"[{label}] null-default: {kw_probe(9)}")
let ranked = [[1, "b"], [3, "a"], [2, "c"]].sort_by(fn (p) { p[0] })
print(f"[{label}] sort_by: {ranked.map(fn (p) { p[1] })}")
'''


def main():
    workdir = tempfile.mkdtemp(prefix="ox-builde2e-")
    src = os.path.join(workdir, "main.ox")
    with open(src, "w", encoding="utf-8") as f:
        f.write(PROG)

    # 1. interpreter reference output
    interp = subprocess.run([sys.executable, "-m", "ox", "run", src],
                            capture_output=True, text=True, timeout=120,
                            cwd=ROOT)
    if interp.returncode != 0:
        print("interpreter run failed:")
        print(interp.stdout + interp.stderr)
        return 1
    # normalize the timing line (varies run to run)
    def norm(s):
        return [line.split(" in ")[0] if line.startswith("[build-e2e] co:")
                else line for line in s.strip().splitlines()]
    want = norm(interp.stdout)
    print("interpreter output:")
    for line in want:
        print("  " + line)

    # 2. build zipapp
    bld = subprocess.run([sys.executable, "-m", "ox", "build", src],
                         capture_output=True, text=True, timeout=180, cwd=workdir,
                         env={**os.environ, "PYTHONPATH": ROOT})
    if bld.returncode != 0:
        print("build failed:")
        print(bld.stdout + bld.stderr)
        return 1
    print("build output:\n  " + bld.stdout.strip().splitlines()[-1])

    # locate the artifact (ox build writes build/<stem>)
    art = None
    for dirpath, _, files in os.walk(workdir):
        for f in files:
            if f != "main.ox" and not f.endswith(".ox"):
                art = os.path.join(dirpath, f)
    if art is None:
        print("no artifact produced; dir:", os.listdir(workdir))
        return 1

    # 3. run the artifact
    exe = subprocess.run([sys.executable, art], capture_output=True, text=True,
                         timeout=120, cwd=workdir)
    if exe.returncode != 0:
        print("artifact run failed:")
        print(exe.stdout + exe.stderr)
        return 1
    got = norm(exe.stdout)
    print("artifact output:")
    for line in got:
        print("  " + line)

    # 4. parity
    if got != want:
        print("MISMATCH between interpreter and compiled artifact")
        return 1
    print("\n== build e2e: interpreter == compiled artifact (byte parity)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
