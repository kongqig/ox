# hello.ox — the 30-second tour of ox
# run: ox run examples/hello.ox

let name = "world"
print(f"hello, {name}!")

# functions with defaults, closures, varargs
fn greet(who, punct="!") { f"hi {who}{punct}" }
fn counter(start) {
  var n = start
  fn () { n += 1
    n }
}
fn total(* nums) {
  var s = 0
  for n in nums { s += n }
  s
}
print(greet("ox"))
print(greet("ox", punct="?"))
print(f"counter: {counter(10)()}")
print(f"total: {total(1, 2, 3, 4)}")

# strings interpolate any expression; 'single quotes' are raw
let n = 3
print(f"n={n}, doubled={n * 2}, upper={'ox'.upper()}")

# lists & dicts with rich methods
let langs = ["ox", "python", "c"].map(fn (l) { l.upper() })
print(f"langs: {langs.join(', ')}")
let info = {name: "ox", version: 1, tags: ["small", "sturdy"]}
print(f"{info.name} v{info.version}: {info.tags.join(' + ')}")

# control flow; if/match blocks have values
fn grade(score) {
  if score >= 90 { "A" } else if score >= 80 { "B" } else { "C" }
}
print(f"grade 87 -> {grade(87)}")
match langs.len() {
  3 => { print("three languages listed") }
  _ => { print("some other count") }
}

# durations are values: 100ms + 2s == 2.1
print(f"timing budget: {100ms + 2s}")

# errors as values, try/catch/finally
try {
  throw error("something went sideways", code=500)
} catch e {
  print(f"caught: {e.msg} (code {e.code})")
}

# verify is a statement — assertions anywhere
verify grade(95) == "A", "95 should be an A"
print("all good ✓")
