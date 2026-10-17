"""ox init — scaffold a new project."""
import json
import os

from . import __version__, tty

MAIN_OX = """# {name} — an ox project
# docs: docs/LANGUAGE.md · stdlib: docs/STDLIB.md

import fs
import log

fn main() {
  log.info("hello from {name}!")

  # edit me — try: net, workflows, serve, py, c...
  let files = fs.list(".")
  log.table(files)
  return 0
}

main()
"""

TEST_OX = """import fs
import verify

test "scaffold sanity" {
  verify.eq(1 + 1, 2)
}

test "fs is importable" {
  verify.true(fs.exists("."))
}
"""

README = """# {name}

An [ox](https://github.com/ox-lang/ox) automation project.

## usage

    ox run .            # run main.ox
    ox test             # run tests/*.test.ox
    ox check .          # static analysis
    ox build .          # compile a self-contained executable
"""


GITIGNORE = """.ox/
build/
__pycache__/
*.pyc
ox-test-report.json
"""


def init_project(name, force=False):
    root = name or "."
    if name:
        os.makedirs(root, exist_ok=True)
    label = os.path.basename(os.path.abspath(root))
    files = {
        "main.ox": MAIN_OX.replace("{name}", label),
        "tests/main.test.ox": TEST_OX,
        "ox.proj.json": json.dumps(
            {"name": label, "version": "0.1.0", "entry": "main.ox",
             "ox": ">=%s" % __version__}, indent=2) + "\n",
        "README.md": README.replace("{name}", label),
        ".gitignore": GITIGNORE,
    }
    created, skipped = [], []
    for rel, content in files.items():
        path = os.path.join(root, rel)
        if os.path.exists(path) and not force:
            skipped.append(rel)
            continue
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        created.append(rel)
    print(tty.green("✓ project '%s'" % label))
    for rel in created:
        print("  " + tty.green("+") + " " + rel)
    for rel in skipped:
        print("  " + tty.yellow("=") + " " + rel + " (kept, use --force to "
              "overwrite)")
    print("")
    print("next: " + tty.cyan("cd %s && ox run ." % root))
    return 0
