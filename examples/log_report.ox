# log_report.ox — nginx access-log analyzer (no regex, pure string ops)
#
# A realistic "Friday afternoon" task: here is an access.log, tell me who
# is hammering us, what's failing, and how traffic distributes over hours.
# Generates a sample log first so the script is self-contained; point
# log_path at a real file to analyze production logs.
#
#   python -m ox run examples/log_report.ox

import fs
import json

let workspace = fs.temp_dir("ox-log-report")
let log_path = fs.join(workspace, "access.log")

# ---- 1. synthesize a realistic access log -----------------------------------
# (skip this section when analyzing a real log)

fn gen_log() {
  let ips = ["203.0.113.7", "198.51.100.24", "203.0.113.7", "192.0.2.55",
    "198.51.100.24", "203.0.113.99", "192.0.2.13", "203.0.113.7",
    "198.51.100.77", "192.0.2.55"]
  let paths = ["/", "/api/items", "/api/items", "/login", "/static/app.js",
    "/api/orders", "/health", "/api/items", "/api/cart",
    "/static/app.js"]
  let codes = [200, 200, 200, 401, 200, 500, 200, 304, 200, 404]
  let lines = []
  var i = 0
  for h in range(14, 18) {
    for n in range(0, 750) {
      let ip = ips[i % ips.len()]
      let path = paths[(i * 3) % paths.len()]
      let code = codes[(i * 7) % codes.len()]
      let bytes = 512 + (i * 37) % 9000
      let minute = (n * 4) % 60
      lines.push(ip + " - - [14/Oct/2026:" + str(h) + ":" + str(minute) +
        ":05 +0800] \"GET " + path + " HTTP/1.1\" " + str(code) +
        " " + str(bytes))
      i = i + 1
    }
  }
  fs.write_lines(log_path, lines)
  return lines.len()
}

let n_lines = gen_log()
print("log: " + str(n_lines) + " requests -> " + log_path)

# ---- 2. parse ----------------------------------------------------------------
# log format: ip - - [14/Oct/2026:14:52:05 +0800] "GET /path HTTP/1.1" 200 5491

fn parse_line(line) {
  let ip = line.split(" ")[0]
  let ts = line.split("[")[1].split("]")[0] # 14/Oct/2026:14:52:05 +0800
  let hour = int(ts.split(":")[1])
  let req = line.split("\" ")[0].split(" \"")[1] # GET /path HTTP/1.1
  let tail = line.split("\" ")[1].split(" ") # [code, bytes]
  let rp = req.split(" ")
  return {ip: ip, hour: hour, method: rp[0], path: rp[1],
    status: int(tail[0]), bytes: int(tail[1])}
}

var by_ip = { }
var by_path = { }
var by_class = { }
var by_hour = { }
var total_bytes = 0
var total = 0

for line in fs.read_lines(log_path) {
  if line.empty() { continue }
  let e = parse_line(line)
  total = total + 1
  total_bytes = total_bytes + e.bytes
  by_ip.set(e.ip, by_ip.get(e.ip, 0) + 1)
  by_path.set(e.path, by_path.get(e.path, 0) + 1)
  by_class.set(str(int(e.status / 100)) + "xx",
    by_class.get(str(int(e.status / 100)) + "xx", 0) + 1)
  by_hour.set(e.hour, by_hour.get(e.hour, 0) + 1)
}

# ---- 3. rank -----------------------------------------------------------------

fn top_n(d, n) {
  return d.items().sort_by(fn (p) { p[1] }, reverse=true).slice(0, n)
}

fn human_bytes(n) {
  let units = ["B", "KB", "MB", "GB"]
  var v = n * 1.0
  var u = 0
  while v >= 1024 and u < units.len() - 1 {
    v = v / 1024
    u = u + 1
  }
  return str(v.round(1)) + " " + units[u]
}

fn bar(count, max_count, width) {
  let filled = int(width * count / max_count)
  var s = ""
  for _ in range(0, width) { s = s + "-" }
  return "#" * filled + s.slice(filled, width)
}

let top_ips = top_n(by_ip, 10)
let top_paths = top_n(by_path, 10)
let peak = by_hour.values().max()

# ---- 4. report ---------------------------------------------------------------

var md = []
md.push("# Access log report — 14 Oct 2026")
md.push("")
md.push("- requests: **" + str(total) + "**")
md.push("- transferred: **" + human_bytes(total_bytes) + "**")
md.push("- clients: **" + str(by_ip.len()) + "**")
md.push("")
md.push("## Status classes")
md.push("")
md.push("| class | count | share |")
md.push("| ----- | ----: | ----: |")
for cls in by_class.keys().sort() {
  let c = by_class.get(cls)
  md.push("| " + cls + " | " + str(c) + " | " +
    str((100.0 * c / total).round(1)) + "% |")
}
md.push("")
md.push("## Top clients")
md.push("")
md.push("| ip | requests |")
md.push("| -- | -------: |")
for p in top_ips {
  md.push("| " + p[0] + " | " + str(p[1]) + " |")
}
md.push("")
md.push("## Top paths")
md.push("")
md.push("| path | requests |")
md.push("| ---- | -------: |")
for p in top_paths {
  md.push("| " + p[0] + " | " + str(p[1]) + " |")
}
md.push("")
md.push("## Traffic by hour")
md.push("")
for h in by_hour.keys().sort() {
  let c = by_hour.get(h)
  md.push(f"{h}:00  {bar(c, peak, 40)}  {c}")
}
md.push("")

fs.write(fs.join(workspace, "report.md"), md.join("
"))
json.write(fs.join(workspace, "report.json"), {
    total: total, bytes: total_bytes, clients: by_ip.len(),
    classes: by_class, top_ips: by_ip.sort_keys(),
    hours: by_hour.sort_keys(),
  })

# ---- 5. console summary --------------------------------------------------------

print("")
print("== summary ======================================================")
print("requests      " + str(total))
print("transferred   " + human_bytes(total_bytes))
print("clients       " + str(by_ip.len()))
for cls in by_class.keys().sort() {
  let c = by_class.get(cls)
  print("  " + cls + "        " + str(c).pad_left(6) +
    "  " + bar(c, total, 24))
}
print("noisiest client  " + top_ips[0][0] + " (" + str(top_ips[0][1]) + " hits)")
print("busiest path     " + top_paths[0][0] + " (" + str(top_paths[0][1]) + " hits)")
print("")
for h in by_hour.keys().sort() {
  print("  " + str(h).pad_left(2) + ":00  " +
    bar(by_hour.get(h), peak, 36) + "  " + str(by_hour.get(h)))
}
print("")
print("report: " + fs.join(workspace, "report.md"))

verify total > 0, "parsed nothing"
verify by_ip.len() > 1, "expected multiple clients"
verify by_class.has("2xx"), "expected successful responses"
