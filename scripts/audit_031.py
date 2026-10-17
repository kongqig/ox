#!/usr/bin/env python3
"""0.3.1 语法一致性/稳定性/实用性审查 harness。

三部分：
  A. 坏输入稳定性 —— 每个坏程序必须干净退出（code 2，无 Python traceback）
  B. 语义一致性 —— 一批小程序，解释器输出 == 期望输出
  C. 编译 parity —— 同一批程序，编译产物输出 == 解释器输出
"""
import os
import subprocess
import sys
import tempfile

ROOT = "/home/z/my-project/ox"
sys.path.insert(0, ROOT)
PY = sys.executable
FAIL = []
PASS = 0


def run_ox(src, mode="interp"):
    """mode: interp -> python -m ox run ; build -> transpile & run python."""
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "t.ox")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(src)
        if mode == "interp":
            r = subprocess.run([PY, "-m", "ox", "run", f], cwd=ROOT,
                               capture_output=True, text=True, timeout=60)
        else:
            from ox.transpiler import transpile
            from ox.lexer import Lexer
            from ox.parser import Parser
            program = Parser(Lexer(src, f).tokenize(), f).parse_program()
            code = transpile(program)
            env = dict(os.environ, PYTHONPATH=ROOT)
            r = subprocess.run([PY, "-c", code], cwd=td,
                               capture_output=True, text=True, timeout=60,
                               env=env)
        return r.returncode, r.stdout, r.stderr


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append((name, detail))
        print("  ✗ %s\n    %s" % (name, detail))


# ---------------------------------------------------------------- A. 坏输入
BAD = {
    "unterminated string":      'let s = "abc',
    "unterminated raw":         "let s = 'abc",
    "unknown escape":           'let s = "a\\qb"',
    "bad number suffix":        "let n = 5kg",
    "bang negation":            "let b = !true",
    "unclosed paren":           "let x = (1 + 2",
    "unclosed bracket":         "let l = [1, 2",
    "semicolon in brackets":    "let l = [1;\n2]",
    "missing brace":            "fn f() { let x = 1",
    "bad dict key":             "let d = {[1]: 2}",
    "let without value":        "let x",
    "positional after kw":      "fn f(a, b) { a }\nf(b=3, 2)",
    "dupe param":               "fn f(a, a) { }",
    "param after default":      "fn f(a=1, b) { }",
    "assign to literal":        "1 = 2",
    "empty index":              "let l = [1]\nl[]",
    "throw non-error head":     "throw",
    "try without catch/fin":    "try { }",
    "match arrow missing":      "match 1 {\n  1 { }\n}",
    "import nothing":           "import",
    "top-level break":          "break",
    "top-level continue":       "continue",
    "unterminated triple":      'let s = """abc',
    "kwarg double eq":          "fn f(a) { }\nf(a = = 1)",
    "spawn nothing":            "spawn",
    "serve no port":            "serve { }",
    "test no name":             'test { }',
    "workflow no name":         "workflow { }",
    "step outside workflow":    'step "x" { }',
    "route outside serve":      'get "/" { }',
}
# break/continue 脱离循环是干净的运行时错误（rc=1），不是解析错误
BAD.pop("top-level break")
BAD.pop("top-level continue")
print("== A. 坏输入稳定性 ==")
for name, src in BAD.items():
    rc, out, err = run_ox(src)
    tb = "Traceback (most recent call last" in err
    check("bad:%s" % name,
          rc == 2 and not tb,
          "rc=%s traceback=%s\n    stderr: %s" % (rc, tb, err.strip()[:300]))

# 运行时错误应退出 1 且带位置
print("== A2. 运行时错误质量 ==")
RUNTIME_BAD = {
    "undefined var":   ("print(nope)", "nope"),
    "type error":      ('print(1 + "a" + 2)', None),
    "bad index":       ("let l = [1]\nprint(l[5])", "out of range"),
    "dict no key":     ("let d = {}\nprint(d.k)", "no key"),
    "not callable":    ("let x = 5\nx()", "not callable"),
    "let reassign":    ("let x = 1\nx = 2", None),
    "verify fails":    ('verify false, "boom"', "boom"),
    "break no loop":   ("break", "outside of a loop"),
    "continue no loop": ("continue", "outside of a loop"),
}
for name, (src, expect) in RUNTIME_BAD.items():
    rc, out, err = run_ox(src)
    tb = "Traceback (most recent call last" in err
    ok = rc == 1 and not tb and "⨯" in err
    if expect and expect not in err:
        ok = False
    check("rt:%s" % name, ok,
          "rc=%s tb=%s\n    stderr: %s" % (rc, tb, err.strip()[:300]))

# ---------------------------------------------------------------- B. 语义一致性
# (name, source, expected stdout)
SEM = [
    # 优先级
    ("prec not vs cmp",   'print(not 1 == 2)', "true\n"),
    ("prec unary pow",    "print(-2 ** 2)", "-4\n"),
    ("prec add mul",      "print(2 + 3 * 4)", "14\n"),
    ("prec or and",       "print(true or false and false)", "true\n"),
    ("prec nullish low",  "print(false or null ?? \"d\")", "d\n"),
    ("prec range cmp",    "print(1 + 1 == 2)", "true\n"),
    ("prec pipe",         "fn inc(x) { x + 1 }\nprint(3 |> inc |> inc)", "5\n"),
    # 除法语义
    ("div float",         "print(7 / 2)", "3.5\n"),
    ("floor div",         "print(7 // 2)", "3\n"),
    ("floor div neg",     "print(-7 // 2)", "-4\n"),
    ("floor div float",   "print(7.5 // 2)", "3.0\n"),
    ("mod",               "print(7 % 3)", "1\n"),
    # deep eq / bool vs int
    ("bool ne int",       "print(true == 1)", "false\n"),
    ("deep eq list",      "print([1, [2, {a: 3}]] == [1, [2, {a: 3}]])", "true\n"),
    ("deep eq dict",      "print({a: [1, 2]} == {a: [1, 2]})", "true\n"),
    ("str plus num",      'print("n=" + 1)', "n=1\n"),
    ("num plus str err",  "print(1 + \"a\")", None),
    # duration
    ("dur add",           "print(100ms + 2s)", "2.1s\n"),
    ("dur cmp",           "print(1500ms > 1s)", "true\n"),
    ("dur mul",           "print(2s * 3)", "6s\n"),
    ("dur sub",           "print(1h - 30m)", "30m\n"),
    ("dur int ms",        "print(100ms + 100ms)", "200ms\n"),
    # and/or 返回操作数
    ("or value",          'print(null or \"x\")', "x\n"),
    ("and value",         'print(1 and "y")', "y\n"),
    ("nullish value",     'print(null ?? 0 ?? "z")', "0\n"),
    ("nullish falsy",     'print(false ?? \"z\")', "false\n"),
    # truthiness
    ("truthy 0",          "print(0 ? 1 : 0)", None),  # 三元不存在 → 应为解析错误? 跳过
    ("empty str falsy",   'if "" { print("t") } else { print("f") }', "f\n"),
    ("empty list falsy",  "if [] { print(\"t\") } else { print(\"f\") }", "f\n"),
    # 插值
    ("plain dq literal brace", 'let s = "x {y"\nprint(s)', "x {y\n"),
    ("plain dq literal brace 2", 'let y = 1\nlet s = "{y z w}"\nprint(s)', "{y z w}\n"),
    ("interp expr",       'let n = 3\nprint(f"n={n * 7}")', "n=21\n"),
    ("interp nested str", 'let w = "wo"\nprint(f"{w + \"rld\"}!")', "world!\n"),
    ("interp escape",     'print("brace: \\{ ok")', "brace: { ok\n"),
    ("raw no interp",     "print('{x}')", "{x}\n"),
    ("interp fmt dur",    'print(f"{2s + 500ms}")', "2.5s\n"),
    # 切片/索引
    ("slice",             "let l = [0,1,2,3,4,5]\nprint(l[1:3])", "[1, 2]\n"),
    ("slice step",        "let l = [0,1,2,3,4,5]\nprint(l[::2])", "[0, 2, 4]\n"),
    ("neg index",         "let l = [0,1,2]\nprint(l[-1])", "2\n"),
    ("str index",         'print("abc"[1])', "b\n"),
    # match（语句形式 + 表达式形式）
    ("match literal",     'match 2 { 1 => "a" 2 => "b" _ => "c" }\n', ""),
    ("match stmt print",  'match 5 { n => print(f"v={n}") }', "v=5\n"),
    ("match list rest",   'match [1,2,3] { [a, ...r] => print(a + r.len()) }', "3\n"),
    ("match dict part",   'match {name: "ox", x: 1} { {name} => print(name) }', "ox\n"),
    ("match range",       'let m = match 7 { 1..9 => "low" _ => "high" }\nprint(m)', "low\n"),
    ("match exclusive",   'let m = match 9 { 1..<9 => "low" _ => "high" }\nprint(m)', "high\n"),
    ("match first wins",  'let m = match 1 { n => "bind" 1 => "lit" }\nprint(m)', "bind\n"),
    # 闭包/作用域
    ("closure counter",   "fn mk() { var n = 0\nfn () { n += 1; n } }\nlet c = mk()\nc()\nc()\nprint(c())", "3\n"),
    ("shadow inner",      "let x = 1\nif true { let x = 2\nprint(x) }", "2\n"),
    ("for capture",       "var fs = []\nfor i in 0..<3 { fs = push(fs, fn () { i }) }\nprint(fs[2]())", "2\n"),
    # 块表达式（0.3.1: if/match/try 是真表达式）
    ("if expr",           'let g = if 1 > 0 { "y" } else { "n" }\nprint(g)', "y\n"),
    ("if expr no else",   "print(if false { 1 })", "null\n"),
    ("if else-if expr",  'let g = if false { "a" } else if true { "b" } else { "c" }\nprint(g)', "b\n"),
    ("try expr",          'let v = try { throw error("x") } catch e { f"caught:{e.msg}" }\nprint(v)', "caught:x\n"),
    ("match expr",        'let m = match 1 { 1 => "one" _ => "?" }\nprint(m)', "one\n"),
    ("match paren pipe",  '(match 2 { 1 => "a" 2 => "b" _ => "c" }) |> print', "b\n"),
    ("if expr outer write", "var n = 0\nlet r = if true { n += 5; \"w\" } else { \"x\" }\nprint(r + f\" {n}\")", "w 5\n"),
    ("match expr bind",   'let m = match 5 { n => f"v={n}" }\nprint(m)', "v=5\n"),
    # 字符串方法
    ("str trim",          'print("  hi  ".trim())', "hi\n"),
    ("str split join",    'print("a,b,c".split(",").join("-"))', "a-b-c\n"),
    ("str pad",           'print("5".pad_left(3, "0"))', "005\n"),
    # 列表方法
    ("list push",         "var l = []\nl.push(1)\nl.push(2)\nprint(l)", "[1, 2]\n"),
    ("list map",          "print([1,2,3].map(fn (x) { x * 2 }))", "[2, 4, 6]\n"),
    ("list sort by",      'print([{k:"b"},{k:"a"}].sort_by("k"))', '[{"k": "a"}, {"k": "b"}]\n'),
    ("list reduce",       "print([1,2,3,4].reduce(fn (a, b) { a + b }))", "10\n"),
    ("list unique",       "print([1, 2, 1, 3, 2].unique())", "[1, 2, 3]\n"),
    # dict 方法
    ("dict get def",      'print({}.get("k", 42))', "42\n"),
    ("dict pick",         'print({a:1, b:2, c:3}.pick(["a", "c"]))', '{"a": 1, "c": 3}\n'),
    ("dict merge",        'print({a:1}.merge({b:2}))', '{"a": 1, "b": 2}\n'),
    ("dict json style",   'print({name: "ox", n: [1, "x"]})', '{"name": "ox", "n": [1, "x"]}\n'),
    # 数字方法
    ("num round",         "print(3.56.round(1))", "3.6\n"),
    ("num clamp",         "print(9.clamp(0, 5))", "5\n"),
    ("num times",         "var n = 0\n3.times(fn (i) { n += i })\nprint(n)", "3\n"),
    # misc
    ("pass stmt",         "pass\nprint(\"ok\")", "ok\n"),
    ("underscore discard","let _ = 1\nlet _ = 2\nprint(\"ok\")", "ok\n"),
    ("trailing dot chain","let l = [3, 1, 2]\nlet m = l\n  .sort()\nprint(m)", "[1, 2, 3]\n"),
    ("kwargs call",       'fn f(a, b=2) { f"{a}/{b}" }\nprint(f(1, b=9))', "1/9\n"),
    ("varargs",           "fn f(a, *rest) { rest }\nprint(f(1, 2, 3))", "[2, 3]\n"),
    ("varargs empty",     "fn f(a, *rest) { rest }\nprint(f(9))", "[]\n"),
    ("varargs methods",   "fn f(*r) { r.len() }\nprint(f(1, 2))", "2\n"),
    ("unicode ident-free","print(\"你好 ox 🐂\")", "你好 ox 🐂\n"),
    ("chained cmp err",   "print(1 < 2 < 3)", None),
    # break 在表达式-if 中穿透到循环（动态模式合法；编译由 analyzer 拦截）
    ("break thru expr-if", "var n = 0\nfor i in 0..<3 { let x = if true { break } else { 0 }; n += 1 }\nprint(n)", "0\n"),
]
print("== B. 语义一致性（解释器）==")
for item in SEM:
    name, src, want = item
    if want is None:
        # None = 期望报错（rc 1/2，无 traceback）
        rc, out, err = run_ox(src)
        tb = "Traceback (most recent call last" in err
        check("sem:%s" % name, rc in (1, 2) and not tb,
              "rc=%s tb=%s err=%s" % (rc, tb, err.strip()[:200]))
        continue
    try:
        rc, out, err = run_ox(src)
    except subprocess.TimeoutExpired:
        check("sem:%s" % name, False, "TIMEOUT")
        continue
    check("sem:%s" % name, rc == 0 and out == want,
          "rc=%s want=%r got=%r err=%s" % (rc, want, out, err.strip()[:200]))

# ---------------------------------------------------------------- C. 编译 parity
print("== C. 编译 parity ==")
for item in SEM:
    name, src, want = item
    if want is None or name == "break thru expr-if":
        continue  # 错误场景与动态专属语义不参与 parity
    try:
        rc, out, err = run_ox(src, "build")
    except Exception as e:
        check("parity:%s" % name, False, "compile fail: %s" % e)
        continue
    check("parity:%s" % name, rc == 0 and out == want,
          "rc=%s want=%r got=%r err=%s" % (rc, want, out, err.strip()[:300]))

# ---------------------------------------------------------------- D. analyzer 拦截
print("== D. analyzer 拦截（ox check）==")
CHECK_CASES = {
    "break in expr-if": ("for i in 0..<3 { let x = if true { break } else { 0 } }",
                         "cannot cross"),
    "return in expr-if": ("fn f() { let x = if true { return 1 } else { 0 } }\nf()",
                          "cannot cross"),
    "continue in expr-if": ("for i in 0..<3 { let x = if true { continue } else { 0 } }",
                            "cannot cross"),
    "nested fn ok": ("fn f() { let x = if true { fn g() { return 9 }; g() } else { 0 } }\nprint(f())", None),
}
for name, (src, expect) in CHECK_CASES.items():
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "t.ox")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(src)
        r = subprocess.run([PY, "-m", "ox", "check", f], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
        if expect is None:
            check("chk:%s" % name, r.returncode == 0,
                  "rc=%s out=%s" % (r.returncode, (r.stdout + r.stderr).strip()[:200]))
        else:
            check("chk:%s" % name, r.returncode == 1 and expect in r.stdout + r.stderr,
                  "rc=%s out=%s" % (r.returncode, (r.stdout + r.stderr).strip()[:300]))

print()
print("pass=%d fail=%d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:")
    for n, d in FAIL:
        print("  - %s: %s" % (n, d.splitlines()[0] if d else ""))
sys.exit(1 if FAIL else 0)
