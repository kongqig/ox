# data_pipeline.ox — CSV ETL: clean -> enrich -> aggregate -> report
#
# The bread-and-butter data task: a vendor sends a messy CSV, finance
# wants a summary by region yesterday. Generates a realistic export
# (including junk rows vendors always send), cleans it, enriches with a
# computed column, aggregates, and writes JSON + markdown outputs.
#
#   python -m ox run examples/data_pipeline.ox

import data
import fs
import json
import time

let work = fs.temp_dir("ox-etl")
let src = fs.join(work, "sales.csv")

# ---- 1. synthesize the vendor export ------------------------------------------

fn synth_export() {
  let regions = ["east", "east", "west", "north", "south", "east", "west",
    "north", "south", "east"]
  let products = ["widget", "gadget", "gizmo", "widget", "doohickey",
    "gadget", "widget", "gizmo", "gadget", "doohickey"]
  let lines = ["date,region,product,qty,unit_price"]
  var total = 0.0
  for i in range(0, 300) {
    let region = regions[i % regions.len()]
    let product = products[(i * 3) % products.len()]
    let qty = 1 + (i * 7) % 12
    let price = (4.5 + ((i * 13) % 220) / 10.0).round(2)
    let day = time.format(time.now() - (i % 7) * 86400, "%Y-%m-%d")
    lines.push(day + "," + region + "," + product + "," + str(qty) + "," +
      str(price))
    total = total + qty * price
  }
  # the junk every real export contains (the blank line is dropped by
  # the csv reader itself; the other three survive into the pipeline)
  lines.push("2026-10-13,,widget,3,9.99") # missing region
  lines.push("2026-10-13,east,gadget,,19.99") # missing qty
  lines.push("2026-10-13,west,gizmo,2,-5") # negative price
  lines.push(",,,") # empty row
  fs.write_lines(src, lines)
  return total
}

let expected_total = synth_export()
print("export: 304 lines (300 good, 3 junk + 1 blank) -> " + src)

# ---- 2. clean + enrich -----------------------------------------------------------

let raw = data.read_csv(src)
var clean = []
var rejected = []

for row in raw {
  var ok = true
  var qty = 0
  var price = 0.0
  try {
    qty = int(row.qty)
    price = float(row.unit_price)
  } catch e {
    ok = false
  }
  if ok and row.region != "" and row.product != "" and qty > 0 and price > 0 {
    clean.push({date: row.date, region: row.region, product: row.product,
        qty: qty, price: price,
        revenue: (qty * price).round(2)})
  } else {
    rejected.push(row)
  }
}

print("cleaned: " + str(clean.len()) + " kept, " + str(rejected.len()) +
  " rejected")

# ---- 3. aggregate -----------------------------------------------------------------

var by_region = { } # region -> {orders, qty, revenue}
var by_product = { } # product -> revenue
var by_date = { } # date -> revenue

for r in clean {
  let acc = by_region.get(r.region, null)
  if acc == null {
    by_region.set(r.region, {orders: 1, qty: r.qty, revenue: r.revenue})
  } else {
    acc.orders = acc.orders + 1
    acc.qty = acc.qty + r.qty
    acc.revenue = (acc.revenue + r.revenue).round(2)
  }
  by_product.set(r.product, (by_product.get(r.product, 0) + r.revenue).round(2))
  by_date.set(r.date, (by_date.get(r.date, 0) + r.revenue).round(2))
}

fn money(n) {
  let v = n * 1.0
  if v >= 1000 {
    return str((v / 1000).round(1)) + "k"
  }
  return str(v.round(1))
}

# ---- 4. report ----------------------------------------------------------------------

let region_rows = by_region.items().sort_by(fn (p) { p[1].revenue },
  reverse=true)
let product_rows = by_product.items().sort_by(fn (p) { p[1] }, reverse=true)
let date_rows = by_date.items().sort()
let grand = by_region.values().map(fn (a) { a.revenue }).sum()

var md = []
md.push("# Sales summary — vendor export")
md.push("")
md.push("- orders: **" + str(clean.len()) + "** (rejected " +
  str(rejected.len()) + " malformed rows)")
md.push("- revenue: **" + money(grand) + "**")
md.push("")
md.push("## By region")
md.push("")
md.push("| region | orders | units | revenue | avg order |")
md.push("| ------ | -----: | ----: | ------: | --------: |")
for p in region_rows {
  let a = p[1]
  md.push("| " + p[0] + " | " + str(a.orders) + " | " + str(a.qty) + " | " +
    money(a.revenue) + " | " + money(a.revenue / a.orders) + " |")
}
md.push("")
md.push("## Top products")
md.push("")
md.push("| product | revenue | share |")
md.push("| ------- | ------: | ----: |")
for p in product_rows.slice(0, 5) {
  md.push("| " + p[0] + " | " + money(p[1]) + " | " +
    str((100.0 * p[1] / grand).round(1)) + "% |")
}
md.push("")
md.push("## Revenue by day")
md.push("")
md.push("| date | revenue |")
md.push("| ---- | ------: |")
for p in date_rows {
  md.push("| " + p[0] + " | " + money(p[1]) + " |")
}
md.push("")

fs.write(fs.join(work, "summary.md"), md.join("
"))
json.write(fs.join(work, "summary.json"), {
    orders: clean.len(), rejected: rejected.len(), revenue: grand,
    by_region: by_region.sort_keys(),
    by_product: by_product.sort_keys(),
    by_date: by_date.sort_keys(),
  })

# ---- 5. console digest ---------------------------------------------------------------

print("")
print("== sales summary ==============================================")
print("orders        " + str(clean.len()) + " (" + str(rejected.len()) +
  " rejected)")
print("revenue       " + money(grand))
print("")
print("region     orders   revenue")
for p in region_rows {
  print("  " + p[0].pad_right(10) + str(p[1].orders).pad_left(4) + "   " +
    money(p[1].revenue).pad_left(8))
}
print("")
print("top products:")
for p in product_rows.slice(0, 3) {
  print("  " + p[0].pad_right(12) + money(p[1]).pad_left(8) + "  " +
    str((100.0 * p[1] / grand).round(1)) + "%")
}
print("")
print("outputs: " + fs.join(work, "summary.md") +
  " , summary.json")

# sanity: the pipeline must not lose money — clean revenue must equal
# the sum we tracked while generating (junk rows contribute nothing)
verify (grand - expected_total).abs() < 0.05, "revenue mismatch: " +
str(grand) + " vs generated " + str(expected_total)
verify clean.len() == 300, "expected 300 clean rows, got " + str(clean.len())
verify rejected.len() == 3, "expected 3 rejected rows, got " +
str(rejected.len())
