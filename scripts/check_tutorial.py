#!/usr/bin/env python3
"""端到端验证中文教程中的关键示例：实际输出 == 文档宣称的输出。"""
import subprocess
import sys
import tempfile
import os

ROOT = "/home/z/my-project/ox"
PY = sys.executable
sys.path.insert(0, ROOT)

CASES = [
    ("hello 教程", """let name = "世界"
fn greet(who, punct="！") { "你好 {who}{punct}" }
print("你好，{name}！")
print(greet("ox", punct="？"))
print("预算：{100ms + 2s}")
""", "你好，世界！\n你好 ox？\n预算：2.1s\n"),
    ("闭包计数器", """fn make_counter(start) { var n = start
  fn () { n += 1; n } }
let c = make_counter(10)
print(c())
print(c())
""", "11\n12\n"),
    ("表达式化块", """let score = 95
let grade = if score >= 90 { "A" } else { "B" }
let code = 404
let label = match code { 200 => "ok" 404 => "missing" _ => "other" }
print(grade)
print(label)
print(if false { 1 })
""", "A\nmissing\nnull\n"),
    ("模式匹配", """match [1, 2, 3] { [head, ...rest] => print("头 {head}，尾 {rest.len()} 个") }
match {name: "ox", admin: true} { {name, admin: true} => print("管理员 {name}") }
""", "头 1，尾 2 个\n管理员 ox\n"),
    ("sh 结果字典", """let r = sh("echo hello")
if r.ok { print("{r.out.trim()} 收到") }
""", "hello 收到\n"),
    ("值方法", """print("a,b".split(","))
print([3, 1, 2].sort())
print({a: 1, b: 2}.pick(["a"]))
var out = ""
5.times(fn (i) { out = out + "{i}" })
print(out)
print((1..5).to_list())
""", '["a", "b"]\n[1, 2, 3]\n{"a": 1}\n01234\n[1, 2, 3, 4, 5]\n'),
    ("fs 读写", """import fs
fs.write("t.md", "# 备注\\n内容")
print(fs.read("t.md"))
fs.append("t.md", "\\n追加")
print(fs.read("t.md"))
print(fs.read_lines("t.md").len())
""", "# 备注\n内容\n# 备注\n内容\n追加\n3\n"),
    ("str/repr/插值 null 一致", """let x = null
print("[{x}] [" + str(x) + "] [" + repr(x) + "]")
""", "[null] [null] [null]\n"),
    ("cron 下次触发可算", """import co
import time
let t = co.cron_next("30 3 * * *")
verify t > time.epoch()
print("ok")
""", "ok\n"),
    ("锁互斥", """import fs
let lk = fs.try_lock("l1.lock")
verify lk != null
verify fs.try_lock("l1.lock") == null
lk.release()
let lk2 = fs.try_lock("l1.lock")
verify lk2 != null
lk2.release()
fs.remove("l1.lock")
print("ok")
""", "ok\n"),
]

fail = 0
for name, src, want in CASES:
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "t.ox")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(src)
        r = subprocess.run([PY, "-m", "ox", "run", f], cwd=td,
                           capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PYTHONPATH=ROOT))
        if r.returncode != 0 or r.stdout != want:
            fail += 1
            print("✗ %s\n  want=%r\n  got =%r rc=%s err=%s"
                  % (name, want, r.stdout, r.returncode, r.stderr.strip()[:200]))
        else:
            print("✓ %s" % name)
print("fail=%d" % fail)
sys.exit(1 if fail else 0)
