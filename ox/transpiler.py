"""Transpiler: ox AST -> readable, semantically-faithful Python source.

This is the back half of `ox build`. The generated module:
  * defines every top-level `fn` as an `async def` (hoisted, like the
    interpreter does),
  * runs all other top-level statements inside `async def _ox_main()`,
  * routes every call / operator / attribute access through `ox.runtime`
    helpers so semantics match the interpreter exactly (string coercion in
    `+`, deep equality, pipe-style method dispatch, duration math, ...),
  * registers DSL blocks (workflow / serve / test / on) with runtime helpers.

The result runs on the plain python3 + the bundled `ox` runtime package.
"""
import keyword

from . import __version__
from . import ast_nodes as A
from .values import Duration

_RT_RESERVED = {"_rt", "asyncio", "_ox_main", "__name__", "__file__",
                  "self", "_ox_ret"}


def mangle(name):
    if keyword.iskeyword(name) or name in _RT_RESERVED or name.startswith("_ox"):
        return "ox_" + name
    return name


def _py_str(s):
    return repr(s)


class Transpiler:
    def __init__(self, program):
        self.program = program
        self.lines = []
        self.tmp = 0
        self.depth = 0
        # every user-defined name anywhere (over-approximation used to decide
        # between `_rt.call(name, ...)` and `_rt.call("name", ...)`);
        # module_names is the precise module-level subset, used for the
        # nonlocal/global analysis
        self.defined = set()
        self.module_names = set()
        self.fn_stack = []      # per-function sets of python-visible locals
        self._collect_names(program)
        for st in program.stmts:
            self._walk_scope_stmt(st, self.module_names, set())

    # ---- name collection ---------------------------------------------------
    def _collect_names(self, program):
        for stmt in program.stmts:
            self._collect_stmt(stmt)

    def _collect_stmt(self, s):
        t = type(s)
        if t is A.Let:
            self.defined.add(s.name)
            self._collect_expr(s.value)
        elif t is A.FnDecl:
            self.defined.add(s.name)
            for d in s.defaults:
                if d is not None:
                    self._collect_expr(d)
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.FnLit:
            for d in s.defaults:
                if d is not None:
                    self._collect_expr(d)
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t in (A.ExprStmt, A.Return, A.Throw):
            if getattr(s, "value", None) is not None:
                self._collect_expr(s.value)
            if getattr(s, "expr", None) is not None:
                self._collect_expr(s.expr)
        elif t is A.Assign:
            self._collect_expr(s.target)
            self._collect_expr(s.value)
        elif t is A.If:
            self._collect_expr(s.cond)
            for st in s.then.stmts:
                self._collect_stmt(st)
            if s.els is not None:
                for st in (s.els.stmts if isinstance(s.els, A.Block) else s.els):
                    self._collect_stmt(st)
        elif t is A.While:
            self._collect_expr(s.cond)
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.Loop:
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.For:
            for n in s.names:
                self.defined.add(n)
            self._collect_expr(s.iterable)
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.Try:
            for st in s.try_block.stmts:
                self._collect_stmt(st)
            if s.catch_var:
                self.defined.add(s.catch_var)
            if s.catch_block is not None:
                for st in s.catch_block.stmts:
                    self._collect_stmt(st)
            if s.finally_block is not None:
                for st in s.finally_block.stmts:
                    self._collect_stmt(st)
        elif t is A.Match:
            self._collect_expr(s.subject)
            for arm in s.arms:
                self._collect_expr(arm.pattern)
                self._collect_stmt(arm.body)
        elif t is A.OnEvent:
            self._collect_stmt(_as_stmt(s.handler))
        elif t is A.HookDecl:
            self._collect_stmt(_as_stmt(s.handler))
        elif t is A.Emit:
            if s.payload is not None:
                self._collect_expr(s.payload)
        elif t is A.Verify:
            self._collect_expr(s.cond)
            if s.msg is not None:
                self._collect_expr(s.msg)
        elif t is A.TestDecl:
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.WorkflowDecl:
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.StepDecl:
            for st in s.body.stmts:
                self._collect_stmt(st)
            if s.rollback is not None:
                for st in s.rollback.stmts:
                    self._collect_stmt(st)
        elif t is A.ServeDecl:
            self._collect_expr(s.port)
            for _k, v in s.options:
                self._collect_expr(v)
            for st in s.router.stmts:
                self._collect_stmt(st)
        elif t is A.RouteDecl:
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.WsDecl:
            for st in s.body.stmts:
                self._collect_stmt(st)
        elif t is A.Import:
            self.defined.add(s.alias or s.module or _stem_of(s.path))
        elif t is A.Block:
            for st in s.stmts:
                self._collect_stmt(st)

    def _collect_expr(self, e):
        if e is None:
            return
        t = type(e)
        if t is A.Ident:
            pass  # references are not definitions
        elif t in (A.Literal, A.InterpString):
            if t is A.InterpString:
                for kind, p in e.parts:
                    if kind == "expr":
                        self._collect_expr(p)
        elif t is A.ListLit:
            for x in e.items:
                self._collect_expr(x)
        elif t is A.DictLit:
            for k, v in e.pairs:
                self._collect_expr(k)
                self._collect_expr(v)
        elif t is A.RangeLit:
            self._collect_expr(e.start)
            self._collect_expr(e.end)
        elif t is A.Unary:
            self._collect_expr(e.expr)
        elif t is A.Binary:
            self._collect_expr(e.left)
            self._collect_expr(e.right)
        elif t is A.Call:
            self._collect_expr(e.callee)
            for a in e.args:
                self._collect_expr(a)
            for _k, v in e.kwargs:
                self._collect_expr(v)
        elif t is A.Index:
            self._collect_expr(e.obj)
            self._collect_expr(e.index)
        elif t is A.Slice:
            self._collect_expr(e.obj)
            for part in (e.start, e.end, e.step):
                if part is not None:
                    self._collect_expr(part)
        elif t is A.GetAttr:
            self._collect_expr(e.obj)
        elif t is A.Spawn:
            if isinstance(e.arg, A.Block):
                for st in e.arg.stmts:
                    self._collect_stmt(st)
            else:
                self._collect_expr(e.arg)
        elif t in (A.If, A.Match, A.Try):
            # expression-position if/match/try: names inside live in the
            # emitted thunk; collect them like spawn blocks
            self._collect_stmt(e)
        elif t is A.PatList:
            for p in e.items:
                self._collect_expr(p)
        elif t is A.PatDict:
            for _k, p in e.pairs:
                self._collect_expr(p)
        elif t is A.PatExpr:
            self._collect_expr(e.expr)

    # ---- emission helpers ----------------------------------------------------
    def emit(self, line, indent=None):
        pad = "    " * (self.depth if indent is None else indent)
        self.lines.append(pad + line if line else "")

    def temp(self, prefix):
        self.tmp += 1
        return "_ox_%s_%d" % (prefix, self.tmp)

    # ---- program ----------------------------------------------------------------
    def transpile(self):
        self.emit('"""Generated by ox %s from %s — do not edit."""'
                  % (__version__, self.program.file))
        self.emit("import ox.runtime as _rt")
        self.emit("")
        # module-level ox variables become real python globals so that the
        # top-level fns below can see them (they are emitted beside _ox_main,
        # not inside it); _ox_main rebinds them via `global`
        for name in sorted(self.module_names):
            self.emit("%s = None" % mangle(name))
        if self.module_names:
            self.emit("")

        main_stmts = []
        for s in self.program.stmts:
            if isinstance(s, A.FnDecl):
                self.transpile_fn_decl(s)
            elif isinstance(s, A.Import) and s.module is not None:
                name = s.alias or s.module
                self.emit("%s = _rt.get_module(%s)" % (mangle(name), _py_str(s.module)))
            elif isinstance(s, A.Import):
                name = s.alias or _stem_of(s.path)
                self.emit("%s = None" % mangle(name))
                main_stmts.append(s)
            elif isinstance(s, A.Export):
                continue  # exports only matter for interpreted modules
            else:
                main_stmts.append(s)

        self.emit("")
        self.emit("async def _ox_main():")
        self.depth += 1
        globals_needed = sorted(self.module_names)
        if globals_needed:
            self.emit("global %s" % ", ".join(mangle(n)
                                              for n in globals_needed))
        for s in main_stmts:
            if isinstance(s, A.Import):
                name = s.alias or _stem_of(s.path)
                self.emit("global %s" % mangle(name))
                self.emit("%s = await _rt.load_ox_module(%s)"
                          % (mangle(name), _py_str(s.path)))
            else:
                self.stmt(s)
        self.emit("return None")
        self.depth -= 1
        self.emit("")
        self.emit('if __name__ == "__main__":')
        self.emit("    import sys")
        self.emit("    sys.exit(_rt.run_compiled(_ox_main))")
        return "\n".join(self.lines) + "\n"

    # ---- functions -----------------------------------------------------------------
    def transpile_fn_decl(self, s):
        params = list(s.params)
        sig_parts = []
        for i, p in enumerate(params):
            name = mangle(p)
            if s.defaults[i] is not None:
                sig_parts.append("%s=%s" % (name, self.inline(s.defaults[i])))
            else:
                sig_parts.append(name)
        if s.vararg:
            sig_parts.append("*" + mangle(s.vararg))
        ox_params = list(s.params) + ([s.vararg] if s.vararg else [])
        decls = self._enter_fn(ox_params, s.body)
        self.emit("async def %s(%s):" % (mangle(s.name), ", ".join(sig_parts)))
        self.depth += 1
        for d in decls:
            self.emit(d)
        if s.vararg:
            self.emit("%s = list(%s)" % (mangle(s.vararg), mangle(s.vararg)))
        self.emit("_ox_ret = None")
        self.fn_body(s.body)
        self.emit("return _ox_ret")
        self.depth -= 1
        self._leave_fn()
        self.emit("")

    def body(self, block, implicit=()):
        """Emit block statements; implicit bindings become params of a thunk."""
        for st in block.stmts:
            self.stmt(st)

    def fn_body(self, block):
        """Function/thunk body: tracks the block's value (= value of its last
        statement), mirroring the interpreter's implicit block return.
        if/match/try contribute their branch values."""
        stmts = list(block.stmts)
        for i, st in enumerate(stmts):
            last = i == len(stmts) - 1
            t = type(st)
            if t is A.ExprStmt:
                self.emit("_ox_ret = %s" % self.inline(st.expr))
            elif t is A.If:
                self.if_stmt(st, is_elif=False, value=True, last=last)
            elif t is A.Match:
                self.match_stmt(st, value=True, last=last)
            elif t is A.Try:
                self.try_stmt(st, value=True)
            else:
                self.stmt(st)
                if last:
                    self.emit("_ox_ret = None")

    # ---- statements -------------------------------------------------------------------
    def stmt(self, s):
        t = type(s)
        if t is A.Let:
            value = self.inline(s.value)
            self.emit("%s = %s" % (mangle(s.name), value))
        elif t is A.ExprStmt:
            self.emit(self.inline(s.expr))
        elif t is A.Assign:
            self.assign(s)
        elif t is A.Return:
            if s.value is not None:
                self.emit("return %s" % self.inline(s.value))
            else:
                self.emit("return None")
        elif t is A.If:
            self.if_stmt(s, is_elif=False)
        elif t is A.While:
            self.emit("while _rt.truthy(%s):" % self.inline(s.cond))
            self.depth += 1
            self.body(s.body)
            self.depth -= 1
        elif t is A.Loop:
            self.emit("while True:")
            self.depth += 1
            self.body(s.body)
            self.depth -= 1
        elif t is A.For:
            self.for_stmt(s)
        elif t is A.Break:
            self.emit("break")
        elif t is A.Continue:
            self.emit("continue")
        elif t is A.Pass:
            self.emit("pass")
        elif t is A.Try:
            self.try_stmt(s)
        elif t is A.Throw:
            self.emit("_rt.throw(%s)" % self.inline(s.expr))
        elif t is A.Match:
            self.match_stmt(s)
        elif t is A.OnEvent:
            self.emit("_rt._on(%s, %s)" % (_py_str(s.name),
                                           self.handler_def(s.handler, ("event",))))
        elif t is A.Emit:
            payload = self.inline(s.payload) if s.payload is not None else "None"
            self.emit("await _rt._emit(%s, %s)" % (_py_str(s.name), payload))
        elif t is A.Verify:
            msg = self.inline(s.msg) if s.msg is not None else "None"
            self.emit("_rt.verify(%s, %s)" % (self.inline(s.cond), msg))
        elif t is A.TestDecl:
            timeout = self.inline(s.timeout) if s.timeout is not None else "None"
            self.emit("_rt._test(%s, %s, %s)"
                      % (_py_str(s.name), timeout, self.thunk_def(s.body, ())))
        elif t is A.WorkflowDecl:
            self.emit("await _rt._workflow(%s, %s)"
                      % (_py_str(s.name), self.router_thunk(s.body)))
        elif t is A.StepDecl:
            retry = self.inline(s.retry) if s.retry is not None else "1"
            backoff = self.inline(s.backoff) if s.backoff is not None else "0"
            rollback = self.thunk_def(s.rollback, ()) if s.rollback else "None"
            self.emit("_rt._step(%s, %s, retry=%s, backoff=%s, rollback=%s)"
                      % (_py_str(s.name), self.thunk_def(s.body, ()), retry,
                         backoff, rollback))
        elif t is A.HookDecl:
            self.emit("_rt._hook(%s, %s)" % (_py_str(s.kind),
                                             self.thunk_def(_block_of(s.handler),
                                                            ())))
        elif t is A.DescDecl:
            self.emit("_rt._desc(%s)" % _py_str(s.text))
        elif t is A.ServeDecl:
            opts = "{" + ", ".join("%s: %s" % (_py_str(k), self.inline(v))
                                   for k, v in s.options) + "}"
            self.emit("return await _rt._serve(%s, %s, %s)"
                      % (self.inline(s.port), opts or "None",
                         self.router_thunk(s.router)))
        elif t is A.RouteDecl:
            # block handlers are called as handler(req, res) by the dispatcher
            handler = (self.thunk_def(_block_of(s.body), ("req", "res"))
                       if isinstance(s.body, A.Block)
                       else self.fn_def(s.body))
            self.emit("_rt._route(%s, %s, %s)"
                      % (_py_str(s.method), _py_str(s.path), handler))
        elif t is A.StaticDecl:
            dstr = _py_str(s.dir) if isinstance(s.dir, str) else self.inline(s.dir)
            self.emit("_rt._static(%s, %s)" % (_py_str(s.prefix), dstr))
        elif t is A.WsDecl:
            handler = (self.thunk_def(_block_of(s.body), ("conn",))
                       if isinstance(s.body, A.Block)
                       else self.fn_def(s.body))
            self.emit("_rt._ws(%s, %s)" % (_py_str(s.path), handler))
        elif t is A.Import:
            # handled at program level; module-level imports inside blocks:
            if s.module is not None:
                self.emit("%s = _rt.get_module(%s)" % (mangle(s.alias or s.module),
                                                       _py_str(s.module)))
            else:
                self.emit("%s = await _rt.load_ox_module(%s)"
                          % (mangle(s.alias or _stem_of(s.path)),
                             _py_str(s.path)))
        elif t is A.Export:
            pass
        elif t is A.FnDecl:
            # nested named fn: a local async def (the interpreter defines
            # these sequentially too — only module-level fns are hoisted)
            self.transpile_fn_decl(s)
        elif t is A.Block:
            self.depth += 1
            self.body(s)
            self.depth -= 1
        else:
            raise ValueError("cannot transpile statement %s" % t.__name__)

    def assign(self, s):
        target = s.target
        value = self.inline(s.value)
        op_map = {"=": None, "+=": "add", "-=": "sub", "*=": "mul",
                  "/=": "div", "//=": "floordiv", "%=": "mod"}
        helper = op_map[s.op]
        if isinstance(target, A.Ident):
            name = mangle(target.name)
            if helper is None:
                self.emit("%s = %s" % (name, value))
            else:
                self.emit("%s = _rt.%s(%s, %s)" % (name, helper, name, value))
            return
        if isinstance(target, A.Index):
            obj = self.inline(target.obj)
            idx = self.inline(target.index)
            if helper is None:
                self.emit("%s[%s] = %s" % (obj, idx, value))
            else:
                self.emit("%s[%s] = _rt.%s(%s[%s], %s)"
                          % (obj, idx, helper, obj, idx, value))
            return
        if isinstance(target, A.GetAttr):
            obj = self.inline(target.obj)
            name = target.name
            if helper is None:
                self.emit("_rt.set_attr(%s, %s, %s)" % (obj, _py_str(name),
                                                        value))
            else:
                self.emit("_rt.set_attr(%s, %s, _rt.%s(_rt.get_attr(%s, %s), %s))"
                          % (obj, _py_str(name), helper, obj, _py_str(name),
                             value))

    def if_stmt(self, s, is_elif, value=False, last=False):
        prefix = "elif " if is_elif else "if "
        self.emit("%s_rt.truthy(%s):" % (prefix, self.inline(s.cond)))
        self.depth += 1
        if value:
            self.emit("_ox_ret = None")
        self.body(s.then) if not value else self.fn_body(s.then)
        self.depth -= 1
        has_else = s.els is not None
        if has_else:
            if isinstance(s.els, A.Block):
                self.emit("else:")
                self.depth += 1
                if value:
                    self.emit("_ox_ret = None")
                self.fn_body(s.els) if value else self.body(s.els)
                self.depth -= 1
            else:  # [If] chain
                self.if_stmt(s.els[0], is_elif=True, value=value, last=last)
        elif value and last:
            self.emit("else:")
            self.depth += 1
            self.emit("_ox_ret = None")
            self.depth -= 1

    def for_stmt(self, s):
        it = self.inline(s.iterable)
        if len(s.names) == 2:
            a, b = mangle(s.names[0]), mangle(s.names[1])
            self.emit("for %s, %s in _rt.iter_pairs(%s):" % (a, b, it))
        else:
            self.emit("for %s in %s:" % (mangle(s.names[0]), it))
        self.depth += 1
        self.body(s.body)
        self.depth -= 1

    def try_stmt(self, s, value=False):
        self.emit("try:")
        self.depth += 1
        if value:
            self.emit("_ox_ret = None")
        self.fn_body(s.try_block) if value else self.body(s.try_block)
        self.depth -= 1
        if s.catch_block is not None:
            self.emit("except _rt.OxThrow as _ox_e:")
            self.depth += 1
            if s.catch_var:
                self.emit("%s = _ox_e.value" % mangle(s.catch_var))
            if value:
                self.emit("_ox_ret = None")
            self.fn_body(s.catch_block) if value else self.body(s.catch_block)
            self.depth -= 1
            self.emit("except BaseException as _ox_e:")
            self.depth += 1
            self.emit("if isinstance(_ox_e, (_rt.OxExit, _rt.BreakSignal, "
                      "_rt.ContinueSignal, _rt.ReturnSignal, "
                      "KeyboardInterrupt, SystemExit)):")
            self.depth += 1
            self.emit("raise")
            self.depth -= 1
            if s.catch_var:
                self.emit("%s = _rt.to_error(_ox_e)" % mangle(s.catch_var))
            if value:
                self.emit("_ox_ret = None")
            self.fn_body(s.catch_block) if value else self.body(s.catch_block)
            self.depth -= 1
        if s.finally_block is not None:
            self.emit("finally:")
            self.depth += 1
            self.body(s.finally_block)
            self.depth -= 1

    def match_stmt(self, s, value=False, last=False):
        subj = self.temp("m")
        self.emit("%s = %s" % (subj, self.inline(s.subject)))
        n_open = 0
        saw_wild = False
        for arm in s.arms:
            pat = arm.pattern
            if isinstance(pat, A.Ident) and pat.name == "_":
                # wildcard: we are already inside the previous arm's else;
                # later arms are unreachable
                self._match_arm_body(arm, value)
                saw_wild = True
                break
            pre = []
            struct = self.pattern_py(pat, pre)
            for line in pre:
                self.emit(line)
            b = self.temp("b")
            self.emit("%s = _rt.match_pattern(%s, %s)" % (b, struct, subj))
            self.emit("if %s is not None:" % b)
            self.depth += 1
            for name in self._pattern_binds(pat):
                self.emit("%s = %s[%r]" % (name, b, name))
            self._match_arm_body(arm, value)
            self.depth -= 1
            self.emit("else:")
            self.depth += 1
            n_open += 1
        if n_open:
            if not saw_wild:
                if value and last:
                    self.emit("_ox_ret = None")
                else:
                    self.emit("pass")
            self.depth -= n_open

    def _match_arm_body(self, arm, value):
        if value:
            self.emit("_ox_ret = None")
        if isinstance(arm.body, A.Block):
            self.fn_body(arm.body) if value else self.body(arm.body)
        else:
            if value:
                self.emit("_ox_ret = %s" % self.inline(arm.body.expr))
            else:
                self.emit(self.inline(arm.body.expr))

    def pattern_py(self, pat, pre):
        """Pattern AST -> python source of the runtime structure.
        Expression sub-patterns are pre-evaluated into temps (appended to
        `pre`) so awaits stay at statement level."""
        t = type(pat)
        if t is A.PatList:
            inner = ", ".join(self.pattern_py(p, pre) for p in pat.items)
            if inner:
                inner += ","
            rest = mangle(pat.rest) if pat.rest and pat.rest != "" \
                else pat.rest
            return '("list", (%s), %r)' % (inner, rest)
        if t is A.PatDict:
            inner = ", ".join("(%r, %s)" % (k, self.pattern_py(p, pre))
                               for k, p in pat.pairs)
            if inner:
                inner += ","
            rest = mangle(pat.rest) if pat.rest and pat.rest != "" \
                else pat.rest
            return '("dict", (%s), %r)' % (inner, rest)
        if t is A.Ident:
            if pat.name == "_":
                return '("wild",)'
            return '("bind", %r)' % mangle(pat.name)
        if t is A.Literal:
            return '("lit", %s)' % self.inline(pat)
        # expression pattern (PatExpr wraps ranges, -1, interpolated strings)
        expr = pat.expr if t is A.PatExpr else pat
        if type(expr) is A.RangeLit:
            return '("range", %s, %s, %r)' % (self.inline(expr.start),
                                              self.inline(expr.end),
                                              bool(expr.exclusive))
        tmp = self.temp("p")
        pre.append("%s = %s" % (tmp, self.inline(expr)))
        return '("expr", %s)' % tmp

    def _pattern_binds(self, pat):
        out = []
        self._walk_binds(pat, out)
        return out

    def _walk_binds(self, pat, out):
        t = type(pat)
        if t is A.PatList:
            for p in pat.items:
                self._walk_binds(p, out)
            if pat.rest and pat.rest != "":
                out.append(mangle(pat.rest))
        elif t is A.PatDict:
            for _k, p in pat.pairs:
                self._walk_binds(p, out)
            if pat.rest and pat.rest != "":
                out.append(mangle(pat.rest))
        elif t is A.Ident and pat.name != "_":
            out.append(mangle(pat.name))

    # ---- function scopes (nonlocal/global) ---------------------------------

    def _enter_fn(self, ox_params, body):
        """Push a python function scope for a body about to be emitted.

        The interpreter's assignments walk the environment chain, so a
        nested fn assigning an outer variable updates the OUTER binding.
        Plain python would create a local instead — so for every name that
        is assigned here but created outside, emit nonlocal/global.
        Returns the declaration lines to place right after 'async def'.
        """
        created = set(ox_params or ())
        assigned = set()
        if body is not None:
            for st in body.stmts:
                self._walk_scope_stmt(st, created, assigned)
        bound = set(created)
        decls = []
        for name in sorted(assigned - created):
            for i in range(len(self.fn_stack) - 1, -1, -1):
                if name in self.fn_stack[i]:
                    decls.append("nonlocal %s" % mangle(name))
                    bound.add(name)
                    break
            else:
                if name in self.module_names:
                    decls.append("global %s" % mangle(name))
                    bound.add(name)
                # names assigned but created nowhere are analyzer errors;
                # the build stops before transpilation in that case
        self.fn_stack.append(bound)
        return decls

    def _leave_fn(self):
        self.fn_stack.pop()

    def _walk_scope_stmt(self, s, creates, assigns):
        """Collect names created/assigned in the current function scope.
        Does not cross into nested scopes (thunks, fns, handlers): those
        get their own _enter_fn when emitted."""
        t = type(s)
        if t.__name__ in _SCOPE_BOUNDARIES:
            return
        if t is A.Let:
            creates.add(s.name)
        elif t is A.Assign:
            if isinstance(s.target, A.Ident):
                assigns.add(s.target.name)
        elif t is A.Import:
            if s.module is not None:
                creates.add(s.alias or s.module)
            else:
                creates.add(s.alias or _stem_of(s.path))
        elif t is A.For:
            for n in s.names:
                creates.add(n)
            for st in s.body.stmts:
                self._walk_scope_stmt(st, creates, assigns)
        elif t is A.Try:
            if s.catch_var:
                creates.add(s.catch_var)
            for blk in (s.try_block, s.catch_block, s.finally_block):
                if blk is not None:
                    for st in blk.stmts:
                        self._walk_scope_stmt(st, creates, assigns)
        elif t is A.Match:
            for arm in s.arms:
                _pat_binds_raw(arm.pattern, creates)
                if isinstance(arm.body, A.Block):
                    for st in arm.body.stmts:
                        self._walk_scope_stmt(st, creates, assigns)
        elif t is A.If:
            for st in s.then.stmts:
                self._walk_scope_stmt(st, creates, assigns)
            if s.els is not None:
                for st in (s.els.stmts if isinstance(s.els, A.Block)
                           else s.els):
                    self._walk_scope_stmt(st, creates, assigns)
        elif t is A.While or t is A.Loop:
            if s.body is not None:
                for st in s.body.stmts:
                    self._walk_scope_stmt(st, creates, assigns)
        # ExprStmt / Return / Throw / Verify / Emit / Export / Pass / Break /
        # Continue / DescDecl / StaticDecl / pattern-only bodies: no bindings

    # ---- thunk / handler definitions (emit nested async defs) ---------------
    def router_thunk(self, block):
        name = self.temp("router")
        decls = self._enter_fn((), block)
        self.emit("async def %s():" % name)
        self.depth += 1
        for d in decls:
            self.emit(d)
        self.body(block)
        self.emit("return None")
        self.depth -= 1
        self._leave_fn()
        return name

    def thunk_def(self, block, params):
        name = self.temp("thunk")
        decls = self._enter_fn(params, block)
        self.emit("async def %s(%s):" % (name, ", ".join(params)))
        self.depth += 1
        for d in decls:
            self.emit(d)
        if block is None:
            self.emit("pass")
        else:
            self.emit("_ox_ret = None")
            self.fn_body(block)
            self.emit("return _ox_ret")
        self.depth -= 1
        self._leave_fn()
        return name

    def handler_def(self, handler, implicit):
        if isinstance(handler, A.Block):
            return self.thunk_def(handler, implicit)
        return self.fn_def(handler)

    def fn_def(self, fnlit):
        """Anonymous fn expression -> nested async def emitted before use."""
        name = self.temp("fn")
        params = [mangle(p) for p in fnlit.params]
        sig = []
        for i, p in enumerate(params):
            if fnlit.defaults[i] is not None:
                sig.append("%s=%s" % (p, self.inline(fnlit.defaults[i])))
            else:
                sig.append(p)
        if fnlit.vararg:
            sig.append("*" + mangle(fnlit.vararg))
        ox_params = list(fnlit.params) + \
            ([fnlit.vararg] if fnlit.vararg else [])
        decls = self._enter_fn(ox_params, fnlit.body)
        self.emit("async def %s(%s):" % (name, ", ".join(sig)))
        self.depth += 1
        for d in decls:
            self.emit(d)
        if fnlit.vararg:
            self.emit("%s = list(%s)" % (mangle(fnlit.vararg),
                                         mangle(fnlit.vararg)))
        self.emit("_ox_ret = None")
        self.fn_body(fnlit.body)
        self.emit("return _ox_ret")
        self.depth -= 1
        self._leave_fn()
        return name

    # ---- expressions -----------------------------------------------------------
    def inline(self, e):
        t = type(e)
        if t is A.Literal:
            v = e.value
            if isinstance(v, Duration):
                return "_rt.Duration(%r)" % float(v)
            if v is None:
                return "None"
            if v is True:
                return "True"
            if v is False:
                return "False"
            return repr(v)
        if t is A.InterpString:
            parts = []
            for kind, p in e.parts:
                parts.append('("s", %s)' % _py_str(p) if kind == "lit"
                             else '("e", %s)' % self.inline(p))
            return "_rt.interp_parts([%s])" % ", ".join(parts)
        if t is A.Ident:
            return mangle(e.name)
        if t is A.ListLit:
            return "[%s]" % ", ".join(self.inline(x) for x in e.items)
        if t is A.DictLit:
            pairs = []
            for k, v in e.pairs:
                kk = self.dict_key(k)
                pairs.append("%s: %s" % (kk, self.inline(v)))
            return "{%s}" % ", ".join(pairs)
        if t is A.RangeLit:
            return "_rt.range_lit(%s, %s, %s)" % (self.inline(e.start),
                                                   self.inline(e.end),
                                                   "True" if e.exclusive else "False")
        if t is A.Unary:
            if e.op == "await":
                return "await _rt.unwrap(%s)" % self.inline(e.expr)
            if e.op == "not":
                return "(not _rt.truthy(%s))" % self.inline(e.expr)
            if e.op == "-":
                return "_rt.neg(%s)" % self.inline(e.expr)
        if t is A.Binary:
            return self.binary(e)
        if t is A.Call:
            return self.call(e)
        if t is A.Index:
            return "%s[%s]" % (self.inline(e.obj), self.inline(e.index))
        if t is A.Slice:
            parts = ["" if e.start is None else self.inline(e.start),
                     "" if e.end is None else self.inline(e.end),
                     "" if e.step is None else self.inline(e.step)]
            return "%s[%s]" % (self.inline(e.obj), ":".join(parts))
        if t is A.GetAttr:
            return "_rt.get_attr(%s, %s)" % (self.inline(e.obj),
                                             _py_str(e.name))
        if t is A.FnLit:
            # nested async def emitted just before the statement using it
            # (inline() is evaluated before emit() appends the statement line)
            return self.fn_def(e)
        if t is A.Spawn:
            return "_rt.spawn(%s)" % self.spawn_thunk(e)
        if t is A.ServeDecl:
            # serve in expression position (let h = serve ...): same call as
            # the statement form, returning the daemon handle
            opts = "{" + ", ".join("%s: %s" % (_py_str(k), self.inline(v))
                                   for k, v in e.options) + "}"
            router = self.router_thunk(e.router)
            return "(await _rt._serve(%s, %s, %s))" % (
                self.inline(e.port), opts or "None", router)
        if t in (A.If, A.Match, A.Try):
            # if/match/try in expression position: nested async def thunk
            # carrying the block's value (matches interpreter block values)
            return "await %s()" % self.expr_thunk(e)
        raise ValueError("cannot transpile expression %s" % t.__name__)

    def expr_thunk(self, node):
        """Emit `async def _expr_N(): ...; return _ox_ret` for an
        expression-position if/match/try, and return its name."""
        name = self.temp("expr")
        wrap = A.Block([node], ())
        decls = self._enter_fn((), wrap)
        self.emit("async def %s():" % name)
        self.depth += 1
        for d in decls:
            self.emit(d)
        self.emit("_ox_ret = None")
        t = type(node)
        if t is A.If:
            self.if_stmt(node, is_elif=False, value=True, last=True)
        elif t is A.Match:
            self.match_stmt(node, value=True, last=True)
        else:
            self.try_stmt(node, value=True)
        self.emit("return _ox_ret")
        self.depth -= 1
        self._leave_fn()
        return name

    def dict_key(self, k):
        if isinstance(k, A.Literal):
            if isinstance(k.value, str):
                return _py_str(k.value)
            return repr(k.value)
        return "(%s)" % self.inline(k)

    def binary(self, e):
        op = e.op
        left = self.inline(e.left)
        right = self.inline(e.right)
        if op == "and":
            return "(%s and %s)" % (left, right)
        if op == "or":
            return "(%s or %s)" % (left, right)
        if op == "??":
            return "(%s if %s is not None else %s)" % (left, left, right)
        helpers = {"+": "add", "-": "sub", "*": "mul", "/": "div",
                   "//": "floordiv", "%": "mod", "**": "pow_",
                   "==": "eq", "!=": "ne", "<": "lt", "<=": "le",
                   ">": "gt", ">=": "ge"}
        h = helpers.get(op)
        if h is None:
            raise ValueError("unknown operator %r" % op)
        return "_rt.%s(%s, %s)" % (h, left, right)

    def call(self, e):
        args = ", ".join(self.inline(a) for a in e.args)
        # kwarg keys: user-defined functions bind by their (python-safe)
        # mangled param names; builtins and module methods bind by the
        # original ox names — e.g. net.get(url, verify=false) stays 'verify'
        if isinstance(e.callee, A.GetAttr):
            user_fn = False
        elif isinstance(e.callee, A.Ident):
            user_fn = e.callee.name in self.defined
        else:
            user_fn = True
        key = mangle if user_fn else (lambda k: k)
        kw = ", ".join("%s: %s" % (_py_str(key(k)), self.inline(v))
                       for k, v in e.kwargs)
        argstr = "[%s]" % args
        kwstr = "{%s}" % kw if kw else "{}"
        if isinstance(e.callee, A.GetAttr):
            return "await _rt.mcall(%s, %s, %s, %s)" % (
                self.inline(e.callee.obj), _py_str(e.callee.name), argstr,
                kwstr)
        if isinstance(e.callee, A.Ident):
            if e.callee.name in self.defined:
                return "await _rt.call(%s, %s, %s)" % (mangle(e.callee.name),
                                                       argstr, kwstr)
            return 'await _rt.call("%s", %s, %s)' % (e.callee.name, argstr,
                                                     kwstr)
        return "await _rt.call(%s, %s, %s)" % (self.inline(e.callee), argstr,
                                               kwstr)

    def spawn_thunk(self, e):
        if isinstance(e.arg, A.Block):
            return self.thunk_def(e.arg, ())
        if isinstance(e.arg, A.FnLit):
            return self.fn_def(e.arg)
        name = self.temp("sp")
        src = self.inline(e.arg)
        self.emit("async def %s():" % name)
        self.depth += 1
        self.emit("return %s" % src)
        self.depth -= 1
        return name


def _block_of(handler):
    if isinstance(handler, A.Block):
        return handler
    return handler.body


def _as_stmt(handler):
    if isinstance(handler, A.Block):
        return handler
    return handler


def _stem_of(path):
    import os
    stem = os.path.splitext(os.path.basename(path or "module"))[0]
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in stem) \
        or "module"


# statements whose bodies compile to separate python functions — scope
# boundaries for the nonlocal/global analysis below
_SCOPE_BOUNDARIES = ("FnDecl", "WorkflowDecl", "ServeDecl", "TestDecl",
                     "StepDecl", "RouteDecl", "WsDecl", "OnEvent",
                     "HookDecl", "Spawn")


def _pat_binds_raw(pat, out):
    """ox names bound by a match pattern (no mangling); `out` is a set."""
    t = type(pat)
    if t.__name__ == "PatList":
        for p in pat.items:
            _pat_binds_raw(p, out)
        if pat.rest and pat.rest != "":
            out.add(pat.rest)
    elif t.__name__ == "PatDict":
        for _k, p in pat.pairs:
            _pat_binds_raw(p, out)
        if pat.rest and pat.rest != "":
            out.add(pat.rest)
    elif t.__name__ == "Ident" and pat.name != "_":
        out.add(pat.name)


def transpile(program):
    return Transpiler(program).transpile()


def transpile_source(source, file="<ox>"):
    from .lexer import Lexer
    from .parser import Parser
    tokens = Lexer(source, file).tokenize()
    program = Parser(tokens, file).parse_program()
    return transpile(program)
