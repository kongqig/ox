# The ox language — reference

ox is dynamically typed, expression-oriented where it matters, and built
around the automation domain: files, commands, network, data, tasks.

## 1. Lexical structure

```ox
# comments run to end of line (a leading #! shebang line is a comment too)

let x = 1_000 + 0xFF + 0b1010 + 1.5e3   # numbers: separators, hex, binary,
                                         # octal (0o17), floats, exponents
let d = 150ms + 2s + 1m + 1h + 1d       # duration literals (values, in seconds)
let e = 1.5s + 250.5ms                # fractional durations work too

let s  = f"hello {name}, n={n + 1}"      # interpolation of any expression
let r  = 'raw {string}'                 # raw string: no interpolation
let ml = f"""
  multi-line text with {interpolation}  # triple-quoted strings
"""
let css = "body { color: red }"          # plain "..." never interpolates
let esc = f"brace: \{ escaped"          # inside f-strings, \{ is a literal {
```

Identifiers are `[A-Za-z_][A-Za-z0-9_]*`. Statements are separated by
newlines (or `;`). Newlines inside `( )` and `[ ]` are ignored, so calls and
lists can span lines. A line that *ends* with an operator continues the
expression; a line that *starts* with `.` continues a method chain.

**Keywords**: `let var fn return if else for in while loop break continue try
catch finally throw async await spawn on emit import export as and or not
true false null match pass workflow serve test verify`

`get/put/post/delete/patch/head/static/ws/step/retry/backoff/rollback/desc/
fail/done` are contextual — they are only special inside `serve` /
`workflow` blocks and can be used as names everywhere else.

## 2. Values and types

| Type | Examples |
|---|---|
| null | `null` |
| bool | `true`, `false` (distinct from numbers: `true == 1` is `false`) |
| int / float | `42`, `3.14`; `/` always yields a float, `//` floors |
| duration | `2s`, `150ms`, `1h` — numbers (of seconds) that print nicely |
| str | `f"interpolated"`, `"plain"`, `'raw'`, `f"""multi-line"""` |
| list | `[1, "two", [3]]` |
| dict | `{name: "ox", "weird key": 1, (expr): 2}` |
| range | `1..5` (inclusive), `0..<5` (exclusive), `range(0, 10, 2)` |
| fn | `fn (a, b) { a + b }`, named `fn` declarations |
| error | `error("msg", code=42, data={...})` — a value you can throw |
| task | what `spawn` returns; consume with `await` |
| module | what `import` binds |

Truthiness: `false`, `null`, `0`, `""`, `[]`, `{}` are falsy; everything
else is truthy.

### Operators

```ox
+  -  *  /  //  %  **        # arithmetic (durations participate: 2s + 500ms)
==  !=  <  <=  >  >=         # == is deep equality for lists/dicts
and  or  not                 # short-circuit; return the deciding operand
??                           # null coalescing
|>                           # pipe: xs |> sort |> reverse
..   ..<                     # ranges
```

`+` also concatenates lists and merges dicts; `"n=" + 1` coerces when the
left side is a string.

**Precedence** (tightest first):

| level | operators | notes |
|---|---|---|
| 1 | `.` `()` `[]` | postfix call / index / attribute |
| 2 | `**` | right-associative; `-2 ** 2` is `-(2 ** 2)` |
| 3 | unary `-`, `await` | |
| 4 | `*` `/` `//` `%` | |
| 5 | `+` `-` | |
| 6 | `..` `..<` | non-chaining |
| 7 | `==` `!=` `<` `<=` `>` `>=` | non-chaining (`a < b < c` is an error) |
| 8 | `not` | looser than comparisons: `not a == b` is `not (a == b)` |
| 9 | `and` | |
| 10 | `or` | |
| 11 | `??` | looser than `or`: `false or null ?? "d"` is `(false or null) ?? "d"` |
| 12 | `|>` | loosest — pipes take everything on the left |

When in doubt, parenthesise.

### Indexing & slicing

```ox
let l = [0, 1, 2, 3, 4, 5]
l[0]        # 0
l[-1]       # 5
l[1:3]      # [1, 2]     (python-style slices, step allowed: l[::2])
let d = {nested: {deep: 42}}
d.nested.deep      # attribute access on dicts
d["nested"]["deep"]
```

## 3. Statements

### Bindings

```ox
let x = 10        # immutable in this scope (reassignment is an error)
var y = 0         # rebindable
var z             # starts as null
x += 1            # error: x was declared with let
y += 1            # fine
```

Shadowing in inner scopes is always allowed. `_` is a discard name — it can
be rebound and never warns.

### Functions

```ox
fn add(a, b) { return a + b }

fn greet(name, punct="!") {          # defaults (evaluated at definition)
  f"hi {name}{punct}"                 # implicit return: last expression
}

fn varargs(a, *rest) { rest }        # varargs collect into a list
greet("ox", punct="?")               # keyword arguments at callsites
net.get(url, verify=false)           # keyword names may be ox keywords

let double = fn (x) { x * 2 }        # anonymous functions
fn make_counter(start) {             # closures capture their environment
  var n = start
  fn () { n += 1; n }
}
```

Top-level `fn` declarations are hoisted — callable before their definition.

Argument-name rules (0.4.1):

- a keyword token followed by `=` in an argument list is a keyword-argument
  name — `net.get(url, verify=false)` parses; inside `(...)` a keyword can
  never start a statement, so this is unambiguous
- parameter names may be `verify`, `on`, `test` or `workflow` (soft
  keywords: usable as names *and* references); other keywords are rejected
  with a clear error
- a default of `null` is a real default — `fn f(a, opt=null)` can be
  called as `f(1)` (before 0.4.1 `opt` was treated as required)

`if` / `match` / `try` are **expressions**: their value is the value of the
branch that ran (a branch with no else / no matching arm yields `null`).

```ox
let grade = if score >= 90 { "A" } else { "B" }
let name  = match id { 1 => "one" _ => "?" }        # see patterns below
let safe  = try { risky() } catch e { null }
print(if dry_run { "(dry)" })                        # prints "(dry)" or null
```

They also work in statement position (the value is simply discarded), in
function bodies as implicit returns, and inside call arguments. One rule
for *compiled* code (`ox build`): `return` / `break` / `continue` cannot
cross an if/match/try expression — `ox check` rejects it with a helpful
message; assign to a variable and use the statement form instead. The
interpreter is more permissive (a `break` inside an expression `if` breaks
the enclosing loop).

### Control flow

```ox
if score >= 90 { "A" } else if score >= 80 { "B" } else { "C" }

for x in [1, 2, 3] { ... }
for k, v in {a: 1, b: 2} { ... }     # unpack dicts into pairs
for i in 0..<10 { ... }

while cond { ... }
loop { if done { break } else { continue } }

match method {
  "GET"  => { ... }
  "POST" => { ... }
  _      => { ... }                  # wildcard
}
```

### Value methods

Every value type carries methods (no imports needed). These are the tables
— the same names the static analyzer accepts:

**str**: `len empty upper lower trim trim_left trim_right split split_lines
replace startswith endswith has contains index slice repeat pad_left
pad_right chars reverse first last capitalize title swapcase`

**list**: `len empty push push_all pop shift unshift insert remove remove_at
index has contains count join concat first last slice reverse unique
flatten clone sum min max avg zip indexes map filter each find find_index
any all reduce sort sort_by`

**dict**: `len empty keys values items has contains get set del merge update
pick omit clone sort_keys map_values filter first`

**number**: `abs floor ceil round clamp times`

**range**: `len empty to_list`

```ox
"a,b".split(",")             # ["a", "b"]
[3, 1, 2].sort()              # [1, 2, 3]
{a: 1}.pick(["a"])            # {"a": 1}
5.times(fn (i) { print(i) })   # 0 1 2 3 4
(1..5).to_list()              # [1, 2, 3, 4, 5]
```

Note: `print` renders dicts JSON-style (`{"a": 1}`), keys quoted; use
`log.json` or `data.json_dump` when you need machine-readable output and
`str(x)` for the same human form.

### Match patterns

Arm patterns do more than compare literals:

```ox
match value {
  42                => "the answer"  # literals compare by value
  "GET"             => "method"
  1..9              => "single digit"   # ranges match by containment
  1..<9             => "1 to 8"
  n                 => f"bound: {n}"  # a bare ident binds the subject
  [a, b]            => f"pair {a},{b}"       # lists: exact length
  [head, ...rest]   => f"head+{rest.len()}"  # ...rest captures the tail
  {name, admin: true} => f"admin {name}"     # dicts: partial match
  {ok: true, data}  => f"ok {data}"          # shorthand binds key to itself
  {a, ...rest}      => f"a plus {rest.len()} extra keys"
  [{x}, {y}]        => "nested works too"
  _                 => "anything"
}
```

Rules, in one place:

- literals (`1`, `"s"`, `true`, `null`, `5s`) compare with deep equality
- ranges (`1..5`, `0..<n`) match when the subject is a number inside them
- a bare identifier **binds** the subject (it is not compared against an
  outer variable of the same name — that was 0.2 behaviour, changed in 0.3)
- list patterns need the exact length unless `...rest` (or bare `...`)
  absorbs the tail; the subject must be a list
- dict patterns match partially (extra keys are fine), missing keys fail;
  `...rest` collects the unmatched keys as a dict
- anything else (calls, `-1`, interpolated strings) is evaluated and
  compared by value
- bindings are scoped to the arm body; the first matching arm wins

### Errors

```ox
try {
  throw error("disk full", code=500, data={path: "/db"})
} catch e {                          # e is the error value
  print(f"{e.msg} (code {e.code})")
} finally {
  cleanup()
}

verify fs.exists(path), f"path must exist: {path}"
# ^ verify throws a verification error when the condition is falsy
```

Programming errors (type errors, undefined variables, bad indexes) throw
catchable errors too. IO helpers like `sh()` and `net.get()` return
**result dicts** (`{ok, ...}`) instead of throwing — branch on `.ok`.

### Imports & modules

```ox
import fs                          # stdlib module
import net as networking           # aliased
import "./utils.ox" as utils       # local file (relative to this file)
import "./lib"                     # directory: lib/main.ox or lib/index.ox
```

A module's top-level `fn`s are hoisted. Exports:

```ox
export helper, other               # explicit list
export fn public_fn() { ... }      # prefix form
export let version = "1.0"
```

If a module declares no exports, every top-level name not starting with `_`
is public. Names starting with `_` are always private.

## 4. Concurrency & events

**Await is optional everywhere.** Every call — sync fn, async builtin, or
spawned block — evaluates to its final value; `await` never changes the
result, it only matters for ordering (e.g. waiting on a list of spawned
tasks). There is no task/handle leak by forgetting `await`: you either get
the value directly, or a handle only where an API explicitly returns one
(`spawn`, `co.every`, `serve ... daemon=true`).

```ox
let t1 = spawn { heavy(1) }        # runs concurrently
let t2 = spawn { heavy(2) }
let both = await [t1, t2]          # await a list to collect results

await co.sleep(200ms)              # same as: co.sleep(200ms)
let fast = await co.timeout(1s, fn () { slow_thing() })   # fast == the value

let monitor = await co.every(5s, fn () { check_health() })   # repeating task
monitor.stop()

let once = await co.after(30s, fn () { remind() })           # one-shot task
```

Events are a process-wide bus:

```ox
on "deploy.done" fn (evt) { log.info(f"payload: {evt}") }
on "ping" { print(f"got: {event}") }     # block form binds `event`

emit "deploy.done" {host: "prod-1", ms: 812}
emit "ping" "hello"
```

Handler errors are caught and logged; `emit` never kills the emitter.
`events.list()` / `events.off("name")` manage handlers.

## 5. Workflows

```ox
workflow "deploy" {
  desc "Deploy the app to production"        # optional description

  step "build" {
    sh("make build")
  } retry 3 backoff 2s                       # attempts / delay growth

  step "migrate" {
    sh("migrate up")
  } rollback {
    sh("migrate down")                       # undo on later failure
  }

  step "health" {
    let r = net.get("http://localhost:3000/healthz")
    verify r.ok, "health check failed"
  }

  on fail { log.error("deploy failed") }
  on done { emit "deploy.ok" }
}
```

Running and inspecting:

```ox
let r = run("deploy")              # {ok, workflow, run, status, steps, ms, ...}
run("deploy", dry=true)            # print the plan; execute nothing
run("deploy", only=["build", "migrate"])   # subset (hooks are skipped)
run("deploy", skip=["health"])     # everything except
run("deploy", resume=true)         # redo only unfinished steps of the last
                                   # failed run
wf.list()                          # defined workflows
wf.steps("deploy")                 # step names
wf.status("deploy")                # last run summary
wf.history("deploy", n=10)         # run history
wf.state_dir(".ox/state")          # where history lives (default .ox/state)
```

Semantics:

- a step runs its block; success = no thrown error; the block's value is
  recorded in the run log
- `retry N` = total attempts; `backoff D` sleeps `D * attempt` between tries
- when a step finally fails: **its own rollback runs first** (partial-work
  cleanup), then the rollbacks of previously-succeeded steps in reverse
  order; rollback errors are logged, not fatal
- every run (per-step status, attempts, duration, error) is appended to
  `.ox/state/<name>.json` — that history powers `wf.status` / `wf.history`
  and `resume`

## 6. Servers

```ox
serve 8080 {                                # blocks until Ctrl+C
  get "/"            { res.html("<h1>hi</h1>") }
  get "/users/:id"   { res.json({id: req.params.id}) }
  get "/search"      { res.json(req.query) }
  post "/echo"       { res.json(req.json) }
  put "/items/:id"   { res.json({ok: true}) }
  static "/assets"   "./public"             # static files (traversal-safe)
  ws "/chat" {
    conn.on("message", fn (m) { conn.send(m) })
    conn.on("close",   fn (_) { ... })
  }
}
```

Route handler blocks get implicit `req` and `res` bindings (explicit
`fn (req, res)` handlers work too). `req` is a dict:

```ox
req.method   req.path        req.params     req.query     req.headers
req.body     req.json        req.form       req.ip        req.raw_path
```

`res` methods: `send(text, status=, headers=)`, `json(obj, status=)`,
`html(...)`, `redirect(url, status=302)`, `file(path, download=)`,
`set_header(k, v)`, `status(code)`.

Unmatched paths return a JSON 404; wrong methods return 405 with `Allow`.
Handler errors become 500s (the error text is included when started with
`debug=true` or `OX_DEBUG=1`).

Options:

```ox
serve 8443, tls={cert: "cert.pem", key: "key.pem"} { ... }   # HTTPS
let s = serve 8080, daemon=true { ... }                       # background
s.stop()                                                     # ...then stop
s.port                                                       # bound port
serve 8080, host="0.0.0.0" { ... }                           # interface
```

WebSocket connections (`conn`) have: `send(text)`, `send_json(obj)`,
`close()`, `on("message" | "close", fn)`, `.id`, `.ip`.

## 7. Tests

```ox
# anything.test.ox
import verify

test "arithmetic" {
  verify 1 + 1 == 2
}

test "slow thing", timeout=2s {
  verify true
}

test "helpers" {
  verify.eq(sort([2, 1]), [1, 2])
  verify.approx(0.1 + 0.2, 0.3)
  let err = verify.throws(fn () { throw error("x") })
  verify.eq(err.msg, "x")
}
```

`ox test` discovers `*.test.ox` under `tests/` (or a path you give it).
Top-level statements in a test file run first — use them for fixtures.
Failures report file/line; `--json` writes `ox-test-report.json`.

## 8. Dynamic evaluation & compilation

```ox
let x = 20
eval("x + 22")              # -> 42 (parses & runs ox source at runtime)
let py = compile('fn f(n) { n * 2 }')
# py is the Python source that `ox build` would emit for that program
```

## 9. Semantic invariants

These are deliberate language decisions, pinned by
`tests/lang_semantics.test.ox` (and enforced in both the interpreter and
compiled artifacts):

**Strings** — interpolation is opt-in via the `f` prefix. A plain `"..."`
string treats `{` and `}` as literal characters, so CSS, JSON, regexes and
shell snippets are safe without escaping. `'...'` strings are raw (no
escapes, no interpolation). Inside an f-string, `\{` and `\}` produce
literal braces. `ox check` warns when a plain double-quoted string contains
`{name}`-shaped text that was probably meant to interpolate.

**Await** — every call evaluates to its final value; `await` is optional and
never changes the result. Handles exist only where an API explicitly returns
one (`spawn`, `co.every`, `co.after`, `serve daemon=true`).

**Bools are not numbers** — `true + 1` is a type error and `true == 1` is
`false`. Numeric contexts never coerce booleans.

**Division by zero** is always a catchable error (`/`, `//`, `%`); there are
no NaN/Infinity values in ox arithmetic.

**Recursion depth** is limited (~900 frames in the interpreter, more in
compiled artifacts); overflowing raises a catchable `stack overflow` error
with an ox-level trace, never a Python traceback.

**Iteration** — `for x in xs` iterates elements (lists) or keys (dicts);
`for k, v in xs` unpacks each element (dicts yield key/value pairs, lists
yield their elements). `d.items()` returns `[k, v]` pairs explicitly.

**Deep equality** — `==` compares values structurally (lists, dicts, nested
data), not identities. Cyclic structures render with `...` instead of
crashing.

**Match bindings** — bare identifiers in patterns *bind*, they never
compare against outer variables. `ox check` warns when a binding shadows a
user-defined name; prefix the name with `_` to bind on purpose.
