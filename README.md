# ox

**A sturdy little language for automation & tooling.**

ox is a dynamically-typed scripting language built for the jobs shell scripts
and small Python tools usually do — files & directories, shell commands,
HTTP servers & clients, websockets, data wrangling, scheduled and concurrent
tasks — with first-class **workflows** (steps, retries, rollback, persisted
state) and clean, obvious tooling:

```text
ox run deploy.ox      # run it (dynamic interpretation)
ox test               # test it (built-in runner)
ox check deploy.ox    # statically analyze it
ox build deploy.ox    # compile it into a self-contained executable
ox repl               # play with it
```

It reaches the **Python** and **C** ecosystems directly, runs on python3.9+
with **zero third-party dependencies**, and the whole language fits in your
head.

---

## The 60-second tour

```ox
# hello.ox — run with: ox run hello.ox
let name = "world"
print("hello, {name}!")                    # string interpolation

fn greet(who, punct="!") { "hi {who}{punct}" }   # defaults + implicit return
print(greet("ox", punct="?"))

# durations are values
print("budget: {100ms + 2s}")              # -> 2.1s

# concurrency: spawn + await
let results = await [
  spawn { net.get("http://example.com") },
  spawn { net.get("http://example.org") },
]

# workflows: steps, retries, rollback, persisted history
workflow "backup" {
  desc "Nightly backup"

  step "dump"    { sh("pg_dump app > dump.sql") } retry 3 backoff 2s
  step "upload"  { net.post("https://backups", data=fs.read("dump.sql")) } \
                 rollback { sh("rm dump.sql") }
  step "verify"  { verify fs.size("dump.sql") > 0, "empty dump" }

  on fail { log.error("backup failed") }
  on done { emit "backup.ok" }
}

let r = run("backup")        # -> {ok, steps, ms, ...}
run("backup", dry=true)      # show the plan, execute nothing
run("backup", resume=true)   # redo only unfinished steps of the last failed run
```

```ox
# servers are a statement, too
serve 8080 {
  get "/hello/:name" { res.json({msg: "hi " + req.params.name}) }
  post "/echo"       { res.json(req.json) }
  static "/assets"   "./public"
  ws "/chat"         { conn.on("message", fn (m) { conn.send(m) }) }
}
```

```ox
# the ecosystems are one import away
import py
import c

let math = py.import("math")
print(math.sqrt(2.0))                      # python, directly

let libm = c.lib("m")
let pow_fn = libm.fn("pow", [c.double, c.double], c.double)
print(pow_fn(2.0, 10.0))                   # -> 1024.0, via C
```

## Install

Requires python3.9+ and nothing else.

```sh
git clone <this repo> && cd ox
pip install .          # gives you the `ox` command
ox version
```

or use it straight from the repo without installing:

```sh
python3 -m ox run examples/hello.ox
```

## What's inside

| Area | Highlights |
|---|---|
| **Language** | dynamic types, closures, varargs/kwargs, `match`, string interpolation (`"n={n}"`), raw strings, triple-quoted strings, durations (`2s`, `150ms`), ranges (`1..5`), pipes (`xs |> sort |> reverse`), deep equality, `let`/`var` immutability checking, implicit block returns |
| **Async** | every call is awaitable; `spawn { }` / `await`, `co.all/any/timeout/every/after`, event bus (`on "evt"` / `emit "evt"`) |
| **fs** | read/write/append/lines, walk, glob, copy/move/remove, json helpers, grep, replace, hashes, `fs.watch` directory monitors |
| **os / sh** | `sh()` with capture/env/cwd/timeout, exit codes, env vars, device info (cpu/mem/disk/net), platform info, script args |
| **net** | `net.get/post/put/patch/delete/head`, query params, headers, forms, JSON, downloads, `net.ws(...)` websocket client, `tcp_ping`, URL utilities |
| **server** | `serve <port>` with routing, `:params`, static files, keep-alive, 405s, graceful Ctrl+C, **HTTPS** (`tls={cert, key}`), **WebSocket** endpoints |
| **data** | JSON / CSV / YAML / TOML, deep merge, schema `validate()` with predicates |
| **workflows** | steps with `retry`/`backoff`, per-step `rollback`, `on fail/done` hooks, dry runs, partial runs (`only=`), `resume`, persisted history + status (`wf` module) |
| **testing** | `test "name" { ... }` files, `verify` statement, `verify.*` helpers, timeouts, `--json` reports |
| **interop** | `py.import/eval/exec/pip`, `c.lib("m").fn(...)` ctypes FFI |
| **tooling** | `ox run/test/check/build/repl/init`, pretty errors with ox-level tracebacks, static analysis (undefined vars, let reassignment, unreachable code, unused vars) |
| **compile** | `ox build` statically checks, transpiles to readable Python and packages a self-contained zipapp executable |

## Documentation

- [docs/LANGUAGE.md](docs/LANGUAGE.md) — the full language spec
- [docs/STDLIB.md](docs/STDLIB.md) — every module, every function
- [docs/CLI.md](docs/CLI.md) — commands, flags, exit codes, project layout
- [docs/DESIGN.md](docs/DESIGN.md) — how it works inside, and why
- [examples/](examples/) — runnable tours: `hello`, `files`, `backup`, `server`, `fetch`, `interop`, `tool`, `devserver`

**中文文档**（详细）：

- [docs/zh/README.md](docs/zh/README.md) — 总览
- [docs/zh/tutorial.md](docs/zh/tutorial.md) — 入门教程（30 分钟上手）
- [docs/zh/language.md](docs/zh/language.md) — 语言参考
- [docs/zh/stdlib.md](docs/zh/stdlib.md) — 标准库手册
- [docs/zh/cli.md](docs/zh/cli.md) — 命令行手册

## Status

v0.4.0 — the language core, stdlib, test suite (190 tests), compiler and
packaging are working and covered by tests; see [CHANGELOG.md](CHANGELOG.md).
The design goals and known limitations are documented honestly in
[docs/DESIGN.md](docs/DESIGN.md#limitations). Order-of-magnitude performance
expectations live in [docs/PERF.md](docs/PERF.md).

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux (glibc, Python 3.12+) | **supported** | all 190 tests run here |
| macOS | supported (untested here) | same POSIX surface; `fcntl`/process groups behave the same |
| Windows | **not supported** | `fs.lock` (flock) and `os.start` (process groups) are POSIX-only; the CLI prints a warning and those APIs raise clear errors. WSL2 works |

ox is single-machine, single-process, trusted-environment tooling by
design: `py.exec` / `py.eval` / `c.lib` are deliberate arbitrary-code
execution bridges, not a sandbox. Do not run untrusted ox programs.

## License

MIT — see [LICENSE](LICENSE).
