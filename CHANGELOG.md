# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-20

First public release.

### Added

- `SearchSpace` / `ParamSpec`: bounded parameters, sampling, quantisation and
  content hashing for cache keys.
- `coordinate_descent` and `random_search` with an interruptible budget.
- `Loop`: cached, budgeted evaluation loop with JSON history.
- `blender` runner: `RLIMIT_AS` cap, `flock` serialisation, timeouts and a
  structured `RunResult`.
- Mask metrics: IoU, RMSE, pixel agreement, centroid and bounding box.
- Single-file HTML report with inline SVG score chart and base64 images.
- `demo`: end-to-end silhouette self-iteration example (real Blender render).
- `bench`: machine benchmark (startup, render, boolean, RSS).
- **MCP server** (`blender-automation-skill-mcp`, stdio) exposing six tools:
  `blender_capabilities`, `blender_bench`, `blender_run_script`,
  `blender_optimize`, `blender_demo`, `blender_report`. Works on `mcp>=2`
  (`MCPServer`) and `mcp` 1.x (`FastMCP`).
- `SKILL.md`, `docs/mcp.md` and `examples/mcp-clients/`: how Claude Code,
  Codex, Cursor and DSH wire the server up.
- `py.typed` so the package ships its type information.
- 83 unit tests (CLI, MCP tool surface, demo layout, core loop) that run
  without Blender; CI on Python 3.10–3.12 with ruff check + format gates.

### Changed

- Repository and distribution renamed to **blender-automation-skill**
  (was `model-loop`); the Python package stays `model_loop` and the
  `model-loop` console script remains as an alias.
- Python package renamed `blender_loop` → `model_loop`; git history preserved.
- Packaging metadata migrated to PEP 639 (`license = "MIT"`,
  `License-Expression` in the wheel) and `setuptools>=77`.
- `docs/` is published to GitHub Pages; documentation links point at the
  GitHub blob URLs because Markdown is served verbatim.

### Fixed

- `demo` no longer creates an empty `renders/` directory; images live under
  `work/renders/`.
- `blender_run_script` and `blender_optimize` now expose real tool
  descriptions in `tools/list` (they were empty, so agents could not select
  them).
- CI matrix jobs keep the `test (<version>)` names required by the
  `require-ci` branch ruleset.
