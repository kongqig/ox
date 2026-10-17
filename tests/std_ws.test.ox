import net
import verify

test "ws echo roundtrip", timeout = 5s {
  let server = serve 0, daemon = true {
    ws "/echo" {
      conn.on("message", fn (msg) {
          conn.send(f"echo: {msg}")
        })
      conn.on("connect", fn (_) {
          conn.send("welcome")
        })
    }
  }
  await sleep(100ms)
  let c = net.ws(f"ws://127.0.0.1:{server.port}/echo")
  let first = c.recv(timeout=1s)
  verify.eq(first, "welcome")
  await c.send("ping")
  let reply = c.recv(timeout=1s)
  verify.eq(reply, "echo: ping")
  await c.send_json({a: 1})
  let r2 = c.recv(timeout=1s)
  verify.eq(r2, 'echo: {"a": 1}')
  await c.close()
  server.stop()
}

test "ws broadcast to multiple clients", timeout = 5s {
  var clients = []
  let server = serve 0, daemon = true {
    ws "/chat" {
      clients.push(conn)
      conn.on("message", fn (msg) {
          for c in clients { c.send(msg) }
        })
      conn.on("close", fn (_) { clients.remove(conn) })
    }
  }
  await sleep(100ms)
  let url = f"ws://127.0.0.1:{server.port}/chat"
  let c1 = net.ws(url)
  let c2 = net.ws(url)
  var c1_got = []
  var c2_got = []
  c1.on("message", fn (m) { c1_got.push(m) })
  c2.on("message", fn (m) { c2_got.push(m) })
  await sleep(100ms)
  await c1.send("hello")
  await sleep(150ms)
  await c2.send("world")
  await sleep(150ms)
  verify.eq(c1_got, ["hello", "world"])
  verify.eq(c2_got, ["hello", "world"])
  await c1.close()
  await c2.close()
  await sleep(150ms)
  verify.eq(clients.len(), 0, f"clients not cleaned up: {clients.len()}")
  server.stop()
}
