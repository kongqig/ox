import py
import c
import verify

test "py.import and call" {
  let math = py.import("math")
  verify.approx(math.sqrt(2.0), 1.41421356, eps=1e-5)
  verify.eq(math.floor(3.7), 3)
}

test "py.eval" {
  verify.eq(py.eval("2 + 3"), 5)
  verify.eq(py.eval("[x * 2 for x in range(4)]"), [0, 2, 4, 6])
}

test "py.exec" {
  py.exec("RESULT = 99")
  verify.eq(py.eval("RESULT"), 99)
}

test "py attribute paths" {
  let dt = py.import("datetime.datetime")
  verify.true(dt.now() != null)
}

test "c libm" {
  let libm = c.lib("m")
  let pow_fn = libm.fn("pow", [c.double, c.double], c.double)
  verify.eq(pow_fn(2.0, 10.0), 1024.0)
  let sqrt_fn = libm.fn("sqrt", [c.double], c.double)
  verify.approx(sqrt_fn(9.0), 3.0)
}

test "c libc" {
  let libc = c.lib("c")
  let strlen = libc.fn("strlen", [c.char_p], c.size_t)
  verify.eq(strlen("hello ox"), 8)
  let abs_fn = libc.fn("abs", [c.int], c.int)
  verify.eq(abs_fn(-42), 42)
}

test "compile builtin emits python" {
  let src = compile('fn id(x) { x }')
  verify.true(src.has("async def id"))
  verify.true(src.has("_rt"))
}

test "eval builtin shares the environment" {
  let local = 100
  verify.eq(eval("local + 1"), 101)
}
