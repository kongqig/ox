"""Static analyzer for ox — the front half of `ox build` / `ox check`.

Scope-aware walk over the AST producing errors (severe) and warnings:
  * use of an undefined variable
  * reassignment of a `let` binding
  * `let` use before definition at module top level (fns are hoisted)
  * unused variables (names not starting with `_`)
  * unreachable statements after return/break/continue/throw
  * break/continue outside a loop; return outside a function
  * unknown builtin modules / missing import paths
  * duplicate workflow names, route paths, test names
  * double-quoted strings containing `{name}` (probably meant f"...")
  * match patterns whose binding shadows an outer variable
"""
import os
import re

from . import ast_nodes as A
from .errors import AnalyzeError, AnalyzeWarning
from .values import LIST_METHODS, DICT_METHODS, STR_METHODS, NUM_METHODS, \
    RANGE_METHODS

_METHOD_NAMES = set(LIST_METHODS) | set(DICT_METHODS) | set(STR_METHODS) \
    | set(NUM_METHODS) | set(RANGE_METHODS)

# `{name}` / `{user.id}` shapes inside a plain double-quoted string are a
# strong hint the author expected interpolation (which is now opt-in).
_SUSPECT_INTERP = re.compile(r"\{[\w.]+\}")

GLOBALS = {"print", "len", "type", "str", "repr", "int", "float", "bool",
           "range", "error", "exit", "input", "sh", "sleep", "run", "eval",
           "compile"}

BUILTIN_MODULES = {"fs", "os", "env", "log", "time", "math", "crypto",
                   "verify", "data", "json", "net", "http", "server", "wf",
                   "co", "events", "py", "c"}

SIGNALS = (A.Break, A.Continue, A.Return, A.Throw)


class Scope:
    def __init__(self, parent=None, kind="block"):
        self.parent = parent
        self.kind = kind  # "module" | "fn" | "block"
        self.names = {}   # name -> ("let"|"var"|"fn"|"param"|"import", node)
        self.used = set()

    def define(self, name, how, node):
        self.names[name] = (how, node)

    def lookup(self, name):
        s = self
        while s:
            if name in s.names:
                return s
            s = s.parent
        return None

    def kind_of(self, name):
        s = self.lookup(name)
        return s.names[name][0] if s else None


class Analyzer:
    def __init__(self, program):
        self.program = program
        self.errors = []
        self.warnings = []
        self.exported = set()
        self.workflows = {}
        self.routes = set()
        self.tests = set()
        self.loop_depth = 0
        self.fn_depth = 0
        self.expr_depth = 0  # inside an if/match/try used as an expression

    def err(self, msg, node):
        self.errors.append(AnalyzeError(msg, getattr(node, "line", None),
                                         getattr(node, "col", None),
                                         self.program.file))

    def warn(self, msg, node):
        self.warnings.append(AnalyzeWarning(msg, getattr(node, "line", None),
                                            getattr(node, "col", None),
                                            self.program.file))

    def analyze(self):
        module = Scope(kind="module")
        for name in GLOBALS:
            module.define(name, "builtin", None)
        for s in self.program.stmts:
            if isinstance(s, A.FnDecl):
                module.define(s.name, "fn", s)
        for s in self.program.stmts:
            self.stmt(s, module)
        self.report_unused(module)
        return self.errors, self.warnings

    # ---- statements -------------------------------------------------------
    def stmt(self, s, scope):
        t = type(s)
        if t is A.Let:
            if s.name != "_" and s.name in scope.names and scope.kind != "block":
                self.err("'%s' is already defined in this scope" % s.name, s)
            if s.name in scope.names and scope.kind == "block":
                self.err("'%s' is already defined in this scope" % s.name, s)
            self.expr(s.value, scope)
            scope.define(s.name, "var" if s.mutable else "let", s)
            if s.exported:
                self.exported.add(s.name)
                scope.used.add(s.name)
        elif t is A.FnDecl:
            for d in s.defaults:
                if d is not None:
                    self.expr(d, scope)
            if s.exported:
                self.exported.add(s.name)
                scope.used.add(s.name)
            fn_scope = Scope(scope, "fn")
            for p in s.params:
                fn_scope.define(p, "param", s)
            if s.vararg:
                fn_scope.define(s.vararg, "param", s)
            self.fn_depth += 1
            saved = self.expr_depth
            self.expr_depth = 0
            self.block(s.body, fn_scope)
            self.expr_depth = saved
            self.fn_depth -= 1
        elif t is A.ExprStmt:
            self.expr(s.expr, scope)
        elif t is A.Assign:
            self.expr(s.value, scope)
            self.assign_target(s, scope)
        elif t is A.Return:
            if self.expr_depth > 0:
                self.err("'return' cannot cross an if/match/try expression "
                         "(assign to a var and return that instead)", s)
            if self.fn_depth == 0:
                self.err("'return' outside of a function", s)
            if s.value is not None:
                self.expr(s.value, scope)
        elif t is A.If:
            self.expr(s.cond, scope)
            self.block(s.then, Scope(scope))
            if s.els is not None:
                for st in (s.els.stmts if isinstance(s.els, A.Block) else s.els):
                    self.stmt(st, Scope(scope))
        elif t is A.While:
            self.expr(s.cond, scope)
            self.loop_depth += 1
            self.block(s.body, Scope(scope))
            self.loop_depth -= 1
        elif t is A.Loop:
            self.loop_depth += 1
            self.block(s.body, Scope(scope))
            self.loop_depth -= 1
        elif t is A.For:
            self.expr(s.iterable, scope)
            inner = Scope(scope)
            for n in s.names:
                inner.define(n, "var", s)
            self.loop_depth += 1
            self.block(s.body, inner)
            self.loop_depth -= 1
        elif t is A.Break:
            if self.expr_depth > 0:
                self.err("'break' cannot cross an if/match/try expression "
                         "(use a statement form instead)", s)
            elif self.loop_depth == 0:
                self.err("'break' outside of a loop", s)
        elif t is A.Continue:
            if self.expr_depth > 0:
                self.err("'continue' cannot cross an if/match/try expression "
                         "(use a statement form instead)", s)
            elif self.loop_depth == 0:
                self.err("'continue' outside of a loop", s)
        elif t is A.Try:
            self.block(s.try_block, Scope(scope))
            if s.catch_block is not None:
                cscope = Scope(scope)
                if s.catch_var:
                    cscope.define(s.catch_var, "var", s)
                self.block(s.catch_block, cscope)
            if s.finally_block is not None:
                self.block(s.finally_block, Scope(scope))
        elif t is A.Throw:
            self.expr(s.expr, scope)
        elif t is A.Match:
            self.expr(s.subject, scope)
            for arm in s.arms:
                arm_scope = Scope(scope)
                for name in _pattern_binds(arm.pattern):
                    if name != "_" and not name.startswith("_"):
                        holder = scope.lookup(name)
                        # only user-defined names: shadowing a builtin
                        # (e.g. binding `type` from `{ type }`) is fine
                        if holder is not None and not (
                                holder.kind == "module"
                                and holder.names[name][0] == "builtin"):
                            self.warn(
                                "match binding '%s' shadows an outer variable — "
                                "bare identifiers in patterns BIND, they do not "
                                "compare; use a literal, a guard, or a _-prefixed "
                                "name to bind on purpose" % name,
                                arm.pattern)
                    arm_scope.define(name, "let", arm.pattern)
                self._pattern_uses(arm.pattern, scope)
                if isinstance(arm.body, A.Block):
                    self.block(arm.body, arm_scope)
                else:
                    self.expr(arm.body.expr, arm_scope)
        elif t is A.Import:
            if s.module is not None:
                if s.module not in BUILTIN_MODULES:
                    self.err("unknown module '%s'" % s.module, s)
                scope.define(s.alias or s.module, "import", s)
            else:
                base = s.path if os.path.isabs(s.path) else \
                    os.path.join(os.path.dirname(os.path.abspath(
                        self.program.file)), s.path)
                if not any(os.path.isfile(c) for c in
                           (base, base + ".ox",
                            os.path.join(base, "main.ox"),
                            os.path.join(base, "index.ox"))):
                    self.err("no module file found for '%s'" % s.path, s)
                stem = os.path.splitext(os.path.basename(s.path))[0]
                scope.define(s.alias or stem, "import", s)
        elif t is A.Export:
            for name in s.names:
                if scope.kind_of(name) is None:
                    self.err("cannot export '%s': not defined" % name, s)
                self.exported.add(name)
                scope.used.add(name)
                s2 = scope.lookup(name)
                while s2:
                    s2.used.add(name)
                    s2 = s2.parent
        elif t is A.OnEvent:
            self.handler(s.handler, scope, ("event",))
        elif t is A.Emit:
            if s.payload is not None:
                self.expr(s.payload, scope)
        elif t is A.Verify:
            self.expr(s.cond, scope)
            if s.msg is not None:
                self.expr(s.msg, scope)
        elif t is A.TestDecl:
            if s.name in self.tests:
                self.warn("duplicate test name '%s'" % s.name, s)
            self.tests.add(s.name)
            if s.timeout is not None:
                self.expr(s.timeout, scope)
            self.block(s.body, Scope(scope))
        elif t is A.WorkflowDecl:
            if s.name in self.workflows:
                self.warn("duplicate workflow '%s'" % s.name, s)
            self.workflows[s.name] = s
            inner = Scope(scope)
            self.block(s.body, inner, in_workflow=True)
        elif t is A.StepDecl:
            self.block(s.body, Scope(scope))
            if s.retry is not None:
                self.expr(s.retry, scope)
            if s.backoff is not None:
                self.expr(s.backoff, scope)
            if s.rollback is not None:
                self.block(s.rollback, Scope(scope))
        elif t is A.HookDecl:
            self.handler(s.handler, scope, ())
        elif t is A.DescDecl:
            pass
        elif t is A.ServeDecl:
            self.expr(s.port, scope)
            for _k, v in s.options:
                self.expr(v, scope)
            inner = Scope(scope)
            self.block(s.router, inner, in_serve=True)
        elif t is A.RouteDecl:
            key = (s.method, s.path)
            if key in self.routes:
                self.warn("duplicate route %s '%s'" % (s.method, s.path), s)
            self.routes.add(key)
            self.handler(s.body, scope, ("req", "res"))
        elif t is A.StaticDecl:
            if s.dir is not None and not isinstance(s.dir, str):
                self.expr(s.dir, scope)
        elif t is A.WsDecl:
            self.handler(s.body, scope, ("conn",))
        elif t is A.Block:
            self.block(s, Scope(scope))

    def handler(self, h, scope, implicits):
        if isinstance(h, A.Block):
            inner = Scope(scope)
            for n in implicits:
                inner.define(n, "param", h)
            self.fn_depth += 1
            saved = self.expr_depth
            self.expr_depth = 0
            self.block(h, inner)
            self.expr_depth = saved
            self.fn_depth -= 1
        else:  # FnLit
            fn_scope = Scope(scope, "fn")
            for p in h.params:
                fn_scope.define(p, "param", h)
            if h.vararg:
                fn_scope.define(h.vararg, "param", h)
            self.fn_depth += 1
            saved = self.expr_depth
            self.expr_depth = 0
            self.block(h.body, fn_scope)
            self.expr_depth = saved
            self.fn_depth -= 1

    def assign_target(self, s, scope):
        target = s.target
        if isinstance(target, A.Ident):
            name = target.name
            kind = scope.kind_of(name)
            if kind is None:
                self.err("undefined variable '%s'" % name, s)
            elif kind == "let":
                self.err("cannot reassign '%s' — declared with 'let'; use "
                         "'var' to rebind" % name, s)
            scope.used.add(name)
        elif isinstance(target, A.Index):
            self.expr(target.obj, scope)
            self.expr(target.index, scope)
        elif isinstance(target, A.GetAttr):
            self.expr(target.obj, scope)

    def block(self, block, scope, in_workflow=False, in_serve=False):
        # contextual keyword misuse is a parse-time concern; here we only
        # check unreachable code and recurse
        stmts = block.stmts
        for i, s in enumerate(stmts):
            if in_workflow and isinstance(s, (A.StepDecl, A.HookDecl, A.DescDecl)):
                self.stmt(s, scope)
                continue
            if in_serve and isinstance(s, (A.RouteDecl, A.StaticDecl, A.WsDecl)):
                self.stmt(s, scope)
                continue
            if isinstance(s, (A.StepDecl, A.HookDecl, A.DescDecl)):
                self.err("'%s' can only be used inside a workflow block"
                         % type(s).__name__.replace("Decl", "").lower(), s)
                continue
            if isinstance(s, (A.RouteDecl, A.StaticDecl, A.WsDecl)):
                self.err("route declarations can only be used inside a serve "
                         "block", s)
                continue
            self.stmt(s, scope)
            if isinstance(s, SIGNALS) and i + 1 < len(stmts):
                self.warn("unreachable code after '%s'"
                          % type(s).__name__.lower(), stmts[i + 1])

    def report_unused(self, module):
        def walk(scope):
            for name, (kind, node) in scope.names.items():
                if name.startswith("_") or kind in ("builtin", "import"):
                    continue
                if name in self.exported:
                    continue
                if name not in scope.used and name not in self._touched:
                    self.warn("unused variable '%s'" % name, node)
        walk(module)

    # ---- expressions --------------------------------------------------------
    def _pattern_uses(self, pat, scope):
        """Visit expression sub-patterns (uses); bind idents are not uses."""
        t = type(pat)
        if t is A.PatList:
            for p in pat.items:
                self._pattern_uses(p, scope)
        elif t is A.PatDict:
            for _k, p in pat.pairs:
                self._pattern_uses(p, scope)
        elif t is A.PatExpr:
            self.expr(pat.expr, scope)
        elif t not in (A.Ident, A.Literal):
            # legacy expression node used as a pattern (range, unary, call)
            self.expr(pat, scope)

    def expr(self, e, scope):
        if e is None:
            return
        t = type(e)
        if t is A.Literal:
            # migration guard: plain "...{name}..." almost certainly wanted
            # interpolation, which requires the f prefix since 0.4
            if isinstance(e.value, str) \
                    and getattr(e, "quote", None) == '"' \
                    and _SUSPECT_INTERP.search(e.value):
                self.warn('string contains {name}-like text — if it should '
                          'interpolate, use f"..." (or single quotes for '
                          'literal text)', e)
        elif t is A.Ident:
            name = e.name
            if name == "_":
                return  # wildcard / discard
            if scope.lookup(name) is None and name not in GLOBALS:
                if name not in _METHOD_NAMES:
                    self.err("undefined variable '%s'" % name, e)
            else:
                scope.used.add(name)
            # mark used in all scopes where defined
                s = scope.lookup(name)
                while s:
                    s.used.add(name)
                    s = s.parent
        elif t is A.InterpString:
            for kind, p in e.parts:
                if kind == "expr":
                    self.expr(p, scope)
        elif t is A.ListLit:
            for x in e.items:
                self.expr(x, scope)
        elif t is A.DictLit:
            for k, v in e.pairs:
                self.expr(k, scope)
                self.expr(v, scope)
        elif t is A.RangeLit:
            self.expr(e.start, scope)
            self.expr(e.end, scope)
        elif t is A.Unary:
            self.expr(e.expr, scope)
        elif t is A.Binary:
            self.expr(e.left, scope)
            self.expr(e.right, scope)
        elif t is A.Call:
            if isinstance(e.callee, A.Ident) and \
                    scope.lookup(e.callee.name) is None and \
                    e.callee.name not in GLOBALS:
                pass  # pipe-style method dispatch (sort(xs)) is allowed
            else:
                self.expr(e.callee, scope)
            for a in e.args:
                self.expr(a, scope)
            for _k, v in e.kwargs:
                self.expr(v, scope)
        elif t is A.Index:
            self.expr(e.obj, scope)
            self.expr(e.index, scope)
        elif t is A.Slice:
            self.expr(e.obj, scope)
            for part in (e.start, e.end, e.step):
                if part is not None:
                    self.expr(part, scope)
        elif t is A.GetAttr:
            self.expr(e.obj, scope)
            # module member access is always fine; dict keys are dynamic
        elif t is A.FnLit:
            self.handler(e, scope, ())
        elif t is A.Spawn:
            if isinstance(e.arg, A.Block):
                self.block(e.arg, Scope(scope))
            else:
                self.expr(e.arg, scope)
        elif t in (A.If, A.Match, A.Try):
            # if/match/try in expression position: analyze their bodies too
            self.expr_depth += 1
            try:
                self.stmt(e, scope)
            finally:
                self.expr_depth -= 1

    @property
    def _touched(self):
        return set()


def _pattern_binds(pat):
    """Names bound by a match pattern (idents in binding position)."""
    t = type(pat)
    if t is A.PatList:
        out = []
        for p in pat.items:
            out.extend(_pattern_binds(p))
        if pat.rest and pat.rest != "":
            out.append(pat.rest)
        return out
    if t is A.PatDict:
        out = []
        for _k, p in pat.pairs:
            out.extend(_pattern_binds(p))
        if pat.rest and pat.rest != "":
            out.append(pat.rest)
        return out
    if t is A.Ident:
        return [] if pat.name == "_" else [pat.name]
    return []


def analyze(program):
    return Analyzer(program).analyze()
