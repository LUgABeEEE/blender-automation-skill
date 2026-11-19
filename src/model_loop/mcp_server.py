"""MCP server: drive headless Blender modelling from any agent.

The server speaks the Model Context Protocol over stdio, so Claude Code,
Codex, Cursor, DSH or any other MCP client can drive the same closed loop the
CLI uses. Every tool returns a JSON string and never raises for expected
failures (missing Blender, bad JSON, exhausted budget) - it reports them.

Start it with::

    blender-automation-skill-mcp          # console script
    python -m model_loop.mcp_server       # same thing
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .bench import collect_host_info, run_benchmark
from .blender import BlenderConfig, BlenderError, require_blender, run_script, version
from .demo import TARGET_PARAMS, run_demo
from .metrics import load_mask, silhouette_metrics
from .params import ParamError, ParamSpec, SearchSpace
from .pipeline import Evaluation, Loop, LoopResult
from .report import render_report

__all__ = ["SERVER_NAME", "build_server", "main", "server_main"]

SERVER_NAME = "blender-automation-skill"

INSTRUCTIONS = """\
Closed-loop modelling for Blender, exposed as tools.

Workflow: render (or reuse) a target silhouette -> describe the parameter
space -> let coordinate descent search it -> read the best parameters, the
score history and the HTML report. Blender must be installed locally; the
tools start it as a subprocess with a memory cap, a timeout and an optional
lock, exactly like the CLI does.
"""

_SCRIPT_CONTRACT = (
    "The script is run as: blender --background --python <script> -- <params-json> <png-out> [resolution]. "
    "It must read argv after '--', render one silhouette to <png-out> and exit 0."
)

# Clients discover tools through their description, which the SDK takes from
# the function docstring. A docstring assembled with "+" is not a docstring at
# all - Python stores nothing, so the description silently becomes empty - hence
# the two tools that embed the script contract pass it explicitly instead.
_RUN_SCRIPT_DESCRIPTION = (
    "Run one Blender script with JSON parameters and report what it produced.\n\n"
    + _SCRIPT_CONTRACT
)
_OPTIMIZE_DESCRIPTION = (
    "Search a parameter space against a target silhouette (maximise mask IoU).\n\n"
    + _SCRIPT_CONTRACT
)


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False, default=str)


def _config(
    blender: str = "blender",
    memory_mb: int = 8192,
    timeout_s: float = 900.0,
    lock: str | None = None,
) -> BlenderConfig:
    return BlenderConfig(
        binary=blender,
        memory_mb=int(memory_mb),
        timeout_s=float(timeout_s),
        lock_path=Path(lock) if lock else None,
    )


def _space(specs: dict[str, list[float]] | list[dict[str, Any]]) -> SearchSpace:
    """Accept {"width": [min, max]} or a list of ParamSpec dicts."""
    if isinstance(specs, dict):
        items: list[dict[str, Any]] = []
        for name, bounds in specs.items():
            low, high = float(bounds[0]), float(bounds[1])
            default = float(bounds[2]) if len(bounds) > 2 else (low + high) / 2.0
            items.append({"name": name, "low": low, "high": high, "default": default})
    else:
        items = list(specs)
    return SearchSpace(
        [
            ParamSpec(
                str(item["name"]),
                float(item["low"]),
                float(item["high"]),
                default=float(item["default"]) if item.get("default") is not None else None,
            )
            for item in items
        ]
    )


def _new_server() -> Any:
    """Build the MCP server, on mcp>=2 (MCPServer) or mcp 1.x (FastMCP)."""
    try:  # mcp >= 2.0
        from mcp.server.mcpserver import MCPServer

        return MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS, version=__version__)
    except ImportError:  # pragma: no cover - mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)


def build_server() -> Any:
    """Create the MCP server with every tool registered."""
    server = _new_server()

    @server.tool()
    def blender_capabilities(blender: str = "blender") -> str:
        """Check the local Blender install and describe what this machine can do."""
        config = _config(blender)
        payload: dict[str, Any] = {
            "ok": True,
            "package": {"name": SERVER_NAME, "version": __version__},
            "host": collect_host_info(),
            "blender": {"binary": blender, "found": False, "version": None},
            "defaults": {"memory_mb": 8192, "timeout_s": 900.0},
        }
        try:
            payload["blender"] = {
                "binary": require_blender(config),
                "found": True,
                "version": version(config),
            }
        except BlenderError as exc:
            payload["ok"] = False
            payload["error"] = str(exc)
            payload["hint"] = "Install Blender 4.x and pass its absolute path as 'blender'."
        return _json(payload)

    @server.tool()
    def blender_bench(
        out_dir: str = "out/bench",
        blender: str = "blender",
        memory_mb: int = 8192,
        timeout_s: float = 900.0,
    ) -> str:
        """Benchmark this machine: cold start, render cost, boolean cost and peak RSS."""
        try:
            report = run_benchmark(_config(blender, memory_mb, timeout_s), out_dir)
        except (BlenderError, OSError, ValueError) as exc:
            return _json({"ok": False, "error": str(exc)})
        return _json({"ok": True, "out_dir": str(out_dir), "report": report})

    @server.tool(description=_RUN_SCRIPT_DESCRIPTION)
    def blender_run_script(
        script: str,
        params: dict[str, float] | None = None,
        out_dir: str = "out/run",
        resolution: int = 128,
        blender: str = "blender",
        memory_mb: int = 8192,
        timeout_s: float = 900.0,
    ) -> str:
        workdir = Path(out_dir)
        workdir.mkdir(parents=True, exist_ok=True)
        png = workdir / "render.png"
        try:
            result = run_script(
                _config(blender, memory_mb, timeout_s),
                Path(script),
                [json.dumps(params or {}, sort_keys=True), str(png), str(int(resolution))],
            )
        except (BlenderError, OSError) as exc:
            return _json({"ok": False, "error": str(exc)})
        return _json(
            {
                "ok": result.ok(),
                "exit_code": result.exit_code,
                "duration_s": round(result.duration_s, 3),
                "png": str(png) if png.exists() else None,
                "stdout_tail": result.stdout[-2000:],
                "stderr_tail": result.stderr[-2000:],
            }
        )

    @server.tool(description=_OPTIMIZE_DESCRIPTION)
    def blender_optimize(
        script: str,
        target_png: str,
        space: dict[str, list[float]] | list[dict[str, Any]],
        out_dir: str = "out/loop",
        resolution: int = 128,
        rounds: int = 4,
        budget: int = 60,
        blender: str = "blender",
        memory_mb: int = 8192,
        timeout_s: float = 900.0,
    ) -> str:
        try:
            search = _space(space)
            target = load_mask(Path(target_png))
        except (OSError, ValueError, KeyError, ParamError) as exc:
            return _json({"ok": False, "error": f"bad input: {exc}"})

        workdir = Path(out_dir)
        workdir.mkdir(parents=True, exist_ok=True)
        config = _config(blender, memory_mb, timeout_s)
        counter = {"n": 0}

        def evaluate(values: dict[str, float], where: Path) -> Evaluation:
            counter["n"] += 1
            png = where / "renders" / f"eval_{counter['n']:03d}.png"
            run_script(
                config,
                Path(script),
                [json.dumps(values, sort_keys=True), str(png), str(int(resolution))],
            ).check()
            metrics = silhouette_metrics(load_mask(png), target)
            return Evaluation(
                params=dict(values),
                score=metrics["iou"],
                metrics=metrics,
                artifacts=[str(png)],
            )

        try:
            loop = Loop(search, evaluate, workdir / "work", budget=int(budget), maximize=True)
            result = loop.run_coordinate_descent(rounds=int(rounds))
        except (BlenderError, OSError, ValueError) as exc:
            return _json({"ok": False, "error": str(exc), "evaluations": counter["n"]})

        history_path = result.save(workdir / "history.json")
        report_path = render_report(result, workdir / "report.html", title="Blender optimisation")
        return _json(
            {
                "ok": True,
                "best": result.best.as_dict() if result.best else None,
                "scores": [round(score, 6) for score in result.scores],
                "evaluations": len(result.history),
                "history_json": str(history_path),
                "report_html": str(report_path),
            }
        )

    @server.tool()
    def blender_demo(
        out_dir: str = "out/demo",
        rounds: int = 4,
        budget: int = 60,
        resolution: int = 128,
        blender: str = "blender",
    ) -> str:
        """Run the built-in silhouette demo (no assets needed) and return its report."""
        try:
            result = run_demo(
                _config(blender),
                out_dir,
                resolution=int(resolution),
                rounds=int(rounds),
                budget=int(budget),
            )
        except (BlenderError, OSError, ValueError) as exc:
            return _json({"ok": False, "error": str(exc)})
        return _json(
            {
                "ok": True,
                "best": result.best.as_dict() if result.best else None,
                "evaluations": len(result.history),
                "truth_hint": TARGET_PARAMS,
                "history_json": str(Path(out_dir) / "history.json"),
                "report_html": str(Path(out_dir) / "report.html"),
            }
        )

    @server.tool()
    def blender_report(
        history: str,
        out: str = "out/report.html",
        title: str = "Self-iteration report",
    ) -> str:
        """Render a single-file HTML report from a history.json produced by a loop."""
        try:
            result = LoopResult.load(Path(history))
            path = render_report(result, out, title=title)
        except (OSError, ValueError, KeyError) as exc:
            return _json({"ok": False, "error": str(exc)})
        return _json({"ok": True, "report_html": str(path), "evaluations": len(result.history)})

    return server


def server_main() -> None:
    build_server().run()


def main() -> None:  # pragma: no cover - process entry point
    server_main()


if __name__ == "__main__":  # pragma: no cover
    main()
