# core language semantics
import verify

test "let/var/reassignment" {
  let x = 10
  var y = 1
  y += 5
  verify.eq(x, 10)
  verify.eq(y, 6)
  let e = verify.throws(fn () {
      x=99
    })
  verify.ne(e, null)
}

test "var without initializer is null" {
  var empty
  verify.true(empty == null)
}

test "arithmetic" {
  verify.eq(2 + 3 * 4, 14)
  verify.eq((2 + 3) * 4, 20)
  verify.eq(7 / 2, 3.5)
  verify.eq(7 // 2, 3)
  verify.eq(7 % 3, 1)
  verify.eq(2 ** 10, 1024)
  verify.eq(-2 ** 2, -4)
  verify.eq(0x10, 16)
  verify.eq(0b101, 5)
  verify.eq(1_000_000, 1000000)
  verify.eq(1.5e3, 1500.0)
}

test "string interpolation" {
  let name = "ox"
  let n = 3
  verify.eq(f"hi {name} x{n}", "hi ox x3")
  verify.eq(f"nested {f"a{n}"}", "nested a3")
  verify.eq('raw {name}', 'raw {name}')
  verify.eq("esc { ok", "esc { ok")
}

test "booleans and logic" {
  verify.true(true and not false)
  verify.false(false or (false and true))
  verify.eq(true and "x", "x")
  verify.eq(null ?? "dflt", "dflt")
  verify.eq(1 ?? 2, 1)
  verify.false(true == 1)
  verify.eq(1 == 1.0, true)
}

test "strings methods" {
  let s = "  Hello Ox  "
  verify.eq(s.trim(), "Hello Ox")
  verify.eq("a,b,c".split(","), ["a", "b", "c"])
  verify.eq("ab".repeat(3), "ababab")
  verify.eq("ox".upper(), "OX")
  verify.eq("a-b-c".replace("-", "+"), "a+b+c")
  verify.eq("ox"[0], "o")
  verify.eq("ox".len(), 2)
  verify.true("oxlang".has("xla"))
  verify.eq("hello".slice(1, 3), "el")
  verify.eq("x".pad_left(3, "0"), "00x")
}

test "lists" {
  let l = [3, 1, 2]
  verify.eq(l.len(), 3)
  verify.eq(l.sort(), [1, 2, 3])
  verify.eq(l.reverse(), [2, 1, 3])
  verify.eq(l.map(fn (x) { x * 2 }), [6, 2, 4])
  verify.eq(l.filter(fn (x) { x > 1 }), [3, 2])
  verify.eq(l.reduce(fn (a, b) { a + b }), 6)
  verify.eq(l.sum(), 6)
  verify.eq(l.min(), 1)
  verify.eq(l.max(), 3)
  verify.eq(l.concat([4]), [3, 1, 2, 4])
  verify.eq(l.join("-"), "3-1-2")
  verify.eq(l.first(), 3)
  verify.eq(l.last(), 2)
  verify.eq(l.unique().len(), 3)
  verify.eq([[1, 2], [3]].flatten(), [1, 2, 3])
  verify.eq([1, 2, 3, 4].slice(1, 3), [2, 3])
  verify.eq(l.has(2), true)
  verify.eq(l.index(2), 2)
  verify.eq(l.zip([4, 5, 6]), [[3, 4], [1, 5], [2, 6]])
}

test "list mutation" {
  var l = []
  l.push(1)
  l.push(2)
  verify.eq(l, [1, 2])
  verify.eq(l.pop(), 2)
  l.unshift(0)
  verify.eq(l, [0, 1])
  verify.eq(l.shift(), 0)
  l.insert(0, 9)
  verify.eq(l, [9, 1])
  verify.eq(l.remove(9), true)
  verify.eq(l, [1])
  l[0] = 7
  verify.eq(l[0], 7)
}

test "dicts" {
  let d = {name: "ox", year: 2026, nested: {a: 1}}
  verify.eq(d.name, "ox")
  verify.eq(d["year"], 2026)
  verify.eq(d.nested.a, 1)
  verify.eq(d.keys().sort(), ["name", "nested", "year"])
  verify.eq(d.has("name"), true)
  verify.eq(d.get("missing", "dflt"), "dflt")
  verify.eq(d.pick(["name"]), {name: "ox"})
  verify.eq(d.omit(["name"]).has("name"), false)
  verify.eq({a: 1}.merge({b: 2}), {a: 1, b: 2})
  verify.eq({a: {x: 1}}.merge({a: {y: 2}}, deep=true), {a: {x: 1, y: 2}})
  verify.eq(d.items().len(), 3)
  d.set("new", 5)
  verify.eq(d.new, 5)
}

test "control flow" {
  var acc = []
  for i in 0..<5 { acc.push(i) }
  verify.eq(acc, [0, 1, 2, 3, 4])
  acc = []
  for i in 1..3 { acc.push(i) }
  verify.eq(acc, [1, 2, 3])
  var n = 0
  while n < 10 { n += 3 }
  verify.eq(n, 12)
  var count = 0
  loop {
    count += 1
    if count >= 4 { break } else { continue }
  }
  verify.eq(count, 4)
}

test "for over dict and unpacking" {
  let d = {a: 1, b: 2}
  var keys = []
  for k in d { keys.push(k) }
  verify.eq(keys.sort(), ["a", "b"])
  var sum = 0
  for k, v in d { sum += v }
  verify.eq(sum, 3)
  var pairs = ""
  for i, v in [["x", 1], ["y", 2]] { pairs += f"{i}{v}" }
  verify.eq(pairs, "x1y2")
}

test "functions and closures" {
  fn add(a, b) { return a + b }
  verify.eq(add(2, 3), 5)
  fn greet(name, punct="!") { return f"hi {name}{punct}" }
  verify.eq(greet("ox"), "hi ox!")
  verify.eq(greet("ox", punct="?"), "hi ox?")
  fn counter(start) {
    var n = start
    return fn () { n += 1
      n }
  }
  let c = counter(10)
  c()
  verify.eq(c(), 12)
  let mk = fn (a) { fn (b) { a + b } }
  verify.eq(mk(3)(4), 7)
}

test "implicit block return" {
  fn square(x) { x * x }
  verify.eq(square(5), 25)
  let dbl = fn (x) { x * 2 }
  verify.eq(dbl(4), 8)
}

test "varargs and kwargs" {
  fn total(* nums) {
    var s = 0
    for n in nums { s += n }
    s
  }
  verify.eq(total(1, 2, 3), 6)
  fn opts(a, b=2, * rest) { return [a, b, rest] }
  verify.eq(opts(1), [1, 2, []])
  verify.eq(opts(1, 9, 7, 8), [1, 9, [7, 8]])
  verify.eq(opts(1, b=5), [1, 5, []])
}

test "if/else chains and match" {
  fn grade(n) {
    if n >= 90 { "A" } else if n >= 80 { "B" } else { "C" }
  }
  verify.eq(grade(95), "A")
  verify.eq(grade(85), "B")
  verify.eq(grade(50), "C")
  fn kind(x) {
    match x {
      1 => { return "one" }
      "two" => { return "two!" }
      _ => { return "many" }
    }
  }
  verify.eq(kind(1), "one")
  verify.eq(kind("two"), "two!")
  verify.eq(kind(99), "many")
}

test "match with expression arms" {
  var picked = null
  match 2 { 1 => { picked = "a" } 2 => { picked = "b" } _ => { picked = "c" } }
  verify.eq(picked, "b")
}

test "errors: throw/catch/finally" {
  var finally_ran = false
  # catch can inspect the error, then rethrow; finally still runs
  let err = verify.throws(fn () {
      try {
        throw error("boom", code=42, data={ctx: "test"})
      } catch e {
        verify.eq(e.msg, "boom")
        verify.eq(e.code, 42)
        verify.eq(e.data.ctx, "test")
        throw error("rethrown")
      } finally {
        finally_ran=true
      }
    })
  verify.eq(err.msg, "rethrown")
  verify.true(finally_ran)
  try { throw "plain" } catch e { verify.eq(e.msg, "plain") }
  try {
    pass
  } finally {
    finally_ran = true
  }
  verify.true(finally_ran)
  # catch without binding
  try { throw error("x") } catch { }
  # try/finally without catch: error still propagates
  let err2 = verify.throws(fn () {
      try { throw error("y") } finally { }
    })
  verify.eq(err2.msg, "y")
}

test "type errors are catchable" {
  let e = verify.throws(fn () { 1 + "a" })
  verify.true(e.msg.has("cannot add"))
  let e2 = verify.throws(fn () { [1][5] })
  verify.true(e2.msg.has("out of range"))
  let e3 = verify.throws(fn () { missing_var })
  verify.true(e3.msg.has("undefined variable"))
}

test "ranges" {
  let r = 1..5
  verify.eq(r.len(), 5)
  verify.eq(r.to_list(), [1, 2, 3, 4, 5])
  verify.eq((0..<3).to_list(), [0, 1, 2])
  verify.eq(range(4).to_list(), [0, 1, 2, 3])
  verify.eq(range(0, 10, 3).to_list(), [0, 3, 6, 9])
}

test "durations" {
  verify.eq(100ms, 0.1)
  verify.eq(2s, 2000ms)
  verify.eq(1m, 60)
  verify.eq(1h, 3600)
  verify.eq(2s + 500ms, 2.5)
  verify.eq(1d, 86400)
}

test "pipe operator" {
  let result = [3, 1, 2] |> sort |> reverse
  verify.eq(result, [3, 2, 1])
  let doubled = 5 |> fn (x) { x * 2 }
  verify.eq(doubled, 10)
  verify.eq("ox" |> upper, "OX")
}

test "slices and indexing" {
  let l = [0, 1, 2, 3, 4, 5]
  verify.eq(l[1:3], [1, 2])
  verify.eq(l[:2], [0, 1])
  verify.eq(l[4:], [4, 5])
  verify.eq(l[::2], [0, 2, 4])
  verify.eq(l[-1], 5)
  verify.eq(l[-2:], [4, 5])
}

test "deep equality" {
  verify.true([1, [2, [3]]] == [1, [2, [3]]])
  verify.true({a: [1, {b: 2}]} == {a: [1, {b: 2}]})
  verify.false([1, 2] == [2, 1])
  verify.false({a: 1} == {b: 1})
}

test "comparisons" {
  verify.true(1 < 2)
  verify.true("a" < "b")
  verify.true(2 >= 2)
  verify.true(1 != 2)
  verify.false([1] == [2])
  let e = verify.throws(fn () { 1 < "a" })
  verify.true(e.msg.has("cannot compare"))
}

test "globals: type/str/repr/int/float" {
  verify.eq(type(1), "int")
  verify.eq(type(1.5), "float")
  verify.eq(type("x"), "str")
  verify.eq(type(null), "null")
  verify.eq(type(true), "bool")
  verify.eq(type([]), "list")
  verify.eq(type({ }), "dict")
  verify.eq(type(fn () { }), "fn")
  verify.eq(str(42), "42")
  verify.eq(str([1, "a"]), '[1, "a"]')
  verify.eq(int("42"), 42)
  verify.eq(int("0xff"), 255)
  verify.eq(int(3.99), 3)
  verify.eq(float("2.5"), 2.5)
  verify.eq(repr("hi"), '"hi"')
  verify.eq(len({a: 1, b: 2}), 2)
}

test "recursion" {
  fn fib(n) {
    if n < 2 { return n }
    fib(n - 1) + fib(n - 2)
  }
  verify.eq(fib(20), 6765)
}

test "hoisting: fns defined later are callable" {
  verify.eq(later_fn(2), 4)
}

fn later_fn(x) { x * 2 }

test "dynamic eval" {
  let x = 20
  verify.eq(eval("x + 1"), 21)
  verify.eq(eval("2 ** 5"), 32)
}
