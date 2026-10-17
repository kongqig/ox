# ox 命令行手册

```
ox <命令> [选项]
```

全局选项：`--no-color`（强制纯文本输出）、`--version`。

## ox run

```
ox run <文件|目录> [--check] [-- 传给脚本的参数]
```

- 文件：运行该 `.ox` 文件
- 目录：读 `ox.proj.json`（用其 `entry`，默认 `main.ox`），否则依次
  尝试 `main.ox`、`app.ox`、`index.ox`
- 无参数：对当前目录做同样的解析
- `--check`：执行前先跑静态分析（快速失败）
- `--` 之后的全部内容通过 `os.args()` 交给脚本

退出码：`0` 成功 · `1` 运行时错误 · `2` 用法/解析错误 · `130` 被
Ctrl+C 中断。

```sh
ox run deploy.ox -- --env prod --dry-run
```

```ox
# deploy.ox 内部
let args = os.args()          # ["--env", "prod", "--dry-run"]
```

后台进程（`os.start`）在脚本结束时自动清理；`detach=true` 的除外。

## ox test

```
ox test [文件|目录] [--json]
```

发现 `tests/`（默认）或指定路径下的 `*.test.ox`。每个文件的顶层语
句先执行（做夹具），然后逐个运行 `test "名字" { ... }` 块；超时用
`test "慢操作", timeout=5s { ... }` 控制。

- `--json`：同时写出 `ox-test-report.json`
- 有失败则退出 `1`
- 每个测试文件结束后清理它启动的后台进程

## ox check

```
ox check <文件|目录> [--strict]
```

静态分析，检测：未定义变量、`let` 重赋值、不可达代码、未使用变量、
循环外的 `break`/`continue`、函数外的 `return`、未知模块或缺失的导
入路径、重复的工作流/路由/测试名，以及**穿越表达式化块的
return/break/continue**（编译不支持，见语言参考）。

`--strict` 把警告也算错误。分析错误退出 `1`，解析错误退出 `2`。

## ox build

```
ox build <文件|目录> [-o 输出] [--emit py] [--binary]
```

三个阶段：

1. **check** —— 完整静态分析必须通过
2. **transpile** —— 程序转译成可读、语义保真的 Python（每个运算符
   和调用都经由 `ox.runtime` 助手，行为与解释器一致）
3. **package** —— 转译产物 + ox 运行时打包成自包含 zipapp 可执行文
   件（默认 `build/<名字>`）

```sh
ox build backup.ox -o backup      # ./backup 在任何有 python3.9+ 的机器上可跑
ox build backup.ox --emit py      # 只看生成的 Python
ox build backup.ox --binary       # ./backup.bin 完全不需要 Python
```

说明：

- zipapp 在目标机需要 python3.9+——仅此而已
- `--binary` 用 PyInstaller 冻结成单文件可执行（约 10 MB），目标机
  无需装 Python；构建机需要
  `python3 -m pip install pyinstaller`
- import 的**本地 .ox 模块**照常工作：运行时启动时加载并解释它们
  （编译/解释混合执行）
- `test` 块会注册但不在编译产物里自动运行；测试保持用 `ox test` 跑

## ox fmt

```
ox fmt [文件|目录] [--check]
```

原地格式化 `.ox` 源码。无参数时格式化当前目录树（跳过隐藏目录、文
档和 `ox/` 包自身）。`--check` 只报告哪些文件会变、有则退出 `1`
——给 CI 用。

格式化器刻意保守：**不合并、不重排任何东西，不丢任何记号或注释**，
输出重新词法化后与输入的记号流完全一致。它只做规整：

- 两空格缩进（按括号深度逐行重算）
- 行内空格（运算符、逗号、字典冒号、调用括号、关键字参数）
- 连续空行折叠为一；去行尾空白；文件恰好以一个换行结尾
- shebang、注释、单双引号的选择、数字写法（`0x1F`、`1_000`、
  `150ms`、`1.5s`）原样保留

幂等：对已格式化的代码再跑一次不变。

## ox repl

交互式会话。语句跨输入保持；表达式结果自动打印。`Ctrl+D` 或
`.exit` 退出，`.help` 看提示。花括号不闭合时自动续行。

## ox init

```
ox init [名字] [--force]
```

脚手架一个项目：`main.ox`、`tests/main.test.ox`、`ox.proj.json`、
`README.md`、`.gitignore`。

```json
{
  "name": "my-tool",
  "version": "0.1.0",
  "entry": "main.ox",
  "ox": ">=0.1.0"
}
```

## ox version

打印 ox 版本、Python 版本与平台。

## 环境变量

| 变量 | 作用 |
|---|---|
| `NO_COLOR` | 关闭彩色输出 |
| `OX_DEBUG` | 服务器在 500 响应里包含错误详情 |
| `OX_STATE_DIR` | 工作流历史目录（默认 `.ox/state`） |

## shebang

ox 脚本可以直接当可执行文件：

```sh
#!/usr/bin/env -S ox run --
```

shebang 行在 ox 里是注释，文件内不需要任何额外处理。

## 退出码速查

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 运行时错误 / 测试失败 / check 发现错误 / fmt --check 有差异 |
| 2 | 用法错误、解析错误 |
| 130 | Ctrl+C 中断 |

脚本里 `exit(n)` 的 n 原样透传。
