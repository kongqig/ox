#!/usr/bin/env python3
"""Find every interpolated double-quoted string in the corpus (using the
CURRENT lexer, before the f-prefix change) so we can plan the migration.

Reports each file + line:col where an f-prefix must be inserted.
"""
import sys
import os
import re

sys.path.insert(0, "/home/z/my-project/ox")
from ox.lexer import Lexer  # noqa: E402

ROOT = "/home/z/my-project/ox"


def scan_source(src, label, base_line=1):
    """Return [(line, col, preview)] of strings needing the f prefix."""
    try:
        toks = Lexer(src, label).tokenize()
    except Exception as e:  # noqa: BLE001
        print(f"!! lex error in {label}: {e}")
        return []
    hits = []
    for t in toks:
        if t.type == "STRING" and isinstance(t.value, list) and t.quote == '"':
            preview = ""
            for p in t.value[:3]:
                preview += p[1] if p[0] == "lit" else "{" + p[1] + "}"
            hits.append((t.line, t.col, preview[:60]))
    return hits


FENCE_RE = re.compile(r"^```ox\r?\n(.*?)^```", re.S | re.M)


def main():
    total = 0
    # 1. .ox files
    for sub in ("tests", "examples"):
        d = os.path.join(ROOT, sub)
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".ox"):
                continue
            path = os.path.join(d, fn)
            src = open(path, encoding="utf-8").read()
            hits = scan_source(src, path)
            if hits:
                total += len(hits)
                print(f"{sub}/{fn}: {len(hits)} interpolated strings")
                for line, col, prev in hits:
                    print(f"    {line}:{col}  \"{prev}\"")
    # 2. markdown fences
    for dirpath, _, files in os.walk(os.path.join(ROOT, "docs")):
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            src = open(path, encoding="utf-8").read()
            rel = os.path.relpath(path, ROOT)
            n = 0
            for m in FENCE_RE.finditer(src):
                fence_body = m.group(1)
                start_line = src[:m.start()].count("\n") + 2  # first body line
                hits = scan_source(fence_body, path, base_line=start_line)
                for line, col, prev in hits:
                    n += 1
                    print(f"{rel}:{start_line + line - 1}:{col}  \"{prev}\"")
            if n:
                total += n
                print(f"-- {rel}: {n} in fences")
    # 3. scaffold template
    path = os.path.join(ROOT, "ox", "scaffold.py")
    src = open(path, encoding="utf-8").read()
    hits = scan_source(src, path)
    if hits:
        total += len(hits)
        print(f"ox/scaffold.py: {len(hits)} (raw py source, check manually)")
        for line, col, prev in hits:
            print(f"    {line}:{col}  \"{prev}\"")
    print(f"\n== total: {total} interpolated strings need f-prefix")


if __name__ == "__main__":
    main()
