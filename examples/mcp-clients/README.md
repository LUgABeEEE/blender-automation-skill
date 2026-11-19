# MCP 客户端配置片段

每个文件都是**可直接复制**的配置：内容与 [docs/mcp.md](../../docs/mcp.md) 的片段一致。

| 文件 | 放到哪里 | 备注 |
|---|---|---|
| `claude-code.mcp.json` | 仓库根 `.mcp.json` | Claude Code 项目作用域；等价命令 `claude mcp add --scope project blender -- blender-automation-skill-mcp` |
| `cursor-mcp.json` | `<项目>/.cursor/mcp.json` 或 `~/.cursor/mcp.json` | Cursor 项目级 / 全局 |
| `codex-config.toml` | 追加到 `~/.codex/config.toml` | 顶层键是 `mcp_servers`（不是 `mcpServers`）；等价命令 `codex mcp add blender -- blender-automation-skill-mcp` |
| `dsh-cordis.patch.yml` | profile 的 `cordis.patch.yml` 里已有的 `insert:` 列表 | 插件 `@deepseek-ai/dsh-mcp-client`；改完重启 dsh-web |

## 前提

这些片段都假设 `blender-automation-skill-mcp` 已在**客户端能看见的 PATH** 上：

```bash
python -m pip install -e ".[mcp]"        # 含 mcp SDK，装完 console script 进 venv/bin
(sleep 10 | timeout 3 blender-automation-skill-mcp); echo "exit=$?"   # 期望 124
```

## 客户端看不见那个命令时（GUI 客户端常见）

把 `command` 换成**解释器的绝对路径**，用模块入口拉起同一个 server：

```json
{
  "mcpServers": {
    "blender": {
      "type": "stdio",
      "command": "/absolute/path/to/repo/.venv/bin/python",
      "args": ["-m", "model_loop.mcp_server"],
      "env": {}
    }
  }
}
```

Windows 把 `command` 写成 `C:/absolute/path/to/repo/.venv/Scripts/python.exe`（正斜杠或双反斜杠都行）。

## 接上之后先验一句

在客户端里调 `blender_capabilities`：返回 JSON 里 `package.name` 是 `blender-automation-skill`、
`blender.found` 为 `true` 就通了；`found` 为 `false` 就看 `error` 里的路径提示。
