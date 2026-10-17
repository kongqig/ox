# interop.ox — reach the Python and C ecosystems directly
# run: ox run examples/interop.ox

import py
import c
import log

# ---- python: import modules, call functions, eval snippets ----
let math = py.import("math")
log.info(f"python math.sqrt(2) = {math.sqrt(2.0)}")

let dt = py.import("datetime.datetime")
log.info(f"python datetime: {dt.now().isoformat()}")

let json_mod = py.import("json")
let payload = json_mod.dumps({ok: true, items: [1, 2, 3]})
log.info(f"python json.dumps: {payload}")

py.exec("def triple(x):
    return 3 * x")
log.info(f"py.exec + py.eval: {py.eval('triple(14)')}")

# install packages on demand (uncomment to try):
# py.pip("install --quiet ascii-stats")
# let art = py.import("art")
# print(art.text2art("ox", font="small"))

# ---- C: load shared libraries and call them via ctypes ----
let libm = c.lib("m")
let pow_fn = libm.fn("pow", [c.double, c.double], c.double)
let sqrt_fn = libm.fn("sqrt", [c.double], c.double)
log.info(f"C pow(2, 16) = {pow_fn(2.0, 16.0)}")
log.info(f"C sqrt(144) = {sqrt_fn(144.0)}")

let libc = c.lib("c")
let strlen = libc.fn("strlen", [c.char_p], c.size_t)
log.info(f"C strlen('hello ox') = {strlen('hello ox')}")

# ---- dynamic parsing & compilation, at runtime ----
let program = eval("40 + 2") # interpret a string now
log.info(f"eval('40 + 2') = {program}")

let py_src = compile('fn scale(x, k=10) { x * k }')
log.info(f"compile() produced {py_src.split_lines().len()} lines of python — the same pipeline ox build uses")

# ---- a workflow step that uses both bridges ----
workflow "interop-check" {
  step "verify" {
    verify pow_fn(3.0, 4.0) == 81.0
    verify math.pi > 3.14 and math.pi < 3.15
    "both bridges agree"
  }
}
let r = run("interop-check")
verify r.ok
log.ok("interop verified")
