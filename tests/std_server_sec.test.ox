# Server security invariants: path traversal, header injection, body limits.
# These pin the guards added in 0.4 (see STDLIB.md > server > res.file).

import fs
import net
import verify

fn tmpdir() {
  return fs.temp_dir("ox-sec")
}

test "res.file root= blocks path traversal" {
  let d = tmpdir()
  fs.write(d + "/ok.txt", "secret-onion")

  let h = serve 0, daemon = true {
    get "/download" {
      # path comes from the query string — classic user-controlled input
      res.file(fs.join(d, req.query.path), root=d)
    }
  }
  let base = f"http://127.0.0.1:{h.port}"

  # normal fetch inside the root works
  let r1 = net.get(base + "/download?path=ok.txt")
  verify.eq(r1.status, 200)
  verify.eq(r1.body, "secret-onion")

  # traversal attempts are rejected with 403
  let r2 = net.get(base + "/download?path=../ok.txt")
  verify.eq(r2.status, 403)
  let r3 = net.get(base + "/download?path=..%2F..%2Fetc%2Fhostname")
  verify.eq(r3.status, 403)
  let r4 = net.get(base + "/download?path=/etc/hostname")
  verify.eq(r4.status, 403)

  h.stop()
  fs.remove(d)
}

test "header values cannot inject CRLF" {
  let h = serve 0, daemon = true {
    get "/" {
      res.headers["X-Test"] = "value\r
X-Injected: yes"
      res.headers["X-Quote"] = '" onclick="alert(1)'
      res.send("ok")
    }
  }
  let r = net.get(f"http://127.0.0.1:{h.port}/")
  verify.eq(r.status, 200)
  verify.eq(r.body, "ok")
  # the injected header must not exist as a separate header
  verify.eq(r.headers.keys().contains("x-injected"), false)
  verify.true(r.headers["x-test"].contains("value"))
  h.stop()
}

test "download filename cannot inject headers" {
  let d = tmpdir()
  fs.write(d + "/a.txt", "x")
  let h = serve 0, daemon = true {
    get "/" {
      res.file(d + "/a.txt",
        download="evil\r
Set-Cookie: pwn=1\r
X-Injected: yes")
    }
  }
  let r = net.get(f"http://127.0.0.1:{h.port}/")
  verify.eq(r.status, 200)
  verify.eq(r.headers.keys().contains("x-injected"), false)
  verify.eq(r.headers.keys().contains("set-cookie"), false)
  verify.true(r.headers["content-disposition"].contains("evil"))
  h.stop()
  fs.remove(d)
}

test "oversized bodies are rejected with 413" {
  let h = serve 0, daemon = true {
    post "/echo" {
      res.send(req.body)
    }
  }
  # 33 MB of body against the 32 MB cap; net.post runs off-loop, so the
  # server can drain and answer while the client is still sending
  let blob = "x".repeat(33 * 1024 * 1024)
  let r = net.post(f"http://127.0.0.1:{h.port}/echo", data=blob, timeout=30s)
  verify.eq(r.status, 413)
  verify.eq(r.ok, false)
  h.stop()
}

test "static routes still reject traversal (regression)" {
  let d = tmpdir()
  fs.write(d + "/index.html", "<h1>ok</h1>")
  let h = serve 0, daemon = true {
    static "/assets" d
  }
  let r = net.get(f"http://127.0.0.1:{h.port}/assets/../../etc/hostname")
  verify.true(r.status == 403 or r.status == 404)
  h.stop()
  fs.remove(d)
}
