import co
import events
import time
import verify

test "spawn and await" {
  let t = spawn { 21 * 2 }
  verify.eq(await t, 42)
  fn slow_add(a, b) {
    await co.sleep(10ms)
    a + b
  }
  let r = await slow_add(1, 2)
  verify.eq(r, 3)
}

test "await list runs concurrently" {
  fn work(ms) {
    await co.sleep(ms)
    ms
  }
  let t0 = time.now()
  let results = await [spawn { work(50ms) }, spawn { work(60ms) }, spawn { work(70ms) }]
  let took = (time.now() - t0) * 1000
  verify.eq(results, [50ms, 60ms, 70ms])
  verify.true(took < 190, f"should run concurrently, took {took}ms")
}

test "co.timeout" {
  fn quick() { 1 }
  fn slow() { await co.sleep(5s)
    2 }
  verify.eq(await co.timeout(1s, quick), 1)
  let e = verify.throws(fn () { await co.timeout(50ms, slow) })
  verify.true(e.msg.has("timed out"))
}

test "co.every monitor with stop" {
  var ticks = 0
  let m = await co.every(30ms, fn () { ticks+=1 })
  await sleep(200ms)
  m.stop()
  verify.true(ticks >= 3, f"expected ticks, got {ticks}")
  let before = ticks
  await sleep(100ms)
  verify.eq(ticks, before, "monitor should have stopped")
}

test "co.after one-shot" {
  var ran = false
  let h = await co.after(50ms, fn () { ran=true })
  verify.false(ran)
  await sleep(150ms)
  verify.true(ran)
}

test "events: on/emit" {
  var got = []
  on "test.evt" fn (payload) { got.push(payload) }
  on "test.evt" { got.push(event) }
  emit "test.evt" 1
  emit "test.evt" 2
  verify.eq(got, [1, 1, 2, 2])
}

test "events: handler errors are isolated" {
  on "bad.evt" fn (_) { throw error("handler exploded") }
  emit "bad.evt" null
  verify.true(true, "emit survived a bad handler")
}

test "events module: list/off" {
  on "off.evt" { pass }
  on "off.evt" { pass }
  verify.eq(events.list()["off.evt"], 2)
  verify.eq(events.off("off.evt"), 2)
  verify.false(events.list().has("off.evt"))
}
