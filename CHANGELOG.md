# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **MCP server** (`blender-automation-skill-mcp`, stdio) exposing six tools:
  `blender_capabilities`, `blender_bench`, `blender_run_script`,
  `blender_optimize`, `blender_demo`, `blender_report`. Works on `mcp>=2`
  (`MCPServer`) and `mcp` 1.x (`FastMCP`).
- `SKILL.md` describing when and how an agent should call the toolkit.
- `examples/mcp.json` client configuration sample.

### Changed

- Repository and distribution renamed to **blender-automation-skill**
  (was `model-loop`); the Python package stays `model_loop` and the
  `model-loop` console script remains as an alias.
- Python package renamed `blender_loop` → `model_loop`, CLI `blender-loop` →
  `model-loop`; git history preserved.

## [0.1.0] - 2026-10-27

### Added

- `SearchSpace` / `ParamSpec`: bounded parameters, sampling, quantisation and
  content hashing for cache keys.
- `coordinate_descent` and `random_search` with an interruptible budget.
- `Loop`: cached, budgeted evaluation loop with JSON history.
- `blender` runner: `RLIMIT_AS` cap, `flock` serialisation, timeouts and a
  structured `RunResult`.
- Mask metrics: IoU, RMSE, pixel agreement, centroid and bounding box.
- Single-file HTML report with inline SVG score chart and base64 images.
- `model-loop demo`: end-to-end silhouette self-iteration example.
- `model-loop bench`: machine benchmark (startup, render, boolean, RSS).
- 54 unit tests that run without Blender; GitHub Actions CI.
