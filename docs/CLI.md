# The ox CLI

```
ox <command> [options]
```

Global flags: `--no-color` (force plain output), `--version`.

## ox run

```
ox run <file|dir> [--check] [-- <args passed to the script>]
```

- file: run that `.ox` file
- directory: read `ox.proj.json` if present (uses its `entry`, default
  `main.ox`), else try `main.ox`, `app.ox`, `index.ox`
- no argument: same resolution for the current directory
- `--check`: run the static analyzer before executing (fail fast)
- everything after `--` is available to the script as `os.args()`

Exit codes: `0` ok · `1` runtime error · `2` usage/parse error · `130`
interrupted (Ctrl+C).

```sh
ox run deploy.ox -- --env prod --dry-run
```

```ox
# inside deploy.ox
let args = os.args()          # ["--env", "prod", "--dry-run"]
```

## ox test

```
ox test [file|dir] [--json]
```

Discovers `*.test.ox` files under `tests/` (default) or the given path.
Each file's top level runs first (fixtures); `test "name" { ... }` blocks
run individually with timeouts (`test "slow", timeout=5s { ... }`).

- `--json`: also write `ox-test-report.json`
- exit `1` if anything failed

## ox check

```
ox check <file|dir> [--strict]
```

Static analysis: undefined variables, `let` reassignment, unreachable code,
unused variables, `break/continue` outside loops, unknown modules or
missing import paths, duplicate workflow/route/test names. `--strict`
treats warnings as errors.

## ox build

```
ox build <file|dir> [-o out] [--emit py] [--binary]
```

Three stages:

1. **check** — the full static analysis must pass
2. **transpile** — the program becomes readable, semantically-faithful
   Python (every operator and call routes through the `ox.runtime`
   helpers, so behavior matches the interpreter exactly)
3. **package** — transpiled code + the ox runtime are packed into a
   self-contained zipapp executable (default `build/<name>`)

```sh
ox build backup.ox -o backup      # ./backup runs anywhere with python3.9+
ox build backup.ox --emit py      # inspect the generated python instead
ox build backup.ox --binary       # ./backup.bin runs with NO python at all
```

Notes:

- the zipapp needs python3.9+ on the target machine — nothing else
- `--binary` freezes the same program with PyInstaller into a single
  executable (~10 MB) that needs no python install; it requires
  `python3 -m pip install pyinstaller` on the build machine
- imported **.ox modules** still work: the runtime loads and interprets
  them at startup (mixed compiled/interpreted execution)
- `test` blocks are registered but not auto-run in built apps; keep tests
  interpreted via `ox test`

## ox fmt

```
ox fmt [files|dirs] [--check]
```

Formats `.ox` source in place (no argument formats the current tree,
 skipping hidden dirs, docs and the `ox/` package). `--check` reports
 which files would change and exits `1` if any — for CI.

The formatter is deliberately conservative: it never joins or reorders
anything and never drops a token or comment, so the output re-lexes to the
exact same token stream. What it normalises:

- two-space indentation, recomputed per line from bracket depth
- spacing within lines (operators, commas, dict colons, call parens,
  keyword arguments)
- runs of blank lines collapse to one; trailing whitespace trimmed;
  files end with exactly one newline
- shebangs, comments, raw vs interpolated string quoting, and number
  spelling (`0x1F`, `1_000`, `150ms`, `1.5s`) are preserved verbatim

It is idempotent: `ox fmt` on already-formatted code changes nothing.

## ox repl

An interactive session. Statements persist; expression results are printed.
`Ctrl+D` or `.exit` to leave, `.help` for tips. Multiline input continues
automatically while braces are unbalanced.

## ox init

```
ox init [name] [--force]
```

Scaffolds a project: `main.ox`, `tests/main.test.ox`, `ox.proj.json`,
`README.md`, `.gitignore`.

```json
{
  "name": "my-tool",
  "version": "0.1.0",
  "entry": "main.ox",
  "ox": ">=0.1.0"
}
```

## ox version

Prints the ox version, python version and platform.

## Environment variables

| variable | effect |
|---|---|
| `NO_COLOR` | disable colored output |
| `OX_DEBUG` | servers include error details in 500 responses |
| `OX_STATE_DIR` | where workflow history lives (default `.ox/state`) |

## Shebangs

`ox` scripts work as executables:

```sh
#!/usr/bin/env -S ox run --
```

(shebang lines are comments in ox, so nothing extra is needed in the file)
