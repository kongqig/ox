# devserver.ox — the "start it, probe it, stop it, ship it" pattern.
#
# Demonstrates os.start (background processes), net.wait_port (readiness
# probes) and fs.zip (artifact archiving) working together. Run with:
#
#   ox run examples/devserver.ox

import fs
import net
import os
import py

# --- 1. build a tiny static site -------------------------------------------

let work = fs.temp_dir("ox-devserver")
let site = fs.join(work, "site")
fs.mkdirs(fs.join(site, "css"))
fs.write(fs.join(site, "index.html"),
  "<html><head><link rel=stylesheet href=css/app.css></head>" +
  "<body><h1>built by ox</h1></body></html>")
fs.write(fs.join(site, "css/app.css"), 'h1 { color: #0a7 }')

# --- 2. pick a free port (borrow a socket via the py bridge) ----------------

py.exec("import socket
" +
  "_s = socket.socket()
" +
  "_s.bind(('127.0.0.1', 0))
" +
  "PORT = _s.getsockname()[1]
" +
  "_s.close()")
let port = py.eval("PORT")

# --- 3. serve it with python's http.server in the background ----------------

let proc = os.start(f"python3 -m http.server {port} --bind 127.0.0.1 --directory {site}")
print(f"started pid {proc.pid} on port {port}")

if not (await net.wait_port("127.0.0.1", port, timeout=10s)) {
  print("server never came up. stderr so far:")
  print(proc.err())
  await proc.kill()
  throw error("dev server failed to start")
}

# --- 4. probe it ------------------------------------------------------------

let r = await net.get(f"http://127.0.0.1:{port}/index.html")
verify r.status == 200
verify r.body.has("built by ox")
print(f"GET /index.html -> {r.status} ({r.body.len()} bytes)")

let css = await net.get(f"http://127.0.0.1:{port}/css/app.css")
verify css.status == 200
print(f"GET /css/app.css -> {css.status}")

# --- 5. stop it -------------------------------------------------------------

await proc.kill()
verify proc.running == false
print(f"server stopped (pid {proc.pid} reaped, exit handled by kill)")

# --- 6. ship the artifacts --------------------------------------------------

let artifact = fs.join(work, "site.zip")
let n = fs.zip(site, artifact)
verify n == 2
print(f"archived {n} files -> {artifact}")

# prove the roundtrip while we are at it
let restored = fs.join(work, "restored")
verify fs.unzip(artifact, restored) == 2
verify fs.read(fs.join(restored, "site/css/app.css")) == 'h1 { color: #0a7 }'
print(f"roundtrip ok — {artifact}")
