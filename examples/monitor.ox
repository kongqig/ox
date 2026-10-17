# monitor.ox — endpoint uptime/latency monitor with percentiles and alerts
#
# The "is my service healthy" loop every ops person writes on day two.
# Spins up a deliberately flaky local API, polls it, then reports uptime,
# p50/p95/max latency and an incident list — with a verify gate at the end
# so the script doubles as an alerting job (non-zero exit on breach).
#
#   python -m ox run examples/monitor.ox

import co
import net
import time

var hits = 0

# a small API that misbehaves: every 7th request is a 500, every 13th
# is slow (300ms) — enough structure to make the report interesting
let api = serve 0, daemon = true {
  get "/api/stats" {
    hits = hits + 1
    if hits % 7 == 0 {
      res.status(500).json({error: "circuit overload", hit: hits})
    } else {
      if hits % 13 == 0 {
        co.sleep(300ms)
      }
      res.json({ok: true, hit: hits, load: (hits % 90) / 100.0})
    }
  }
}

let base = "http://127.0.0.1:" + str(api.port)
print("monitoring " + base + " every 100ms for 3s...")

var samples = [] # [{ms, status}]
var incidents = []

fn probe() {
  let t0 = time.now()
  let r = net.get(base + "/api/stats", timeout=2)
  let ms = ((time.now() - t0) * 1000).round(1)
  samples.push({ms: ms, status: r.status})
  if r.status != 200 {
    incidents.push({hit: hits, status: r.status, at: time.iso()})
  }
}

let poll = co.every(100ms, fn () { probe() })
co.sleep(3s)
poll.stop()
co.sleep(150ms) # let any in-flight probe land
api.stop()

# ---- stats --------------------------------------------------------------------

let latencies = samples.map(fn (s) { s.ms }).sort()
let ok_count = samples.filter(fn (s) { s.status == 200 }).len()
let uptime = 100.0 * ok_count / samples.len()

fn pct(sorted, p) {
  return sorted[int((sorted.len() - 1) * p / 100.0)]
}

let p50 = pct(latencies, 50)
let p95 = pct(latencies, 95)

print("")
print("== monitor report =============================================")
print("probes        " + str(samples.len()))
print("ok / errors   " + str(ok_count) + " / " +
  str(samples.len() - ok_count))
print("uptime        " + str(uptime.round(2)) + "%")
print("latency p50   " + str(p50) + " ms")
print("latency p95   " + str(p95) + " ms")
print("latency max   " + str(latencies.last()) + " ms")
print("incidents     " + str(incidents.len()))
for i in incidents {
  print("  - hit " + str(i.hit).pad_left(3) + " -> HTTP " + str(i.status) +
    " at " + i.at)
}

# latency histogram (4ms buckets up to p95+)
let bucket = 4
let max_bucket = (int(p95 / bucket) + 2) * bucket
var histo = { }
for ms in latencies {
  if ms <= max_bucket {
    let b = int(ms / bucket) * bucket
    histo.set(b, histo.get(b, 0) + 1)
  }
}
print("")
print("latency distribution (4ms buckets):")
let peak = histo.values().max()
for b in histo.keys().sort() {
  let n = histo.get(b)
  var bar = ""
  for _ in range(0, int(26 * n / peak)) { bar = bar + "#" }
  print("  " + (str(b) + "-" + str(b + bucket) + "ms").pad_right(12) +
    bar + " " + str(n))
}

# ---- alerting gate -------------------------------------------------------------

verify samples.len() >= 20, "expected at least 20 probes, got " +
str(samples.len())
verify uptime >= 85.0, "uptime " + str(uptime.round(2)) +
"% is below the 85% SLO"
verify p95 < 400, "p95 latency " + str(p95) + "ms exceeds the 400ms budget"

print("")
print("SLO check passed: uptime >= 85%, p95 < 400ms")
