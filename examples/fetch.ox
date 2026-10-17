# fetch.ox — concurrency: fetch several URLs in parallel with spawn/await
# run: ox run examples/fetch.ox

import log
import math
import net
import time

fn fetch(name, url) {
  let t0 = time.now()
  let r = net.get(url, timeout=5s)
  {name: name, ok: r.ok, status: r.status,
    ms: math.round((time.now() - t0) * 1000)}
}

# ---- sequential (for comparison) ----
let t0 = time.now()
let a = fetch("example.com", "http://example.com")
let b = fetch("example.org", "http://example.org")
let seq_ms = math.round((time.now() - t0) * 1000)
log.table([a, b], cols=["name", "ok", "status", "ms"])
log.info(f"sequential: {seq_ms}ms total")

# ---- concurrent: spawn each fetch, await them together ----
let t1 = time.now()
let results = await [
  spawn { fetch("example.com", "http://example.com") },
  spawn { fetch("example.org", "http://example.org") },
  spawn { fetch("example.net", "http://example.net") },
]
let par_ms = math.round((time.now() - t1) * 1000)
log.table(results, cols=["name", "ok", "status", "ms"])
log.info(f"concurrent: {par_ms}ms total (3 requests)")

# ---- a tiny health-check workflow driven by the same primitive ----
workflow "check-sites" {
  desc "probe a few hosts in parallel"
  step "probe" {
    let rs = await [
      spawn { net.tcp_ping("example.com", 80, timeout=3s) },
      spawn { net.tcp_ping("example.org", 80, timeout=3s) },
    ]
    verify rs.filter(fn (r) { r.ok }).len() >= 1, "at least one host up"
    f"{rs.filter(fn (r) { r.ok }).len()}/2 hosts reachable"
  }
}
let r = run("check-sites")
verify r.ok
log.ok(f"done — {r.steps[0].error ?? 'sites probed'}")
