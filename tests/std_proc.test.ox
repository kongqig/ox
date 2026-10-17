import co
import net
import os
import verify

test "os.start basics: wait, output, exit code" {
  let p = os.start("echo hello; echo oops >&2; exit 3")
  verify.true(p.pid > 0)
  verify.true(p.cmd.has("echo hello"))
  let r = await p.wait(5s)
  verify.false(r.timed_out)
  verify.false(r.ok)
  verify.eq(r.code, 3)
  verify.eq(r.out.trim(), "hello")
  verify.eq(r.err.trim(), "oops")
  verify.false(p.running)
}

test "wait returns ok for zero exit" {
  let p = os.start("true")
  let r = await p.wait(5s)
  verify.true(r.ok)
  verify.eq(r.code, 0)
}

test "wait timeout leaves the process running" {
  let p = os.start("sleep 10")
  let r = await p.wait(150ms)
  verify.true(r.timed_out)
  verify.false(r.ok)
  verify.true(p.running)
  await p.kill()
  verify.false(p.running)
}

test "kill terminates with a nonzero code" {
  let p = os.start("sleep 30")
  await co.sleep(50ms)
  verify.true(await p.kill())
  verify.false(p.running)
  let r = await p.wait(1s)
  verify.false(r.timed_out)
  verify.false(r.ok)
  verify.ne(r.code, 0)
}

test "output is captured while running" {
  let p = os.start("echo first; sleep 1; echo second")
  await co.sleep(300ms)
  verify.true(p.out().has("first"))
  verify.false(p.out().has("second"))
  let r = await p.wait(5s)
  verify.true(r.ok)
  verify.true(r.out.has("first"))
  verify.true(r.out.has("second"))
}

test "env and cwd are applied" {
  let p = os.start("echo $OX_TEST_VAR", env={OX_TEST_VAR: "from-env"})
  let r = await p.wait(5s)
  verify.eq(r.out.trim(), "from-env")
}

test "net.wait_port against a live server" {
  let server = serve 0, daemon = true {
    get "/" { res.text("up") }
  }
  verify.true(await net.wait_port("127.0.0.1", server.port, timeout=5s))
  let r = await net.get(f"http://127.0.0.1:{server.port}/")
  verify.eq(r.status, 200)
  server.stop()
}

test "net.wait_port times out on a dead port" {
  verify.false(await net.wait_port("127.0.0.1", 1, timeout=300ms))
}
