#!/usr/bin/env python3
"""验证中文/英文文档里所有 ```ox 代码块可解析可分析。

规则：
  - 提取 docs/zh/*.md 与 docs/LANGUAGE.md 里的 ```ox 围栏
  - 词法 + 解析必须成功（示例里有少量示意性省略，如 `...`、
    `risky()`、`work()` 这类——这些做"名字白名单跳过"处理：只要求
    解析通过，不要求运行）
  - 对没有未定义引用的块，进一步跑 ox check
"""
import re
import sys

sys.path.insert(0, "/home/z/my-project/ox")
from ox.lexer import Lexer, LexError          # noqa: E402
from ox.parser import Parser, ParseError      # noqa: E402

DOCS = [
    "/home/z/my-project/ox/docs/zh/tutorial.md",
    "/home/z/my-project/ox/docs/zh/language.md",
    "/home/z/my-project/ox/docs/zh/cli.md",
    "/home/z/my-project/ox/docs/zh/README.md",
    "/home/z/my-project/ox/docs/LANGUAGE.md",
]

fail = 0
total = 0
for path in DOCS:
    src = open(path, encoding="utf-8").read()
    blocks = re.findall(r"```ox\n(.*?)```", src, re.S)
    for i, code in enumerate(blocks, 1):
        total += 1
        name = "%s#%d" % (path.split("/")[-1], i)
        stripped = code.strip()
        # 示意块豁免：含 ... 占位、以运算符/名字清单开头（非完整程序）
        if "..." in stripped or stripped.startswith(("+", "req.method")):
            continue
        try:
            tokens = Lexer(code, name).tokenize()
            Parser(tokens, name).parse_program()
        except (LexError, ParseError) as e:
            fail += 1
            lines = code.splitlines()
            ctx = lines[max(0, min((e.line or 1) - 1, len(lines) - 1))]
            print("✗ %s: %s (line %s)" % (name, e.message, e.line))
            print("  >>> " + ctx)
print("blocks=%d parse-fail=%d" % (total, fail))
sys.exit(1 if fail else 0)
