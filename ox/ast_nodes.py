"""AST node definitions for ox.

Nodes are plain data holders. Every node gets `.line` / `.col` assigned by
the parser. Generic nodes are produced by the `N` factory; a few have
custom classes where extra behaviour is needed.
"""


class Node:
    _fields = ()

    def __init__(self, *args):
        self.line = None
        self.col = None
        for f, v in zip(self._fields, args):
            setattr(self, f, v)

    def __repr__(self):
        inner = ", ".join("%s=%r" % (f, getattr(self, f, None))
                          for f in self._fields)
        return "%s(%s)" % (type(self).__name__, inner)


def N(name, *fields):
    return type(name, (Node,), {"_fields": fields})


# --- statements -----------------------------------------------------------
Program      = N("Program", "stmts", "file")
Block        = N("Block", "stmts", "implicits")     # implicits: names bound on entry
Let          = N("Let", "name", "value", "mutable", "exported")
FnDecl       = N("FnDecl", "name", "params", "defaults", "vararg", "body", "exported")
Return       = N("Return", "value")
If           = N("If", "cond", "then", "els")
While        = N("While", "cond", "body")
Loop         = N("Loop", "body")
For          = N("For", "names", "iterable", "body")
Break        = N("Break")
Continue     = N("Continue")
Pass         = N("Pass")
Try          = N("Try", "try_block", "catch_var", "catch_block", "finally_block")
Throw        = N("Throw", "expr")
Match        = N("Match", "subject", "arms")        # arms: [(pattern, Block|ExprStmt)]
MatchArm     = N("MatchArm", "pattern", "body")
Import       = N("Import", "module", "path", "alias")
Export       = N("Export", "names")
OnEvent      = N("OnEvent", "name", "handler")      # handler: FnLit | Block
HookDecl     = N("HookDecl", "kind", "handler")     # on fail / on done (workflow ctx)
Emit         = N("Emit", "name", "payload")
Verify       = N("Verify", "cond", "msg")
TestDecl     = N("TestDecl", "name", "timeout", "body")
WorkflowDecl = N("WorkflowDecl", "name", "body")
StepDecl     = N("StepDecl", "name", "body", "retry", "backoff", "rollback")
DescDecl     = N("DescDecl", "text")
ServeDecl    = N("ServeDecl", "port", "options", "router")
RouteDecl    = N("RouteDecl", "method", "path", "body")
StaticDecl   = N("StaticDecl", "prefix", "dir")
WsDecl       = N("WsDecl", "path", "body")
ExprStmt     = N("ExprStmt", "expr")
Assign       = N("Assign", "target", "op", "value")

# --- expressions ----------------------------------------------------------
Literal      = N("Literal", "value")
InterpString = N("InterpString", "parts")           # parts: ("lit", s) | ("expr", Node)
Ident        = N("Ident", "name")
ListLit      = N("ListLit", "items")
DictLit      = N("DictLit", "pairs")                # pairs: (key_node, value_node)
RangeLit     = N("RangeLit", "start", "end", "exclusive")
Unary        = N("Unary", "op", "expr")             # op: "-" | "not" | "await"
Binary       = N("Binary", "left", "op", "right")   # arith/comparison/and/or/?? /etc.
Call         = N("Call", "callee", "args", "kwargs")
Index        = N("Index", "obj", "index")
Slice        = N("Slice", "obj", "start", "end", "step")
GetAttr      = N("GetAttr", "obj", "name")
FnLit        = N("FnLit", "params", "defaults", "vararg", "body")
Spawn        = N("Spawn", "arg")                    # arg: Block | expression


# --- match patterns --------------------------------------------------------
# Only appear as `match` arm patterns. Bare idents bind; literals compare;
# lists/dicts destructure; anything else (PatExpr) is evaluated and compared.
PatList      = N("PatList", "items", "rest")        # rest: None | "" | "name"
PatDict      = N("PatDict", "pairs", "rest")        # pairs: [(key, pattern)]
PatExpr      = N("PatExpr", "expr")                  # fallback: compare by value


# node classification helpers used by analyzer / transpiler
BLOCK_STATEMENTS = (If, While, Loop, For, Try, FnDecl, Match)
LITERALS = (Literal, InterpString, ListLit, DictLit, RangeLit)
