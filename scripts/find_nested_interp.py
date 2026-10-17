#!/usr/bin/env python3
"""Find double-quoted strings NESTED inside interpolation sources that
still contain {name}-like text — these need an inner f prefix (the token
level migration cannot see them because the lexer discards nested
strings while scanning an interpolation).
"""
import sys
import os
import re

sys.path.insert(0, "/home/z/my-project/ox")
from ox.lexer import Lexer  # noqa: E402

ROOT = "/home/z/my-project/ox"
SUSPECT = re.compile(r"\{[\w.]+\}")


def find_nested(src, label, off_line=0, off_col=0, depth=0, hits=None):
    """Recursively locate nested double-quoted strings inside interps."""
    if hits is None:
        hits = []
    try:
        toks = Lexer(src, label).tokenize()
    except Exception:  # noqa: BLE001
        return hits
    for t in toks:
        if t.type != "STRING" or not isinstance(t.value, list):
            continue
        for p in t.value:
            if p[0] != "interp":
                continue
            _, isrc, iline, icol = p
            # inner tokens of this interpolation source
            try:
                inner = Lexer(isrc, label).tokenize()
            except Exception:  # noqa: BLE001
                continue
            for it in inner:
                if it.type == "STRING" and it.quote == '"' \
                        and isinstance(it.value, str) \
                        and SUSPECT.search(it.value):
                    hits.append((label, iline, icol + it.col, it.value))
                # recurse: f-string inside the interpolation
                if it.type == "STRING" and isinstance(it.value, list):
                    sub = "".join(x[1] for x in it.value)
                    find_nested(it.value if isinstance(it.value, str) else sub,
                                label, 0, 0, depth + 1, hits)
    return hits


def main():
    total = 0
    for sub in ("tests", "examples"):
        d = os.path.join(ROOT, sub)
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".ox"):
                continue
            path = os.path.join(d, fn)
            src = open(path, encoding="utf-8").read()
            for label, line, col, val in find_nested(src, path):
                print(f"{sub}/{fn}:{line}:{col}  nested \"{val}\"")
                total += 1
    print(f"== {total} nested strings need an inner f prefix")


if __name__ == "__main__":
    main()
