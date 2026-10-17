"""ox fmt — format .ox source.

A conservative, token-aware formatter. It never joins or reorders tokens
and never drops anything (comments included), so the output is guaranteed
to re-lex to the same token stream — semantics are preserved by
construction. What it normalises:

  * indentation: two spaces per bracket depth, recomputed for every line
  * spacing within lines: operators, commas, colons, call parens, kwargs
  * runs of blank lines collapse to one; trailing whitespace is trimmed
  * shebangs, comments, string quoting (raw vs interpolated vs triple)
    and number spelling (0x1F, 1_000, 150ms) are kept as written
  * line structure is respected: nothing is ever split or joined
  * idempotent: fmt(fmt(x)) == fmt(x)
"""
from .errors import OxToolError
from .lexer import KEYWORDS, Lexer

INDENT = "  "

BINOPS = {"+", "-", "*", "/", "%", "**", "//", "==", "!=", "<=", ">=",
          "<", ">", "and", "or", "in", "??", "|>", "=>", "=", "+=", "-=",
          "*=", "/=", "%=", "//="}
UNARYABLE = {"-", "+"}

_ESC_COMMON = {"\\": "\\\\", "\r": "\\r", "\0": "\\0"}
# plain double quotes: `{` is a literal character, no need to escape it
_ESC_DQ = dict(_ESC_COMMON, **{'"': '\\"'})
# f-strings: literal braces must be escaped so they survive re-lexing
_ESC_DQ_F = dict(_ESC_DQ, **{"{": "\\{", "}": "\\}"})
_ESC_SQ = dict(_ESC_COMMON, **{"'": "\\'"})


def _render_string(tok):
    """Re-render a STRING token exactly as it should appear in source."""
    q = tok.quote or '"'
    is_f = bool(getattr(tok, "fprefix", False))
    if q == "'":
        esc = _ESC_SQ
    elif is_f:
        esc = _ESC_DQ_F
    else:
        esc = _ESC_DQ
    prefix = 'f' if is_f else ''
    if tok.triple:
        triple = q * 3
        if isinstance(tok.value, str):
            return prefix + triple + _escape(tok.value, esc, keep_nl=True) + triple
        parts = []
        for p in tok.value:
            if p[0] == "lit":
                parts.append(_escape(p[1], esc, keep_nl=True))
            else:
                parts.append("{" + p[1] + "}")
        return prefix + triple + "".join(parts) + triple
    if isinstance(tok.value, str):
        return prefix + q + _escape(tok.value, esc) + q
    parts = []
    for p in tok.value:
        if p[0] == "lit":
            parts.append(_escape(p[1], esc))
        else:
            parts.append("{" + p[1] + "}")
    return prefix + q + "".join(parts) + q


def _escape(s, esc, keep_nl=False):
    out = []
    for ch in s:
        if ch == "\n" and keep_nl:
            out.append(ch)
        elif ch == "\t" and keep_nl:
            out.append(ch)
        else:
            out.append(esc.get(ch, ch))
    return "".join(out)


def _render_token(tok):
    ty = tok.type
    if ty == "STRING":
        return _render_string(tok)
    if ty == "IDENT":
        return tok.value
    if tok.lexeme is not None:
        return tok.lexeme
    return ty


def _token_end_line(tok):
    n = 0
    if tok.type == "STRING":
        if isinstance(tok.value, str):
            n = tok.value.count("\n")
        else:
            for p in tok.value:
                if p[0] == "lit":
                    n += p[1].count("\n")
    return tok.line + n


class _Formatter:
    def __init__(self, src, file):
        self.src = src
        self.file = file

    def run(self):
        lex = Lexer(self.src, self.file)
        toks = [t for t in lex.tokenize() if t.type != "EOF"]
        events = [("tok", t.line, t.col, t) for t in toks]
        events += [("cmt", line, col, text)
                   for line, col, text in lex.comments]
        events.sort(key=lambda e: (e[1], e[2]))
        self.events = events

        self.out = []          # finished lines
        self.cur = []          # pieces of the current line
        self.depth = 0         # bracket nesting (indent level)
        self.stack = []        # (bracket, kind) for "(" "[" "{"; kind for
        #                       braces: "dict" | "block" — drives spacing
        self.paren_depth = 0   # ( ) nesting only, for '=' tightness
        self.prev = None       # previous token (None at line starts)
        self.prev2 = None      # token before prev (for `mod.keyword(...)`)
        self.prev_unary = False
        self.last_end_line = 0  # source line where emitted content ended

        for self.i, (kind, line, col, payload) in enumerate(events):
            if kind == "cmt":
                self._comment(line, payload)
            else:
                self._token(payload)
        self._end_line()
        # trim leading/trailing blanks, ensure exactly one final newline
        while self.out and self.out[-1] == "":
            self.out.pop()
        while self.out and self.out[0] == "":
            self.out.pop(0)
        return "\n".join(self.out) + "\n"

    def _peek_token(self, k=1):
        """Type of the k-th next TOKEN event (comments skipped)."""
        n = 0
        for j in range(self.i + 1, len(self.events)):
            if self.events[j][0] == "tok":
                n += 1
                if n == k:
                    return self.events[j][3].type
        return None

    # ---- event handling -------------------------------------------------
    def _comment(self, line, text):
        if self.cur and line > self.last_end_line:
            self._end_line()
        if not self.cur:
            self._maybe_blank(line)
            self.cur.append(INDENT * self.depth)
            self.cur.append(text)
        else:
            self.cur.append(" " + text)
        self.last_end_line = line

    def _token(self, tok):
        ty = tok.type
        if ty == "NEWLINE":
            if self.cur:
                self._end_line()
            self.prev = None
            return
        if self.cur and tok.line > self.last_end_line:
            self._end_line()
        if not self.cur:
            self._maybe_blank(tok.line)
            # a closing bracket dedents its own line; at line starts the
            # spacing is always "" (prev is None), so popping first is safe
            if ty in (")", "]", "}"):
                self._pop(ty)
            self.cur.append(INDENT * self.depth)
            sp = self._spacing(tok)
        else:
            # mid-line closing bracket: spacing must see its own opener,
            # so compute it BEFORE popping
            if ty in (")", "]", "}"):
                sp = self._spacing(tok)
                self._pop(ty)
            else:
                sp = self._spacing(tok)
        if ty == "{":
            kind = "dict" if self._looks_like_dict() else "block"
            self.stack.append((ty, kind))
            self.depth += 1
        elif ty in ("(", "["):
            self.stack.append((ty, None))
            self.depth += 1
            if ty == "(":
                self.paren_depth += 1

        if sp:
            self.cur.append(sp)
        self.cur.append(_render_token(tok))

        if ty in UNARYABLE:
            p = self.prev.type if self.prev else None
            self.prev_unary = (
                p is None or p in ("(", "[", "{", ",") or
                p in BINOPS or p in KEYWORDS)
        else:
            self.prev_unary = False
        self.prev2 = self.prev
        self.prev = tok
        self.last_end_line = _token_end_line(tok)

    def _pop(self, ty):
        if self.stack:
            self.stack.pop()
        self.depth = max(0, self.depth - 1)
        if ty == ")":
            self.paren_depth = max(0, self.paren_depth - 1)

    def _maybe_blank(self, line):
        if line - self.last_end_line > 1:
            self.out.append("")

    def _end_line(self):
        text = "".join(self.cur).rstrip()
        del self.cur[:]
        if text:
            self.out.append(text)
        self.prev = None

    # ---- spacing ----------------------------------------------------------
    def _innermost(self):
        return self.stack[-1][0] if self.stack else None

    def _looks_like_dict(self):
        """After an opening '{': is the next thing 'key:' or shorthand
        'key,' (a dict literal/pattern)? Blocks never start like that."""
        first = self._peek_token(1)
        second = self._peek_token(2)
        if first in ("IDENT", "STRING", "INT", "FLOAT", "DUR",
                     "true", "false", "null"):
            if second == ":":
                return True
            if first == "IDENT" and second == ",":
                return True   # shorthand pattern: {code, msg}
        return False

    def _spacing(self, tok):
        """Space (or '') between the previous token and this one."""
        if self.prev is None:
            return ""
        p = self.prev.type
        t = tok.type
        if t == "}" and self._innermost() == "{" and \
                self.stack[-1][1] == "block" and p not in ("(", "["):
            return " "     # one-line blocks keep a space: { do() }
        if t in (")", "]", "}", ","):
            return ""
        if p == ",":
            return " "
        if p in ("(", "["):
            return ""
        if t == "." or p == ".":
            return ""
        if t in ("..", "..<"):
            return ""
        if p in ("..", "..<"):
            return ""
        if p == "...":
            return ""
        if p == "{" and t == "[":
            return " "     # patterns read better: { [a, b] => ... }
        if p == "{":
            # dict values sit tight: {a: 1}; block bodies get a space
            return "" if (self.stack and self.stack[-1][1] == "dict") \
                else " "
        # '=' tightness applies before the '{'-after-'=' case: kwargs
        # (query={...}) and defaults stay tight inside parens
        if t in ("=", "+=", "-=", "*=", "/=", "%=", "//=") or \
                p in ("=", "+=", "-=", "*=", "/=", "%=", "//="):
            return "" if self.paren_depth > 0 else " "
        if t in ("(", "["):
            if p in KEYWORDS and self.prev2 is not None \
                    and self.prev2.type == ".":
                return ""     # module member that collides with a keyword:
                #             verify.true(...)
            if p in KEYWORDS or p in BINOPS:
                return " "
            if p in (")", "]", "}"):
                return ""
            if p in ("IDENT", "INT", "FLOAT", "DUR", "STRING"):
                return ""
            return " "
        if t == "{":
            if p in ("(", "["):
                return ""
            return " "
        if t == ":":
            return ""
        if p == ":":
            return "" if self._innermost() == "[" else " "
        if t == "...":
            return ""
        if t in ("-", "+"):
            return " "
        if p in ("-", "+") and self.prev_unary:
            return ""
        if t in BINOPS or p in BINOPS:
            return " "
        if p in KEYWORDS or t in KEYWORDS:
            return " "
        return " "


def format_source(src, file="<ox>"):
    """Format ox source; returns the formatted text (always ends in \n)."""
    try:
        return _Formatter(src, file).run()
    except OxToolError:
        raise
    except Exception as e:  # noqa: BLE001 — formatter must not crash hard
        raise OxToolError("fmt: internal error: %s" % e)


def format_file(path, check=False):
    """Format one file in place (or report with check=True).

    Returns (changed: bool, new_text: str)."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    formatted = format_source(src, path)
    if formatted == src:
        return False, src
    if not check:
        with open(path, "w", encoding="utf-8") as f:
            f.write(formatted)
    return True, formatted
