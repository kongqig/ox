import data
import json
import verify

test "json parse/dump" {
  let v = json.parse('{"a": 1, "b": [true, null, "x"]}')
  verify.eq(v.a, 1)
  verify.eq(v.b, [true, null, "x"])
  verify.eq(json.dump(v), '{"a": 1, "b": [true, null, "x"]}')
  verify.eq(json.dump({a: 1}, pretty=true).has("
"), true)
  let e = verify.throws(fn () { json.parse("{oops") })
  verify.true(e.msg.has("invalid JSON"))
}

test "csv" {
  let csv_text = "name,age
ada,36
linus,55
"
  let rows = data.csv_parse(csv_text)
  verify.eq(rows.len(), 2)
  verify.eq(rows[0].name, "ada")
  verify.eq(rows[1].age, "55")
  verify.eq(data.csv_dump(rows), csv_text)
  let raw = data.csv_parse("1,2
3,4", header=false)
  verify.eq(raw, [["1", "2"], ["3", "4"]])
}

test "yaml" {
  let y = data.yaml_parse("name: ox
nums:
  - 1
  - 2
")
  verify.eq(y.name, "ox")
  verify.eq(y.nums, [1, 2])
  verify.eq(data.yaml_dump({a: [1, 2]}), "a:
- 1
- 2
")
}

test "toml" {
  let t = data.toml_parse('title = "ox"
[owner]
name = "you"
')
  verify.eq(t.title, "ox")
  verify.eq(t.owner.name, "you")
}

test "merge" {
  verify.eq(data.merge({a: 1}, {b: 2}), {a: 1, b: 2})
  let deep = data.merge({x: {y: 1, z: 1}}, {x: {z: 2}}, deep=true)
  verify.eq(deep, {x: {y: 1, z: 2}})
}

test "validate: types" {
  let schema = {name: "str", age: "int", email: "email?", tags: ["str"],
    score: "num?", active: "bool?"}
  let good = {name: "ox", age: 1, tags: []}
  verify.true(data.validate(good, schema).ok)
  let bad = {name: 42, age: "old", tags: ["a", 5]}
  let r = data.validate(bad, schema)
  verify.false(r.ok)
  verify.eq(r.errors.len(), 3)
  verify.true(r.errors[0].msg.has("expected str"))
}

test "validate: nested + strict + predicates" {
  let schema = {user: {name: "str"}, "_strict": true}
  verify.true(data.validate({user: {name: "x"}}, schema).ok)
  verify.false(data.validate({user: {name: "x"}, extra: 1}, schema).ok)
  let positive = fn (v) { v >= 0 }
  verify.true(data.validate(5, positive).ok)
  verify.false(data.validate(-1, positive).ok)
}

test "list helpers via methods" {
  let rows = [{n: "b", v: 2}, {n: "a", v: 1}]
  verify.eq(rows.sort_by("n")[0].n, "a")
  verify.eq(rows.sort_by("v", reverse=true)[0].n, "b")
}
