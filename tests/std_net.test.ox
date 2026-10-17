import co
import net
import time
import verify

var base = null
var server = null

test "boot server", timeout = 5s {
  server = serve 0, daemon = true {
    get "/" { res.json({msg: "hello"}) }
    get "/users/:id" { res.json({id: req.params.id}) }
    get "/q" { res.json(req.query) }
    post "/echo" { res.json({got: req.json ?? req.form}) }
    put "/echo" { res.json({method: "PUT"}) }
    patch "/echo" { res.json({method: "PATCH"}) }
    delete "/gone" { res.json({method: "DELETE"}) }
    get "/agent" { res.json({ua: req.headers["user-agent"]}) }
    get "/slow" { await co.sleep(50ms)
      res.json({ok: true}) }
  }
  base = f"http://127.0.0.1:{server.port}"
  await sleep(100ms)
}

test "GET json" {
  let r = net.get(f"{base}/")
  verify.true(r.ok, f"status {r.status}")
  verify.eq(r.status, 200)
  verify.eq(r.json.msg, "hello")
}

test "path params" {
  let r = net.get(f"{base}/users/77")
  verify.eq(r.json.id, "77")
}

test "query params" {
  let r = net.get(f"{base}/q", query={a: "1", b: "two words"})
  verify.eq(r.json.a, "1")
  verify.eq(r.json.b, "two words")
}

test "POST json body" {
  let r = net.post(f"{base}/echo", json={x: [1, 2], y: "z"})
  verify.eq(r.json.got.x, [1, 2])
  verify.eq(r.json.got.y, "z")
}

test "POST form body" {
  let r = net.post(f"{base}/echo", form={a: 1})
  verify.eq(r.json.got.a, "1")
}

test "custom headers" {
  let r = net.get(f"{base}/agent", headers={"User-Agent": "ox-test/1.0"})
  verify.eq(r.json.ua, "ox-test/1.0")
}

test "PUT/PATCH/DELETE" {
  verify.eq(net.put(f"{base}/echo").json.method, "PUT")
  verify.eq(net.patch(f"{base}/echo").json.method, "PATCH")
  verify.eq(net.delete(f"{base}/gone").json.method, "DELETE")
}

test "concurrent requests overlap", timeout = 5s {
  let t0 = time.now()
  let rs = await [spawn { net.get(f"{base}/slow") }, spawn { net.get(f"{base}/slow") }]
  let took = (time.now() - t0) * 1000
  verify.true(rs[0].ok and rs[1].ok)
  verify.true(took < 120, f"requests should overlap, took {took}ms")
}

test "404 and connection refusal" {
  verify.eq(net.get(f"{base}/missing").status, 404)
  let bad = net.get("http://127.0.0.1:1/", timeout=200ms)
  verify.false(bad.ok)
}

test "parse_url" {
  let u = net.parse_url("https://example.com:8443/a/b?x=1&y=2#frag")
  verify.eq(u.scheme, "https")
  verify.eq(u.host, "example.com")
  verify.eq(u.port, 8443)
  verify.eq(u.path, "/a/b")
  verify.eq(u.query, {x: "1", y: "2"})
}

test "tcp_ping" {
  verify.true(net.tcp_ping("127.0.0.1", server.port, timeout=1s).ok)
  verify.false(net.tcp_ping("127.0.0.1", 1, timeout=200ms).ok)
}

test "shutdown server" {
  server.stop()
  await sleep(50ms)
  let r = net.get(f"{base}/", timeout=300ms)
  verify.false(r.ok, "server should be down")
}
