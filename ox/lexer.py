"""Lexer for the ox language.

Tokens carry (type, value, line, col, file). Token *type* is a string:
"IDENT", "INT", "FLOAT", "DUR", "STRING", "NEWLINE", "EOF", a keyword
("let", "fn", ...) or an operator symbol ("+", "==", "|>", ...).

Notable behaviours:
  * `#` starts a comment (a leading `#!` shebang line is just a comment).
  * Newlines are significant as statement separators, but suppressed inside
    round/ square brackets so calls and lists can span lines. `;` behaves
    exactly like a newline.
  * `f"..."` strings interpolate `{expr}`; plain `"..."` strings treat `{`
    as a literal character; `'...'` strings are raw (no escapes, no
    interpolation).
  * Duration literals: 5ms, 2s, 3m, 1h, 2d — lexed as DUR (float seconds).
  * Numbers: decimal, 0x/0b/0o bases, `_` separators, floats, exponents.
    `1..5` lexes as INT 1, range op, INT 5; `1.round()` as INT, `.`, IDENT.
"""
from .errors import LexError

KEYWORDS = frozenset("""
let var fn return if else for in while loop break continue try catch finally
throw async await spawn on emit import export as and or not true false null
match pass workflow serve test verify
""".split())

# statement-only keywords that also work as ordinary names in expression
# position (params, kwargs, references): a bare `on` / `test` / `workflow`
# is never a valid statement on its own, so treating it as an identifier
# inside expressions is unambiguous. `verify` is special-cased in the
# parser (module reference) but behaves the same way. NOTE: `serve` must
# NOT be here — it has an expression form (daemon handles) whose branch
# would be shadowed.
SOFT_KEYWORDS = frozenset(("on", "test", "workflow"))

DUR_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}

OPERATORS3 = ("...", "..<", "//=")
OPERATORS2 = ("**", "//", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=",
              "%=", "..", "=>", "??", "|>")
OPERATORS1 = "+-*/%=<>()[]{},.:"

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0",
           "\\": "\\", '"': '"', "'": "'", "{": "{", "}": "}"}


HEX_DIGITS = frozenset("0123456789abcdefABCDEF_")
BASE_PREFIXES = frozenset("xXbBoO")
LOWER_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyz")


class Token:
    __slots__ = ("type", "value", "line", "col", "file", "lexeme", "quote",
                 "triple", "fprefix")

    def __init__(self, type_, value=None, line=1, col=1, file=None,
                 lexeme=None, quote=None, triple=False, fprefix=False):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col
        self.file = file
        self.lexeme = lexeme   # original source text (INT/FLOAT/DUR)
        self.quote = quote     # original quote char (STRING)
        self.triple = triple   # """...""" / '''...''' (STRING)
        self.fprefix = fprefix  # f"...": interpolation enabled (STRING)

    def __repr__(self):
        v = "" if self.value is None else " %r" % (self.value,)
        return "Token(%s%s @%s:%s)" % (self.type, v, self.line, self.col)


class Lexer:
    def __init__(self, source, file="<ox>", line=1):
        self.src = source
        self.n = len(source)
        self.i = 0
        self.line = line
        self.col = 1
        self.file = file
        self.brackets = []  # per-nesting newline suppression:
        # ( and [ suppress newlines; { re-enables them (blocks need statements)
        self.comments = []  # (line, col, text) for every comment incl. shebang

    # ---- helpers -------------------------------------------------------
    def error(self, msg, line=None, col=None):
        raise LexError(msg, line or self.line, col or self.col, self.file)

    def cur(self):
        return self.src[self.i] if self.i < self.n else ""

    def at(self, off):
        j = self.i + off
        return self.src[j] if j < self.n else ""

    def advance(self):
        c = self.cur()
        self.i += 1
        if c == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return c

    def emit(self, type_, value=None):
        self.tokens.append(Token(type_, value, tok_line, tok_col, self.file))

    def add(self, type_, value, line, col):
        tok = Token(type_, value, line, col, self.file)
        self.tokens.append(tok)
        return tok

    # ---- entry ---------------------------------------------------------
    def tokenize(self):
        self.tokens = []
        while self.i < self.n:
            c = self.cur()
            if c in " \t\r":
                self.advance()
            elif c == "#" and self.at(1) == "!" and self.i == 0:
                self.skip_comment()  # shebang
            elif c == "#":
                self.skip_comment()
            elif c == "\n":
                self.newline()
            elif c == ";":
                if self.brackets and self.brackets[-1]:
                    self.error("unexpected ';' inside brackets")
                # a ';' is a newline without consuming another character
                line, col = self.line, self.col
                self.advance()
                if not (self.tokens and
                        self.tokens[-1].type == "NEWLINE"):
                    self.tokens.append(Token("NEWLINE", None, line, col,
                                             self.file))
            elif c.isalpha() or c == "_":
                self.scan_ident()
            elif c.isdigit():
                self.scan_number()
            elif c == '"' or c == "'":
                self.scan_string_token(c)
            else:
                self.scan_operator()
        self.tokens.append(Token("EOF", None, self.line, self.col, self.file))
        return self.tokens

    def skip_comment(self):
        start = self.i
        line, col = self.line, self.col
        while self.i < self.n and self.cur() != "\n":
            self.advance()
        self.comments.append((line, col, self.src[start:self.i]))

    def newline(self, strict=True):
        col = self.col          # column of the '\n' character
        self.advance()  # consume \n
        if self.brackets and self.brackets[-1]:
            return
        if strict and self.tokens and self.tokens[-1].type == "NEWLINE":
            return
        self.tokens.append(Token("NEWLINE", None, self.line - 1, col,
                                 self.file))

    def scan_ident(self):
        line, col = self.line, self.col
        j = self.i
        while j < self.n and (self.src[j].isalnum() or self.src[j] == "_"):
            j += 1
        word = self.src[self.i:j]
        while self.i < j:
            self.advance()
        if word in KEYWORDS:
            self.add(word, None, line, col)
            return
        # `f"..."` string prefix: interpolation is opt-in (0.4). Plain
        # double-quoted strings treat `{` as a literal character.
        if word == "f" and self.cur() == '"':
            self.scan_string_token('"', interp=True)
            return
        if word == "f" and self.cur() == "'":
            self.error("f-prefix works with double quotes only", line, col)
        self.add("IDENT", word, line, col)

    # ---- numbers -------------------------------------------------------
    def scan_number(self):
        line, col = self.line, self.col
        start = self.i
        if self.cur() == "0" and self.at(1) in BASE_PREFIXES:
            self.advance()  # 0
            base_ch = self.advance().lower()
            base = {"x": 16, "b": 2, "o": 8}[base_ch]
            ds = self.i
            while self.cur() in HEX_DIGITS:
                self.advance()
            digits = self.src[ds:self.i].replace("_", "")
            if not digits:
                self.error("invalid %s literal" %
                           ("hex" if base == 16 else "binary" if base == 2 else "octal"),
                           line, col)
            value = int(digits, base)
            self.tokens.append(Token("INT", value, line, col, self.file,
                                     lexeme=self.src[start:self.i]))
            return
        is_float = False
        while self.cur().isdigit() or self.cur() == "_":
            self.advance()
        # fraction: only when '.' is followed by a digit (keeps `1..5` and
        # `1.round()` working)
        if self.cur() == "." and self.at(1).isdigit():
            is_float = True
            self.advance()
            while self.cur().isdigit() or self.cur() == "_":
                self.advance()
        # exponent
        if self.cur() in ("e", "E"):
            nxt, nxt2 = self.at(1), self.at(2)
            if nxt.isdigit() or (nxt in ("+", "-") and nxt2.isdigit()):
                is_float = True
                self.advance()  # e
                if self.cur() in ("+", "-"):
                    self.advance()
                while self.cur().isdigit():
                    self.advance()
        text = self.src[start:self.i].replace("_", "")
        value = float(text) if is_float else int(text)
        # duration suffix: 5s / 150ms / 2m / 1h / 3d / 1.5s
        if self.cur() in LOWER_LETTERS:
            j = self.i
            while j < self.n and self.src[j].isalpha():
                j += 1
            unit = self.src[self.i:j]
            nxt = self.src[j] if j < self.n else ""
            if unit in DUR_UNITS and not (nxt.isalnum() or nxt == "_"):
                while self.i < j:
                    self.advance()
                self.tokens.append(Token("DUR", value * DUR_UNITS[unit], line, col,
                                         self.file, lexeme=self.src[start:self.i]))
            else:
                self.error("invalid number suffix '%s' (durations use ms/s/m/h/d)" % unit,
                           line, col)
            return
        tok = Token("FLOAT" if is_float else "INT", value, line, col,
                    self.file, lexeme=self.src[start:self.i])
        self.tokens.append(tok)

    # ---- strings -------------------------------------------------------
    def scan_string_token(self, quote, interp=False):
        line, col = self.line, self.col
        triple = self.at(1) == quote and self.at(2) == quote
        if triple:
            # triple-quoted string: multi-line, escapes on; interpolation
            # only with the f prefix
            self.advance()
            self.advance()
            self.advance()
            parts = self.scan_triple_body(quote, interp)
        else:
            self.advance()  # opening quote
            parts = self.scan_string_body(quote, interp)
        if not parts:
            tok = self.add("STRING", "", line, col)
        elif len(parts) == 1 and parts[0][0] == "lit":
            tok = self.add("STRING", parts[0][1], line, col)
        else:
            tok = self.add("STRING", parts, line, col)
        tok.quote = quote
        tok.triple = triple
        tok.fprefix = interp

    def scan_triple_body(self, quote, interp):
        """Multi-line string body, closed by `quote * 3`."""
        parts = []
        buf = []
        close = quote * 3
        while True:
            if self.i >= self.n:
                self.error("unterminated triple-quoted string")
            if self.src.startswith(close, self.i):
                self.advance()
                self.advance()
                self.advance()
                break
            c = self.cur()
            if c == "\\":
                e = self.at(1)
                if e not in ESCAPES:
                    self.error("unknown escape '\\%s'" % e)
                buf.append(ESCAPES[e])
                self.advance()
                self.advance()
                continue
            if c == "{" and interp:
                if buf:
                    parts.append(("lit", "".join(buf)))
                    buf = []
                iline, icol = self.line, self.col
                self.advance()  # {
                src = self.scan_interp()
                parts.append(("interp", src, iline, icol))
                continue
            buf.append(c)
            self.advance()
        if buf:
            parts.append(("lit", "".join(buf)))
        return parts

    def scan_string_body(self, quote, interp):
        """Scan until closing quote; returns list of parts.
        parts: ("lit", text) or ("interp", source, line, col)."""
        parts = []
        buf = []
        while True:
            if self.i >= self.n:
                self.error("unterminated string")
            c = self.cur()
            if c == quote:
                self.advance()
                break
            if c == "\\":
                e = self.at(1)
                if e not in ESCAPES:
                    self.error("unknown escape '\\%s'" % e)
                buf.append(ESCAPES[e])
                self.advance()
                self.advance()
                continue
            if c == "{" and interp:
                if buf:
                    parts.append(("lit", "".join(buf)))
                    buf = []
                iline, icol = self.line, self.col
                self.advance()  # {
                src = self.scan_interp()
                parts.append(("interp", src, iline, icol))
                continue
            if c == "\n":
                buf.append(c)
                self.advance()
                continue
            buf.append(c)
            self.advance()
        if buf:
            parts.append(("lit", "".join(buf)))
        return parts

    def scan_interp(self):
        """Consume source up to the matching '}'. Nested braces and nested
        strings (with their own interpolations) are handled recursively."""
        start = self.i
        depth = 1
        while True:
            if self.i >= self.n:
                self.error("unterminated '{' interpolation")
            c = self.cur()
            if c == "{":
                depth += 1
                self.advance()
            elif c == "}":
                depth -= 1
                self.advance()
                if depth == 0:
                    return self.src[start:self.i - 1]
            elif c == '"' or c == "'":
                self.advance()
                # discard, keeps positions in sync (nested strings may hold
                # their own interpolations, so scan with interpolation on)
                self.scan_string_body(c, True)
            elif c == "#":
                self.skip_comment()
            else:
                self.advance()

    # ---- operators -----------------------------------------------------
    def scan_operator(self):
        line, col = self.line, self.col
        three = self.src[self.i:self.i + 3]
        two = self.src[self.i:self.i + 2]
        if three in OPERATORS3:
            for _ in range(3):
                self.advance()
            self.add(three, None, line, col)
            return
        if two in OPERATORS2:
            self.advance()
            self.advance()
            self.add(two, None, line, col)
            return
        c = self.advance()
        if c in OPERATORS1:
            if c in "([{":
                self.brackets.append(c in "([")
            elif c in ")]}":
                if self.brackets:
                    self.brackets.pop()
            self.add(c, None, line, col)
            return
        if c == "!":
            self.error("unexpected '!' (ox uses 'not' for negation)", line, col)
        self.error("unexpected character %r" % c, line, col)


def lex(source, file="<ox>", line=1):
    return Lexer(source, file, line).tokenize()
