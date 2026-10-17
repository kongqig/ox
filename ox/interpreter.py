"""The ox interpreter: an async tree-walking evaluator.

Every eval/exec is a coroutine, which is what makes `spawn` / `await` /
async servers and clients feel native instead of bolted on.

The interpreter also owns:
  * module loading & caching (import "./util.ox" as util)
  * the event bus (on "name" ... / emit "name" ...)
  * registration collectors for workflow/serve/test DSL blocks
  * the call stack used for ox-level tracebacks
"""
import asyncio
import inspect
import os

from . import ast_nodes as A
from . import runtime
from .environment import Env
from .errors import (OxExit, OxThrow, BreakSignal, ContinueSignal, ReturnSignal)
from .values import (NO_DEFAULT, BoundMethod, BuiltinFunction, NativeModule,
                     OxErrorValue, OxFunction, OxModule, Range, call_method,
                     call_value, get_attr_value, getitem, method_table, ox_add,
                     ox_cmp, ox_div, ox_eq, ox_floordiv, ox_mod, ox_mul, ox_neg,
                     ox_pow, ox_repr, ox_str, ox_sub, set_attr_value, setitem,
                     to_ox_error, truthy, type_name, Duration)

MAX_DEPTH = 900
SKIP_DIRS = {".git", ".ox", "node_modules", "__pycache__", "build", ".venv"}


class RegisteredTest:
    __slots__ = ("name", "timeout", "body", "env")

    def __init__(self, name, timeout, body, env):
        self.name = name
        self.timeout = timeout
        self.body = body
        self.env = env


class Interpreter:
    def __init__(self, file="<ox>", globals_env=None, argv=None):
        from .builtins import make_globals, MODULES  # deferred: avoids cycles
        self.file = file
        self.globals = globals_env or Env(name="globals")
        if globals_env is None:
            for name, val in make_globals().items():
                self.globals.define(name, val, mutable=True)
        self.native_modules = MODULES
        self.argv = argv or []
        self.module_cache = {}
        self.file_stack = [file]
        self.call_stack = []   # frames: [name, file, line, col]
        self.depth = 0
        self.collectors = []   # workflow body collectors
        self.route_collectors = []  # serve router collectors
        self.export_stack = []  # per-module export name sets
        self.events = {}       # name -> list of (handler_node, env) | callables
        self.tests = []        # RegisteredTest
        self.py_tests = []     # tests registered from compiled code
        self.workflows = {}    # name -> taskmod.Workflow
        self.sources = {}      # file -> source text (for pretty errors)

        self._stmt = {
            A.Let: self.exec_let, A.FnDecl: self.exec_fn_decl,
            A.Return: self.exec_return, A.If: self.exec_if,
            A.While: self.exec_while, A.Loop: self.exec_loop,
            A.For: self.exec_for, A.Break: self.exec_break,
            A.Continue: self.exec_continue, A.Pass: self.exec_pass,
            A.Try: self.exec_try, A.Throw: self.exec_throw,
            A.Match: self.exec_match, A.Import: self.exec_import,
            A.Export: self.exec_export, A.OnEvent: self.exec_on_event,
            A.HookDecl: self.exec_hook_decl, A.Emit: self.exec_emit,
            A.Verify: self.exec_verify, A.TestDecl: self.exec_test_decl,
            A.WorkflowDecl: self.exec_workflow_decl, A.StepDecl: self.exec_step_decl,
            A.DescDecl: self.exec_desc_decl, A.ServeDecl: self.exec_serve_decl,
            A.RouteDecl: self.exec_route_decl, A.StaticDecl: self.exec_static_decl,
            A.WsDecl: self.exec_ws_decl, A.ExprStmt: self.exec_expr_stmt,
            A.Assign: self.exec_assign,
        }
        self._eval = {
            A.Literal: self.eval_literal, A.InterpString: self.eval_interp_string,
            A.Ident: self.eval_ident, A.ListLit: self.eval_list_lit,
            A.DictLit: self.eval_dict_lit, A.RangeLit: self.eval_range_lit,
            A.Unary: self.eval_unary, A.Binary: self.eval_binary,
            A.Call: self.eval_call, A.Index: self.eval_index,
            A.Slice: self.eval_slice, A.GetAttr: self.eval_get_attr,
            A.FnLit: self.eval_fn_lit, A.Spawn: self.eval_spawn,
            A.ServeDecl: self.eval_serve_expr,
            # if/match/try are expressions too (let x = if c { a } else { b })
            A.If: self.exec_if, A.Match: self.exec_match, A.Try: self.exec_try,
        }

    # ---- context --------------------------------------------------------
    @property
    def current_file(self):
        return self.file_stack[-1] if self.file_stack else "<ox>"

    @property
    def current_dir(self):
        f = self.current_file
        if f and f != "<ox>" and os.path.exists(f):
            return os.path.dirname(os.path.abspath(f))
        return os.getcwd()

    def rt_error(self, msg, node=None, kind="error"):
        pos = None
        if node is not None and getattr(node, "line", None):
            pos = (self.current_file, node.line, node.col)
        return OxThrow(OxErrorValue(msg, kind=kind, pos=pos,
                                    trace=list(self.call_stack)))

    def make_function(self, node, env, name=None):
        # fn literals evaluate defaults lazily per closure creation
        # (eval_fn_lit); decls go through exec_fn_decl. Defaults here are
        # AST nodes — no longer used as values anywhere.
        raise RuntimeError("make_function is unused; use eval_fn_lit")

    async def _eval_defaults(self, node_defaults, env):
        """Evaluate a param-default list once, keeping NO_DEFAULT for
        'no default' so that a default of null stays distinguishable."""
        out = []
        for d in node_defaults:
            out.append(NO_DEFAULT if d is None else await self.eval(d, env))
        return out

    # ---- program / module execution --------------------------------------
    async def run_program(self, program, env=None):
        env = env or self.globals
        self.sources.setdefault(program.file, None)
        self.file_stack.append(program.file)
        self._hoist(program.stmts, env)
        try:
            for stmt in program.stmts:
                await self.exec_stmt(stmt, env)
        finally:
            self.file_stack.pop()

    def _hoist(self, stmts, env):
        """Top-level fn declarations are visible before their definition.
        (Defaults are unevaluated here; they are evaluated at the fn decl's
        sequential position by exec_fn_decl.)"""
        for s in stmts:
            if isinstance(s, A.FnDecl) and not env.has_here(s.name):
                env.define(s.name, OxFunction(s.name, s.params,
                                              [None] * len(s.params),
                                              s.vararg, s.body, env))
            if isinstance(s, A.Export) or getattr(s, "exported", False):
                if self.export_stack:
                    if isinstance(s, A.Export):
                        self.export_stack[-1].update(s.names)
                    else:
                        self.export_stack[-1].add(s.name)

    async def exec_stmt(self, stmt, env):
        method = self._stmt.get(type(stmt))
        if method is None:
            raise self.rt_error("cannot execute %s" % type(stmt).__name__, stmt)
        try:
            return await method(stmt, env)
        except (OxThrow, OxExit, BreakSignal, ContinueSignal, ReturnSignal,
                asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except RecursionError:
            raise self.rt_error("stack overflow: recursion too deep", stmt)
        except TypeError as e:
            raise self.rt_error("type error: %s" % e, stmt)
        except ValueError as e:
            raise self.rt_error("value error: %s" % e, stmt)
        except KeyError as e:
            raise self.rt_error(str(e.args[0]) if e.args else "key error", stmt)
        except (OSError, IndexError, ZeroDivisionError, ArithmeticError) as e:
            raise self.rt_error(to_ox_error(e).msg, stmt)
        except Exception as e:
            raise self.rt_error(to_ox_error(e).msg, stmt)

    async def exec_block(self, block, env, bindings=None):
        if bindings:
            env = Env(env, "block")
            for k, v in bindings.items():
                env.define(k, v, mutable=True)
        result = None
        for stmt in block.stmts:
            result = await self.exec_stmt(stmt, env)
        return result

    # ---- statements -------------------------------------------------------
    async def exec_let(self, stmt, env):
        value = await self.eval(stmt.value, env)
        name = stmt.name
        if name != "_" and env.has_here(name):
            raise self.rt_error("'%s' is already defined in this scope "
                                "(use a different name, or `var` to rebind)"
                                % name, stmt)
        env.define(name, value, mutable=stmt.mutable)
        if stmt.exported and self.export_stack:
            self.export_stack[-1].add(name)
        return None

    async def exec_fn_decl(self, stmt, env):
        defaults = await self._eval_defaults(stmt.defaults, env)
        fn = OxFunction(stmt.name, stmt.params, defaults,
                        stmt.vararg, stmt.body, env)
        env.define(stmt.name, fn)
        if stmt.exported and self.export_stack:
            self.export_stack[-1].add(stmt.name)
        return None

    async def exec_return(self, stmt, env):
        value = await self.eval(stmt.value, env) if stmt.value is not None else None
        raise ReturnSignal(value)

    async def exec_if(self, stmt, env):
        if truthy(await self.eval(stmt.cond, env)):
            return await self.exec_block(stmt.then, Env(env, "if"))
        if stmt.els is not None:
            if isinstance(stmt.els, A.Block):
                return await self.exec_block(stmt.els, Env(env, "else"))
            for s in stmt.els:  # else-if chain
                return await self.exec_stmt(s, env)
        return None

    async def exec_while(self, stmt, env):
        while truthy(await self.eval(stmt.cond, env)):
            try:
                await self.exec_block(stmt.body, Env(env, "while"))
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return None

    async def exec_loop(self, stmt, env):
        while True:
            try:
                await self.exec_block(stmt.body, Env(env, "loop"))
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return None

    async def exec_for(self, stmt, env):
        seq = await self.eval(stmt.iterable, env)
        two = len(stmt.names) == 2
        pairs = self._iter_pairs(seq, stmt, two)
        for item in pairs:
            ienv = Env(env, "for")
            if two:
                k, v = item
                ienv.define(stmt.names[0], k, mutable=True)
                ienv.define(stmt.names[1], v, mutable=True)
            else:
                ienv.define(stmt.names[0], item, mutable=True)
            try:
                await self.exec_block(stmt.body, ienv)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return None

    def _iter_pairs(self, seq, stmt, two):
        if isinstance(seq, Range):
            items = list(seq)
        elif isinstance(seq, list):
            items = list(seq)
        elif isinstance(seq, str):
            items = list(seq)
        elif isinstance(seq, dict):
            if two:
                return [[k, v] for k, v in seq.items()]
            return list(seq.keys())
        else:
            raise self.rt_error("cannot iterate %s%s" % (
                type_name(seq),
                " (use a range like 0..n)" if isinstance(seq, (int, float)) else ""),
                stmt)
        if two:
            out = []
            for x in items:
                if isinstance(x, list) and len(x) == 2:
                    out.append(x)
                else:
                    raise self.rt_error(
                        "cannot unpack %s into two loop variables" % type_name(x),
                        stmt)
            return out
        return items

    async def exec_break(self, stmt, env):
        raise BreakSignal((self.current_file, stmt.line, stmt.col))

    async def exec_continue(self, stmt, env):
        raise ContinueSignal((self.current_file, stmt.line, stmt.col))

    async def exec_pass(self, stmt, env):
        return None

    async def exec_try(self, stmt, env):
        try:
            return await self.exec_block(stmt.try_block, Env(env, "try"))
        except OxThrow as t:
            if stmt.catch_block is None:
                raise
            cenv = Env(env, "catch")
            if stmt.catch_var:
                cenv.define(stmt.catch_var, t.value, mutable=True)
            return await self.exec_block(stmt.catch_block, cenv)
        except Exception as e:
            if stmt.catch_block is None:
                raise
            if isinstance(e, (OxExit, BreakSignal, ContinueSignal, ReturnSignal)):
                raise
            err = to_ox_error(e)
            if err.pos is None and getattr(stmt, "line", None):
                err.pos = (self.current_file, stmt.line, stmt.col)
            cenv = Env(env, "catch")
            if stmt.catch_var:
                cenv.define(stmt.catch_var, err, mutable=True)
            return await self.exec_block(stmt.catch_block, cenv)
        finally:
            if stmt.finally_block is not None:
                await self.exec_block(stmt.finally_block, Env(env, "finally"))

    async def exec_throw(self, stmt, env):
        v = await self.eval(stmt.expr, env)
        if isinstance(v, OxErrorValue):
            if v.pos is None and getattr(stmt, "line", None):
                v.pos = (self.current_file, stmt.line, stmt.col)
                v.trace = list(self.call_stack)
            raise OxThrow(v)
        if isinstance(v, str):
            raise self.rt_error(v, stmt)
        raise self.rt_error("throw expects an error or string, got %s" % type_name(v),
                            stmt)

    async def exec_match(self, stmt, env):
        subject = await self.eval(stmt.subject, env)
        for arm in stmt.arms:
            pat = await self._pattern_structure(arm.pattern, env)
            bindings = runtime.match_pattern(pat, subject)
            if bindings is not None:
                arm_env = Env(env, "match")
                for name, value in bindings.items():
                    arm_env.define(name, value)
                if isinstance(arm.body, A.Block):
                    return await self.exec_block(arm.body, arm_env)
                return await self.eval(arm.body.expr, arm_env)
        return None

    async def _pattern_structure(self, pat, env):
        """Compile an AST pattern into the runtime structure (see
        runtime.match_pattern). PatExpr nodes are evaluated up front."""
        t = type(pat)
        if t is A.PatList:
            items = []
            for p in pat.items:
                items.append(await self._pattern_structure(p, env))
            return ("list", tuple(items), pat.rest)
        if t is A.PatDict:
            pairs = []
            for k, p in pat.pairs:
                pairs.append((k, await self._pattern_structure(p, env)))
            return ("dict", tuple(pairs), pat.rest)
        if t is A.Ident:
            return ("wild",) if pat.name == "_" else ("bind", pat.name)
        if t is A.Literal:
            return ("lit", pat.value)
        # expression patterns (PatExpr wraps ranges, -1, interpolated strings)
        expr = pat.expr if t is A.PatExpr else pat
        if type(expr) is A.RangeLit:
            lo = await self.eval(expr.start, env)
            hi = await self.eval(expr.end, env)
            return ("range", lo, hi, expr.exclusive)
        pv = await self.eval(expr, env)
        return ("expr", pv)

    async def exec_import(self, stmt, env):
        if stmt.module is not None:
            name = stmt.module
            if name in self.native_modules:
                env.define(stmt.alias or name, self.native_modules[name])
                return None
            for cand in (name + ".ox", name,
                         os.path.join(name, "main.ox"),
                         os.path.join(name, "index.ox")):
                p = os.path.join(self.current_dir, cand)
                if os.path.isfile(p):
                    mod = await self.load_ox_module(p)
                    env.define(stmt.alias or name, mod)
                    return None
            raise self.rt_error("no module named '%s' (not a builtin module and "
                                "no ./%s.ox found)" % (name, name), stmt)
        path = stmt.path
        base = path if os.path.isabs(path) else os.path.join(self.current_dir, path)
        for cand in (base, base + ".ox",
                     os.path.join(base, "main.ox"),
                     os.path.join(base, "index.ox")):
            if os.path.isfile(cand):
                mod = await self.load_ox_module(cand)
                if stmt.alias is None:
                    stem = os.path.splitext(os.path.basename(cand))[0]
                    stem = "".join(ch if (ch.isalnum() or ch == "_") else "_"
                                   for ch in stem) or "module"
                    env.define(stem, mod)
                else:
                    env.define(stmt.alias, mod)
                return None
        raise self.rt_error("no module file found for '%s'" % path, stmt)

    async def load_ox_module(self, path):
        ap = os.path.abspath(path)
        if ap in self.module_cache:
            return self.module_cache[ap]
        from .lexer import Lexer
        from .parser import Parser
        try:
            src = open(ap, encoding="utf-8").read()
        except OSError as e:
            raise self.rt_error("cannot read module '%s': %s" % (path, e))
        self.sources[ap] = src
        tokens = Lexer(src, ap).tokenize()
        program = Parser(tokens, ap).parse_program()
        mod_env = Env(self.globals, name=os.path.basename(ap))
        placeholder = OxModule(os.path.basename(ap), {}, ap)
        self.module_cache[ap] = placeholder  # cycle guard
        self.export_stack.append(set())
        self.file_stack.append(ap)
        try:
            self._hoist(program.stmts, mod_env)
            for s in program.stmts:
                await self.exec_stmt(s, mod_env)
        finally:
            self.file_stack.pop()
            exports = self.export_stack.pop()
        if exports:
            missing = [n for n in exports if not mod_env.has_here(n)]
            if missing:
                raise self.rt_error("module '%s' exports undefined name(s): %s"
                                    % (path, ", ".join(missing)))
            members = {n: mod_env.get(n) for n in exports}
        else:
            members = {k: v for k, v in mod_env.values.items()
                       if not k.startswith("_")}
        module = OxModule(os.path.splitext(os.path.basename(ap))[0], members, ap)
        self.module_cache[ap] = module
        return module

    async def exec_export(self, stmt, env):
        if self.export_stack:
            for name in stmt.names:
                if not env.has_here(name):
                    raise self.rt_error("cannot export '%s': not defined here" % name,
                                        stmt)
            self.export_stack[-1].update(stmt.names)
        return None

    async def exec_on_event(self, stmt, env):
        handler = stmt.handler
        interp = self

        async def thunk(payload):
            if isinstance(handler, A.FnLit):
                fn = OxFunction("<event>", handler.params,
                                await interp._eval_defaults(handler.defaults,
                                                            env),
                                handler.vararg, handler.body, env)
                return await call_value(interp, fn, [payload], {})
            return await interp.exec_block(handler, env, {"event": payload})

        self.events.setdefault(stmt.name, []).append(thunk)
        return None

    async def exec_hook_decl(self, stmt, env):
        if not self.collectors:
            raise self.rt_error("'on %s' can only be used inside a workflow block"
                                % stmt.kind, stmt)
        handler = stmt.handler
        interp = self

        async def thunk():
            if isinstance(handler, A.FnLit):
                fn = OxFunction("<hook>", handler.params,
                                await interp._eval_defaults(handler.defaults,
                                                            env),
                                handler.vararg, handler.body, env)
                return await call_value(interp, fn, [], {})
            return await interp.exec_block(handler, env)

        self.collectors[-1].append(("hook", stmt.kind, thunk))
        return None

    async def exec_emit(self, stmt, env):
        payload = await self.eval(stmt.payload, env) if stmt.payload is not None else None
        await self.emit_event(stmt.name, payload)
        return None

    async def emit_event(self, name, payload):
        from .builtins import logmod
        from .values import call_value as _cv
        for entry in list(self.events.get(name, [])):
            try:
                if callable(entry):
                    result = entry(payload)
                    if inspect.isawaitable(result):
                        await result
                else:
                    handler, henv = entry
                    if isinstance(handler, A.FnLit):
                        fn = OxFunction("<event:%s>" % name, handler.params,
                                        await self._eval_defaults(
                                            handler.defaults, henv),
                                        handler.vararg, handler.body, henv)
                        await _cv(self, fn, [payload], {})
                    else:
                        await self.exec_block(handler, henv, {"event": payload})
            except (OxThrow, Exception) as e:  # noqa: BLE001 — handlers isolated
                err = to_ox_error(e)
                logmod.log_error("event handler for '%s' failed: %s" % (name,
                                                                        err.msg))

    async def exec_verify(self, stmt, env):
        cond = await self.eval(stmt.cond, env)
        if not truthy(cond):
            msg = None
            if stmt.msg is not None:
                msg = await self.eval(stmt.msg, env)
            raise self.rt_error(msg if msg else "verification failed", stmt,
                                kind="verify")
        return None

    async def exec_test_decl(self, stmt, env):
        timeout = None
        if stmt.timeout is not None:
            timeout = await self.eval(stmt.timeout, env)
        self.tests.append(RegisteredTest(stmt.name, timeout, stmt.body, env))
        return None

    async def exec_workflow_decl(self, stmt, env):
        from .builtins import taskmod
        await taskmod.define_workflow(self, stmt, env)
        return None

    async def exec_step_decl(self, stmt, env):
        if not self.collectors:
            raise self.rt_error("'step' can only be used inside a workflow block",
                                stmt)
        retry = 1
        if stmt.retry is not None:
            retry = await self.eval(stmt.retry, env)
        backoff = 0
        if stmt.backoff is not None:
            backoff = await self.eval(stmt.backoff, env)
        interp = self
        body = stmt.body

        async def body_thunk():
            return await interp.exec_block(body, Env(env))

        rollback_thunk = None
        if stmt.rollback is not None:
            rb = stmt.rollback

            async def rollback_thunk():  # noqa: F811
                return await interp.exec_block(rb, Env(env))

        self.collectors[-1].append(
            ("step", {"name": stmt.name, "body": body_thunk,
                      "retry": int(retry), "backoff": float(backoff),
                      "rollback": rollback_thunk}))
        return None

    async def exec_desc_decl(self, stmt, env):
        if not self.collectors:
            raise self.rt_error("'desc' can only be used inside a workflow block",
                                stmt)
        self.collectors[-1].append(("desc", stmt.text))
        return None

    async def exec_serve_decl(self, stmt, env):
        from .builtins import servermod
        port = await self.eval(stmt.port, env)
        options = {}
        for k, vexpr in stmt.options:
            options[k] = await self.eval(vexpr, env)
        await servermod.serve(self, port, options, stmt.router, env)
        return None

    async def exec_route_decl(self, stmt, env):
        if not self.route_collectors:
            raise self.rt_error("route declarations can only be used inside a "
                                "serve block", stmt)
        body = stmt.body
        interp = self

        async def handler(req, res):
            if isinstance(body, A.FnLit):
                fn = OxFunction("<{method} {path}>".format(method=stmt.method,
                                                            path=stmt.path),
                                body.params,
                                await interp._eval_defaults(body.defaults, env),
                                body.vararg, body.body, env)
                return await call_value(interp, fn, [req, res], {})
            return await interp.exec_block(body, env, {"req": req, "res": res})

        self.route_collectors[-1].append(("route", stmt.method, stmt.path,
                                          handler))
        return None

    async def exec_static_decl(self, stmt, env):
        if not self.route_collectors:
            raise self.rt_error("'static' can only be used inside a serve block",
                                stmt)
        from . import ast_nodes as _A
        d = stmt.dir
        if not isinstance(d, str):
            d = await self.eval(d, env)
        self.route_collectors[-1].append(("static", stmt.prefix, d))
        return None

    async def exec_ws_decl(self, stmt, env):
        if not self.route_collectors:
            raise self.rt_error("'ws' can only be used inside a serve block", stmt)
        body = stmt.body
        interp = self

        async def handler(conn):
            if isinstance(body, A.FnLit):
                fn = OxFunction("<ws {path}>".format(path=stmt.path), body.params,
                                await interp._eval_defaults(body.defaults, env),
                                body.vararg, body.body, env)
                return await call_value(interp, fn, [conn], {})
            return await interp.exec_block(body, env, {"conn": conn})

        self.route_collectors[-1].append(("ws", stmt.path, handler))
        return None

    async def exec_expr_stmt(self, stmt, env):
        return await self.eval(stmt.expr, env)

    async def exec_assign(self, stmt, env):
        target = stmt.target
        if stmt.op == "=":
            value = await self.eval(stmt.value, env)
        else:
            current = await self.eval(target, env)
            rhs = await self.eval(stmt.value, env)
            try:
                value = self._compound(stmt.op, current, rhs)
            except TypeError as e:
                raise self.rt_error(str(e), stmt)
        if isinstance(target, A.Ident):
            name = target.name
            if not env.assign(name, value):
                raise self.rt_error("undefined variable '%s'" % name, stmt)
            if not env.is_mutable(name):
                raise self.rt_error(
                    "cannot reassign '%s' — declared with 'let'. Use 'var' to "
                    "declare a rebindable name" % name, stmt)
            return None
        if isinstance(target, A.Index):
            obj = await self.eval(target.obj, env)
            idx = await self.eval(target.index, env)
            try:
                setitem(obj, idx, value)
            except (TypeError, IndexError, KeyError) as e:
                raise self.rt_error(str(e.args[0]) if isinstance(e, KeyError)
                                    else str(e), stmt)
            return None
        if isinstance(target, A.GetAttr):
            obj = await self.eval(target.obj, env)
            try:
                set_attr_value(obj, target.name, value)
            except (KeyError, TypeError) as e:
                raise self.rt_error(str(e.args[0]) if isinstance(e, KeyError)
                                    else str(e), stmt)
            return None
        raise self.rt_error("invalid assignment target", stmt)

    def _compound(self, op, current, rhs):
        if op == "+=":
            return ox_add(current, rhs)
        if op == "-=":
            return ox_sub(current, rhs)
        if op == "*=":
            return ox_mul(current, rhs)
        if op == "/=":
            return ox_div(current, rhs)
        if op == "//=":
            return ox_floordiv(current, rhs)
        if op == "%=":
            return ox_mod(current, rhs)
        raise TypeError("unknown operator %s" % op)

    # ---- expressions ------------------------------------------------------
    async def eval(self, node, env):
        method = self._eval.get(type(node))
        if method is None:
            raise self.rt_error("cannot evaluate %s" % type(node).__name__, node)
        return await method(node, env)

    async def eval_literal(self, node, env):
        return node.value

    async def eval_interp_string(self, node, env):
        out = []
        for kind, part in node.parts:
            if kind == "lit":
                out.append(part)
            else:
                out.append(ox_str(await self.eval(part, env)))
        return "".join(out)

    async def eval_ident(self, node, env):
        try:
            return env.get(node.name)
        except KeyError:
            raise self.rt_error("undefined variable '%s'" % node.name, node)

    async def eval_list_lit(self, node, env):
        return [await self.eval(item, env) for item in node.items]

    async def eval_dict_lit(self, node, env):
        out = {}
        for key_node, value_node in node.pairs:
            key = await self.eval(key_node, env)
            value = await self.eval(value_node, env)
            try:
                out[key] = value
            except TypeError:
                raise self.rt_error("unhashable dict key of type %s"
                                    % type_name(key), key_node)
        return out

    async def eval_range_lit(self, node, env):
        a = await self.eval(node.start, env)
        b = await self.eval(node.end, env)
        for v in (a, b):
            if isinstance(v, bool) or not isinstance(v, int):
                raise self.rt_error("range bounds must be integers, got %s"
                                    % type_name(v), node)
        return Range(a, b, node.exclusive)

    async def eval_unary(self, node, env):
        if node.op == "await":
            v = await self.eval(node.expr, env)
            return await self.unwrap_await(v)
        v = await self.eval(node.expr, env)
        if node.op == "not":
            return not truthy(v)
        if node.op == "-":
            try:
                return ox_neg(v)
            except TypeError as e:
                raise self.rt_error(str(e), node)
        raise self.rt_error("unknown unary operator %s" % node.op, node)

    async def unwrap_await(self, v):
        if asyncio.isfuture(v) or isinstance(v, asyncio.Task):
            return await v
        if isinstance(v, list):
            out = []
            for x in v:
                out.append(await self.unwrap_await(x))
            return out
        return v

    async def eval_binary(self, node, env):
        op = node.op
        if op == "and":
            left = await self.eval(node.left, env)
            return await self.eval(node.right, env) if truthy(left) else left
        if op == "or":
            left = await self.eval(node.left, env)
            return left if truthy(left) else await self.eval(node.right, env)
        if op == "??":
            left = await self.eval(node.left, env)
            return left if left is not None else await self.eval(node.right, env)
        left = await self.eval(node.left, env)
        right = await self.eval(node.right, env)
        try:
            if op == "+":
                return ox_add(left, right)
            if op == "-":
                return ox_sub(left, right)
            if op == "*":
                return ox_mul(left, right)
            if op == "/":
                return ox_div(left, right)
            if op == "//":
                return ox_floordiv(left, right)
            if op == "%":
                return ox_mod(left, right)
            if op == "**":
                return ox_pow(left, right)
            if op == "==":
                return ox_eq(left, right)
            if op == "!=":
                return not ox_eq(left, right)
            if op == "<":
                return ox_cmp(left, right, lambda a, b: a < b)
            if op == "<=":
                return ox_cmp(left, right, lambda a, b: a <= b)
            if op == ">":
                return ox_cmp(left, right, lambda a, b: a > b)
            if op == ">=":
                return ox_cmp(left, right, lambda a, b: a >= b)
        except (TypeError, ZeroDivisionError) as e:
            raise self.rt_error(str(e), node)
        raise self.rt_error("unknown operator '%s'" % op, node)

    async def eval_call(self, node, env):
        args = [await self.eval(a, env) for a in node.args]
        kwargs = {}
        for k, v in node.kwargs:
            kwargs[k] = await self.eval(v, env)
        if isinstance(node.callee, A.Ident):
            name = node.callee.name
            try:
                callee = env.get(name)
            except KeyError:
                # pipe-style method dispatch: `sort(xs)` == `xs.sort()`
                if args:
                    table = method_table(args[0])
                    if table is not None and name in table:
                        return await call_method(self, args[0], name, args[1:],
                                                 kwargs)
                raise self.rt_error("undefined variable '%s'" % name, node)
        else:
            callee = await self.eval(node.callee, env)
        fname = None
        if isinstance(callee, OxFunction):
            fname = callee.name
        elif isinstance(callee, (BuiltinFunction,)):
            fname = callee.name
        elif isinstance(callee, BoundMethod):
            fname = callee.name
        if fname:
            self.call_stack.append([fname, self.current_file,
                                     node.line, node.col])
        try:
            return await call_value(self, callee, args, kwargs, env)
        finally:
            if fname:
                self.call_stack.pop()

    async def eval_index(self, node, env):
        obj = await self.eval(node.obj, env)
        idx = await self.eval(node.index, env)
        try:
            return getitem(obj, idx)
        except (TypeError, IndexError, KeyError) as e:
            msg = str(e.args[0]) if isinstance(e, KeyError) else str(e)
            raise self.rt_error(msg, node)

    async def eval_slice(self, node, env):
        obj = await self.eval(node.obj, env)
        start = await self.eval(node.start, env) if node.start is not None else None
        end = await self.eval(node.end, env) if node.end is not None else None
        step = await self.eval(node.step, env) if node.step is not None else None
        if not isinstance(obj, (list, str)):
            raise self.rt_error("cannot slice %s" % type_name(obj), node)
        try:
            return obj[slice(start, end, step)]
        except (TypeError, ValueError) as e:
            raise self.rt_error(str(e), node)

    async def eval_get_attr(self, node, env):
        obj = await self.eval(node.obj, env)
        try:
            return get_attr_value(obj, node.name)
        except KeyError as e:
            raise self.rt_error(str(e.args[0]), node)
        except Exception:
            raise

    async def eval_fn_lit(self, node, env):
        defaults = await self._eval_defaults(node.defaults, env)
        return OxFunction(None, node.params, defaults, node.vararg, node.body, env)

    async def eval_spawn(self, node, env):
        arg = node.arg
        interp = self

        async def runner():
            if isinstance(arg, A.Block):
                benv = Env(env, "spawn")
                return await interp.exec_block(arg, benv)
            v = await interp.eval(arg, env)
            if isinstance(v, (OxFunction, BuiltinFunction, BoundMethod)) or callable(v):
                return await call_value(interp, v, [], {}, env)
            return v

        task = asyncio.get_running_loop().create_task(runner())
        return task

    async def eval_serve_expr(self, node, env):
        from .builtins import servermod
        port = await self.eval(node.port, env)
        options = {}
        for k, vexpr in node.options:
            options[k] = await self.eval(vexpr, env)
        return await servermod.serve(self, port, options, node.router, env)

    # ---- ox function calls --------------------------------------------------
    async def call_function(self, fn, args, kwargs):
        kwargs = dict(kwargs)
        n_given = len(args) + len(kwargs)
        params = fn.params
        n_params = len(params)
        has_vararg = fn.vararg is not None
        required = sum(1 for d in fn.defaults if d is NO_DEFAULT)
        if n_given < required:
            raise self.rt_error("%s() takes at least %d argument%s, got %d"
                                % (fn.name, required,
                                   "" if required == 1 else "s", n_given))
        if not has_vararg and n_given > n_params:
            raise self.rt_error("%s() takes at most %d argument%s, got %d"
                                % (fn.name, n_params,
                                   "" if n_params == 1 else "s", n_given))
        call_env = Env(fn.env, fn.name)
        consumed = set()
        for i, p in enumerate(params):
            if i < len(args):
                call_env.define(p, args[i], mutable=True)
            elif p in kwargs:
                call_env.define(p, kwargs.pop(p), mutable=True)
                consumed.add(p)
            elif fn.defaults[i] is not NO_DEFAULT:
                call_env.define(p, fn.defaults[i], mutable=True)
            else:
                raise self.rt_error("%s() missing argument '%s'" % (fn.name, p))
        for k in kwargs:
            raise self.rt_error("%s() got an unexpected argument '%s'"
                                % (fn.name, k))
        if has_vararg:
            call_env.define(fn.vararg, list(args[n_params:]), mutable=True)
        if self.depth >= MAX_DEPTH:
            raise self.rt_error("stack overflow: recursion too deep (limit %d)"
                                % MAX_DEPTH)
        self.depth += 1
        self.call_stack.append([fn.name, self.current_file, fn.body.line,
                                fn.body.col])
        try:
            return await self.exec_block(fn.body, call_env)
        except ReturnSignal as r:
            return r.value
        finally:
            self.call_stack.pop()
            self.depth -= 1

    # ---- dynamic eval (the `eval` builtin) -----------------------------------
    async def eval_source(self, source, env, file="<eval>"):
        from .lexer import Lexer
        from .parser import Parser
        try:
            tokens = Lexer(source, file).tokenize()
            program = Parser(tokens, file).parse_program()
        except Exception as e:  # noqa: BLE001 — bad source -> catchable error
            from .values import to_ox_error
            raise OxThrow(to_ox_error(e))
        result = None
        self.file_stack.append(file)
        try:
            for stmt in program.stmts:
                if isinstance(stmt, A.ExprStmt):
                    result = await self.eval(stmt.expr, env)
                else:
                    await self.exec_stmt(stmt, env)
                    result = None
        except (BreakSignal, ContinueSignal) as sig:
            # eval is a nested program: a break/continue with no loop inside
            # the evaluated source cannot reach an outer loop — surface it
            # as a catchable ox error instead of leaking the signal
            word = "'break'" if isinstance(sig, BreakSignal) else "'continue'"
            raise self.rt_error("%s outside of a loop" % word, stmt)
        finally:
            self.file_stack.pop()
        return result
