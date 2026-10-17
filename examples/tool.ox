# tool.ox — a realistic CLI tool: jsonq (query JSON files)
# run: ox run examples/tool.ox -- data.json items name
#      ox run examples/tool.ox -- --help

import fs
import json
import os
import verify

fn usage() {
  print("""
jsonq — query JSON files, the ox way

usage: ox run tool.ox -- <file> <path...>

  <file>      path to a .json file ('-' for stdin)
  <path...>   key path into the document (list indexes allowed)

examples:
  ox run tool.ox -- config.json server port
  ox run tool.ox -- users.json 0 email
""")
}

fn dig(doc, path) {
  var cur = doc
  for part in path {
    var key = part
    try { key = int(part) } catch { key = part } # numeric path elements index lists
    if type(cur) == "dict" and cur.has(key) {
      cur = cur[key]
    } else if type(cur) == "list" and type(key) == "int" and key < cur.len() {
      cur = cur[key]
    } else {
      throw error(f"no such path: {path.join('.')} (stopped at '{part}')",
        code=2)
    }
  }
  cur
}

let args = os.args()
if args.len() == 0 or args[0] == "--help" {
  usage()
  exit(0)
}
if args.len() < 2 {
  usage()
  exit(2)
}

let file = args[0]
let path = args.slice(1)

var text = ""
if file == "-" {
  # read stdin via a shell trick (kept simple for the example)
  text = sh("cat").out
} else {
  verify fs.exists(file), f"no such file: {file}"
  text = fs.read(file)
}

let doc = json.parse(text)
let result = dig(doc, path)

# print scalars plainly, structures as json
if type(result) == "dict" or type(result) == "list" {
  print(json.dump(result, pretty=true))
} else {
  print(result)
}
