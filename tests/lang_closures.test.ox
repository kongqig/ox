import co
import verify

# module-level state written from fns (compiled path needs `global`)
var counter = 0

fn bump(n) {
  counter = counter + n
}

test "fns can update module-level var" {
  bump(2)
  bump(3)
  verify.eq(counter, 5)
}

fn make_counter(start) {
  var n = start
  return fn () {
    n = n + 1
    return n
  }
}

test "closure over fn-local var" {
  let c = make_counter(10)
  verify.eq(c(), 11)
  verify.eq(c(), 12)
  verify.eq(c(), 13)
  # independent instances have independent state
  let d = make_counter(0)
  verify.eq(d(), 1)
  verify.eq(c(), 14)
}

fn outer() {
  var a = 1
  fn middle() {
    var b = 10
    return fn () {
      a = a + 1 # two levels out
      b = b + 5 # one level out
      return [a, b]
    }
  }
  return middle()
}

test "two-level closure writes" {
  let f = outer()
  verify.eq(f(), [2, 15])
  verify.eq(f(), [3, 20])
}

fn for_capture() {
  var total = 0
  for i in 1..4 {
    total = total + i
  }
  return fn () {
    total = total * 2
    return total
  }
}

test "for-loop capture and later writes" {
  let f = for_capture()
  verify.eq(f(), 20) # (1+2+3+4) * 2
  verify.eq(f(), 40)
}

fn match_rebind() {
  var seen = 0
  match [1, 2] {
    [a, b] => {
      let combo = a + b
      match combo {
        n => { seen = n * 10 }
      }
    }
  }
  return fn () {
    seen = seen + 1
    return seen
  }
}

test "match-bound names live in the enclosing scope" {
  let f = match_rebind()
  verify.eq(f(), 31)
}

test "thunk bodies see and update enclosing vars" {
  var hits = 0
  let h = co.every(50ms, fn () { hits=hits + 1 })
  await co.sleep(180ms)
  h.stop()
  verify.true(hits >= 2)
}
