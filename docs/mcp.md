# MCP 接入：让任何 agent 直接调用这套闭环

`blender-automation-skill` 把「参数空间 → 无头渲染 → 量化打分 → 搜索 → 报告」暴露成 **6 个 MCP 工具**。
任何支持 [Model Context Protocol](https://modelcontextprotocol.io) 的客户端（Claude Code / Codex / Cursor / DSH / 自研 agent）
都能在同一套工具上跑闭环，不用写一行 Python 胶水。

| 项 | 值 |
|---|---|
| Server 名 | `blender-automation-skill` |
| 传输 | stdio（客户端拉起本地子进程，逐行收发 JSON-RPC 2.0） |
| 入口 | `blender-automation-skill-mcp`（等价 `python -m model_loop.mcp_server`） |
| 工具数 | 6 |
| 额外依赖 | 本机 Blender 4.x —— 只有真正渲染的工具需要，`blender_report` 等不需要 |

本篇是**接入手册**：装哪里、每个客户端怎么填、参数表、报错怎么读。
闭环本身怎么设计见 [自迭代闭环](self-iteration.md)，脚本边界见 [建模工作流](modeling-workflow.md)。

## 0. 一分钟版

```bash
# 1) 装进同一个 Python 环境（含 mcp SDK）
python -m pip install -e ".[mcp]"          # 仓库内；或 pip install "blender-automation-skill[mcp]"

# 2) 确认入口能常驻：3 秒后仍在跑 ⇒ 退出码 124
#    必须让 stdin 保持打开；stdin 一结束 server 会干净退出 0 —— 那是正常关机，不是崩溃
(sleep 10 | timeout 3 blender-automation-skill-mcp); echo "exit=$?"

# 3) 接进客户端（以 Claude Code 为例）
claude mcp add --scope project blender -- blender-automation-skill-mcp
```

然后在客户端里说一句：**「调 blender_capabilities，告诉我这台机器的 Blender 路径和版本」**。
返回里 `blender.found` 为 `true` 就通了。

## 1. 这个 server 做什么、不做什么

| 做 | 不做 |
|---|---|
| 把同一个闭环以工具形式交给 agent | 不内置模型资产，几何全由你的 Blender 脚本决定 |
| 每次渲染都受内存上限和超时约束 | 不做分布式、不做并行调度 |
| 预期失败返回 `{"ok": false, "error": ...}` | 不为错误抛异常打断 agent 的回合 |
| 产物落盘（PNG / history.json / report.html） | 不把二进制塞进协议的返回体 |
| 6 个工具参数固定、可枚举 | 不接受任意 Python 代码（只接受脚本**路径**） |

工具调用成功与否和 `ok` 字段**不是一回事**：`blender_capabilities` 的 `ok` 表示「这台机器有可用的 Blender」，
没有 Blender 时它照样是一次成功的工具调用（`ok: false` + `error` + `hint`）。

## 2. 安装

### 2.1 从仓库源码（推荐，开发态）

```bash
git clone https://github.com/LUgABeEEE/blender-automation-skill
cd blender-automation-skill
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install -e ".[mcp]"
```

`[mcp]` 这个 extra 只装 `mcp`（SDK）；numpy / Pillow 是基础依赖，装包时自动带上。

### 2.2 从构建产物（无网环境）

```bash
python -m pip install dist/blender_automation_skill-0.1.0-py3-none-any.whl "mcp>=1.9"
```

### 2.3 装完先自检（不依赖任何客户端）

```bash
(sleep 10 | timeout 3 blender-automation-skill-mcp > /dev/null 2>&1); echo "exit=$?"   # 期望 124（常驻，未崩溃）
python -m pytest -q tests/test_mcp_e2e.py     # 真实 stdio 握手 + 6 工具 + 一次调用，约 5 秒
```

第一条是「进程没崩」，第二条是「协议对得上」——两条都过，再谈接客户端。

> 为什么是 `sleep 10 |`：server 在 stdin 上等 JSON-RPC，**stdin 关闭（EOF）它会干净退出 0**。
> 直接 `timeout 3 blender-automation-skill-mcp < /dev/null` 得到 0 是正常关机，不是崩溃；
> 要观察「常驻」必须让 stdin 一直开着（管道 / 客户端的 PIPE）。

### 2.4 Blender 本体

工具参数 `blender` 的默认值就是字符串 `blender`（走 PATH）。三种处理方式，从省事到稳妥：

1. 让 Blender 在 PATH 里（Linux 包管理器 / macOS 符号链接）；
2. 客户端配置的 `env` 里补 `PATH`；
3. **每次调用显式传绝对路径**（最可靠，也是 GUI 客户端下唯一稳的做法）：
   `{"blender": "/opt/blender-4.2/blender"}`，Windows 写 `C:/Program Files/Blender Foundation/Blender 4.2/blender.exe`（正斜杠或双反斜杠）。

## 3. 通用 JSON 配置（大多数客户端直接吃这份）

仓库里现成的：`examples/mcp.json`（通用）、`examples/mcp-clients/`（按客户端分的片段）。

```json
{
  "mcpServers": {
    "blender": {
      "type": "stdio",
      "command": "blender-automation-skill-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

当客户端的 PATH 里没有那个 console script（GUI 客户端常见：从桌面图标启动时 PATH 更短），
改成用它**能看见的解释器**显式拉起同一个 server：

```json
{
  "mcpServers": {
    "blender": {
      "type": "stdio",
      "command": "/path/to/repo/.venv/bin/python",
      "args": ["-m", "model_loop.mcp_server"],
      "env": {}
    }
  }
}
```

Windows 上 `command` 写成 `C:/path/to/repo/.venv/Scripts/python.exe`。这两种写法**完全等价**，第二种只是把「找命令」换成「找解释器」。

## 4. 各客户端接入

### 4.1 Claude Code

```bash
# project 作用域：写进仓库根的 .mcp.json（可入库、可分享）
claude mcp add --scope project blender -- blender-automation-skill-mcp

# 只想给自己用：默认作用域 local，写 ~/.claude.json
claude mcp add blender -- blender-automation-skill-mcp

# 检查
claude mcp list
```

或者直接把 §3 的 JSON 存成仓库根的 `.mcp.json`（或任意路径，再用 `claude --mcp-config <file>` 指过去）。

- 三个作用域：`local`（默认，私有于本项目的 `~/.claude.json`）、`project`（`.mcp.json`，建议入库）、`user`（全局）。
- 客户端内 `/mcp` 可以看连接状态和工具清单。
- 首次启动 server 有超时，默认 30 秒；机器慢（冷启动 import numpy/Pillow）可用 `MCP_TIMEOUT` 环境变量调大。
- 工具名在 Claude Code 里是 `mcp__blender__blender_capabilities` 这种全名——用全名授权，别只写短名。

### 4.2 Codex CLI

```bash
codex mcp add blender -- blender-automation-skill-mcp
```

等价于手写 `~/.codex/config.toml`（注意顶层键是 `mcp_servers`，**不是** `mcpServers`）：

```toml
[mcp_servers.blender]
command = "blender-automation-skill-mcp"
args = []
```

需要环境变量时用子表：

```toml
[mcp_servers.blender.env]
PATH = "/usr/local/bin:/usr/bin:/bin"
```

同一个 server 要么给 `command`（stdio），要么给 `url`（HTTP），不要两个都写。

### 4.3 Cursor

项目级 `.cursor/mcp.json` 或全局 `~/.cursor/mcp.json`，内容就是 §3 的 JSON（`type: "stdio"` 保留）：

```json
{
  "mcpServers": {
    "blender": {
      "type": "stdio",
      "command": "blender-automation-skill-mcp",
      "args": []
    }
  }
}
```

- Settings → MCP 面板里能看到 server 和它的 6 个工具；
- 默认每次工具调用都要确认（Cursor 的策略），批量跑搜索时可以把该 server 设为自动批准；
- 报「command not found」就换成 venv 解释器写法（§3 第二份 JSON）。

### 4.4 DSH（DeepSeek Harness）

DSH 把 MCP server 作为插件注册在 profile 的 `cordis.patch.yml` 里（追加到已有的 `insert:` 列表，缩进与同级插件对齐）：

```yaml
insert:
    - id: mcp-blender-automation-skill
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: blender
        transport: stdio
        command: blender-automation-skill-mcp
        args: []
```

- 插件名是 `@deepseek-ai/dsh-mcp-client`（DSH 0.2.x 的写法）；如果你的 profile 里已有同类条目，照着它们的字段抄最稳。
- 改完要**重启 dsh-web** 才生效；临时停用就在条目上加 `disabled: true`。
- 依赖装在别的环境里时补 `env`（本机 `mcp-minas` 就是这么写的）：

```yaml
      config:
        serverName: blender
        transport: stdio
        command: /usr/bin/python3
        args: ['-m', 'model_loop.mcp_server']
        cwd: /path/to/repo
        env:
          PYTHONPATH: /path/to/repo/src
```

- 工具在 agent 眼里会变成 `mcp__blender__blender_optimize` 这样的全名。

### 4.5 其它客户端（Windsurf / Cline / 自研）

只要客户端吃 `mcpServers` 这份 JSON，就照 §3 填；只要它支持 stdio，就能用。
判断标准只有三条：**能拉起子进程**、**按行收发 JSON-RPC 2.0**、**能列出 `tools/list`**。

## 5. 6 个工具与参数

| 工具 | 必填参数 | 作用 |
|---|---|---|
| `blender_capabilities` | — | 探测 Blender 路径/版本、本机 CPU 与内存 |
| `blender_bench` | — | 冷启动、渲染、布尔耗时与峰值 RSS |
| `blender_run_script` | `script` | 用一组 JSON 参数跑一次 Blender 脚本，回传产物 |
| `blender_optimize` | `script` `target_png` `space` | 对目标剪影做坐标下降搜索（最大化掩膜 IoU） |
| `blender_demo` | — | 内置剪影自迭代示例，零资产跑通闭环 |
| `blender_report` | `history` | history.json → 单文件 HTML 报告 |

所有工具都返回**一个 JSON 字符串**（mcp 2.x 另外在 `structuredContent.result` 里给同一份内容）。

### 5.1 `blender_capabilities`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `blender` | string | `"blender"` | Blender 可执行文件路径或命令名 |

返回：`ok`、`package{name,version}`、`host{platform,python,cpu_count,mem_total_mb,max_rss_mb,blender_on_path}`、
`blender{binary,found,version}`、`defaults{memory_mb,timeout_s}`；找不到 Blender 时另有 `error` 与 `hint`。

```json
{
  "ok": false,
  "package": {"name": "blender-automation-skill", "version": "0.1.0"},
  "host": {"platform": "Linux-6.8.0-x86_64-with-glibc2.39", "python": "3.12.3", "cpu_count": 16},
  "blender": {"binary": "/nonexistent/blender-binary", "found": false, "version": null},
  "defaults": {"memory_mb": 8192, "timeout_s": 900.0},
  "error": "Blender binary not found: '/nonexistent/blender-binary'. Pass --blender /path/to/blender or install Blender (>= 3.6).",
  "hint": "Install Blender 4.x and pass its absolute path as 'blender'."
}
```

### 5.2 `blender_bench`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `out_dir` | string | `"out/bench"` | 产物目录（建议绝对路径） |
| `blender` | string | `"blender"` | Blender 路径或命令名 |
| `memory_mb` | int | `8192` | 每个子进程的地址空间上限 |
| `timeout_s` | number | `900.0` | 单次子进程的墙钟上限 |

返回：`ok`、`out_dir`、`report`（冷启动/渲染/布尔耗时与峰值 RSS）。

### 5.3 `blender_run_script`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `script` | string | **必填** | Blender 脚本路径 |
| `params` | object<string, number> | `null` | 传给脚本的参数 JSON |
| `out_dir` | string | `"out/run"` | 产物目录，渲染图落在 `<out_dir>/render.png` |
| `resolution` | int | `128` | 渲染边长（像素） |
| `blender` | string | `"blender"` | Blender 路径或命令名 |
| `memory_mb` | int | `8192` | 地址空间上限 |
| `timeout_s` | number | `900.0` | 单次墙钟上限 |

返回：`ok`、`exit_code`、`duration_s`、`png`、`stdout_tail`、`stderr_tail`（后两者各截 2000 字符）。

### 5.4 `blender_optimize`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `script` | string | **必填** | Blender 脚本路径（每次评估跑一次） |
| `target_png` | string | **必填** | 目标剪影 PNG |
| `space` | object / array | **必填** | 参数空间，两种写法见下 |
| `out_dir` | string | `"out/loop"` | 产物目录 |
| `resolution` | int | `128` | 渲染边长 |
| `rounds` | int | `4` | 坐标下降的轮数 |
| `budget` | int | `60` | 评估次数上限（总预算） |
| `blender` | string | `"blender"` | Blender 路径或命令名 |
| `memory_mb` | int | `8192` | 地址空间上限 |
| `timeout_s` | number | `900.0` | 单次墙钟上限 |

返回：`ok`、`best{params,score,metrics,artifacts}`、`scores[]`、`evaluations`、`history_json`、`report_html`。

`space` 的两种写法完全等价：

```json
{"width": [0.4, 2.0], "height": [0.3, 1.6, 1.0]}
```

```json
[{"name": "width", "low": 0.4, "high": 2.0, "default": 1.0},
 {"name": "height", "low": 0.3, "high": 1.6, "default": 1.0}]
```

`[min, max]` 形式的第三个数字是默认值，省略时取中值。

### 5.5 `blender_demo`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `out_dir` | string | `"out/demo"` | 产物目录 |
| `rounds` | int | `4` | 坐标下降轮数 |
| `budget` | int | `60` | 评估次数上限 |
| `resolution` | int | `128` | 渲染边长 |
| `blender` | string | `"blender"` | Blender 路径或命令名 |

返回：`ok`、`best`、`evaluations`、`truth_hint`（示例的隐藏真值，仅用于对照）、`history_json`、`report_html`。

### 5.6 `blender_report`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `history` | string | **必填** | `history.json` 路径 |
| `out` | string | `"out/report.html"` | 输出 HTML 路径 |
| `title` | string | `"Self-iteration report"` | 报告标题 |

返回：`ok`、`report_html`、`evaluations`。这个工具**不需要 Blender**，可以离线重放任意历史。

### 5.7 脚本契约（`blender_run_script` / `blender_optimize`）

```
blender --background --python <script> -- <params-json> <png-out> [resolution]
```

脚本从 `sys.argv` 里 `--` 之后读三个参数：参数字典的 JSON、输出 PNG 路径、渲染边长；渲染一张剪影后 `exit 0`。
完整可运行的例子在 `src/model_loop/demo.py`。

## 6. 验证接入（三档，从便宜到贵）

| 档 | 命令 | 通过的标志 |
|---|---|---|
| 进程 | `(sleep 10 \| timeout 3 blender-automation-skill-mcp); echo $?` | `124`（还在跑，没崩） |
| 协议 | `pytest -q tests/test_mcp_e2e.py` | 9 passed |
| 客户端 | 在客户端里调一次 `blender_capabilities` | 返回 JSON 里 `package.name` 正确 |

不装任何 MCP 客户端也能验协议（纯 stdlib，逐行 JSON-RPC）：

```bash
python - <<PY
import json, subprocess, sys
proc = subprocess.Popen([sys.executable, "-m", "model_loop.mcp_server"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def send(message):
    proc.stdin.write(json.dumps(message) + "\n"); proc.stdin.flush()
send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "smoke", "version": "0"}}})
print(json.loads(proc.stdout.readline())["result"]["serverInfo"])
send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
print([tool["name"] for tool in json.loads(proc.stdout.readline())["result"]["tools"]])
proc.terminate()
PY
```

## 7. 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 工具返回 `ok: false`，`error` 含 `Blender binary not found` | 传给工具的 `blender` 不在 PATH 或路径写错 | 传绝对路径；Windows 注意空格与斜杠 |
| 客户端里 server 起不来 / 工具列表为空 / 30 秒超时 | 那个环境没装 `mcp` SDK | 用**同一个**解释器 `pip install -e ".[mcp]"`；或配置里写 venv 绝对 python |
| 报 `command not found: blender-automation-skill-mcp` | 客户端 PATH 里没有该 console script | 换成 `{"command": "/abs/.venv/bin/python", "args": ["-m", "model_loop.mcp_server"]}` |
| `blender_optimize` 返回 `bad input: ...` | `space` / `target_png` / `script` 形状不对或文件不存在 | 看 `error` 冒号后的具体原因，`space` 用 §5.4 两种写法之一 |
| 参数类型完全不对（例如 `space` 传了字符串） | 在进函数前就被 SDK 拒了 | 修参数类型；这类错客户端会显示校验信息，不是 `{"ok": false}` |
| 工具调用「超时」但 Blender 在跑 | 客户端超时比渲染短，或 `timeout_s` 太小 | 调大 `timeout_s`；把 `budget` 先降到 10–20 次 |
| 产物跑到奇怪的地方 | 相对 `out_dir` 落在 server 的 cwd（客户端启动目录），不一定是仓库根 | `out_dir` 一律用绝对路径 |
| 客户端解析不了 server 输出 | 有东西往 stdout 打了日志 | 不要在 server 里 `print`；`tests/test_mcp_e2e.py` 有专门的守护用例 |

几条经验：

- **先 `blender_capabilities` 再干活**。`ok: false` 就把 `error` 原样报回去，别继续调渲染工具。
- **首次接触用小预算**：`budget: 10~20` 试通路，确认 IO 与产物路径都对，再放大。
- **报告路径优先回报**：把 `report_html` / `history_json` 的路径给用户，比贴一屏 `stdout_tail` 有用。

## 8. 资源、并发与安全

- `memory_mb`（默认 8192）是**每个 Blender 子进程**的地址空间上限（POSIX 上走 `RLIMIT_AS`），不是整机预算。
- `timeout_s`（默认 900）是**单次**子进程的墙钟上限；`blender_optimize` 的 `budget` 次评估各算一次。
- 串行锁：MCP 工具**没有**暴露 lock 参数（CLI 的 `--lock` 才有）。要让同一台机器上的渲染排队，请让客户端只发一个并发调用，
  或改用 CLI 批量跑（`--lock /tmp/blender.lock`）。
- 不要拿它跑不可信脚本：工具只接受脚本**路径**，脚本本身以当前用户权限运行，没有沙箱。
- 不要把 `/path/to/blender` 指到来路不明的二进制。

## 9. 哪些是实跑，哪些是查文档

| 内容 | 来源 |
|---|---|
| 握手、6 个工具、参数默认值、返回字段、错误文案 | 本仓库实跑：`.venv/bin/python -m pytest -q tests/test_mcp_e2e.py` |
| 进程常驻（`exit=124`）、stdin EOF 干净退出、stdout 只有 JSON-RPC | 本机命令实跑 |
| DSH 的插件名与字段 | 本机 `~/.dsh/profiles/<profile>/cordis.patch.yml` 里同类条目（其中有条 blender MCP 的历史配置） |
| Claude Code / Codex / Cursor 的命令与字段 | 各客户端官方文档（2026-11 查阅）；本机未安装这些客户端，未实跑 |

如果你手里的客户端版本比文档新，以它自己的 `--help` / 配置校验为准：字段名对不上时，先用 §3 的通用 JSON 试通，再换成客户端原生文件。

## 10. 参考

- 协议规范：<https://modelcontextprotocol.io>
- 本仓库：`src/model_loop/mcp_server.py`（工具定义）、`tests/test_mcp_e2e.py`（真实 stdio 握手测试）
- 客户端配置片段：`examples/mcp.json`、`examples/mcp-clients/`
- 相邻文档：[建模工作流](modeling-workflow.md)、[机器调优](machine-tuning.md)、[自迭代闭环](self-iteration.md)
