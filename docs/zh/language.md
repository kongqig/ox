# ox 语言参考

> 本参考覆盖 ox 0.3.1 的全部语言特性，行为描述以解释器与编译器
> （`ox build` 产物）的双路径一致实现为准。

ox 是动态类型的脚本语言，面向自动化领域设计：文件、命令、网络、数据
和任务。它刻意保持小——一门可以完整装进脑子里的语言；同时把自动化里
最常出错的部分（进程生命周期、重试回滚、并发协调）做成了语言级能力。

## 目录

1. [词法结构](#词法结构)
2. [值与类型](#值与类型)
3. [运算符与优先级](#运算符与优先级)
4. [索引与切片](#索引与切片)
5. [值方法](#值方法)
6. [语句](#语句)
7. [函数与作用域](#函数与作用域)
8. [模式匹配](#模式匹配)
9. [错误处理](#错误处理)
10. [模块系统](#模块系统)
11. [并发与事件](#并发与事件)
12. [工作流](#工作流)
13. [服务器](#服务器)
14. [测试](#测试)
15. [动态求值与编译](#动态求值与编译)
16. [语义不变量](#语义不变量)

## 词法结构

```ox
# 注释一直到行尾（文件首行的 #! shebang 也只是注释）

let x = 1_000 + 0xFF + 0b1010 + 1.5e3   # 数字：下划线分隔、十六进制、
                                         # 二进制、八进制（0o17）、浮点、指数
let d = 150ms + 2s + 1m + 1h + 1d       # 时长字面量（值以秒计）
let e = 1.5s + 250.5ms                  # 小数时长也支持

let s  = f"hello {name}, n={n + 1}"      # f 前缀：启用插值，任意表达式
let r  = 'raw {string}'                 # 单引号：原始字符串，不插值
let ml = f"""
  多行文本，支持 {插值}
"""                                     # f + 三引号：可跨行且插值
let css = "body { color: red }"          # 普通双引号：花括号是字面量
let esc = f"花括号：\{ 转义"            # f 字符串里 \{ 表示字面 {
```

标识符为 `[A-Za-z_][A-Za-z0-9_]*`。语句以换行（或 `;`）分隔；
`( )` 和 `[ ]` 内部的换行被忽略，所以调用和列表可以跨行书写。行尾
是运算符时表达式延续到下一行；行首是 `.` 时延续上一个方法链。

**关键字**：`let var fn return if else for in while loop break continue
try catch finally throw async await spawn on emit import export as and or
not true false null match pass workflow serve test verify`

`get/put/post/delete/patch/head/static/ws/step/retry/backoff/rollback/
desc/fail/done` 是**上下文关键字**——只在 `serve` / `workflow` 块内
特殊，其他场合可以当普通名字用。

### 字符串细则（0.4 起插值显式化）

- 普通双引号 `"..."`：支持转义（`\n \t \r \0 \\ \" \{ \}`），
  但**不插值**——花括号是字面字符。写 CSS、JSON、正则、shell 片段
  都无需担心 `{`。
- **f 前缀 `f"..."`**：在双引号规则基础上启用 `{表达式}` 插值。
  字面花括号用 `\{`、`\}` 转义。
- 单引号 `'...'`：原始字符串——反斜杠没有转义作用，花括号没有插值
  作用，适合正则、Windows 路径等。
- 三引号：`f"""..."""` 可跨行且插值；`"""..."""` 可跨行不插值；
  `'''...'''` 跨行原始。
- 插值内部可以嵌套字符串（含它们自己的插值），可以包含 `{}` 块。
- 未知转义（如 `\q`）是词法错误，而不是静默通过。
- `ox check` 会对普通双引号里形如 `{name}` 的文本发出警告——它
  很可能是想要插值却忘了 f 前缀（从 0.3 迁移时的高频问题）。

## 值与类型

| 类型 | 示例 | 说明 |
|---|---|---|
| null | `null` | 空值；`??` 的触发条件 |
| bool | `true`、`false` | 与数字严格区分：`true == 1` 是 `false` |
| int / float | `42`、`3.14` | `/` 总返回 float；`//` 向下取整 |
| duration | `2s`、`150ms`、`1.5h` | 本质是秒数（float 子类），打印美观 |
| str | `f"插值"`、`"普通"`、`'raw'`、`f"""多行"""` | UTF-8 |
| list | `[1, "two", [3]]` | 可变列表 |
| dict | `{name: "ox", "怪键": 1, (表达式): 2}` | 字符串键字典 |
| range | `1..5`（含 5）、`0..<5`（不含）、`range(0, 10, 2)` | 惰性范围 |
| fn | `fn (a, b) { a + b }` | 具名声明或匿名函数 |
| error | `error("msg", code=42, data={...})` | 可抛出的错误值 |
| task | `spawn` 的返回值 | 用 `await` 消费 |
| module | `import` 绑定的值 | 标准库或本地模块 |

**真值规则**：`false`、`null`、`0`、`""`、`[]`、`{}` 为假，其余为真。

**显示格式**：`print`/`str` 对容器使用 JSON 风格——字典的键带引号
（`{"a": 1}`），列表为 `[1, 2]`，时长打印为 `2.5s`/`150ms`。
`str(null)`、f 字符串插值 `f"{x}"` 与 `repr(x)` 三者对 null 的渲染
一致（均为 `null`）。

## 运算符与优先级

```ox
+  -  *  /  //  %  **        # 算术（时长可参与：2s + 500ms）
==  !=  <  <=  >  >=         # == 对 list/dict 是深度相等
and  or  not                 # 短路；返回决定结果的操作数
??                           # 空值合并（只对 null 生效）
|>                           # 管道：xs |> sort |> reverse
..   ..<                     # 范围
```

`+` 还拼接列表、合并字典；左操作数是字符串时 `"n=" + 1` 自动把右侧
转为字符串。

**优先级**（从紧到松）：

| 级 | 运算符 | 备注 |
|---|---|---|
| 1 | `.` `()` `[]` | 后缀调用/索引/属性 |
| 2 | `**` | 右结合；`-2 ** 2` 是 `-(2 ** 2)` |
| 3 | 一元 `-`、`await` | |
| 4 | `*` `/` `//` `%` | |
| 5 | `+` `-` | |
| 6 | `..` `..<` | 不可链 |
| 7 | `==` `!=` `<` `<=` `>` `>=` | 不可链（`a < b < c` 报错） |
| 8 | `not` | 比比较运算松：`not a == b` 是 `not (a == b)` |
| 9 | `and` | |
| 10 | `or` | |
| 11 | `??` | 比 `or` 松：`false or null ?? "d"` 是 `(false or null) ?? "d"` |
| 12 | `|>` | 最松——管道吃掉左边的一切 |

拿不准就加括号。`??` 与 `or` 混用是允许的（不同于某些语言），按上表
结合。

## 索引与切片

```ox
let l = [0, 1, 2, 3, 4, 5]
l[0]        # 0
l[-1]       # 5（负索引从尾部数）
l[1:3]      # [1, 2]     （Python 风格切片，支持步长）
l[::2]      # [0, 2, 4]
l[1:]       # [1, 2, 3, 4, 5]

let d = {nested: {deep: 42}}
d.nested.deep       # 字典支持属性访问
d["nested"]["deep"] # 等价的下标写法
```

越界索引抛出可捕获错误（含索引值与长度信息）；字典缺键同样抛错——
想拿默认值用 `d.get("k", 默认值)`。

## 值方法

每种值自带一组方法，无需 import，静态分析器认识同一套名字。以下
是完整清单（签名见[标准库手册](stdlib.md#值方法)）：

- **str**：`len empty upper lower trim trim_left trim_right split
  split_lines replace startswith endswith has contains index slice
  repeat pad_left pad_right chars reverse first last capitalize title
  swapcase`
- **list**：`len empty push push_all pop shift unshift insert remove
  remove_at index has contains count join concat first last slice
  reverse unique flatten clone sum min max avg zip indexes map filter
  each find find_index any all reduce sort sort_by`
- **dict**：`len empty keys values items has contains get set del
  merge update pick omit clone sort_keys map_values filter first`
- **数字**：`abs floor ceil round clamp times`
- **range**：`len empty to_list`

```ox
"a,b".split(",")              # ["a", "b"]
[3, 1, 2].sort()              # [1, 2, 3]
[{"k": "b"}, {"k": "a"}].sort_by("k")    # 按字典键排序
{a: 1, b: 2}.pick(["a"])      # {"a": 1}
5.times(fn (i) { print(i) })  # 0 1 2 3 4
(1..5).to_list()              # [1, 2, 3, 4, 5]
```

方法在原生句柄（进程、服务器、WebSocket 连接等）上同样可用，由各自
模块文档说明。

## 语句

### 绑定

```ox
let x = 10        # 本作用域内不可变（重新赋值是静态错误）
var y = 0         # 可重新绑定
var z             # 可变，初值 null
x += 1            # 错误：x 是 let 声明的
y += 1            # 正确
```

内层作用域总是可以遮蔽。`_` 是丢弃名：可重复绑定、永不产生未使用警
告。

### 分支与循环

```ox
if score >= 90 { "A" } else if score >= 80 { "B" } else { "C" }

for x in [1, 2, 3] { ... }
for k, v in {a: 1, b: 2} { ... }     # 双变量解包字典
for i in 0..<10 { ... }              # 范围

while cond { ... }
loop { if done { break } else { continue } }
```

### 表达式化块（0.3.1）

`if` / `match` / `try` 是**真表达式**：值 = 实际执行分支的值。

```ox
let grade = if score >= 90 { "A" } else { "B" }
let name  = match id { 1 => "one" _ => "?" }
let safe  = try { risky() } catch e { null }
print(if dry_run { "(dry)" })         # "(dry)" 或 null
let pair = [if a { 1 }, match b { true => 2 }]   # 参数、列表里都行
```

- 无 else 的 if、无命中分支的 match，值为 `null`
- 语句位置照常使用（值被丢弃）；函数体内作为隐式返回值
- **编译限制**：`return` / `break` / `continue` 不能穿越表达式化块
  （`ox check` 报错并给出改写建议：先赋值给变量，再用语句形式）。
  解释器更宽容——表达式 `if` 里的 `break` 会跳出外围循环

### 其他语句

- `pass`：什么都不做（占位）
- `throw 表达式`：抛出（通常是 `error(...)` 值；任何值都可抛）
- `verify 条件, 消息`：条件为假时抛 verify 错误
- `import` / `export`：见[模块系统](#模块系统)
- `emit "事件名" 载荷`：见[事件](#并发与事件)
- `workflow` / `serve` / `test`：见各自章节

## 函数与作用域

```ox
fn add(a, b) { return a + b }

fn greet(name, punct="！") {   # 默认参数（定义时求值）
  f"嗨 {name}{punct}"           # 隐式返回：最后一个表达式
}

fn varargs(a, *rest) { rest }  # 变长参数收集成 list
greet("ox", punct="？")         # 调用侧关键字参数
net.get(url, verify=false)     # 关键字名可以是语言关键字

let double = fn (x) { x * 2 }  # 匿名函数
```

**提升**：顶层 `fn` 声明先于定义即可调用（默认值在声明处按顺序求
值）。

**参数命名规则（0.4.1）**：

- 参数列表里"关键字 token + `=`"一律按关键字参数名处理——
  `net.get(url, verify=false)` 可以解析；`(...)` 内部关键字不可能
  开启语句，因此没有歧义
- 参数名允许 `verify`、`on`、`test`、`workflow`（软关键字：既能
  声明也能在体内引用）；其余关键字会得到明确报错
- 默认值为 `null` 是货真价实的默认值——`fn f(a, opt=null)` 可以
  直接 `f(1)` 调用（0.4.1 之前 `opt` 会被当作必填参数）

**作用域规则**：

- 块（if/for/while/try/match 分支）引入新的作用域；内层可读外层绑定
- 赋值沿环境链向上查找——闭包里 `n += 1` 更新的是**外层**的 `n`
- `let` 重声明（同一层）是错误；`var` 可以遮蔽
- for 循环变量是每次迭代的独立绑定（闭包捕获不串值）

**调用约定**：位置参数必须在关键字参数之前（`f(a, b=1)` 合法，
`f(b=1, a)` 解析错误）；参数重复绑定报运行时错误；函数值与内置函数
统一走同一套调用协议（`await` 可选——所有调用都可等待）。

## 模式匹配

```ox
match value {
  42                  => "答案"
  "GET"               => "方法"
  1..9                => "个位数"
  1..<9               => "1 到 8"
  n                   => f"绑定：{n}"
  [a, b]              => f"一对 {a},{b}"
  [head, ...rest]     => f"头 {head}，尾 {rest.len()} 个"
  {name, admin: true} => f"管理员 {name}"
  {ok: true, data}    => f"成功 {data}"
  {a, ...extra}       => f"a={a}，另有 {extra.len()} 个键"
  [{x}, {y}]          => "嵌套解构"
  _                   => "任何东西"
}
```

完整规则（一处说清）：

- **字面量**（`1`、`"s"`、`true`、`null`、`5s`）：深度相等比较
- **范围**（`1..5`、`0..<n`）：主体是数字且落在范围内即命中（含端
  点判定：`5` 匹配 `1..5`，不匹配 `1..<5`）
- **裸标识符绑定**主体本身——**不**与外层同名变量比较（0.2 的旧行
  为已在 0.3 改为绑定）
- **列表模式**：主体必须是 list，长度精确匹配，除非 `...rest`（或
  裸 `...` 丢弃尾部）吸收剩余元素
- **字典模式**：部分匹配（多余键无妨），声明的键必须存在且子模式命
  中；`{x}` 是 `{x: x}` 的简写；`...rest` 把未声明的键收集为 dict
- **其他表达式**（调用、`-1`、插值字符串）先求值，再按值比较
- 绑定只在分支体内有效；**第一个命中的分支生效**，其后分支不可达

分支体是单个表达式或 `{ }` 块。模式里的绑定会遮蔽外层同名名字。

## 错误处理

ox 把失败分成两类，处理方式刻意不同：

**结果字典**——可预期的失败（命令退出码、HTTP 状态、包管理器）。
`sh()`、`net.*`、`py.pip()` 返回 `{ok: bool, ...}`，从不抛错：

```ox
let r = sh("make build")
if not r.ok { print(f"stderr: {r.err}") }
```

**错误值**——程序性失败（类型错误、未定义变量、越界、IO 异常都是可
捕获错误）：

```ox
try {
  throw error("磁盘已满", code=500, data={path: "/db"})
} catch e {                     # e 是错误值：e.msg / e.code / e.data / e.kind
  print(f"{e.msg}（code {e.code}）")
} finally {
  cleanup()
}
```

- `try` 必须有 `catch` 或 `finally`（或两者）
- `catch e` 绑定错误值；`catch { ... }` 不绑定也行
- `verify 条件, 消息`：条件为假时抛 `kind="verify"` 的错误——工作
  流步骤与测试的主力断言
- `exit(code)`：干净退出（finally 会执行），退出码透传给 shell
- 未捕获错误：打印 `⨯ runtime error` + 源码定位 + 调用栈，退出码 1

## 模块系统

```ox
import fs                        # 标准库模块
import net as networking         # 别名
import "./utils.ox" as utils     # 本地文件（相对当前文件解析）
import "./lib"                   # 目录：找 lib/main.ox 或 lib/index.ox
```

模块顶层 `fn` 提升。导出：

```ox
export helper, other             # 显式列表
export fn public_fn() { ... }    # 前缀形式
export let version = "1.0"
```

没有声明任何 `export` 的模块，所有不以 `_` 开头的顶层名字都是公开
的；`_` 开头的名字永远私有。模块只执行一次（缓存后复用）。`ox build`
编译的程序 import 本地 `.ox` 模块时由运行时解释执行（混合编译/解释）。

## 并发与事件

**await 处处可选。**任何调用——同步函数、异步内置、spawn 的块——
都直接得到**最终值**；写不写 `await` 结果完全一样，它只影响书写
风格（比如等待一组 spawn 任务时更直观）。不存在"忘了 await 拿到
半成品"的问题：句柄只在 API 明确返回时才存在（`spawn`、`co.every`、
`co.after`、`serve daemon=true`）。

```ox
let t1 = spawn { heavy(1) }        # 立即并发执行
let t2 = spawn { heavy(2) }
let both = await [t1, t2]          # await 一个列表 = 收集全部结果

await co.sleep(200ms)
let fast = await co.timeout(1s, fn () { slow_thing() })   # 超时抛错

let monitor = await co.every(5s, fn () { check() })       # 周期任务
monitor.stop()
let once = await co.after(30s, fn () { remind() })        # 一次性
```

任务是进程内的 asyncio 协程；脚本退出时未完成的任务被取消，后台进
程（`os.start`，非 detach）被终止。

**事件总线**是进程级的：

```ox
on "deploy.done" fn (evt) { log.info(f"载荷：{evt}") }
on "ping" { print(f"收到：{event}") }     # 块形式隐式绑定 event

emit "deploy.done" {host: "prod-1", ms: 812}
emit "ping" "hello"
```

处理器内的错误被捕获并记日志——`emit` 永远不会杀死发射方。
`events.list()` / `events.off("名字")` 管理处理器。

## 工作流

```ox
workflow "deploy" {
  desc "部署到生产环境"               # 可选描述

  step "build" {
    sh("make build")
  } retry 3 backoff 2s               # 总尝试次数 / 退避（D × 次数）

  step "migrate" {
    sh("migrate up")
  } rollback {
    sh("migrate down")               # 失败时撤销
  }

  step "health" {
    let r = net.get("http://localhost:3000/healthz")
    verify r.ok, "健康检查失败"
  }

  on fail { log.error("部署失败") }
  on done { emit "deploy.ok" }
}
```

运行与查询：

```ox
let r = run("deploy")                        # {ok, workflow, run, status, steps, ms, ...}
run("deploy", dry=true)                      # 打印计划，不执行
run("deploy", only=["build", "migrate"])     # 子集（跳过钩子）
run("deploy", skip=["health"])               # 排除法
run("deploy", resume=true)                   # 只补跑上次失败运行的未完成步骤
wf.list()                                    # 已定义的工作流
wf.steps("deploy")                           # 步骤名
wf.status("deploy")                          # 最近一次运行摘要
wf.history("deploy", n=10)                   # 历史记录
wf.state_dir(".ox/state")                    # 历史存放位置（默认 .ox/state）
```

语义：

- 步骤执行其块；**成功 = 没有抛错**；块的值记入运行日志
- `retry N` 是**总尝试次数**；`backoff D` 在重试间睡眠 `D × 第几次`
- 步骤最终失败时：**先跑它自己的 rollback**（清理半成品），再按逆序
  跑此前已成功步骤的 rollback；rollback 错误只记日志，不致命
- 每次运行（步骤状态、尝试、耗时、错误）追加到
  `.ox/state/<名字>.json`——`wf.status` / `wf.history` / `resume`
  都基于这份持久化历史
- `OX_STATE_DIR` 环境变量可改默认位置

## 服务器

```ox
serve 8080 {                                # 阻塞直到 Ctrl+C
  get "/"            { res.html("<h1>hi</h1>") }
  get "/users/:id"   { res.json({id: req.params.id}) }
  get "/search"      { res.json(req.query) }
  post "/echo"       { res.json(req.json) }
  put "/items/:id"   { res.json({ok: true}) }
  static "/assets"   "./public"             # 静态文件（防目录穿越）
  ws "/chat" {
    conn.on("message", fn (m) { conn.send(m) })
    conn.on("close",   fn (_) { ... })
  }
}
```

路由块隐式绑定 `req` / `res`（显式 `fn (req, res)` 处理器同样支
持）。`req` 是字典：

```ox
req.method   req.path        req.params     req.query     req.headers
req.body     req.json        req.form       req.ip        req.raw_path
```

`res` 方法：`send(text, status=, headers=)`、`json(obj, status=)`、
`html(...)`、`redirect(url, status=302)`、`file(path, download=)`、
`set_header(k, v)`、`status(code)`。

未匹配路径返回 JSON 404；方法不匹配返回 405 带 `Allow`；处理器错误
变 500（`debug=true` 或 `OX_DEBUG=1` 时包含错误详情）。

选项：

```ox
serve 8443, tls={cert: "cert.pem", key: "key.pem"} { ... }   # HTTPS
let s = serve 8080, daemon=true { ... }                       # 后台
s.stop()                                                     # 停止
s.port                                                       # 实际绑定端口
serve 8080, host="0.0.0.0" { ... }                           # 指定网卡
```

WebSocket 连接（`conn`）：`send(text)`、`send_json(obj)`、`close()`、
`on("message" | "close", fn)`、`.id`、`.ip`。

## 测试

```ox
# 任意文件名.test.ox
import verify

test "算术" {
  verify 1 + 1 == 2
}

test "慢操作", timeout=2s {
  verify true
}

test "工具函数" {
  verify.eq(sort([2, 1]), [1, 2])
  verify.approx(0.1 + 0.2, 0.3)
  let err = verify.throws(fn () { throw error("x") })
  verify.eq(err.msg, "x")
}
```

`ox test` 发现 `tests/` 下的 `*.test.ox`（或指定路径）。文件顶层
语句先执行（做夹具）；失败报告文件与行号；`--json` 输出
`ox-test-report.json`。测试运行完会清理该文件启动的后台进程。

## 动态求值与编译

```ox
let x = 20
eval("x + 22")              # -> 42（运行时解析并执行 ox 源码）
let py = compile('fn f(n) { n * 2 }')
# py 是 ox build 会为这段程序生成的 Python 源码
```

`eval` 在当前环境执行；`break`/`continue` 不会穿透 eval 边界（转为
可捕获错误）；eval 的**语法错误**同样是可捕获错误而不是崩溃。
`compile` 用于检视编译器输出。

## 语义不变量

以下均为刻意为之的语言决策，由 `tests/lang_semantics.test.ox` 钉死，
解释器与编译产物行为一致：

- **插值显式化**：普通双引号字符串里的 `{` 是字面字符；只有
  `f"..."` 启用插值。CSS/JSON/正则/shell 片段无需转义直接写。
  `ox check` 会提示疑似忘写 f 前缀的字符串。
- **透明等待**：一切调用直接得到最终值，`await` 不改变结果，只
  影响可读性；忘记 `await` 不会泄漏任务。
- **布尔不是数字**：`true + 1` 是类型错误，`true == 1` 是 `false`，
  数字上下文永不隐式转换布尔。
- **除零必报错**：`/`、`//`、`%` 除以零抛可捕获错误；ox 的算术中
  没有 NaN/Infinity。
- **递归有深度上限**（解释器约 900 层，编译产物更宽松）；超限抛
  可捕获的 `stack overflow` 错误并携带 ox 级调用栈，绝不出现
  Python traceback。
- **迭代规则**：`for x in xs` 迭代元素（列表）或键（字典）；
  `for k, v in xs` 解包每个元素（字典产出键值对，列表产出其元素）；
  `d.items()` 显式返回 `[k, v]` 对。
- **深度相等**：`==` 对列表/字典/嵌套数据做结构比较而非身份比较；
  循环引用渲染为 `...` 而不会崩溃。
- **match 绑定**：模式里的裸标识符是**绑定**而非与外层变量比较；
  `ox check` 会在绑定遮蔽用户变量时警告，刻意遮蔽请用 `_` 前缀名。
