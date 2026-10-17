import verify

fn describe(res) {
  match res {
    {ok: true, data} => f"ok: {data}"
    {ok: false, error: {code, msg}} => f"err {code}: {msg}"
    _ => "unknown"
  }
}

fn twice(v) {
  match v { n => n * 2 }
}

fn pick(v) {
  match v {
    1 => "one"
    2 => "two"
    _ => "many"
  }
}

fn lit_str(v) {
  match v { "s" => 1 _ => 0 }
}

fn bool_lit(v) {
  match v { true => "yes" _ => "no" }
}

fn null_lit(v) {
  match v { null => 0 _ => 1 }
}

fn dur_lit(v) {
  match v { 5s => "five" _ => "?" }
}

fn vs_limit(v) {
  let limit = 10
  match v { 1..5 => "low" limit..limit => "at limit" _ => "high" }
}

fn list_shape(v) {
  match v {
    [] => "empty"
    [a] => f"one: {a}"
    [a, b] => f"two: {a},{b}"
    _ => "more"
  }
}

fn single(v) {
  match v { [a] => a _ => -1 }
}

fn two_of_three(v) {
  match v { [a, b] => "two" _ => "three" }
}

fn with_rest(v) {
  match v {
    [0, ...rest] => "starts zero"
    [a, b, ...rest] => f"{a}+{b} then {rest.len()} more: {rest}"
    _ => "?"
  }
}

fn head_only(v) {
  match v { [a, ...] => f"head {a}" _ => "?" }
}

fn rest_empty(v) {
  match v { [a, ...rest] => rest _ => null }
}

fn list_or_not(v) {
  match v { [a, b] => "list" _ => "not list" }
}

fn user_kind(v) {
  match v {
    {name: "ada", admin: true} => "ada the admin"
    { name } => f"just {name}"
    _ => "?"
  }
}

fn simple_user(v) {
  match v {
    {name, admin: true} => f"admin {name}"
    { name } => f"user {name}"
    _ => "?"
  }
}

fn has_a(v) {
  match v { { a } => "has a" _ => "?" }
}

fn click(v) {
  match v {
    {type: "click", pos: {x, y}} => f"click at ({x}, {y})"
    { type } => f"other: {type}"
    _ => "?"
  }
}

fn str_key(v) {
  match v { {"k e y": _v} => _v _ => -1 }
}

fn dict_rest(v) {
  match v {
    {a, ...rest} => f"a={a} rest has {rest.len()} keys: {rest.keys().sort()}"
    _ => "?"
  }
}

fn ignore_rest(v) {
  match v { {x, ...} => "ignored rest" _ => "?" }
}

fn dict_or_not(v) {
  match v { { a } => "dict" _ => "not dict" }
}

fn deep(v) {
  match v {
    [{name: first, tags: [t1, ..._]}, ..._] => f"{first} tagged {t1}"
    _ => "?"
  }
}

fn order(v) {
  match v { n => f"first {n}" 5 => "five" _ => "other" }
}

fn wild_first(v) {
  match v { _ => "always" 2 => "never" }
}

fn dur_frac(v) {
  match v { 1.5s => "one and a half" _ => "?" }
}

test "bare idents bind (0.3.0 semantics)" {
  verify.eq(twice(5), 10)
  var who = "none"
  match "ox" { name => { who = name } }
  verify.eq(who, "ox")
}

test "literals still compare" {
  verify.eq(pick(2), "two")
  verify.eq(pick(1), "one")
  verify.eq(pick(9), "many")
  verify.eq(lit_str("s"), 1)
  verify.eq(bool_lit(true), "yes")
  verify.eq(null_lit(null), 0)
  verify.eq(dur_lit(5s), "five")
}

fn neg_one(v) {
  match v { -1 => "neg one" _ => "?" }
}

test "expression patterns still compare by value" {
  verify.eq(vs_limit(5), "low")
  verify.eq(vs_limit(10), "at limit")
  verify.eq(vs_limit(11), "high")
  verify.eq(neg_one(-1), "neg one")
}

test "list patterns: exact" {
  verify.eq(list_shape([1, 2]), "two: 1,2")
  verify.eq(list_shape([]), "empty")
  verify.eq(single([9]), 9)
  # longer lists do not match shorter patterns
  verify.eq(two_of_three([1, 2, 3]), "three")
}

test "list patterns: literals nested and rest" {
  verify.eq(with_rest([1, 2, 3, 4]), "1+2 then 2 more: [3, 4]")
  verify.eq(with_rest([0, 9]), "starts zero")
  verify.eq(head_only([1]), "head 1")
  # rest binds []
  verify.eq(rest_empty([1]), [])
}

test "list pattern must match a list" {
  verify.eq(list_or_not("ab"), "not list")
}

test "dict patterns: partial match and shorthand" {
  verify.eq(user_kind({name: "ada", admin: true, age: 36}), "ada the admin")
  verify.eq(simple_user({name: "bob", admin: false}), "user bob")
  # extra keys are fine (partial match); missing keys fail
  verify.eq(has_a({a: 1, b: 2}), "has a")
  verify.eq(has_a({b: 2}), "?")
}

test "dict patterns: string keys and nested" {
  verify.eq(click({type: "click", pos: {x: 10, y: 20}}), "click at (10, 20)")
  verify.eq(click({type: "key"}), "other: key")
  verify.eq(str_key({"k e y": 7}), 7)
}

test "dict patterns: rest collects leftovers" {
  verify.eq(dict_rest({a: 1, b: 2, c: 3}),
    "a=1 rest has 2 keys: [\"b\", \"c\"]")
  verify.eq(ignore_rest({x: 1}), "ignored rest")
}

test "dict pattern must match a dict" {
  verify.eq(dict_or_not([1]), "not dict")
}

test "deep nesting: list in dict in list" {
  verify.eq(deep([{name: "a", tags: [1, 2]}, {name: "b", tags: []}]),
    "a tagged 1")
}

test "bindings are scoped to the arm" {
  let x = 1
  match 99 { _x => { verify.eq(_x, 99) } }
  verify.eq(x, 1) # outer x untouched
}

test "match carries a value" {
  verify.eq(describe({ok: true, data: 42}), "ok: 42")
  verify.eq(describe({ok: false, error: {code: 7, msg: "nope"}}),
    "err 7: nope")
  verify.eq(describe("weird"), "unknown")
}

test "first matching arm wins" {
  verify.eq(order(5), "first 5")
}

test "wildcard-first match" {
  verify.eq(wild_first(1), "always")
  verify.eq(wild_first(2), "always")
}

test "fractional duration patterns" {
  verify.eq(dur_frac(1.5s), "one and a half")
}
