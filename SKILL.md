---
name: blender-automation-skill
description: Drive headless Blender modelling from any agent — parameter search, quantified silhouette scoring and self-iteration loops over MCP or CLI. Use when a task needs repeated render/evaluate/optimise cycles on 3D models instead of hand-tuning in the Blender GUI.
license: MIT
---

# blender-automation-skill

Closed-loop modelling for Blender: **parameter space → headless render → quantified score → search → HTML report**.
Every step is scripted, cached and reproducible; Blender is only ever started as a bounded subprocess.

## When to use it

- A model needs repeated geometry tweaks measured against a target (silhouette, mask, custom metric).
- You want to stop hand-tuning in the Blender GUI and instead search a parameter space.
- A machine's render/boolean cost must be known before running a long batch.
- You need an auditable history of every evaluation and a single-file report.

## Prerequisites

- Blender 4.x installed locally (the tool never ships Blender).
- Python 3.10+.
- `pip install "blender-automation-skill[mcp]"`

## MCP server

`blender-automation-skill-mcp` speaks MCP over stdio. Tools:

| Tool | What it does |
|---|---|
| `blender_capabilities` | Detect the Blender binary, its version, host CPU/RAM |
| `blender_bench` | Cold start, render cost, boolean cost, peak RSS |
| `blender_run_script` | Run one Blender script with JSON params, return artifacts |
| `blender_optimize` | Coordinate-descent a parameter space against a target mask (maximise IoU) |
| `blender_demo` | Built-in silhouette demo, no assets required |
| `blender_report` | history.json → single-file HTML report |

Wire it into a client:

```bash
# Claude Code
claude mcp add blender -- blender-automation-skill-mcp

# Codex
codex mcp add blender -- blender-automation-skill-mcp
```

```json
{
  "mcpServers": {
    "blender": {
      "command": "blender-automation-skill-mcp",
      "args": []
    }
  }
}
```

## CLI

```bash
blender-automation-skill bench  --blender /path/to/blender --out out/bench
blender-automation-skill demo   --blender /path/to/blender --out out/demo
blender-automation-skill report --history out/demo/history.json --out out/demo/report.html
```

`model-loop` remains available as an alias.

## Blender script contract

`blender_run_script` and `blender_optimize` run:

```
blender --background --python <script> -- <params-json> <png-out> [resolution]
```

The script reads `sys.argv` after `--`, renders one silhouette to `<png-out>`, exits 0.
A complete working example lives in `src/model_loop/demo.py`.

## Rules for agents

- Always start with `blender_capabilities`; if `ok` is false, stop and report the missing binary.
- Keep `budget` small on first contact (10–20 evaluations) before committing to a long search.
- Never point `blender` at an untrusted binary, and do not evaluate untrusted scripts.
- Report `report_html` and `history_json` paths instead of pasting raw logs.
