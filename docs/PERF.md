# Performance baseline (ox 0.4)

Numbers below are order-of-magnitude expectations on one Linux machine
(CPython 3.12, loopback network, tmpfs-ish /tmp). They exist so you can
sanity-check your own workload, not as guarantees. Reproduce them with
`python scripts/bench_ox.py` from the repo root.

| benchmark | time | note |
|---|---|---|
| startup (empty program) | ~256 ms | process spawn + runtime init |
| fib(26), interpreter | ~3.8 s | tree-walking evaluator, CPU-bound |
| fib(26), compiled zipapp | ~1.1 s | `ox build` output, ~3.4x faster |
| 1k concurrent spawn tasks | ~278 ms | net ~20 ms above startup |
| 10 MB file write+read | ~265 ms | fs layer, dominated by startup |
| 10k-object JSON roundtrip | ~390 ms | json parse + dump |
| 20k f-strings + join + upper | ~392 ms | string layer |
| 20k push/map/filter | ~542 ms | list layer |

## Reading the numbers

**Startup dominates small scripts.** Roughly 250 ms of every run is Python
process creation plus ox runtime init. Below ~100k operations the language
layer is essentially free compared to startup; use one script that does
more, not many scripts that do little.

**The interpreter is a tree-walker.** CPU-bound recursion runs at
"scripting language" speed (fib(26) ≈ 3.8 s). Compiling with `ox build`
translates to native Python coroutines and is ~3.4x faster on the same
program — for hot loops, build first:

```console
$ ox run hot.ox      # interpret (fine for I/O-bound automation)
$ ox build hot.ox    # compile (worth it for CPU-bound work)
```

**I/O and data are Python-speed.** File, JSON, string and list operations
run directly in the stdlib layer (often off the event loop via threads), so
they cost about what the equivalent Python would cost. Concurrency itself
is asyncio tasks: 1k spawned jobs add ~20 ms over an empty program.

**Servers handle automation-scale traffic.** The built-in HTTP server is a
hand-rolled asyncio protocol — right-sized for internal tools, health
checks and dashboards. It is not a replacement for a production WSGI/ASGI
stack under high fan-in; put a real reverse proxy in front if you need one.

## Known limits (deliberate)

- **No NaN/Infinity**: division by zero is always a catchable error.
- **Recursion cap** ~900 frames in the interpreter (more in compiled
  artifacts) — deep recursion fails with a clean error, so rewrite as a
  loop for pathological depths.
- **32 MB request/response body cap** in `serve` (413 beyond).
- **Single-core scheduling**: ox is one asyncio loop; CPU-bound parallelism
  needs `os.start` (subprocesses), not threads.
