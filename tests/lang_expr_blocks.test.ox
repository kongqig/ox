import verify

# if / match / try as expressions (0.3.1) — every case must behave
# identically interpreted and compiled (compiled emits nested thunks).

test "if expression in let" {
  let grade = if 95 >= 90 { "A" } else { "B" }
  verify.eq(grade, "A")
}

test "if expression without else yields null" {
  let v = if false { 1 }
  verify.eq(v, null)
}

test "else-if chain as expression" {
  fn grade(s) {
    if s >= 90 { "A" } else if s >= 80 { "B" } else if s >= 70 { "C" } else { "F" }
  }
  verify.eq(grade(95), "A")
  verify.eq(grade(85), "B")
  verify.eq(grade(75), "C")
  verify.eq(grade(10), "F")
}

test "if expression writing an outer var" {
  var hits = 0
  let label = if true { hits += 1
    "one" } else { "zero" }
  verify.eq(label, "one")
  verify.eq(hits, 1)
}

test "match expression binds" {
  let name = match 5 { n => f"n={n}" }
  verify.eq(name, "n=5")
}

test "match expression with ranges and wildcard" {
  fn bucket(n) {
    match n {
      0..9 => "low"
      10..99 => "mid"
      _ => "high"
    }
  }
  verify.eq(bucket(0), "low")
  verify.eq(bucket(42), "mid")
  verify.eq(bucket(1000), "high")
}

test "match expression unmatched yields null" {
  let v = match 99 { 1 => "one" }
  verify.eq(v, null)
}

test "try/catch as expression" {
  fn risky(boom) {
    try {
      if boom { throw error("kaboom") }
      "clean"
    } catch e {
      f"caught:{e.msg}"
    }
  }
  verify.eq(risky(false), "clean")
  verify.eq(risky(true), "caught:kaboom")
}

test "block expressions in call arguments" {
  fn wrap(s) { f"<{s}>" }
  let w = wrap(if true { "yes" } else { "no" })
  verify.eq(w, "<yes>")
}

test "nested expression blocks" {
  let v = if true {
    match 2 { 1 => "a" 2 => "b" _ => "c" }
  } else {
    "other"
  }
  verify.eq(v, "b")
}

test "spawn block value still works" {
  let t = spawn { if true { 42 } else { 0 } }
  verify.eq(await t, 42)
}

test "varargs are lists (interp and compiled)" {
  fn tail_of(a, * rest) { rest }
  verify.eq(tail_of(1, 2, 3), [2, 3])
  verify.eq(tail_of(9), [])
  verify.eq(tail_of(1, 2).len(), 1)
  verify.true(tail_of(1, 2, 3).has(3))
}

test "break and continue outside loops are clean errors" {
  let e1 = verify.throws(fn () { eval("break") })
  verify.true(e1.msg.has("outside of a loop"))
  let e2 = verify.throws(fn () { eval("continue") })
  verify.true(e2.msg.has("outside of a loop"))
}
