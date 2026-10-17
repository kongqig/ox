# files.ox — file & directory operations tour
# run: ox run examples/files.ox

import fs
import log
import time

let work = fs.temp_dir("ox-demo")
log.info(f"working in {work}")

# --- create
fs.mkdirs(f"{work}/src/deep")
fs.write(f"{work}/src/deep/app.txt", "line one
line two
")
fs.write(f"{work}/notes.md", "# notes
")
fs.write_lines(f"{work}/todo.txt", ["buy milk", "ship ox"])

# --- read
print(fs.read(f"{work}/src/deep/app.txt"))
log.table(fs.list(f"{work}/src"), cols=["name", "type", "size"])

# --- query
let all = fs.walk(work)
log.info(f"walk found {all.len()} files")
let txts = fs.glob("*.txt", path=work)
print(f"txt files: {txts.map(fn (p) { fs.stem(p) }).join(', ')}")

# --- modify
fs.append(f"{work}/todo.txt", "profit")
fs.copy(f"{work}/todo.txt", f"{work}/todo.bak")
fs.move(f"{work}/notes.md", f"{work}/src/README.md")
fs.replace(f"{work}/todo.txt", "milk", "oat milk")

# --- verify
verify fs.read(f"{work}/todo.txt").has("oat milk")
verify fs.exists(f"{work}/todo.bak")
verify fs.size(f"{work}/src/deep/app.txt") > 0

# --- hashes & json
print(f"sha256: {fs.sha256(f"{work}/todo.txt").slice(0, 16)}...")
fs.write_json(f"{work}/state.json", {updated: time.now(), files: all.len()})
let state = fs.read_json(f"{work}/state.json")
log.info(f"state saved with {state.files} files at {time.format(state.updated)}")

# --- cleanup with a workflow (see backup.ox for the full pattern)
fs.remove_tree(work)
verify not fs.exists(work)
log.ok("workspace cleaned up")
