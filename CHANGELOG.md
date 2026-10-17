# Changelog

## 0.4.1 — TLS self-signed tests, workflow state recovery, dogfood fixes

Closes the last two items from the external review checklist (TLS
boundary, state corruption recovery) and hardens the language through
real-world use: four non-trivial automation scripts (log analysis, backup
job with rollback/resume, endpoint monitor, CSV ETL pipeline) were
written and run as a user would, and every papercut they exposed was
fixed and pinned by tests.

Workflow state recovery:
- corrupt state files (truncated, garbage, valid JSON with a wrong shape)
  are backed up to `<name>.json.corrupt` (numbered on repeat) with a loud
  warning instead of being silently discarded; malformed run records are
  dropped while valid ones are salvaged — never a traceback
- a run is persisted as `"running"` *before* its first step and finalized
  at the end, so a process that dies mid-run leaves a visible record that
  `run(..., resume=true)` treats as crashed and recovers from (verified
  end-to-end with a real SIGKILL)
- one live run per workflow: an advisory flock on `<name>.lock` makes a
  second concurrent run fail with a clear error instead of clobbering
  state (cross-process and cross-task)
- known tension, documented: rollbacks are compensating (they also fire
  for already-succeeded steps when a later step fails), which interacts
  badly with `resume=true` if a rollback undoes work resume assumes
  exists — scope rollbacks to the step that owns the partial work

TLS / server:
- new test suite `std_tls` runs a real self-signed HTTPS + WSS server:
  roundtrips with `verify=false`, rejection with `verify=true`, plain
  HTTP against a TLS port, `net.download` over TLS, and clear errors for
  unusable `tls=` options (bad paths / non-dict); certificates are
  generated via the py bridge (cryptography) with an openssl fallback,
  and the suite reports as skipped when neither is available
- `net.ws(url, verify=false)` accepts self-signed certificates for
  `wss://` (previously impossible — the client always verified)
- `serve tls=` with missing/mismatched cert files raises a clear ox error
  instead of a Python traceback
- `ServerHandle.url` reports `https://` for TLS servers (was `wss://`)

Language fixes found by dogfooding:
- keyword tokens work as kwarg names: `net.get(url, verify=false)` used
  to be a parse error; inside an argument list a keyword followed by `=`
  can only be a kwarg name
- `on`, `test`, `workflow` are soft keywords usable as parameter names
  and references; other keywords in parameter position get a clear error
  (`keyword 'in' cannot be a parameter name`)
- a parameter default of `null` is a real default: `fn f(a, opt=null)`
  used to treat `opt` as required (None was overloaded to mean both "no
  default" and "default is null"); handler/route/step closures with
  defaulted params also bind correctly now (they used to receive AST
  nodes as default values)
- `sort_by(fn ...)` works with user functions — it never did (ox
  functions are not python-callable, so any function key raised a type
  error); key-string form unchanged
- compiled code passes keyword arguments to user functions with
  python-reserved names correctly (kwarg keys are now mangled to match
  the mangled parameter names)

Standard library:
- `verify.skip(msg)` marks a test as skipped; `ox test` reports a
  separate skipped count (also in `--json`), and `ox test` exits 0
- `fs.remove_tree` follows rm -rf semantics: removing a missing
  directory is a no-op instead of an error

Examples (new, all run as part of the release check):
- `examples/log_report.ox` — nginx access-log analysis without regex:
  status classes, top clients/paths, hourly histogram, markdown + JSON
- `examples/backup_job.ox` — snapshot → archive → checksum → verify →
  publish → prune workflow with rollback, `OX_FAIL=1` failure injection
  and automatic resume
- `examples/monitor.ox` — endpoint uptime/latency monitor with p50/p95,
  incidents and an SLO gate
- `examples/data_pipeline.ox` — CSV ETL with junk-row rejection, region
  aggregation, markdown/JSON reports and a no-money-lost assertion

## 0.4.0 — explicit interpolation, security hardening, build parity

Driven by an external language review. Every claim in the review was
verified against actual behavior first; the real defects were fixed and the
design decisions that were already correct are now pinned by tests and
documented as invariants.

**Breaking** — interpolation is opt-in:
- plain `"..."` strings treat `{` and `}` as literal characters: CSS, JSON,
  regexes and shell snippets are safe without escaping
- `f"..."` (and `f"""..."""`) enable `{expr}` interpolation; `\{` and `\}`
  produce literal braces inside f-strings
- `'...'` stays raw (no escapes, no interpolation); `f'...'` is a lex error
- `ox check` warns about plain double-quoted strings containing `{name}`-
  shaped text (the classic 0.3 migration miss), and `ox fmt` preserves the
  f prefix
- all tests, examples and docs were migrated (177 automatic + manual fixes
  for interpolation nested inside interpolations)

Language & tooling:
- match patterns: bare identifiers bind (Rust-style, unchanged); `ox check`
  now warns when a binding shadows a user-defined outer variable — use a
  `_`-prefixed name to bind on purpose, or a literal/guard to compare
- transparent await is now a documented invariant with pinning tests:
  every call evaluates to its final value, `await` never changes the
  result, handles exist only where an API returns one (spawn / co.every /
  co.after / serve daemon)
- `eval()` with bad source raises a catchable error instead of leaking a
  python ParseError traceback
- iteration rules documented and pinned: one name over a dict yields keys,
  two names unpack `[k, v]`; `d.items()` returns explicit pairs
- new test suite `tests/lang_semantics.test.ox` (27 tests) pins every
  invariant above in both interpreter and compiled form

Security (server):
- `res.file(path, download=null, root=null)`: pass `root=` to confine
  user-derived paths — anything resolving outside it is a 403. Without
  `root`, arbitrary script-chosen paths stay allowed
- response headers are sanitized (CR/LF stripped from names and values),
  closing a header-injection hole via `res.headers` or `download=`
- oversized bodies are now drained (bounded) before the 413, so
  well-behaved clients receive the status instead of a connection reset;
  malformed content-length answers 400
- new suite `tests/std_server_sec.test.ox`: traversal, CRLF injection,
  filename injection, 413, static-route regression

Compiler correctness (found by the new build end-to-end harness):
- `let h = serve ...` (serve in expression position) failed to transpile
  — now compiles and returns the daemon handle
- `runtime._serve` dropped the server handle (compiled daemons always got
  null) — fixed
- route block handlers were transpiled with zero parameters but are called
  as `handler(req, res)` — the compiled `serve` was never actually usable;
  fixed and covered by `scripts/build_e2e.py` (interpreter vs zipapp
  output parity)

Platform honesty:
- documented platform support (Linux supported, macOS expected, Windows
  explicitly not); `os.start` raises a clear error on non-POSIX platforms
  and the CLI prints a one-line warning on Windows
- `docs/PERF.md` + `docs/zh/perf.md`: measured baselines — startup ~256 ms,
  interpreter fib(26) ~3.8 s vs ~1.1 s compiled (~3.4x), 1k concurrent
  tasks ~+20 ms net, fs/json/string/list at python speed

Docs:
- LANGUAGE.md §9 "Semantic invariants" and the Chinese equivalent pin the
  reviewed decisions (f-strings, await, bool ≠ num, div-by-zero, recursion
  cap, iteration, deep equality, match bindings)
- Chinese docs updated throughout for the f-string change; performance and
  platform-support pages added

## 0.3.1 — consistency audit + detailed Chinese documentation

A full pass over the language with a three-pronged audit harness (bad-input
stability, interpreter-vs-spec semantics, interpreter-vs-compiled parity —
201 checks, all passing) turned up and fixed the following.

Language:
- if / match / try are now true expressions, not just value-carrying
  statements: `let g = if score >= 90 { "A" } else { "B" }`,
  `match x { ... }` in call arguments, pipes over parenthesised blocks.
  The compiled path emits nested thunks; parity verified per-case
- `break` / `continue` outside any loop now produce a clean positioned
  runtime error instead of a python traceback; `eval("break")` surfaces a
  catchable ox error instead of leaking the signal
- `str(null)` now renders "null", matching interpolation and repr (was "")
- removed the stray str-only `is_empty` method (use `empty` like every
  other type)

Compiler:
- varargs parameters are lists in compiled code too (`*rest` used to leak
  python tuples: `(2, 3)` instead of `[2, 3]`, and list methods failed on
  it)
- the static analyzer now checks inside expression-position if/match/try,
  and rejects `return` / `break` / `continue` crossing them (they cannot
  escape a compiled thunk); the interpreter stays permissive

Documentation:
- new detailed Chinese docs under docs/zh/: a 30-minute tutorial, a full
  language reference (precedence table, complete pattern rules, the value
  method tables), a stdlib manual covering every module, and a CLI guide —
  every fenced example is parse-checked and the tutorial's outputs are
  verified end-to-end
- English LANGUAGE.md gained the operator precedence table, the full value
  method tables, and the (now accurate) expression-block rules

Tests: 158 (was 145) — new suite lang_expr_blocks (13). All 26 source files
fmt-clean; examples re-verified in both modes.
## 0.3.0 — patterns, scheduling, formatting, binaries

Language:
- match destructuring: list patterns ([a, b, ...rest], exact length unless
  a rest clause), dict patterns ({name, admin: true, ...rest} — partial
  match, shorthand keys, rest collects leftovers), nesting anywhere;
  range patterns now match by containment (5 matches 1..5, not 1..<5)
- breaking: a bare identifier in a match arm now BINDS the subject instead
  of comparing against an outer variable of that name
- fractional duration literals: 1.5s, 250.5ms

Standard library:
- fs.lock(path, timeout=) / fs.try_lock(path) / fs.with_lock(path, fn) —
  advisory cross-process file locks (flock), handles with release()
- co.cron(expr, fn) — classic five-field cron schedules (steps, ranges,
  lists, names, @daily-style aliases, dom/dow OR-rule) with a handle
  (stop(), next()); co.cron_next(expr, after=) computes the next fire

Toolchain:
- ox fmt — a conservative token-aware formatter (2-space indent, normalised
  spacing, blank-line collapsing) that preserves every token and comment by
  construction; --check for CI. The whole test/example corpus is fmt-clean
- ox build --binary — freeze a program into a standalone executable with
  PyInstaller (no python needed on the target); graceful error when
  PyInstaller is missing

Compiler correctness (found while validating the above):
- closure writes now compile correctly: assignments to enclosing-function
  variables emit nonlocal, module-level variables become real python
  globals so top-level fns can see and update them
- nested named fn declarations (fn inside fn) transpile to local defs
- compiled apps calling exit() exit cleanly instead of crashing with a
  traceback

Tests: 145 (was 103) — new suites: lang_patterns (16), lang_closures (6),
std_lock (6), std_cron (14). Compile/interpret parity is verified
byte-for-byte for patterns and closures.
## 0.2.0 — practical automation additions

Standard library:
- fs archives: `zip` / `unzip` / `tar_gz` / `untar_gz` with `base=` control
  and zip-slip / tar-slip protection (path-traversal entries are rejected)
- `os.start(cmd, cwd=, env=, detach=)` — background processes with a handle:
  `pid`, `cmd`, `running`, `wait(timeout=)` -> {ok, code, out, err, cmd,
  timed_out}, `kill()` (whole process group: TERM then KILL), `out()`/`err()`
  captured continuously. Non-detached procs are terminated at script exit
- `net.wait_port(host, port, timeout=, interval=)` — readiness probe; the
  natural companion to os.start when booting services

Stability:
- os.start procs run in their own session, so kills reach the whole tree
  and terminal Ctrl+C does not leave orphans behind
- process wait polls returncode — works around asyncio's proc.wait() stall
  after signals (observed on Python 3.12)
- subprocess transports are closed on reap: no "Event loop is closed"
  warnings at exit
- `ox test` terminates background procs per file, so no process leaks out
  of a test run

Tests: 103 (was 87) — new `std_archive` (8) and `std_proc` (8) suites.
New example: `examples/devserver.ox` (start -> probe -> verify -> stop ->
archive roundtrip).
## 0.1.0 — first public cut

Language:
- dynamic types, closures, varargs/kwargs, implicit block returns
- string interpolation (nested, recursive), raw & triple-quoted strings
- duration literals (150ms, 2s, 1m, 1h, 1d), inclusive/exclusive ranges
- pipes (`|>`), null coalescing (`??`), deep equality
- `let`/`var` with reassignment checking
- `match`, value-carrying `if`/`try` blocks
- async everywhere: `spawn`, `await` (tasks and lists), event bus
- errors as values (`error(...)`, `throw`, `catch e`)
- modules with `export`, private `_names`, cycles tolerated
- `verify` statement, `test` blocks with timeouts

Standard library (18 modules):
- fs (50+ functions incl. watch), os (sh/env/device), env, log, time, math,
  crypto, data (JSON/CSV/YAML/TOML + schema validate), json alias
- net (HTTP client, websocket client, tcp_ping, downloads), http alias
- server (HTTP/HTTPS/WebSocket, routing, :params, static files)
- wf (workflow engine: steps, retry/backoff, rollback, dry-run, only=,
  resume, persisted history), co (sleep/all/any/timeout/every/after),
  events, verify, py bridge, c bridge (ctypes)

Toolchain:
- ox run (interpret; --check; script args after --)
- ox test (discovery, timeouts, --json reports)
- ox check (static analysis: undefined vars, let rebinding, dead code, ...)
- ox build (analyze → transpile → self-contained zipapp; --emit py)
- ox repl, ox init, pretty errors with ox-level tracebacks
