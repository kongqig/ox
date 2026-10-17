# ox 标准库手册

> 覆盖 ox 0.3.1 的全部 18 个模块名（16 个实体模块，json 与 http 为别名）与内建函数。函数签名按
> 「名字(参数=默认值)」给出；标注 ⏳ 的为异步函数（可直接调用，
> 需要结果时 `await`）。

不 import 即可用的内建：`print len type str repr int float bool range
error exit input sh sleep run eval compile`。

**结果字典约定**：`sh()`、`net.*`、`py.pip()` 返回 `{ok: bool, ...}`
而不抛错——分支判断 `.ok`。文件类助手失败时抛错（先用 `fs.exists`
探测）。

## 目录

- [fs — 文件与目录](#fs--文件与目录)
- [os — 系统与命令](#os--系统与命令)
- [env — 环境变量](#env--环境变量)
- [log — 日志](#log--日志)
- [time — 时间](#time--时间)
- [math — 数学与随机](#math--数学与随机)
- [crypto — 哈希与标识](#crypto--哈希与标识)
- [data — 结构化数据](#data--结构化数据)
- [net — HTTP 与 WebSocket 客户端](#net--http-与-websocket-客户端)
- [server — 服务器](#server--服务器)
- [wf — 工作流引擎](#wf--工作流引擎)
- [co — 并发](#co--并发)
- [events — 事件总线](#events--事件总线)
- [verify — 测试断言](#verify--测试断言)
- [py — Python 桥](#py--python-桥)
- [c — C FFI](#c--c-ffi)
- [值方法](#值方法)

## fs — 文件与目录

```ox
import fs
```

### 读写

| 函数 | 说明 |
|---|---|
| `fs.read(path, encoding="utf-8")` | 读文本 |
| `fs.read_bytes(path)` | 读字节 |
| `fs.read_lines(path, encoding="utf-8")` | 读成行列表（不含换行符） |
| `fs.write(path, data)` | 写文本，返回写入长度 |
| `fs.write_bytes(path, data)` | 写字节 |
| `fs.write_lines(path, lines)` | 每元素一行 |
| `fs.append(path, data)` | 追加文本 |
| `fs.read_json(path)` / `fs.write_json(path, value, pretty=true)` | JSON 文件 |

### 探测

| 函数 | 说明 |
|---|---|
| `fs.exists(path)` / `fs.is_file(path)` / `fs.is_dir(path)` | 存在性与类型 |
| `fs.size(path)` | 字节数 |
| `fs.mtime(path)` | 修改时间（epoch 秒） |
| `fs.empty(path)` | 空文件/空目录？ |
| `fs.touch(path)` | 创建或刷新 mtime |

### 列举

| 函数 | 说明 |
|---|---|
| `fs.list(path=".")` | 条目列表 `[{name, type, size}]`（type 为 "file"/"dir"） |
| `fs.files(path)` / `fs.dirs(path)` | 只要名字 |
| `fs.walk(path, pattern=null)` | 递归列出所有文件；fnmatch 过滤可选 |
| `fs.glob(pattern, path=null)` | glob 匹配（`**`、`*`、`?`、`[...]`） |

```ox
for f in fs.walk("./src", pattern="*.ox") {
  print(f"{f} — {fs.size(f)} 字节")
}
```

### 增删改移

| 函数 | 说明 |
|---|---|
| `fs.mkdir(path)` / `fs.mkdirs(path)` | 建目录（后者含父级） |
| `fs.copy(src, dst)` / `fs.copytree(src, dst)` | 复制文件/整棵树 |
| `fs.move(src, dst)` / `fs.rename(src, dst)` | 移动 |
| `fs.remove(path)` / `fs.delete(path)` | 删文件 |
| `fs.remove_tree(path)` / `fs.rmdir(path)` | 删目录——`remove_tree` 为 rm -rf 语义：目录不存在时静默成功 |
| `fs.chmod(path, mode)` | mode 为整数或八进制字符串 `"755"` |
| `fs.replace(path, old, new, count=-1)` | 文件内文本替换，返回次数 |
| `fs.grep(path, pattern, regex=false)` | 匹配的行；`regex=true` 时按正则 |

### 路径工具

`fs.chdir(path)` `fs.cwd()` `fs.home()` `fs.abs(path)` `fs.join(a, b,
...)` `fs.split(path)` `fs.ext(path)` `fs.stem(path)` `fs.norm(path)`
`fs.rel(path, base=".")` `fs.temp_dir(prefix="ox-")`
`fs.temp_file(suffix=".tmp", prefix="ox-")` `fs.sha256(path)`
`fs.md5(path)`

```ox
let p = fs.join("src", "main.ox")
fs.ext(p)     # ".ox"
fs.stem(p)    # "main"
```

### 归档（0.2+）

| 函数 | 说明 |
|---|---|
| `fs.zip(paths, dest, base=null)` | 从文件/目录创建 zip；paths 为字符串或列表；返回条目数 |
| `fs.unzip(archive, dest)` | 解压；**拒绝路径穿越条目**（zip-slip 防护） |
| `fs.tar_gz(paths, dest, base=null)` / `fs.untar_gz(archive, dest)` | tar.gz 同理（tar-slip 同样防护） |

```ox
fs.zip(["notes.md", "logs/"], "bundle.zip")      # -> 3
let n = fs.unzip("bundle.zip", "out/")           # -> 3
fs.tar_gz("dist", "release.tgz", base="dist")    # 条目名相对 dist/
```

归档条目保留顶层名字（`fs.zip("dist", "d.zip")` 存成 `dist/...`）；
传 `base=` 使条目名相对于该目录。**提醒：单引号字符串是原始串**——
含大量花括号的 CSS/JSON 文本请放 `'...'` 里。

### 文件锁（0.3+）

建议锁（advisory lock，POSIX 上用 flock），基于锁文件。锁排除其他
进程与本进程内的其他加锁尝试；锁文件本身会保留（删除它会引入竞态）。

| 函数 | 说明 |
|---|---|
| `fs.lock(path, timeout=null)` ⏳ | 独占获取；最多等 timeout，超时抛错；返回句柄（`path`、`held`、`release()`） |
| `fs.try_lock(path)` | 非阻塞尝试一次；成功返回句柄，失败返回 null |
| `fs.with_lock(path, fn, timeout=null)` ⏳ | 持锁执行 fn()，必然释放 |

```ox
let lk = fs.try_lock("deploy.lock")
if lk == null { print("另一个部署正在运行"); exit(1) }
# ... 独占工作 ...
lk.release()

fs.with_lock("nightly.lock", fn () { run_backup() }, timeout=30s)
```

### 目录监控

| 函数 | 说明 |
|---|---|
| `fs.watch(path, fn, interval=0.5)` ⏳ | 异步监控；以 `{path, kind}` 调用 fn，kind ∈ `"created" "modified" "deleted"`；返回带 `stop()` 的句柄 |

```ox
let w = fs.watch("./src", fn (evt) {
  log.info(f"{evt.kind}: {evt.path}")
})
# ... 稍后
w.stop()
```

## os — 系统与命令

```ox
import os
```

### 命令

| 函数 | 说明 |
|---|---|
| `os.sh(cmd, cwd=null, env={}, timeout=null, input=null)` | 跑 shell 命令；返回 `{ok, code, out, err, cmd}` |
| `os.sh_ok(cmd, ...)` | 只要成败布尔 |
| `os.sh_lines(cmd, ...)` | stdout 按行列表 |
| `os.args()` | 命令行 `--` 之后的脚本参数 |

全局 `sh(...)` 即 `os.sh`。

```ox
let r = sh("ls -la | wc -l", cwd="/srv", timeout=30s)
if r.ok { print(f"{r.out.trim()} 行") }
```

`env={...}` **合并**到当前环境（不替换）；`input=` 喂 stdin。

### 后台进程（0.2+）

`os.start(cmd, cwd=null, env={}, detach=false)` 在独立会话里启动命令，
返回进程句柄：

- 属性：`pid`、`cmd`、`running`
- `wait(timeout=null)` ⏳ → `{ok, code, out, err, cmd, timed_out}`
- `kill()` ⏳ —— 终止**整个进程组**（先 TERM 后 KILL，兜底强杀）
- `out()` / `err()` —— 持续捕获的输出

除非 `detach=true`，脚本退出时进程被自动终止（先于解释器关闭）。

**仅限 POSIX**——`os.start` 依赖进程组（`start_new_session`/
`killpg`）；在 Windows 上会抛出清晰错误而不是行为异常（平台支持
矩阵见 README）。

```ox
let p = os.start("python3 -m http.server 8000")
if not (await net.wait_port("127.0.0.1", 8000, timeout=10s)) {
  print(p.err())
  await p.kill()
  throw error("服务没起来")
}
let r = await p.wait(200ms)
await p.kill()
```

### 身份与硬件

| 函数 | 说明 |
|---|---|
| `os.cwd()` / `os.chdir(path)` / `os.home()` | 目录 |
| `os.hostname()` / `os.user()` / `os.pid()` | 身份 |
| `os.platform()` | `{system, release, version, machine, python, ox}` |
| `os.device()` | `{hostname, platform, cpu, mem, disk, ifaces, local_ip}` 一站式 |
| `os.cpu()` | `{count, load}`（load 为尽力而为） |
| `os.mem()` / `os.disk(path=".")` | `{total, available, used}` / `{total, free, used}` |
| `os.net_ifaces()` / `os.local_ip()` | 网卡名 / 出口 IP |
| `os.which(cmd)` | 可执行文件位置，找不到为 null |

## env — 环境变量

`env.get(name, default=null)` `env.set(name, value)` `env.has(name)`
`env.del(name)` `env.all()`

```ox
let mode = env.get("MODE", "dev")
if env.has("API_KEY") { ... }
```

## log — 日志

| 函数 | 说明 |
|---|---|
| `log.debug/info/ok/warn/error(msg)` | 分级输出（`success` 是 `ok` 的别名） |
| `log.level("debug")` | 最低级别 |
| `log.quiet(true)` | 全部静音 |
| `log.file("app.log", append=true)` | 同时写入文件 |
| `log.table(rows, cols=null)` | 列表套字典打对齐表格 |
| `log.json(obj, pretty=true)` | JSON 输出 |
| `log.line(ch="-", n=60)` | 分隔线 |

```ox
import log
log.info(f"开始同步 {n} 个文件")
log.table(fs.list("."), cols=["name", "size"])
```

## time — 时间

| 函数 | 说明 |
|---|---|
| `time.now()` | epoch 秒（float） |
| `time.epoch()` | epoch 秒（int） |
| `time.now_str(fmt=null)` | 当前时间字符串 |
| `time.format(ts, fmt)` | epoch → 字符串（strftime 记法） |
| `time.parse(str, fmt)` | 字符串 → epoch；无 fmt 时尝试常见布局 |
| `time.iso(ts=null)` / `time.utc(ts=null)` | ISO 8601 本地/UTC |
| `time.parts(ts=null)` | `{year, month, day, hour, minute, second, weekday, date, time}` |

```ox
print(time.now_str("%Y-%m-%d %H:%M"))
print(time.iso())
let ts = time.parse("2026-01-01 00:00:00")
```

## math — 数学与随机

常量与函数：`math.pi e abs floor ceil round sqrt pow exp log log2
log10 sin cos tan atan atan2 min max sum gcd clamp even odd`

随机：`math.rand(n=null)`（`[0, n)` 内整数，无参则 `[0,1)` 浮点）、
`math.randf()`、`math.choice(list)`、`math.shuffle(list)`（返回新列
表）。

```ox
math.clamp(x, 0, 100)
let pick = math.choice(["a", "b", "c"])
```

## crypto — 哈希与标识

| 函数 | 说明 |
|---|---|
| `crypto.md5/sha1/sha256/sha512(data)` | 数据哈希（str/bytes） |
| `crypto.hash(algo, data)` | 按名字哈希 |
| `crypto.hash_file(path, algo="sha256")` | 文件哈希 |
| `crypto.hmac_sha256(key, msg)` | HMAC |
| `crypto.uuid()` | UUID4 |
| `crypto.b64_encode/decode(s)` | Base64 |
| `crypto.url_encode/decode(s)` | 百分号编码 |
| `crypto.random_id(n=8)` | n 字符随机 ID |

```ox
let digest = crypto.sha256("payload")
let token = crypto.random_id(16)
```

## data — 结构化数据

| 函数 | 说明 |
|---|---|
| `data.json_parse(s)` / `data.json_dump(v, pretty=false)` | JSON |
| `data.read_json(path)` / `data.write_json(path, v, pretty=true)` | JSON 文件 |
| `data.csv_parse(s, delim=",", header=true)` | CSV → 字典列表（`header=false` 则为列表列表） |
| `data.csv_dump(rows, delim=",", header=true)` / `data.read_csv` / `data.write_csv` | CSV |
| `data.yaml_parse(s)` / `data.yaml_dump(v)` | YAML（宿主机需有 PyYAML） |
| `data.toml_parse(s)` | TOML（Python 3.11+） |
| `data.merge(a, b, deep=false)` | 字典合并 |
| `data.validate(value, schema)` | 模式校验 → `{ok, errors}` |

`json` 模块是便捷别名：`json.parse/dump/read/write`。

### 模式校验

```ox
let schema = {
  name:  "str",                  # str int float num bool null any list dict
  email: "email?",               # ? = 可选；"int|str" = 联合
  tags:  ["str"],                # [子类型] = 元素为该类型的列表
  addr:  {city: "str", zip: "str?"},
  age:   fn (v) { v >= 0 and v <= 150 },   # 谓词函数
  "_strict": true                # 禁止多余键
}
let r = data.validate(user, schema)
if not r.ok { log.error(f"{r.errors}") }
```

## net — HTTP 与 WebSocket 客户端

```ox
import net

let r = net.get("https://httpbin.org/get", query={q: "ox"},
                headers={"X-Api-Key": key}, timeout=10s)
r.ok          # 2xx？
r.status      # 201
r.headers     # 小写化的响应头字典
r.body        # 文本
r.json        # JSON 时已解析，否则 null
```

`net.post(url, data=null, json=null, form=null, headers={}, timeout=30s)`
——`json=` 发 JSON、`form=` 发表单、`data=` 发原始文本。`net.put/
patch/delete/head` 同形。`http` 模块是请求函数的别名。

| 其他 | 说明 |
|---|---|
| `net.download(url, to, timeout=60s)` | `{ok, path, size, status}` |
| `net.tcp_ping(host, port=80, timeout=2s)` | `{ok, ms}` |
| `net.wait_port(host, port, timeout=10s, interval=100ms)` ⏳ | 端口可连返回 true，超时 false——与 `os.start` 配对 |
| `net.ws(url, headers={}, timeout=10s, verify=true)` | WebSocket 客户端；`verify=false` 接受自签证书（仅 wss） |
| `net.parse_url(url)` | `{scheme, host, port, path, query, fragment, user, password}` |
| `net.url_encode(s)` / `net.url_decode(s)` | 百分号编码 |

### WebSocket 客户端

```ox
let c = net.ws("wss://example.com/socket")
let c2 = net.ws("wss://127.0.0.1:8443/echo", verify=false)  # 自签证书
await c.send("hello")            # 也有 c.send_json(obj)
let msg = c.recv(timeout=5s)     # 下一条消息；超时为 null
c.on("message", fn (m) { ... })  # 推送模式（也有 "close"）
await c.close()
```

## server — 服务器

`serve` 语句是服务器的全部入口——见[语言参考 · 服务器]
(language.md#服务器)。`server` 模块本身只带说明文字。

### 响应安全（0.4+）

- `res.file(path, download=null, root=null)` —— 从磁盘发送文件。
  当 `path` 来自用户输入（req.params / req.query）时务必传 `root=`：
  解析后落在 root 之外的路径一律返回 403；不传 `root` 时允许任意
  路径（供脚本自己选定的可信路径使用）。
- 所有响应头都会被消毒：名字或值中的 CR/LF 会被剔除，用户可控的
  头无法注入额外的响应头。
- 超大请求体（>32MB）在限量排空后返回 413，良性客户端仍能收到
  状态行而不是连接重置。

## wf — 工作流引擎

`wf.run(name, ...)`（选项同全局 `run`）· `wf.list()` ·
`wf.steps(name)` · `wf.status(name)` · `wf.history(name, n=5)` ·
`wf.state_dir(path=null)`（读取/设置历史存放目录）。

### 状态持久化与恢复（0.4.1）

- 每次运行在**首个步骤执行前**就以待办状态 `"running"` 写入
  `<state_dir>/<name>.json`，结束时改写为 `"ok"` / `"failed"`——
  进程中途崩溃会留下可见的 `"running"` 记录，
  `run(name, resume=true)` 将其视为崩溃并从断点恢复
- 同名工作流同时只允许一个活跃运行：第二个并发运行（另一进程或
  本进程内另一任务）会以 `already running` 明确报错，而不是互相
  覆盖状态
- 损坏的状态文件（截断、乱码、JSON 结构错误）会被备份为
  `<name>.json.corrupt`（重复损坏时自动编号）并给出警告；畸形的
  单条运行记录会被丢弃、完好的保留，然后从干净状态继续——
  永远不会以 traceback 崩溃
- 关于 rollback 的一点说明：它是补偿性的——挂在步骤 X 上的
  rollback 在**后续**步骤失败时也会触发；若打算与 `resume=true`
  组合使用，请把 rollback 限定在真正产生半成品的那个步骤上

## co — 并发

| 函数 | 说明 |
|---|---|
| `co.sleep(d)` ⏳ | 睡眠（时长或秒数） |
| `co.all([tasks])` ⏳ | 全部完成，收集结果 |
| `co.any([tasks])` ⏳ | 任一完成 |
| `co.timeout(d, fn)` ⏳ | 超时抛错 |
| `co.every(interval, fn, delay=0)` ⏳ | 周期任务 → 带 `stop()` 的句柄 |
| `co.after(d, fn)` ⏳ | 一次性延时句柄 |
| `co.cron(expr, fn)` | cron 调度 → 带 `stop()` 与 `next()` 的句柄 |
| `co.cron_next(expr, after=null)` | 下一个匹配的 epoch 秒 |
| `co.pending()` | 尚未完成的任务数 |

### cron 调度（0.3+）

经典五字段 cron（分 时 日 月 周），**本地时间**，支持 `*`、`*/n`、
`a-b`、`a-b/n`、列表、`mon-fri`、`jan-dec` 与 `@hourly @daily
@midnight @weekly @monthly @yearly` 别名。日与周同时受限时，任一命中
即触发（经典规则）。任务失败记日志、保持调度。

```ox
let nightly = co.cron("30 3 * * *", fn () { run_backup() })
let weekday = co.cron("0 9 * * mon-fri", fn () { standup() })
print(f"下次触发：{time.iso(nightly.next())}")
nightly.stop()
```

## events — 事件总线

`events.list()` → `{名字: 处理器数}` · `events.off("名字")`（无参清空
全部） · `events.emit(名字, 载荷)`。

## verify — 测试断言

| 函数 | 说明 |
|---|---|
| `verify.eq(a, b, msg=null)` | 深相等 |
| `verify.ne(a, b, msg=null)` | 不等 |
| `verify.true(x)` / `verify.false(x)` | 真值断言 |
| `verify.has(coll, v)` | 成员断言（list/str/dict） |
| `verify.approx(a, b, eps=1e-9)` | 浮点近似 |
| `verify.throws(fn)` | 执行 fn，返回抛出的错误值；不抛则测试失败 |
| `verify.skip(msg=null)` | 将当前测试标记为跳过（如工具不可用）；`ox test` 单独统计跳过数且退出码为 0 |

## py — Python 桥

```ox
import py

let math = py.import("math")          # 模块与类（"datetime.datetime" 也行）
math.sqrt(2.0)                        # 直接调用

py.eval("2 + 3")                      # 求值 Python 源码
py.exec("X = 1")                      # 执行（共享命名空间）
py.exec_file("script.py")
py.pip("install requests")            # 管包（sh 风格结果字典）
py.version()
```

数值、字符串、列表、字典透明互转。ox 函数**不**过桥——传数据，别传
回调。给 Python 侧注入变量用 `py.exec`：

```ox
py.exec(f"TMP = \"{path}\"")           # 把 ox 的 path 注入 Python 命名空间
py.exec("import shutil; shutil.copy(TMP, TMP + '.bak')")
```

## c — C FFI

```ox
import c

let libm = c.lib("m")                     # 查找并加载共享库
let pow_fn = libm.fn("pow",               # 符号名
                     [c.double, c.double],# 参数类型
                     c.double)            # 返回类型
pow_fn(2.0, 10.0)                         # -> 1024.0

let libc = c.lib("c")
libc.fn("strlen", [c.char_p], c.size_t)("hello ox")   # -> 8
```

类型：`c.int c.uint c.long c.ulong c.float c.double c.bool c.char_p
c.void_p c.size_t c.int8 c.int16 c.int32 c.int64 c.uint8 c.uint16
c.uint32 c.uint64`。字符串按 UTF-8 字节传入；`char_p` 返回值解码为字
符串。绝对路径加载用 `c.lib("/完整/路径.so")`。

## 值方法

每种值自带方法，无需 import（语言参考的[值方法](language.md#值方法)
一节有完整清单）。这里给出常用签名与示例：

### str

| 方法 | 签名/示例 |
|---|---|
| `split` | `"a,b".split(",")` → `["a", "b"]`；无参按空白切 |
| `join`* | 见 list.join |
| `replace` | `"aba".replace("a", "c")` → `"cbc"` |
| `has` / `contains` | `"hello".has("ell")` → true |
| `index` | 子串位置，找不到 -1 |
| `trim` / `trim_left` / `trim_right` | 去两端空白 |
| `pad_left` / `pad_right` | `"5".pad_left(3, "0")` → `"005"` |
| `upper/lower/capitalize/title/swapcase` | 大小写变换 |
| `startswith` / `endswith` | 前后缀 |
| `chars` | 字符列表 |
| `repeat` | `"ab".repeat(3)` |
| `slice` | `"abcd".slice(1, 3)` → `"bc"` |
| `len/empty/first/last/reverse/split_lines` | 顾名思义 |

### list

| 方法 | 签名/示例 |
|---|---|
| `push` / `push_all` | 尾部追加（返回列表自身，可链） |
| `pop` / `shift` / `unshift` | 尾删/头删/头插 |
| `insert` / `remove` / `remove_at` | 按位插入/按值删首个/按位删 |
| `map` / `filter` / `each` | `[1,2].map(fn (x) { x * 2 })` |
| `find` / `find_index` / `any` / `all` | 谓词查找 |
| `reduce` | `[1,2,3,4].reduce(fn (a, b) { a + b })` → 10 |
| `sort` / `sort_by` | `sort(key=fn)`；`sort_by("字段名")` |
| `join` | `[1, 2].join("-")` → `"1-2"`（默认 `", "`） |
| `concat` / `flatten` / `unique` / `reverse` / `clone` | 变换（均返回新值，原列表不变） |
| `has` / `contains` / `count` / `index` | 成员查询 |
| `sum/min/max/avg` | 聚合 |
| `zip` | `l1.zip(l2)` → `[[a1,b1], ...]` |
| `slice` / `first` / `last` / `len` / `empty` / `indexes` | 基础 |

### dict

| 方法 | 签名/示例 |
|---|---|
| `get` | `d.get("k", 默认)` |
| `set` / `del` | 写/删（del 缺键返回 null 不报错） |
| `keys` / `values` / `items` | items 为 `[[k, v], ...]` |
| `has` / `contains` | 键存在？ |
| `merge` / `update` | merge 返回新字典（`deep=true` 深合并）；update 原地 |
| `pick` / `omit` | 选键/去键，返回新字典 |
| `map_values` / `filter` | `d.map_values(fn (v, k) { ... })` |
| `sort_keys` | 按键排序的新字典 |
| `clone` / `first` / `len` / `empty` | 基础 |

### number / range

`n.abs() floor() ceil() round(位数=0) clamp(lo, hi)`（时长保留时长类
型）；`n.times(fn (i) { ... })` 重复执行；`r.len() r.to_list()
r.empty()`。
