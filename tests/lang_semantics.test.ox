# Semantic invariants pinned by the 0.4 review.
# Every test here documents a deliberate language decision so regressions
# in either the interpreter or the compiler are caught immediately.

import verify

# ---------------------------------------------------------------- f-strings
test "plain double quotes never interpolate" {
  let css = "body { color: red }"
  verify.eq(css, 'body { color: red }')
  let json = "{\"a\": 1}"
  verify.eq(json, '{"a": 1}')
  let msg = "got {n} items"
  verify.eq(msg, "got {n} items")
  verify.eq("a } b { c", 'a } b { c')
}

test "f-string interpolation" {
  let name = "ox"
  let n = 3
  verify.eq(f"hi {name} x{n}", "hi ox x3")
  verify.eq(f"expr {n * 2 + 1}", "expr 7")
  verify.eq(f"nested {f"a{n}"}", "nested a3")
  verify.eq(f"first {[1, 2].join("-")}", "first 1-2")
}

test "f-string escapes and literal braces" {
  verify.eq(f"brace \{ ok", "brace { ok")
  verify.eq(f"brace \} ok", "brace } ok")
  verify.eq(f"tab	nl
", "tab	nl
")
  verify.eq(f"", "")
}

test "f-string value rendering matches interpolation" {
  let d = {a: 1}
  verify.eq(f"{d}", f"{d}") # deterministic within a run
  verify.eq(f"{[1, "x"]}", '[1, "x"]')
  verify.eq(f"{null}", "null")
  verify.eq(f"{true}", "true")
}

test "raw single quotes stay literal" {
  verify.eq('no 
 escapes {here}', 'no 
 escapes {here}')
  verify.eq('\\d{2}', '\\d{2}')
}

test "f triple-quoted strings" {
  let who = "ox"
  let t = f"""
line {who}
\{ literal
"""
  verify.true(t.contains("line ox"))
  verify.true(t.contains("{ literal"))
}

test "duration and numbers inside f-strings" {
  verify.eq(f"{2s + 500ms}", "2.5s")
  verify.eq(f"{1_000 + 0x10}", "1016")
}

# ------------------------------------------------------- transparent await
test "calls transparently wait - no await keyword needed" {
  import co
  import time
  let t0 = time.now()
  let v = co.timeout(1s, fn () { 42 })
  let dt = time.now() - t0
  verify.eq(v, 42)
  verify.true(dt < 0.5, "timeout resolves instantly when fn is fast")
}

test "async builtin result is the final value, not a task" {
  import co
  let v = co.timeout(1s, fn () { 10 })
  verify.eq(v + 1, 11) # arithmetic works directly: not a handle
}

test "await on a sync fn is harmless" {
  fn quick() { 1 }
  verify.eq(await quick(), 1)
  verify.eq(quick(), 1)
}

test "un-awaited sleep really sleeps" {
  import co
  import time
  let t0 = time.now()
  co.sleep(100ms)
  verify.true(time.now() - t0 >= 0.09, "must actually wait ~100ms")
}

# ------------------------------------------------------------- value rules
test "bool is not a number" {
  verify.throws(fn () { true +1 })
  verify.throws(fn () { 1 + false })
  verify.eq(true == true, true)
  verify.eq(1 == 1, true)
  verify.eq(true == 1, false)
}

test "division by zero is a clean error" {
  verify.throws(fn () { 1 / 0 })
  verify.throws(fn () { 1 / 0.0 })
  verify.throws(fn () { 1 // 0 })
}

test "unicode strings are code-point indexed" {
  let s = "你好 🚀 café"
  verify.eq(s.len(), 9)
  verify.eq(s.slice(0, 2), "你好")
  verify.eq(s.upper(), "你好 🚀 CAFÉ")
  verify.eq("x".repeat(3), "xxx")
}

test "deep recursion overflows with a catchable error" {
  fn down(n) { if n == 0 { "done" } else { down(n - 1) } }
  verify.throws(fn () { down(100000) })
}

test "stack overflow error is catchable and has a message" {
  fn down(n) { if n == 0 { "done" } else { down(n - 1) } }
  var caught = ""
  try {
    down(50000)
  } catch e {
    caught = e.msg
  }
  verify.true(caught.contains("recursion"))
}

# --------------------------------------------------------- iteration rules
test "for over a dict unpacks key/value pairs" {
  var out = []
  for k, v in {a: 1, b: 2} {
    out.push(f"{k}={v}")
  }
  verify.eq(out.sort(), ["a=1", "b=2"])
}

test "for over a list unpacks elements" {
  var out = []
  for a, b in [["x", 1], ["y", 2]] {
    out.push(f"{a}{b}")
  }
  verify.eq(out, ["x1", "y2"])
}

test "for with one name over a dict yields keys" {
  # one name -> key (Python intuition); use .items() or two names for pairs
  var keys = []
  for k in {a: 1, b: 2} {
    keys.push(k)
  }
  verify.eq(keys.sort(), ["a", "b"])
  var pairs = 0
  for pair in {a: 1}.items() {
    verify.eq(pair, ["a", 1])
    pairs = pairs + 1
  }
  verify.eq(pairs, 1)
}

test "iteration rules are documented behavior" {
  # lists: iterate elements (two names unpack an element)
  # dicts: one name -> key; two names -> key/value; .items() -> [k, v] pairs
  var dict_pairs = []
  for k, v in {only: 1} {
    dict_pairs = [k, v]
  }
  var list_pairs = []
  for k, v in [["only", 1]] {
    list_pairs = [k, v]
  }
  verify.eq(dict_pairs, list_pairs)
  verify.eq({a: 1}.items(), [["a", 1]])
}

# -------------------------------------------------------- contextual keywords
test "workflow context: desc is a normal name" {
  workflow "kw-shadow" {
    let desc = "my description"
    step "s" { verify true }
    verify.eq(desc, "my description")
  }
}

# ------------------------------------------------------------------ pipes
test "pipe feeds the left value into a call" {
  let double = fn (x) { x * 2 }
  verify.eq(5 |> double, 10)
  verify.eq([3, 1, 2] |> sort, [1, 2, 3])
  verify.eq([3, 1, 2] |> sort |> reverse, [3, 2, 1])
  verify.eq("abc" |> upper, "ABC")
}

# ------------------------------------------------------------ cyclic values
test "cyclic dict repr does not crash" {
  let a = {name: "a"}
  a.self = a
  let text = str(a)
  verify.true(text.len() > 0)
  verify.true(text.contains("..."))
}

test "cyclic list repr does not crash" {
  let xs = [1, 2]
  xs.push(xs)
  let text = str(xs)
  verify.true(text.contains("..."))
}

# ------------------------------------------------------------------- eval
test "eval bad syntax is a catchable error" {
  var caught = false
  try {
    eval("let = = 3")
  } catch e {
    caught = true
  }
  verify.true(caught)
}

test "eval runtime errors are catchable" {
  var msg = ""
  try {
    eval("1 / 0")
  } catch e {
    msg = e.msg
  }
  verify.eq(msg, "division by zero")
}

test "eval returns the last expression value" {
  verify.eq(eval("let x = 6; x * 7"), 42)
}

# ------------------------------------------------------- keywords as kwargs
# `verify`, `on`, `in`... are statement keywords, but inside an argument
# list a keyword followed by `=` is a keyword-argument name (0.4.1 fix:
# net.get(url, verify=false) used to be a parse error)
fn kw_probe(a, verify=null, on=null, workflow=null) {
  return [a, verify, on, workflow]
}

test "keyword tokens work as kwarg names" {
  let r = kw_probe(1, verify=false, on=2, workflow=3)
  verify.eq(r, [1, false, 2, 3])
  # positional args still fine, and `==` is not mistaken for `=`
  verify.eq(kw_probe(9, verify=1 == 1), [9, true, null, null])
}

test "sort_by accepts user functions (not just key strings)" {
  let pairs = [[1, 3], [2, 1], [3, 2]]
  verify.eq(pairs.sort_by(fn (p) { p[1] }), [[2, 1], [3, 2], [1, 3]])
  verify.eq(pairs.sort_by(fn (p) { p[1] }, reverse=true),
    [[1, 3], [3, 2], [2, 1]])
  # key-string form still works
  let rows = [{name: "b", n: 1}, {name: "a", n: 2}]
  verify.eq(rows.sort_by("n")[0].name, "b")
}

test "null defaults are real defaults, not required params" {
  # 0.4.1: `opt=null` used to count as a missing default, making the
  # parameter required — None was overloaded to mean both
  fn probe(a, opt=null) { return [a, opt] }
  verify.eq(probe(1), [1, null])
  verify.eq(probe(1, opt=2), [1, 2])
  verify.eq(probe(1, 2), [1, 2])
}
