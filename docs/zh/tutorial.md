# ox 入门教程

> 目标读者：写过 Shell 脚本或 Python 小工具的开发者。
> 预计用时：30–45 分钟。本页所有示例都可直接运行——把代码存成 `.ox`
> 文件，执行 `ox run 文件名.ox` 即可。

## 0. 安装与第一个脚本

ox 需要 Python 3.9+，零第三方依赖：

```sh
git clone <仓库地址> && cd ox
pip install .          # 安装 ox 命令
ox version             # 验证安装
```

不安装也可以直接用：`python3 -m ox run examples/hello.ox`。

创建第一个脚本 `hello.ox`：

```ox
# hello.ox
let name = "世界"
print(f"你好，{name}！")            # f 字符串插值：{表达式} 求值后嵌入

fn greet(who, punct="！") {        # 默认参数 + 隐式返回
  f"你好 {who}{punct}"
}
print(greet("ox", punct="？"))     # 关键字参数

print(f"预算：{100ms + 2s}")        # 时长是值：-> 2.1s
```

运行：`ox run hello.ox`。你会看到：

```text
你好，世界！
你好 ox？
预算：2.1s
```

几个马上能感受到的设计点：语句用换行分隔（不需要分号）；`let` 声明
不可变绑定，`var` 声明可变绑定；`fn` 的函数体最后一个表达式就是返回
值；时长（`2s`、`150ms`）是一等公民，可以直接加减比较。

## 1. 变量与函数

```ox
let x = 10        # 不可变：重新赋值会报错（编译期能查出来）
var y = 0         # 可变
var z             # 可变且初值为 null

x += 1            # 错误：x 是 let 声明的
y += 1            # 正确
```

内层作用域可以随意遮蔽外层名字。`_` 是专门的丢弃名，可以重复绑定，
静态检查不会告警：

```ox
for _ in 0..<3 { work() }     # 只关心执行次数
let _ = fetch()               # 明确表示不关心返回值
```

函数支持默认参数、变长参数、关键字参数和闭包：

```ox
fn add(a, b) { return a + b }

fn greet(name, punct="！") { f"嗨 {name}{punct}" }

fn varargs(a, *rest) { rest }        # rest 收集成列表
greet("ox", punct="？")              # 关键字参数
print(varargs(1, 2, 3))              # -> [2, 3]

let double = fn (x) { x * 2 }        # 匿名函数

fn make_counter(start) {             # 闭包捕获环境
  var n = start
  fn () { n += 1; n }
}
let c = make_counter(10)
c()   # -> 11
c()   # -> 12
```

顶层 `fn` 声明会被提升（hoist）——先调用后定义也可以。

**if / match / try 是表达式**，可以直接用在赋值右边：

```ox
let grade = if score >= 90 { "A" } else { "B" }

let label = match code {
  200 => "ok"
  404 => "missing"
  _   => "other"
}

let safe = try { risky() } catch e { null }
```

分支体既可以是一个表达式（像上面的 `"ok"`），也可以是多语句的块
`{ ... }`。没有 else 的 if、没有命中的 match 结果是 `null`。match 的
完整规则见[语言参考](language.md#模式匹配)。

## 2. 控制流

```ox
if score >= 90 { print("A") } else if score >= 80 { print("B") } else { print("C") }

for x in [1, 2, 3] { print(x) }
for k, v in {a: 1, b: 2} { print(f"{k}={v}") }   # 解包成键值对
for i in 0..<10 { print(i) }                    # 不含 10；1..5 含 5

while not done { poll() }
loop {                                           # 无限循环
  if finished { break }
  continue
}
```

比较运算不能连写：`1 < 2 < 3` 会直接报错，而不是给出意外的静默结果。
区间判断写成两个比较的组合，或者干脆用模式匹配：

```ox
if x >= 1 and x <= 5 { print("在范围内") }

match n {
  1..9    => "个位数"
  10..99  => "两位数"
  _       => "很大"
}
```

## 3. 模式匹配

`match` 是 ox 的主力分支工具，模式远不止字面量：

```ox
match value {
  42                  => "答案"          # 字面量（深比较）
  "GET"               => "方法"
  1..9                => "个位数"        # 范围按包含判断
  1..<9               => "1 到 8"
  n                   => f"绑定：{n}"     # 裸标识符绑定整个值
  [a, b]              => f"一对：{a},{b}"          # 列表：要求精确长度
  [head, ...rest]     => f"头 {head}，尾 {rest.len()} 个"   # 捕获剩余
  {name, admin: true} => f"管理员 {name}"           # 字典：部分匹配
  {ok: true, data}    => f"成功 {data}"             # 简写绑定同名字段
  {a, ...extra}       => f"a={a}，另有 {extra.len()} 个键"
  [{x}, {y}]          => "嵌套也行"                 # 嵌套解构
  _                   => "任何东西"       # 通配符
}
```

规则一览：

- 字面量（`1`、`"s"`、`true`、`null`、`5s`）按深度相等比较
- 范围（`1..5`、`0..<n`）匹配落在其中的数字
- **裸标识符是绑定**，不会与外层同名变量比较（0.2 的旧行为，0.3 起改为绑定）
- 列表模式要求精确长度，除非 `...rest` 吸收尾部；主体必须是列表
- 字典模式是部分匹配（多出来的键没关系），缺键则失败；`...rest`
  把未匹配的键收集成字典
- 其余表达式（函数调用、`-1`、插值字符串）会先求值再比较
- 绑定只在分支体内可见；第一个匹配的分支生效

## 4. 错误处理

ox 区分两种失败：

**可预期的失败** → 结果字典。`sh()`、`net.*`、`py.pip()` 返回
`{ok: bool, ...}`，不会抛错，分支判断 `.ok` 即可：

```ox
let r = sh("ls -la | wc -l")
if r.ok { print(f"{r.out.trim()} 行") } else { print(f"失败：{r.err}") }
```

**程序错误** → 可捕获的 error 值。类型错误、未定义变量、下标越界都
是可捕获错误；显式抛出用 `throw error(...)`：

```ox
try {
  throw error("磁盘已满", code=500, data={path: "/db"})
} catch e {                          # e 就是 error 值
  print(f"{e.msg}（code {e.code}）")
} finally {
  cleanup()
}

verify fs.exists(path), f"路径必须存在：{path}"    # 条件为假时抛 verify 错误
```

`verify` 是"断言即声明"：条件为假时抛出带消息的 verify 错误，在
工作流和测试里大量使用。

## 5. 并发与定时任务

所有调用都是可 await 的；`spawn` 开并发任务，`await` 收结果：

```ox
let results = await [
  spawn { net.get("http://example.com") },
  spawn { net.get("http://example.org") },
]
```

`co` 模块管理并发原语：

```ox
await co.sleep(200ms)
let fast = await co.timeout(1s, fn () { slow_thing() })   # 超时抛错

let monitor = await co.every(5s, fn () { check_health() })  # 周期任务
monitor.stop()

let once = await co.after(30s, fn () { remind() })          # 一次性延时

let nightly = co.cron("30 3 * * *", fn () { run_backup() })  # cron 定时
print(f"下次触发：{time.iso(nightly.next())}")
nightly.stop()
```

cron 是经典五字段（分 时 日 月 周），本地时间，支持 `*/n`、`a-b`、
列表、`mon-fri`、`@daily` 等常用写法。任务失败会记日志并保持调度。

## 6. 文件与 Shell——日常工作的主力

```ox
import fs

fs.write("notes.md", "# 备注\n内容")
let text = fs.read("notes.md")
fs.append("notes.md", "\n追加一行")

let files = fs.walk("./src", pattern="*.ox")     # 递归列出
for f in fs.files("./docs") { print(f) }

fs.copy("a.txt", "b.txt")
fs.move("b.txt", "c.txt")
fs.remove("c.txt")

fs.write_json("cfg.json", {name: "ox", debug: true})
let cfg = fs.read_json("cfg.json")

fs.zip(["notes.md", "logs/"], "bundle.zip")     # -> 条目数
fs.unzip("bundle.zip", "out/")                  # 防路径穿越（zip-slip）

let lk = fs.try_lock("deploy.lock")             # 文件锁
if lk == null { print("另一个部署正在跑"); exit(1) }
# ... 独占工作 ...
lk.release()
```

Shell 命令用 `sh()`（即 `os.sh`）：

```ox
let r = sh("tar czf site.tgz dist/", cwd="/srv", timeout=30s)
verify r.ok, f"打包失败：{r.err}"
```

后台进程用 `os.start`，配合 `net.wait_port` 等"起来了吗"：

```ox
import os
import net

let p = os.start("python3 -m http.server 8000")
if not (await net.wait_port("127.0.0.1", 8000, timeout=10s)) {
  print(p.err())
  await p.kill()
  throw error("服务没起来")
}
await p.kill()          # 脚本退出时未 kill 的进程也会被自动终止
```

## 7. HTTP 服务器与客户端

客户端：

```ox
import net

let r = net.get("https://httpbin.org/get", query={q: "ox"}, timeout=10s)
if r.ok {
  print(r.status)       # 200
  print(r.json)         # 已解析的 JSON（不是 JSON 时为 null）
}
```

服务器是一个语句：

```ox
serve 8080 {
  get "/"            { res.html("<h1>你好</h1>") }
  get "/users/:id"   { res.json({id: req.params.id}) }
  post "/echo"       { res.json(req.json) }
  static "/assets"   "./public"             # 静态文件（防目录穿越）
  ws "/chat" {
    conn.on("message", fn (m) { conn.send(m) })   # WebSocket 回声
  }
}
```

路由块自动获得隐式 `req`/`res` 绑定（也可以写显式
`fn (req, res) { ... }`）。`serve` 阻塞直到 Ctrl+C；`daemon=true` 时
转后台并返回句柄：

```ox
let s = serve 8080, daemon=true { ... }
print(f"端口 {s.port}")
s.stop()
```

## 8. 工作流：步骤、重试、回滚

把一次部署写成声明式工作流：

```ox
workflow "deploy" {
  desc "部署到生产环境"

  step "build" {
    sh("make build")
  } retry 3 backoff 2s                       # 总尝试次数 / 退避增长

  step "migrate" {
    sh("migrate up")
  } rollback {
    sh("migrate down")                       # 后续步骤失败时撤销
  }

  step "health" {
    let r = net.get("http://localhost:3000/healthz")
    verify r.ok, "健康检查失败"
  }

  on fail { log.error("部署失败") }
  on done { emit "deploy.ok" }
}

let r = run("deploy")             # -> {ok, steps, ms, ...}
run("deploy", dry=true)           # 打印计划，不执行
run("deploy", resume=true)        # 只补跑上次失败运行中未完成的步骤
```

每次运行的步骤状态、尝试次数、耗时、错误都追加到 `.ox/state/` 下的
JSON 里——`wf.status("deploy")` / `wf.history("deploy")` 查询，断点续
跑（resume）也靠它。失败时：先跑本步骤的 rollback，再逆序跑已成功步
骤的 rollback；rollback 的错误只记日志，不算致命。

## 9. 生态互操作

Python 和 C 一个 import 之遥：

```ox
import py

let math = py.import("math")
print(math.sqrt(2.0))             # 直接调 Python

py.exec("X = 40 + 2")             # 共享命名空间
py.pip("install requests")        # 管包（sh 风格结果字典）
```

```ox
import c

let libm = c.lib("m")
let pow_fn = libm.fn("pow", [c.double, c.double], c.double)
print(pow_fn(2.0, 10.0))          # -> 1024.0，走 C ABI
```

## 10. 测试与工程化

```ox
# tests/anything.test.ox
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

命令行全家桶：

```sh
ox run deploy.ox       # 运行（动态解释）
ox check deploy.ox     # 静态分析（未定义变量、let 重赋值、不可达代码……）
ox test                # 跑 tests/ 下所有 *.test.ox
ox fmt                 # 原地格式化（--check 供 CI 用）
ox build deploy.ox     # 编译成自包含可执行文件（--binary 免 Python）
ox init my-tool        # 脚手架
ox repl                # 交互环境
```

## 下一步

- [语言参考](language.md)——完整语法规范（运算符优先级、模式匹配全部
  规则、表达式化块……）
- [标准库手册](stdlib.md)——16 个实体模块每个函数的中文说明
- [命令行手册](cli.md)——所有命令、退出码、环境变量
- 仓库 `examples/` 目录——8 个可运行的完整示例
