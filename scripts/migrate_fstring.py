#!/usr/bin/env python3
"""Insert the `f` prefix before every interpolated double-quoted string.

MUST run against the 0.3.1 lexer (before the f-prefix language change):
it tokenizes each file, finds STRING tokens whose value is a parts list
(i.e. contains interpolation), and inserts 'f' before the opening quote.
Markdown ```ox fences are migrated block by block. scaffold.py is
excluded (python-embedded templates — handled manually).
"""
import sys
import os
import re

sys.path.insert(0, "/home/z/my-project/ox")
from ox.lexer import Lexer  # noqa: E402

ROOT = "/home/z/my-project/ox"
FENCE_RE = re.compile(r"(^```ox\r?\n)(.*?)(^```)", re.S | re.M)


def interp_positions(src, label):
    """[(line, col)] of interpolated double-quoted strings in src."""
    try:
        toks = Lexer(src, label).tokenize()
    except Exception:  # noqa: BLE001
        return []
    return [(t.line, t.col) for t in toks
            if t.type == "STRING" and isinstance(t.value, list)
            and t.quote == '"']


def insert_f(src, label):
    """Insert 'f' before each interpolated string; returns (new_src, n)."""
    pos = interp_positions(src, label)
    if not pos:
        return src, 0
    lines = src.split("\n")
    # process bottom-up so earlier columns stay valid
    for line, col in sorted(pos, reverse=True):
        text = lines[line - 1]
        idx = col - 1
        assert text[idx] == '"', (label, line, col, text[:idx + 5])
        lines[line - 1] = text[:idx] + "f" + text[idx:]
    return "\n".join(lines), len(pos)


def migrate_ox_file(path):
    src = open(path, encoding="utf-8").read()
    new, n = insert_f(src, path)
    if n:
        open(path, "w", encoding="utf-8").write(new)
    return n


def migrate_md_file(path):
    src = open(path, encoding="utf-8").read()
    total = 0

    def repl(m):
        nonlocal total
        new_body, n = insert_f(m.group(2), path)
        total += n
        return m.group(1) + new_body + m.group(3)

    new = FENCE_RE.sub(repl, src)
    if total:
        open(path, "w", encoding="utf-8").write(new)
    return total


def main():
    grand = 0
    for sub in ("tests", "examples"):
        d = os.path.join(ROOT, sub)
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".ox"):
                n = migrate_ox_file(os.path.join(d, fn))
                if n:
                    print(f"{sub}/{fn}: {n} inserted")
                    grand += n
    for dirpath, _, files in os.walk(os.path.join(ROOT, "docs")):
        for fn in sorted(files):
            if fn.endswith(".md"):
                n = migrate_md_file(os.path.join(dirpath, fn))
                if n:
                    print(f"docs/.../{fn}: {n} inserted")
                    grand += n
    print(f"\n== inserted f-prefix at {grand} sites")


if __name__ == "__main__":
    main()
