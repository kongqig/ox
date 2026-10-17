# ox — design & architecture

## Goals

1. **Fit the domain.** Automation scripts want files, commands, HTTP,
   schedules, retries and rollback as *first-class* ideas — not as an
   afterthought library you assemble yourself every time.
2. **Small, obvious tooling.** `run`, `test`, `check`, `build`, `repl`,
   `init`. Nothing to configure before the first hello world.
3. **Both dynamic and static.** Iterate like a script (`ox run`), then
   lock it down (`ox check` catches undefined variables and accidental
   rebinding; `ox build` refuses to compile broken code).
4. **Borrowed ecosystems, zero dependencies.** ox itself installs with
   nothing but python3.9+, yet reaches all of PyPI (`py`) and native
   libraries (`c`).

## The implementation in one page

```
                ┌────────────────────────────────────────────┐
  source.ox ──▶ │ lexer ──▶ parser ──▶ AST                   │
                └──────┬──────────────────────┬──────────────┘
                       │                      │
              dynamic path              static path
                       │                      │
                ┌──────▼──────┐        ┌──────▼────────┐
                │ interpreter │        │ analyzer      │  undefined vars,
                │ (async tree │        │ (scopes)      │  let-rebinding,
                │  walker)    │        └──────┬────────┘  dead code ...
                └──────┬──────┘               │
                       │                ┌──────▼────────┐
                runtime values      │   │ transpiler    │  AST → python
                (shared semantics)◀─┼───│ (AST → py)    │
                       │                └──────┬────────┘
                ┌──────▼──────┐               │
                │ builtins/   │          ┌────▼────────┐
                │ 18 modules  │          │ builder     │  zipapp packaging
                └─────────────┘          └─────────────┘
```

### Everything is a coroutine

The interpreter's `eval`/`exec` are `async`. This single decision is what
makes `spawn { }` / `await`, the event bus, `co.every` monitors, and the
hand-rolled asyncio HTTP/WebSocket server feel native instead of bolted
on. Blocking work (`sh`, urllib requests, stdin) runs in worker threads
via `asyncio.to_thread`, so concurrent `spawn`s genuinely overlap.

### One set of semantics, two consumers

`ox/values.py` defines how ox values behave — truthiness, deep equality,
`+` coercion, duration math, method tables, calling conventions. Both the
interpreter and the compiled code produced by `ox build` route every
operation through this module (`ox/runtime.py` re-exports it), which is
why a transpiled program behaves exactly like an interpreted one. The
test suite pins this: the same assertions run interpreted, and the
transpiler smoke tests compare outputs.

### The DSL statements are sugar over callables

`workflow`/`step`/`serve`/`get`/`ws`/`test`/`on`/`emit` parse into
statement nodes, but at execution time they *register callables* —
closures for the interpreter, nested `async def`s for the transpiler.
That means the workflow engine (`ox/builtins/taskmod.py`) and the server
(`servermod.py`) are written once and drive both execution paths.

### Workflow state is append-only JSON

Every run appends a record (per-step status, attempts, durations, errors)
to `.ox/state/<name>.json`. That file *is* the version history:
`wf.status`, `wf.history` and `resume=true` are just reads over it.

### Static compilation model

`ox build` = analyze (must pass) → transpile to readable Python → package
the program *and* the ox runtime into a zipapp with a python3 shebang.
The output is a single executable file that needs only python3.9+.
This is honest AOT-to-VM compilation, not a claim of native speed: the
transpiled program skips parsing and AST dispatch, so it is somewhat
faster than interpretation, and it distributes as one file — those are
the goals.

## Why a Python host?

- the py bridge becomes trivial and complete (no FFI shim for every call)
- `c.lib(...)` gets ctypes for free
- cryptography, TLS, HTTP, and OS APIs come from the standard library,
  keeping ox itself dependency-free
- the implementation stays small enough to audit in an afternoon

The trade-off — python startup time and interpreter speed — is the right
one for a tool language whose scripts spend their time in IO, subprocesses
and the network.

## Limitations (honest list)

- **Speed**: tree-walking interpretation; `ox build` helps modestly, not
  dramatically. ox is for gluing, not number crunching.
- **Recursion depth** is guarded at ~900 frames (clean error, not a crash).
- `match` patterns are equality checks plus `_`; no destructuring yet.
- No classes/structs — dicts, closures and modules cover the tool domain;
  this is deliberate but limiting for large programs.
- Compiled apps register `test` blocks but don't run them (keep testing
  with `ox test`).
- The WebSocket server implements the common subset of RFC 6455 (text
  frames, ping/pong, close, fragmentation) — no permessage-deflate.
- Windows: `os.mem()`/`os.cpu().load` return best-effort data; everything
  else works.

## Roadmap ideas

- pattern destructuring in `match`; string format helpers
- `ox fmt`, `ox doc`
- per-workflow concurrency locks and cron-like schedules
- packaging with an embedded interpreter (PyInstaller/Oxidizer) for
  python-free binaries
- source maps so transpiled tracebacks point at .ox lines
