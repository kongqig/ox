"""Recursive-descent parser for ox.

Grammar highlights (see docs/LANGUAGE.md for the full spec):

    program   := stmt* EOF
    stmt      := let | fn | return | if | while | loop | for | try | match
               | on | emit | verify | throw | import | export | workflow
               | serve | test | step | hook | desc | route | static | ws
               | assignment | expr-stmt | pass | break | continue

    expr      := pipe
    pipe      := nullish ( "|>" postfix )*                # x |> f(a) == f(x, a)
    nullish   := or ( "??" or )*
    or        := and ( "or" and )*
    and       := not ( "and" not )*
    not       := "not" not | comparison
    comparison:= range ( ("=="|"!="|"<"|"<="|">"|">=") range )*
    range     := additive ( (".."|"..<") additive )?
    additive  := mul ( ("+"|"-") mul )*
    mul       := unary ( ("*"|"/"|"//"|"%") unary )*
    unary     := "-" unary | "await" unary | power
    power     := postfix ( "**" unary )?                  # right-assoc
    postfix   := primary ( "." IDENT | "(" args ")" | "[" index "]" )*
    primary   := literal | ident | "(" expr ")" | list | dict | fn-lit
               | spawn (block | expr)

Newlines terminate statements; they are suppressed inside ( ) and [ ] by the
lexer, and skipped by the parser inside dict literals. A binary operator or
`|>` at end of line continues the expression on the next line. A line that
*starts* with `.` continues the previous postfix chain.
"""
from . import ast_nodes as A
from .errors import ParseError
from .lexer import Lexer, KEYWORDS, SOFT_KEYWORDS

ROUTE_METHODS = ("get", "post", "put", "delete", "patch", "head")
ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "//=", "%=")
COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


def show(tok):
    t = tok.type
    if t == "IDENT":
        return "'%s'" % tok.value
    if t == "STRING":
        return "string literal"
    if t == "NEWLINE":
        return "end of line"
    if t == "EOF":
        return "end of file"
    if t in ("INT", "FLOAT", "DUR"):
        return "number '%s'" % tok.value
    return "'%s'" % t


class Parser:
    def __init__(self, tokens, file="<ox>"):
        self.toks = tokens
        self.i = 0
        self.file = file
        self.ctx = []  # "workflow" | "serve"

    # ---- token helpers -------------------------------------------------
    def peek(self, off=0):
        j = min(self.i + off, len(self.toks) - 1)
        return self.toks[j]

    def next(self):
        t = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def check(self, *types):
        return self.peek().type in types

    def match(self, *types):
        if self.check(*types):
            return self.next()
        return None

    def match_ident(self, *words):
        t = self.peek()
        if t.type == "IDENT" and t.value in words:
            return self.next()
        return None

    def expect(self, type_, msg=None):
        t = self.peek()
        if t.type != type_:
            self.error(msg or "expected %s, found %s" %
                       ("'%s'" % type_ if len(type_) > 1 or type_.isalnum() else type_,
                        show(t)), t)
        return self.next()

    def expect_ident(self, what="identifier"):
        t = self.peek()
        if t.type != "IDENT":
            self.error("expected %s, found %s" % (what, show(t)), t)
        return self.next()

    def expect_attr_name(self, what="name"):
        """Attribute / method name after '.': keywords are fine (conn.on)."""
        t = self.peek()
        if t.type == "IDENT":
            return self.next().value
        if t.type in KEYWORDS:
            return self.next().type
        self.error("expected %s, found %s" % (what, show(t)), t)

    def error(self, msg, tok=None):
        t = tok or self.peek()
        raise ParseError(msg, t.line, t.col, self.file)

    def skip_nl(self):
        while self.check("NEWLINE"):
            self.next()

    def node(self, cls, tok, *args):
        n = cls(*args)
        n.line, n.col = tok.line, tok.col
        return n

    def in_ctx(self, flag):
        return flag in self.ctx

    # ---- entry ----------------------------------------------------------
    def parse_program(self):
        t0 = self.peek()
        stmts = self.parse_stmt_list("EOF")
        while self.check("NEWLINE"):
            self.next()
        self.expect("EOF")
        return self.node(A.Program, t0, stmts, self.file)

    def parse_stmt_list(self, terminator):
        stmts = []
        self.skip_nl()
        while not self.check(terminator, "EOF"):
            s = self.parse_statement()
            if s is not None:
                stmts.append(s)
            if self.check("NEWLINE"):
                self.skip_nl()
            elif self.check("}", "EOF") or self.check(terminator):
                pass
            else:
                self.error("expected end of line after statement")
        return stmts

    # ---- statements ------------------------------------------------------
    def parse_statement(self):
        t = self.peek()
        ty = t.type

        if ty == "NEWLINE":
            self.next()
            return None
        if ty == "let" or ty == "var":
            return self.parse_let()
        if ty == "fn":
            # `fn name(...)` is a declaration; `fn (...)` is an expression
            if self.peek(1).type == "IDENT" and self.peek(2).type == "(":
                return self.parse_fn_decl()
            return self.parse_assignment_or_expr()
        if ty == "return":
            self.next()
            val = None
            if not self.check("NEWLINE", "}", "EOF"):
                val = self.parse_expression()
            return self.node(A.Return, t, val)
        if ty == "break":
            self.next()
            return self.node(A.Break, t)
        if ty == "continue":
            self.next()
            return self.node(A.Continue, t)
        if ty == "pass":
            self.next()
            return self.node(A.Pass, t)
        if ty == "throw":
            self.next()
            val = self.parse_expression()
            return self.node(A.Throw, t, val)
        if ty == "if":
            return self.parse_if()
        if ty == "while":
            self.next()
            cond = self.parse_expression()
            body = self.parse_block()
            return self.node(A.While, t, cond, body)
        if ty == "loop":
            self.next()
            body = self.parse_block()
            return self.node(A.Loop, t, body)
        if ty == "for":
            return self.parse_for()
        if ty == "try":
            return self.parse_try()
        if ty == "match":
            return self.parse_match()
        if ty == "on":
            return self.parse_on()
        if ty == "emit":
            self.next()
            name = self.expect("STRING", "expected event name string after 'emit'")
            payload = None
            if not self.check("NEWLINE", "}", "EOF"):
                payload = self.parse_expression()
            return self.node(A.Emit, t, name.value, payload)
        if ty == "verify":
            if self.peek(1).type == ".":
                # `verify.eq(...)` — module usage, not a verify statement
                return self.parse_assignment_or_expr()
            self.next()
            cond = self.parse_expression()
            msg = None
            if self.match(","):
                self.skip_nl()
                msg = self.parse_expression()
            return self.node(A.Verify, t, cond, msg)
        if ty == "import":
            return self.parse_import()
        if ty == "export":
            return self.parse_export()
        if ty == "test":
            return self.parse_test()
        if ty == "workflow":
            return self.parse_workflow()
        if ty == "serve":
            return self.parse_serve()
        # contextual statement keywords (usable as identifiers elsewhere)
        if ty == "IDENT":
            v = t.value
            if v == "step" and self.in_ctx("workflow"):
                return self.parse_step()
            if v == "desc" and self.in_ctx("workflow"):
                self.next()
                s = self.expect("STRING", "expected description string after 'desc'")
                return self.node(A.DescDecl, t, s.value)
            if v in ("get", "post", "put", "delete", "patch", "head") and self.in_ctx("serve"):
                return self.parse_route()
            if v == "static" and self.in_ctx("serve"):
                self.next()
                p1 = self.expect("STRING", "expected url prefix string")
                dexpr = self.parse_expression()
                return self.node(A.StaticDecl, t, p1.value, dexpr)
            if v == "ws" and self.in_ctx("serve"):
                return self.parse_ws_route()
        return self.parse_assignment_or_expr()

    def parse_let(self):
        t = self.match("let", "var")
        mutable = t.type == "var"
        name = self.expect_ident("variable name after '%s'" % t.type)
        if self.match("="):
            self.skip_nl()
            value = self.parse_expression()
        elif mutable:
            value = self.node(A.Literal, t, None)
        else:
            self.error("'%s' requires a value (use 'var' for a possibly-empty "
                       "mutable binding)" % t.type, name)
        return self.node(A.Let, t, name.value, value, mutable, False)

    def parse_params(self):
        """Returns (params, defaults, vararg). defaults aligned with params."""
        params, defaults, vararg = [], [], None
        seen_default = False
        while not self.check(")"):
            if self.match("*"):
                vararg = self.expect_ident("variadic parameter name").value
                break
            # parameter names: IDENT, plus the names that are also legal
            # to *reference* in the body — verify (module-compatible) and
            # the soft keywords. Other keywords parse but can never be
            # referenced, so reject them with a clear message instead.
            if self.check("IDENT", "verify", *SOFT_KEYWORDS):
                p = self.next()
                pname = p.value if p.type == "IDENT" else p.type
            elif self.check(*KEYWORDS):
                bad = self.peek()
                self.error("keyword '%s' cannot be a parameter name" % bad.type,
                           bad)
            else:
                p = self.expect_ident("parameter name")
                pname = p.value
            if pname in params:
                self.error("duplicate parameter '%s'" % pname, p)
            d = None
            if self.match("="):
                self.skip_nl()
                d = self.parse_expression()
            if d is None and seen_default:
                self.error("parameter '%s' needs a default (it follows one "
                           "that has a default)" % pname, p)
            if d is not None:
                seen_default = True
            params.append(pname)
            defaults.append(d)
            if not self.match(","):
                break
        return params, defaults, vararg

    def parse_fn_decl(self, exported=False):
        t = self.expect("fn")
        name = self.expect_ident("function name")
        return self._fn_tail(t, name.value, exported)

    def _fn_tail(self, t, name, exported):
        self.expect("(", "expected '(' after function name")
        params, defaults, vararg = self.parse_params()
        self.expect(")", "expected ')' after parameters")
        self.skip_nl()
        body = self.parse_block()
        return self.node(A.FnDecl if name else A.FnLit, t,
                         name, params, defaults, vararg, body, exported)

    def parse_fn_lit(self):
        t = self.expect("fn")
        if self.check("("):
            return self._fn_lit_tail(t, None)
        # fn expression with a name is allowed but the name is ignored
        name = self.expect_ident()
        return self._fn_lit_tail(t, name.value)

    def _fn_lit_tail(self, t, name):
        self.expect("(", "expected '(' after 'fn'")
        params, defaults, vararg = self.parse_params()
        self.expect(")", "expected ')' after parameters")
        self.skip_nl()
        body = self.parse_block()
        return self.node(A.FnLit, t, params, defaults, vararg, body, None)

    def parse_if(self):
        t = self.expect("if")
        cond = self.parse_expression()
        then = self.parse_block()
        els = None
        if self.match("else"):
            if self.check("if"):
                els = [self.parse_if()]
            else:
                els = self.parse_block().stmts
                els = self.node(A.Block, t, els, ())
        return self.node(A.If, t, cond, then, els)

    def parse_for(self):
        t = self.expect("for")
        names = [self.expect_ident("loop variable").value]
        if self.match(","):
            names.append(self.expect_ident("second loop variable").value)
        self.expect("in", "expected 'in' after loop variable(s)")
        it = self.parse_expression()
        body = self.parse_block()
        return self.node(A.For, t, names, it, body)

    def parse_try(self):
        t = self.expect("try")
        tb = self.parse_block()
        catch_var, cb = None, None
        if self.match("catch"):
            if self.check("IDENT"):
                catch_var = self.next().value
            self.skip_nl()
            cb = self.parse_block()
        fb = None
        if self.match("finally"):
            fb = self.parse_block()
        if cb is None and fb is None:
            self.error("try needs a 'catch' or 'finally' block", t)
        return self.node(A.Try, t, tb, catch_var, cb, fb)

    def parse_match(self):
        t = self.expect("match")
        subject = self.parse_expression()
        self.expect("{", "expected '{' after match subject")
        arms = []
        self.skip_nl()
        while not self.check("}", "EOF"):
            pattern = self.parse_pattern()
            self.expect("=>", "expected '=>' after match pattern")
            self.skip_nl()
            if self.check("{"):
                body = self.parse_block()
            else:
                e = self.parse_expression()
                body = self.node(A.ExprStmt, e, e)
            arms.append(self.node(A.MatchArm, pattern, pattern, body))
            self.skip_nl()
        self.expect("}")
        return self.node(A.Match, t, subject, arms)

    # ---- match patterns --------------------------------------------------
    def parse_pattern(self):
        """A match arm pattern:
          - literals compare by value: 1, "s", true, null, 5s
          - a bare ident binds the subject (`_` is the wildcard)
          - [p, ...] destructures lists (...rest captures the tail)
          - {k: p, k2} destructures dicts (partial match; ...rest collects)
          - anything else is evaluated and compared (ranges, -1, "a{x}"...)
        """
        t = self.peek()
        ty = t.type
        if ty == "[":
            return self.parse_pattern_list()
        if ty == "{":
            return self.parse_pattern_dict()
        nxt = self.peek(1).type
        if ty == "IDENT" and nxt not in ("..", "..<", "."):
            self.next()
            return self.node(A.Ident, t, t.value)
        if ty in ("INT", "FLOAT", "DUR") and nxt not in ("..", "..<", "."):
            self.next()
            return self.node(A.Literal, t, t.value)
        if ty == "STRING" and isinstance(t.value, str) \
                and nxt not in ("..", "..<", "."):
            self.next()
            return self.node(A.Literal, t, t.value)
        if ty in ("true", "false", "null"):
            self.next()
            v = True if ty == "true" else False if ty == "false" else None
            return self.node(A.Literal, t, v)
        e = self.parse_expression()
        return self.node(A.PatExpr, t, e)

    def parse_pattern_list(self):
        t = self.expect("[")
        items = []
        rest = None
        while not self.check("]", "EOF"):
            if self.check("..."):
                self.next()
                if self.check("IDENT"):
                    rest = self.next().value
                else:
                    rest = ""        # ignore the tail
                break
            items.append(self.parse_pattern())
            if not self.match(","):
                break
        self.expect("]", "expected ']' after list pattern")
        return self.node(A.PatList, t, items, rest)

    def parse_pattern_dict(self):
        t = self.expect("{")
        pairs = []
        rest = None
        while not self.check("}", "EOF"):
            if self.check("..."):
                self.next()
                if self.check("IDENT"):
                    rest = self.next().value
                else:
                    rest = ""        # ignore extra keys
                break
            if self.check("IDENT"):
                kt = self.next()
                key = kt.value
            elif self.check("STRING") and isinstance(self.peek().value, str):
                kt = self.next()
                key = kt.value
            else:
                self.error("expected a key (name or string) in dict pattern")
            if self.match(":"):
                val = self.parse_pattern()
            else:
                # shorthand: {x} is {x: x}
                val = self.node(A.Ident, kt, key)
            pairs.append((key, val))
            if not self.match(","):
                break
        self.expect("}", "expected '}' after dict pattern")
        return self.node(A.PatDict, t, pairs, rest)

    def parse_on(self):
        t = self.expect("on")
        if self.check("STRING"):
            name = self.next().value
            self.skip_nl()
            handler = self.parse_handler(("event",))
            return self.node(A.OnEvent, t, name, handler)
        if self.check("IDENT") and self.peek().value in ("fail", "done"):
            if not self.in_ctx("workflow"):
                self.error("'on %s' can only be used inside a workflow block" %
                           self.peek().value)
            kind = self.next().value
            self.skip_nl()
            handler = self.parse_handler(())
            return self.node(A.HookDecl, t, kind, handler)
        self.error("expected event name (string) after 'on'")

    def parse_handler(self, implicits):
        if self.check("fn"):
            return self.parse_fn_lit()
        if self.check("{"):
            return self.parse_block(implicits)
        self.error("expected handler: a block or 'fn (...) { ... }'")

    def parse_import(self):
        t = self.expect("import")
        if self.check("STRING"):
            p = self.next().value
            node = self.node(A.Import, t, None, p, None)
        elif self.check("IDENT"):
            m = self.next().value
            node = self.node(A.Import, t, m, None, None)
        elif self.peek().type in KEYWORDS:
            # stdlib modules that collide with keywords (import verify)
            m = self.next().type
            node = self.node(A.Import, t, m, None, None)
        else:
            self.error("expected module name or path string after 'import'")
        if self.match("as"):
            node.alias = self.expect_ident("alias name").value
        return node

    def parse_export(self):
        t = self.expect("export")
        if self.check("fn"):
            return self.parse_fn_decl(exported=True)
        if self.check("let", "var"):
            n = self.parse_let()
            n.exported = True
            n.line, n.col = t.line, t.col
            return n
        names = [self.expect_ident("exported name").value]
        while self.match(","):
            self.skip_nl()
            names.append(self.expect_ident("exported name").value)
        return self.node(A.Export, t, names)

    def parse_test(self):
        t = self.expect("test")
        name = self.expect("STRING", "expected test name string").value
        timeout = None
        if self.match(","):
            kw = self.expect_ident("'timeout'")
            if kw.value != "timeout":
                self.error("only 'timeout' is allowed here, found '%s'" % kw.value, kw)
            self.expect("=", "expected '=' after 'timeout'")
            self.skip_nl()
            timeout = self.parse_expression()
        self.skip_nl()
        body = self.parse_block()
        return self.node(A.TestDecl, t, name, timeout, body)

    def parse_workflow(self):
        t = self.expect("workflow")
        name = self.expect("STRING", "expected workflow name string").value
        self.skip_nl()
        self.ctx.append("workflow")
        try:
            body = self.parse_block()
        finally:
            self.ctx.pop()
        return self.node(A.WorkflowDecl, t, name, body)

    def parse_step(self):
        t = self.expect_ident()  # 'step'
        name = self.expect("STRING", "expected step name string").value
        self.skip_nl()
        body = self.parse_block()
        retry, backoff, rollback = None, None, None
        if self.match_ident("retry"):
            n = self.expect("INT", "expected attempt count after 'retry'")
            retry = self.node(A.Literal, n, n.value)
        if self.match_ident("backoff"):
            backoff = self.parse_expression()
        if self.match_ident("rollback"):
            self.skip_nl()
            rollback = self.parse_block()
        return self.node(A.StepDecl, t, name, body, retry, backoff, rollback)

    def parse_serve(self):
        t = self.expect("serve")
        port = self.parse_expression()
        options = []
        while self.match(","):
            self.skip_nl()
            k = self.expect_ident("option name").value
            self.expect("=", "expected '=' after option '%s'" % k)
            self.skip_nl()
            options.append((k, self.parse_expression()))
        self.skip_nl()
        self.ctx.append("serve")
        try:
            router = self.parse_block()
        finally:
            self.ctx.pop()
        return self.node(A.ServeDecl, t, port, options, router)

    def parse_route(self):
        t = self.next()  # method ident
        method = t.value.upper()
        path = self.expect("STRING", "expected path string").value
        self.skip_nl()
        if self.check("fn"):
            body = self.parse_fn_lit()
        else:
            body = self.parse_block(("req", "res"))
        return self.node(A.RouteDecl, t, method, path, body)

    def parse_ws_route(self):
        t = self.expect_ident()  # 'ws'
        path = self.expect("STRING", "expected path string").value
        self.skip_nl()
        if self.check("fn"):
            body = self.parse_fn_lit()
        else:
            body = self.parse_block(("conn",))
        return self.node(A.WsDecl, t, path, body)

    # ---- assignment / expression statements -------------------------------
    def parse_assignment_or_expr(self):
        expr = self.parse_expression()
        if self.check(*ASSIGN_OPS):
            t = self.peek()
            if not isinstance(expr, (A.Ident, A.Index, A.GetAttr)):
                self.error("invalid assignment target", t)
            op = self.next().type
            self.skip_nl()
            value = self.parse_expression()
            return self.node(A.Assign, t, expr, op, value)
        return self.node(A.ExprStmt, expr, expr)

    # ---- blocks ----------------------------------------------------------
    def parse_block(self, implicits=()):
        t = self.expect("{", "expected '{'")
        stmts = self.parse_stmt_list("}")
        self.expect("}")
        return self.node(A.Block, t, stmts, tuple(implicits))

    # ---- expressions -----------------------------------------------------
    def parse_expression(self):
        return self.parse_pipe()

    def parse_pipe(self):
        left = self.parse_nullish()
        while self.match("|>"):
            self.skip_nl()
            target = self.parse_postfix()
            if isinstance(target, A.Call):
                target.args.insert(0, left)
                left = target
            else:
                left = self.node(A.Call, target, target, [left], [])
        return left

    def parse_nullish(self):
        left = self.parse_or()
        while self.match("??"):
            self.skip_nl()
            right = self.parse_or()
            left = self.node(A.Binary, self.prev, left, "??", right)
        return left

    @property
    def prev(self):
        return self.toks[max(0, self.i - 1)]

    def parse_or(self):
        left = self.parse_and()
        while self.match("or"):
            self.skip_nl()
            left = self.node(A.Binary, self.prev, left, "or", self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.match("and"):
            self.skip_nl()
            left = self.node(A.Binary, self.prev, left, "and", self.parse_not())
        return left

    def parse_not(self):
        if self.check("not"):
            t = self.next()
            return self.node(A.Unary, t, "not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_range()
        while self.check(*COMPARISONS):
            t = self.next()
            self.skip_nl()
            left = self.node(A.Binary, t, left, t.type, self.parse_range())
        return left

    def parse_range(self):
        left = self.parse_additive()
        if self.check("..", "..<"):
            t = self.next()
            self.skip_nl()
            right = self.parse_additive()
            return self.node(A.RangeLit, t, left, right, t.type == "..<")
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.check("+", "-"):
            t = self.next()
            self.skip_nl()
            left = self.node(A.Binary, t, left, t.type,
                             self.parse_multiplicative())
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.check("*", "/", "//", "%"):
            t = self.next()
            self.skip_nl()
            left = self.node(A.Binary, t, left, t.type, self.parse_unary())
        return left

    def parse_unary(self):
        if self.check("-"):
            t = self.next()
            return self.node(A.Unary, t, "-", self.parse_unary())
        if self.check("await"):
            t = self.next()
            return self.node(A.Unary, t, "await", self.parse_unary())
        return self.parse_power()

    def parse_power(self):
        base = self.parse_postfix()
        if self.check("**"):
            t = self.next()
            self.skip_nl()
            return self.node(A.Binary, t, base, "**", self.parse_unary())
        return base

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            if self.check("."):
                t = self.next()
                name = self.expect_attr_name("property or method name after '.'")
                expr = self.node(A.GetAttr, t, expr, name)
            elif self.check("("):
                args, kwargs = self.parse_args()
                expr = self.node(A.Call, self.prev, expr, args, kwargs)
            elif self.check("["):
                expr = self.parse_index_or_slice(expr)
            elif self.check("NEWLINE"):
                # leading-dot continuation on the next line
                save = self.i
                self.skip_nl()
                if self.check("."):
                    continue
                self.i = save
                break
            else:
                break
        return expr

    def parse_args(self):
        self.expect("(")
        args, kwargs = [], []
        while not self.check(")"):
            # keyword argument name: IDENT, or a keyword token (verify=,
            # on=, in= ...) — inside an argument list a keyword followed
            # by `=` can only be a kwarg name, never a statement
            if (self.check("IDENT", *KEYWORDS) and self.peek(1).type == "="
                    and self.peek(2).type != "="):
                tok = self.next()
                # keyword tokens carry their name in .type (value is None)
                name = tok.value if tok.type == "IDENT" else tok.type
                self.next()  # =
                self.skip_nl()
                kwargs.append((name, self.parse_expression()))
            else:
                if kwargs:
                    self.error("positional argument after keyword argument")
                args.append(self.parse_expression())
            if not self.match(","):
                break
        self.expect(")")
        return args, kwargs

    def parse_index_or_slice(self, obj):
        t = self.expect("[")
        start = end = step = None
        if not self.check(":"):
            start = self.parse_expression()
        if self.match(":"):
            if not self.check(":", "]"):
                end = self.parse_expression()
            if self.match(":"):
                if not self.check("]"):
                    step = self.parse_expression()
            self.expect("]")
            return self.node(A.Slice, t, obj, start, end, step)
        self.expect("]")
        if start is None:
            self.error("empty index", t)
        return self.node(A.Index, t, obj, start)

    def parse_primary(self):
        t = self.peek()
        ty = t.type
        if ty in ("INT", "FLOAT", "DUR"):
            self.next()
            if ty == "DUR":
                from .values import Duration
                return self.node(A.Literal, t, Duration(t.value))
            return self.node(A.Literal, t, t.value)
        if ty == "STRING":
            self.next()
            return self.parse_string_value(t)
        if ty == "true":
            self.next()
            return self.node(A.Literal, t, True)
        if ty == "false":
            self.next()
            return self.node(A.Literal, t, False)
        if ty == "null":
            self.next()
            return self.node(A.Literal, t, None)
        if ty == "IDENT":
            self.next()
            return self.node(A.Ident, t, t.value)
        if ty == "(":
            self.next()
            self.skip_nl()
            if self.check(")"):
                self.error("empty parentheses", t)
            e = self.parse_expression()
            self.skip_nl()
            self.expect(")")
            return e
        if ty == "[":
            return self.parse_list_lit()
        if ty == "{":
            return self.parse_dict_lit()
        if ty == "fn":
            return self.parse_fn_lit()
        if ty == "if":
            # `if` works as a statement and as an expression:
            # let grade = if score >= 90 { "A" } else { "B" }
            return self.parse_if()
        if ty == "match":
            return self.parse_match()
        if ty == "try":
            return self.parse_try()
        if ty == "verify":
            # the verify *module* in expression position: verify.eq(a, b)
            self.next()
            return self.node(A.Ident, t, "verify")
        if ty in SOFT_KEYWORDS:
            # statement-only keywords that double as ordinary names —
            # usable as params/kwargs (conn.on, wf kwargs, a test= flag)
            # because a bare keyword can never be a valid statement here
            self.next()
            return self.node(A.Ident, t, ty)
        if ty == "spawn":
            self.next()
            if self.check("{"):
                blk = self.parse_block()
                return self.node(A.Spawn, t, blk)
            if self.check("fn"):
                return self.node(A.Spawn, t, self.parse_fn_lit())
            return self.node(A.Spawn, t, self.parse_unary())
        if ty == "serve":
            # serve works as a statement and as an expression (daemon handles)
            return self.parse_serve()
        self.error("expected expression, found %s" % show(t))

    def parse_string_value(self, tok):
        v = tok.value
        if isinstance(v, str):
            n = self.node(A.Literal, tok, v)
            # remember the quote char so ox check can flag strings that
            # look like they were meant to interpolate (0.3 -> 0.4)
            n.quote = tok.quote
            return n
        parts = []
        for p in v:
            if p[0] == "lit":
                parts.append(("lit", p[1]))
            else:
                _, src, line, col = p
                sub = Lexer(" " * (col - 1) + src, self.file, line).tokenize()
                sub_parser = Parser(sub, self.file)
                expr = sub_parser.parse_expression()
                sub_parser.skip_nl()
                if not sub_parser.check("EOF"):
                    sub_parser.error("unexpected trailing tokens in interpolation")
                expr.line, expr.col = line, col
                parts.append(("expr", expr))
        return self.node(A.InterpString, tok, parts)

    def parse_list_lit(self):
        t = self.expect("[")
        items = []
        while not self.check("]"):
            self.skip_nl()
            if self.check("]"):
                break
            items.append(self.parse_expression())
            if not self.match(","):
                break
        self.skip_nl()
        self.expect("]")
        return self.node(A.ListLit, t, items)

    def parse_dict_lit(self):
        t = self.expect("{")
        pairs = []
        while True:
            self.skip_nl()
            if self.check("}"):
                break
            k = self.peek()
            if k.type == "IDENT":
                self.next()
                key = self.node(A.Literal, k, k.value)
            elif k.type in KEYWORDS:
                self.next()
                key = self.node(A.Literal, k, k.type)
            elif k.type == "STRING":
                self.next()
                key = self.node(A.Literal, k, k.value)
            elif k.type in ("INT", "FLOAT"):
                self.next()
                key = self.node(A.Literal, k, k.value)
            elif k.type == "(":
                self.next()
                key = self.parse_expression()
                self.expect(")")
            else:
                self.error("invalid dict key %s (use ident, string, number or "
                           "(expression))" % show(k))
            self.expect(":", "expected ':' after dict key")
            self.skip_nl()
            value = self.parse_expression()
            pairs.append((key, value))
            self.skip_nl()
            if not self.match(","):
                break
        self.skip_nl()
        self.expect("}")
        return self.node(A.DictLit, t, pairs)


def parse(source, file="<ox>"):
    tokens = Lexer(source, file).tokenize()
    return Parser(tokens, file).parse_program()
