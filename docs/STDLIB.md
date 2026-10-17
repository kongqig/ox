# ox standard library

18 modules, all importable with `import <name>`. Builtins available without
any import: `print len type str repr int float bool range error exit input
sh sleep run eval compile`.

Result-dict convention: `sh()`, `net.*` and `py.pip()` return
`{ok: bool, ...}` instead of throwing — branch on `.ok`. File helpers throw
on failure (use `fs.exists` to check first).

---

## fs — files & directories

```ox
import fs
```

| function | description |
|---|---|
| `fs.read(path)` / `fs.read_bytes(path)` / `fs.read_lines(path)` | read text / bytes / line list |
| `fs.write(path, data)` / `fs.append(path, data)` | write / append text; returns length |
| `fs.write_bytes(path, data)` / `fs.write_lines(path, lines)` | bytes / one line per item |
| `fs.exists(path)` / `fs.is_file(path)` / `fs.is_dir(path)` | existence & type |
| `fs.size(path)` / `fs.mtime(path)` / `fs.empty(path)` | size (bytes) / modified epoch / empty? |
| `fs.touch(path)` | create or update mtime |
| `fs.mkdir(path)` / `fs.mkdirs(path)` | create (parents optional) |
| `fs.list(path)` | entries as `[{name, type, size}]` |
| `fs.files(path)` / `fs.dirs(path)` | names only |
| `fs.walk(path, pattern=null)` | all files under path (fnmatch filter optional) |
| `fs.glob(pattern, path=null)` | glob pattern match |
| `fs.copy(src, dst)` / `fs.copytree(src, dst)` | copy file or tree |
| `fs.move(src, dst)` / `fs.rename(src, dst)` | move |
| `fs.remove(path)` / `fs.delete(path)` / `fs.remove_tree(path)` / `fs.rmdir(path)` | delete — `remove_tree` is rm -rf style: a missing directory is a no-op |
| `fs.chmod(path, mode)` | mode is int or octal string like `"755"` |
| `fs.chdir(path)` / `fs.cwd()` / `fs.home()` | working directory |
| `fs.abs(path)` `fs.join(a, b, ...)` `fs.split(path)` `fs.ext(path)` `fs.stem(path)` `fs.norm(path)` `fs.rel(path, base)` | path utilities |
| `fs.temp_dir(prefix="ox-")` / `fs.temp_file(suffix, prefix)` | fresh temp paths |
| `fs.sha256(path)` / `fs.md5(path)` | file hashes |
| `fs.read_json(path)` / `fs.write_json(path, value, pretty=true)` | JSON files |
| `fs.replace(path, old, new)` | in-file text replace; returns count |
| `fs.grep(path, pattern, regex=false)` | matching lines |
| `fs.zip(paths, dest, base=null)` | create a zip from files/dirs (paths = str or list); returns entry count |
| `fs.unzip(archive, dest)` | extract a zip; path-traversal entries (zip-slip) are rejected |
| `fs.tar_gz(paths, dest, base=null)` / `fs.untar_gz(archive, dest)` | same for gzipped tarballs |
| `fs.lock(path, timeout=null)` | take an exclusive advisory lock (flock); waits up to timeout, throws on expiry; returns a handle with `path`, `held`, `release()` |
| `fs.try_lock(path)` | one non-blocking attempt; returns a handle or null |
| `fs.with_lock(path, fn, timeout=null)` | run fn() while holding the lock; always releases |
| `fs.watch(path, fn, interval=0.5)` | async monitor; calls `fn({path, kind})` with kind in `"created" "modified" "deleted"`; returns a handle with `stop()` |

```ox
let w = fs.watch("./src", fn (evt) {
  log.info(f"{evt.kind}: {evt.path}")
})
# ... later
w.stop()
```

Archive entries keep top-level names (`fs.zip("dist", "d.zip")` stores
`dist/...`); pass `base=` to make entry names relative to a directory
instead. Remember: single-quoted strings are raw, so CSS-like text with
braces belongs in `'...'`.

```ox
fs.zip(["notes.md", "logs/"], "bundle.zip")     # -> 3
let n = fs.unzip("bundle.zip", "out/")            # -> 3
fs.tar_gz("dist", "release.tgz", base="dist")    # entries relative to dist/
```

### file locks

Advisory locks over a lock file (flock on POSIX). They exclude other
processes and other lock attempts in this process; the lock file itself
persists (deleting it would introduce races).

```ox
let lk = fs.try_lock("deploy.lock")
if lk == null { print("another deploy is running"); exit(1) }
# ... exclusive work ...
lk.release()

fs.with_lock("nightly.lock", fn () { run_backup() }, timeout=30s)
```

## os — system, commands, devices

```ox
import os
```

| function | description |
|---|---|
| `os.sh(cmd, cwd=null, env={}, timeout=null, input=null)` | run a shell command; returns `{ok, code, out, err, cmd}` |
| `os.sh_ok(cmd, ...)` | just the success bool |
| `os.sh_lines(cmd, ...)` | stdout as a line list |
| `os.start(cmd, cwd=null, env={}, detach=false)` | start a background command; returns a proc handle (below) |
| `os.args()` | arguments after `--` on the command line |
| `os.cwd()` / `os.chdir(path)` / `os.home()` | directories |
| `os.hostname()` / `os.user()` / `os.pid()` | identity |
| `os.platform()` | `{system, release, version, machine, python, ox}` |
| `os.device()` | `{hostname, platform, cpu, mem, disk, ifaces, local_ip}` |
| `os.cpu()` / `os.mem()` / `os.disk(path=".")` | `{count, load}` / `{total, available, used}` / `{total, free, used}` (best effort per platform) |
| `os.net_ifaces()` / `os.local_ip()` | interface names / outbound IP |
| `os.which(cmd)` | locate an executable, or null |

The global `sh(...)` is the same function.

```ox
let r = sh("ls -la | wc -l")
if r.ok { print(f"{r.out.trim()} lines") }
```

### background processes

`os.start` runs a command in its own session and returns a handle with
`pid`, `cmd`, `running` fields and `wait(timeout=null)`, `kill()`,
`out()`, `err()` methods. Output is captured continuously. `kill()` takes
down the whole process group (TERM, then KILL). Unless `detach=true`, the
process is terminated automatically when the script exits.

**POSIX only** — `os.start` relies on process groups (`start_new_session`
/ `killpg`); on Windows it raises a clear error instead of misbehaving
(see platform support in the README).

```ox
let p = os.start("python3 -m http.server 8000")
if not (await net.wait_port("127.0.0.1", 8000, timeout=10s)) {
  print(p.err())
  await p.kill()
  throw error("server never came up")
}
let r = await p.wait(200ms)   # {ok, code, out, err, cmd, timed_out}
await p.kill()                # clean shutdown
```

## env — environment variables

`env.get(name, default=null)` `env.set(name, value)` `env.has(name)`
`env.del(name)` `env.all()`

## log — leveled logging

`log.debug/info/ok/error(msg)` (also `log.success`, `log.warn`)
`log.level("debug")` — minimum level
`log.quiet(true)` — silence everything
`log.file("app.log", append=true)` — tee to a file
`log.table(rows, cols=null)` — aligned table from list-of-dicts
`log.json(obj, pretty=true)` — pretty-print JSON
`log.line(ch="-", n=60)` — separator

## time — clocks

`time.now()` epoch seconds · `time.epoch()` int seconds ·
`time.now_str(fmt=null)` · `time.format(ts, fmt)` · `time.parse(str, fmt)`
(parse without a format tries common layouts) · `time.iso(ts=null)` ·
`time.utc(ts=null)` · `time.parts(ts=null)` →
`{year, month, day, hour, minute, second, weekday, date, time}`

## math — numbers & randomness

`math.pi e abs floor ceil round sqrt pow exp log log2 log10 sin cos tan atan
atan2 min max sum gcd clamp even odd` and `math.rand(n=null)` (int in
`[0, n)` or float in `[0,1)`), `math.randf()`, `math.choice(list)`,
`math.shuffle(list)` (returns a new list).

## crypto — hashes & ids

`crypto.md5/sha1/sha256/sha512(data)` `crypto.hash(algo, data)`
`crypto.hash_file(path, algo)` `crypto.hmac_sha256(key, msg)`
`crypto.uuid()` `crypto.b64_encode/decode(s)` `crypto.url_encode/decode(s)`
`crypto.random_id(n=8)`

## data — structured data

| function | description |
|---|---|
| `data.json_parse(s)` / `data.json_dump(v, pretty=false)` | JSON |
| `data.read_json(path)` / `data.write_json(path, v, pretty=true)` | JSON files |
| `data.csv_parse(s, delim=",", header=true)` | rows as dicts (or lists with `header=false`) |
| `data.csv_dump(rows, delim, header)` / `data.read_csv` / `data.write_csv` | CSV |
| `data.yaml_parse(s)` / `data.yaml_dump(v)` | YAML (needs PyYAML on the host) |
| `data.toml_parse(s)` | TOML (python 3.11+) |
| `data.merge(a, b, deep=false)` | dict merge |
| `data.validate(value, schema)` | schema validation → `{ok, errors}` |

The `json` module is a convenience alias: `json.parse/dump/read/write`.

### validate schemas

```ox
let schema = {
  name:  "str",                  # str int float num bool null any list dict
  email: "email?",               # ? = optional;  "int|str" = union
  tags:  ["str"],                # [subtype] = list of
  addr:  {city: "str", zip: "str?"},
  age:   fn (v) { v >= 0 and v <= 150 },   # predicate
  "_strict": true                # forbid extra keys
}
let r = data.validate(user, schema)
if not r.ok { log.error(f"{r.errors}") }
```

## net — HTTP & websocket client

```ox
let r = net.get("https://httpbin.org/get", query={q: "ox"},
                headers={"X-Api-Key": key}, timeout=10s)
r.ok          # 2xx?
r.status      # 201
r.headers     # lower-cased dict
r.body        # text
r.json        # parsed body (when JSON), else null
```

`net.post(url, data=null, json=null, form=null, headers={}, timeout=30s)`
— `json=` sends JSON, `form=` urlencodes, `data=` sends raw text.
Also `net.put/patch/delete/head` with the same shape.

| other | description |
|---|---|
| `net.download(url, to, timeout=60s)` | `{ok, path, size, status}` |
| `net.tcp_ping(host, port=80, timeout=2s)` | `{ok, ms}` |
| `net.wait_port(host, port, timeout=10s, interval=100ms)` | true once the port accepts connections, false on timeout — pairs with `os.start` |
| `net.ws(url, headers={}, timeout=10s, verify=true)` | websocket client — `verify=false` accepts self-signed certs (wss only) |
| `net.parse_url(url)` | `{scheme, host, port, path, query, fragment, user, password}` |
| `net.url_encode(s)` / `net.url_decode(s)` | percent encoding |

The `http` module is an alias for the request functions.

### websocket client

```ox
let c = net.ws("wss://example.com/socket")
let c2 = net.ws("wss://127.0.0.1:8443/echo", verify=false)  # self-signed
await c.send("hello")            # also c.send_json(obj)
let msg = c.recv(timeout=5s)     # next message, or null on timeout
c.on("message", fn (m) { ... })  # push mode (also "close")
c.on("close", fn (_) { ... })
await c.close()
```

## server — see the language reference

The `serve` statement is documented in
[LANGUAGE.md §6](LANGUAGE.md#6-servers); the `server` module itself only
carries a note — everything is driven by `serve`.

### response security (0.4)

- `res.file(path, download=null, root=null)` — serve a file from disk.
  Pass `root=` whenever `path` is derived from user input (req.params /
  req.query): anything resolving outside the root is rejected with 403.
  Without `root`, arbitrary paths are allowed for script-chosen files.
- All response headers are sanitized: CR/LF in names or values are
  stripped, so user-controlled headers cannot inject extra response
  headers.
- Oversized bodies are rejected with 413 after a bounded drain, so
  well-behaved clients still receive the status line.

## wf — workflow engine

`wf.run(name, ...)` (same options as the global `run`) · `wf.list()` ·
`wf.steps(name)` · `wf.status(name)` · `wf.history(name, n=5)` ·
`wf.state_dir(path=null)` (get/set where run history lives).

### state persistence & recovery (0.4.1)

- every run is written to `<state_dir>/<name>.json` as `"running"` before
  its first step executes and finalized as `"ok"` / `"failed"` when it
  ends — a process that dies mid-run leaves a visible `"running"` record
  that `run(name, resume=true)` treats as crashed and recovers from
- only one live run per workflow: a second concurrent run (another
  process, or another task in this one) fails with `already running`
  instead of clobbering state
- corrupt state files (truncated, garbage, wrong shape) are backed up to
  `<name>.json.corrupt` (numbered on repeat) with a warning, malformed
  run records are dropped while valid ones are salvaged, and the
  workflow starts from fresh state — never a traceback
- a note on rollbacks: they are compensating — a rollback attached to
  step X also fires when a *later* step fails, so scope rollbacks to the
  step that owns the partial work if you plan to combine them with
  `resume=true`

## co — concurrency

`co.sleep(d)` · `co.all([tasks])` · `co.any([tasks])` ·
`co.timeout(d, fn)` (throws a timeout error) ·
`co.every(interval, fn, delay=0)` → handle with `stop()` ·
`co.after(d, fn)` → one-shot handle ·
`co.cron(expr, fn)` → handle with `stop()` and `next()` ·
`co.cron_next(expr, after=null)` → next epoch second matching the cron ·
`co.pending()` count.

### cron schedules

Classic five-field cron (minute hour day-of-month month weekday), local
time, with the usual syntax (`*`, `*/n`, `a-b`, `a-b/n`, lists, `mon-fri`,
`jan-dec`) and `@hourly @daily @midnight @weekly @monthly @yearly`
aliases. When both day-of-month and weekday are restricted, either may
match (the classic rule). Failing tasks are logged and keep the schedule.

```ox
let nightly = co.cron("30 3 * * *", fn () { run_backup() })
let weekday = co.cron("0 9 * * mon-fri", fn () { standup() })
print(f"next fire: {time.iso(nightly.next())}")
nightly.stop()
```

## events — event bus control

`events.list()` → `{name: handler_count}` · `events.off("name")` (or
`events.off()` for everything) · `events.emit(name, payload)`.

## verify — test helpers

`verify.eq(a, b, msg=null)` · `verify.ne` · `verify.true(x)` ·
`verify.false(x)` · `verify.has(coll, v)` · `verify.approx(a, b, eps=1e-9)` ·
`verify.throws(fn)` → the error value (fails the test if nothing throws) ·
`verify.skip(msg=null)` → mark the current test as skipped (tooling
unavailable, environment-specific); `ox test` reports skips separately
and still exits 0.

## py — python bridge

```ox
import py
let math = py.import("math")          # modules and classes
                                      # ("datetime.datetime" works)
math.sqrt(2.0)                        # call straight through
py.eval("2 + 3")                      # evaluate python source
py.exec("X = 1")                      # run python source (shared namespace)
py.exec_file("script.py")
py.pip("install requests")            # manage packages (sh-style result)
py.version()
```

Values convert transparently (numbers, strings, lists, dicts). ox functions
do not cross the bridge — pass data, not callbacks.

## c — C FFI

```ox
import c
let libm = c.lib("m")                     # find & load a shared library
let pow_fn = libm.fn("pow",               # symbol
                     [c.double, c.double],# argument types
                     c.double)            # return type
pow_fn(2.0, 10.0)                         # -> 1024.0

let libc = c.lib("c")
libc.fn("strlen", [c.char_p], c.size_t)("hello ox")   # -> 8
```

Types: `c.int c.uint c.long c.ulong c.float c.double c.bool c.char_p
c.void_p c.size_t c.int8 c.int16 c.int32 c.int64 c.uint8 c.uint16 c.uint32
c.uint64`. Strings pass as UTF-8 bytes; `char_p` results decode to strings.
Use `c.lib("/full/path.so")` for absolute paths.
