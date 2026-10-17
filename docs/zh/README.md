# ox 中文文档

> ox 是一门为**自动化与工具链**设计的小语言：文件、Shell 命令、HTTP
> 服务与客户端、WebSocket、数据加工、并发与定时任务——这些日常工
> 作在 ox 里都是一等公民。

| 文档 | 内容 | 适合谁 |
|---|---|---|
| [入门教程](tutorial.md) | 30 分钟从零上手：安装、语法速览、实战示例 | 所有人，从这里开始 |
| [语言参考](language.md) | 完整语法规范：词法、类型、优先级表、模式匹配、工作流、服务器 | 写 ox 的人 |
| [标准库手册](stdlib.md) | 18 个模块名（16 个实体模块 + json/http 别名）每个函数的说明，含值方法全表 | 写 ox 的人 |
| [命令行手册](cli.md) | run/test/check/build/fmt/repl/init 全部用法、退出码、环境变量 | 用 ox 工程化的人 |

英文文档见[仓库 docs/ 目录](../)。两套文档描述同一版本（0.3.1）的
行为；如有出入，以 `ox run` 的实际表现为准并提 issue。

## 三分钟预览

```ox
# 并发抓取 + 结构化输出
let results = await [
  spawn { net.get("http://example.com") },
  spawn { net.get("http://example.org") },
]
for r in results {
  if r.ok { print(f"{r.status} {r.body.len()} 字节") }
}

# 一个带重试与回滚的部署流程
workflow "deploy" {
  step "build"   { sh("make build") } retry 3 backoff 2s
  step "migrate" { sh("migrate up") } rollback { sh("migrate down") }
  step "health"  {
    verify net.get("http://localhost:3000/healthz").ok, "健康检查失败"
  }
}
run("deploy", dry=true)    # 先看看计划
```

```ox
# 一个完整的 HTTP + WebSocket 服务器
serve 8080 {
  get "/hello/:name" { res.json({msg: "你好 " + req.params.name}) }
  static "/assets"   "./public"
  ws "/chat"         { conn.on("message", fn (m) { conn.send(m) }) }
}
```

## 设计哲学（为什么是这副样子）

- **小**：一门能整个装进脑子的语言。没有类、没有继承、没有泛型——
  自动化脚本用不上它们
- **可预期**：命令失败返回 `{ok: false}` 而不是抛异常（可预期失败）
  vs 程序错误一律是可捕获的 error 值（不可预期失败），两类错误处理
  路径从第一天就分开
- **双模式**：动态解释（`ox run`）方便试错；静态编译（`ox build`）
  产出免依赖的单文件可执行——同一段程序两条路行为一致，静态分析器
  是这条契约的守门人
- **生态直通**：Python（`py` 模块）与 C（`c` 模块）一个 import 之
  遥，不重造轮子

## 平台支持

| 平台 | 状态 | 说明 |
|---|---|---|
| Linux（glibc，Python 3.12+） | **完整支持** | 全部 190 个测试在此平台运行 |
| macOS | 支持（本仓未实测） | 同为 POSIX，`fcntl`/进程组行为一致 |
| Windows | **不支持** | `fs.lock`（flock）与 `os.start`（进程组）仅限 POSIX；CLI 会打印警告，这些 API 抛出清晰错误。WSL2 可用 |

ox 的定位是单机、单进程、可信环境下的工具语言：`py.exec` / `py.eval`
/ `c.lib` 是刻意的任意代码执行桥，**不是沙箱**——不要运行来路不明的
ox 程序。

## 性能预期

数量级参考见 [性能基线](perf.md)：启动约 256 ms；解释器适合 I/O 密集
自动化；CPU 密集用 `ox build` 编译后约快 3.4 倍；1k 并发任务净开销
约 20 ms。

## 版本

当前 0.4.0。变更记录见仓库 [CHANGELOG.md](../../CHANGELOG.md)。
