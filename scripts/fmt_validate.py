"""Validation harness for ox fmt.

Proves, for every .ox file in tests/ and examples/:
  1. token equivalence: the formatted source re-lexes to the exact same
     token stream (types and values, NEWLINEs excluded) — semantics are
     preserved by construction
  2. idempotency: format_source(format_source(x)) == format_source(x)
  3. (run separately) the full test suite passes on the formatted corpus
"""
import sys
sys.path.insert(0, "/home/z/my-project/ox")

from ox.fmt import format_source
from ox.lexer import Lexer


def toks_of(src):
    out = []
    for t in Lexer(src, "x").tokenize():
        if t.type == "NEWLINE":
            continue
        v = t.value
        if t.type == "STRING" and isinstance(v, list):
            # interp parts carry (line, col) of the original source; they
            # legitimately move when lines are re-indented — compare content
            v = tuple((p[0], p[1]) if p[0] == "interp" else (p[0], p[1])
                      for p in v)
        out.append((t.type, v))
    return out


def main():
    import glob
    files = sorted(glob.glob("/home/z/my-project/ox/tests/*.test.ox") +
                   glob.glob("/home/z/my-project/ox/tests/mods/*.ox") +
                   glob.glob("/home/z/my-project/ox/examples/*.ox"))
    failures = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            fmt1 = format_source(src, path)
        except Exception as e:
            print("FMT FAIL %s: %s" % (path, e))
            failures += 1
            continue
        if toks_of(src) != toks_of(fmt1):
            a, b = toks_of(src), toks_of(fmt1)
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print("TOKENS DIVERGE %s at %d: %r != %r" % (path, i, x, y))
                    break
            else:
                print("TOKENS DIVERGE %s: len %d != %d" % (path, len(a), len(b)))
            failures += 1
        fmt2 = format_source(fmt1, path)
        if fmt1 != fmt2:
            print("NOT IDEMPOTENT %s" % path)
            failures += 1
    print("checked %d files, %d failures" % (len(files), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
