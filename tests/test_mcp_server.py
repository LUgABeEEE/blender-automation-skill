"""Tests for the MCP surface: tool registration and input handling.

No Blender and no network are required; the tools that would spawn Blender are
exercised through their error paths only.
"""

from __future__ import annotations

import asyncio
import json

import pytest

mcp_server = pytest.importorskip("model_loop.mcp_server")

EXPECTED_TOOLS = {
    "blender_capabilities",
    "blender_bench",
    "blender_run_script",
    "blender_optimize",
    "blender_demo",
    "blender_report",
}


def _payload(result) -> dict:
    """Decode a call_tool result on both mcp 1.x (list) and 2.x (CallToolResult)."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = content[0]
    text = getattr(content, "text", content)
    return json.loads(text)


def _call(server, name: str, args: dict) -> dict:
    return _payload(asyncio.run(server.call_tool(name, args)))


def test_server_registers_the_documented_tools():
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_space_accepts_bounds_and_spec_dicts():
    space = mcp_server._space({"width": [0.4, 2.0, 1.0], "height": [0.3, 1.6]})
    assert space.names == ("width", "height")
    assert space.initial()["width"] == pytest.approx(1.0)
    assert space.initial()["height"] == pytest.approx(0.95)

    explicit = mcp_server._space([{"name": "depth", "low": 0.0, "high": 4.0, "default": 1.5}])
    assert explicit.names == ("depth",)
    assert explicit.initial()["depth"] == pytest.approx(1.5)


def test_capabilities_reports_a_missing_blender_without_raising():
    server = mcp_server.build_server()
    payload = _call(server, "blender_capabilities", {"blender": "/nonexistent/blender"})
    assert payload["ok"] is False
    assert payload["blender"]["found"] is False
    assert "not found" in payload["error"]
    assert payload["package"]["name"] == "blender-automation-skill"


def test_optimize_rejects_bad_space_and_missing_target(tmp_path):
    server = mcp_server.build_server()
    payload = _call(
        server,
        "blender_optimize",
        {
            "script": str(tmp_path / "missing.py"),
            "target_png": str(tmp_path / "missing.png"),
            "space": {"width": [0.4, 2.0]},
        },
    )
    assert payload["ok"] is False
    assert "bad input" in payload["error"]


def test_report_reports_a_missing_history(tmp_path):
    server = mcp_server.build_server()
    payload = _call(server, "blender_report", {"history": str(tmp_path / "nope.json")})
    assert payload["ok"] is False
    assert payload["error"]


def _target_png(path, size: int = 16):
    """Write a small RGBA mask: opaque square on transparent film."""
    from PIL import Image

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for x in range(4, 12):
        for y in range(4, 12):
            image.putpixel((x, y), (255, 255, 255, 255))
    image.save(path)
    return path


def test_bench_wraps_the_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mcp_server,
        "run_benchmark",
        lambda config, out: {"blender_version": "X 1.0", "measured": {}},
    )
    payload = _call(mcp_server.build_server(), "blender_bench", {"out_dir": str(tmp_path)})
    assert payload["ok"] is True
    assert payload["report"]["blender_version"] == "X 1.0"


def test_run_script_surfaces_the_child_exit_code(monkeypatch, tmp_path):
    class Result:
        exit_code = 1
        duration_s = 0.5
        stdout = "partial output"
        stderr = "boom"

        def ok(self) -> bool:
            return False

    monkeypatch.setattr(mcp_server, "run_script", lambda *args, **kwargs: Result())
    payload = _call(
        mcp_server.build_server(),
        "blender_run_script",
        {"script": str(tmp_path / "x.py"), "out_dir": str(tmp_path)},
    )
    assert payload["ok"] is False
    assert payload["exit_code"] == 1
    assert "boom" in payload["stderr_tail"]


def test_demo_wraps_run_demo(monkeypatch, tmp_path):
    from model_loop.pipeline import LoopResult

    monkeypatch.setattr(mcp_server, "run_demo", lambda *args, **kwargs: LoopResult(best=None))
    payload = _call(mcp_server.build_server(), "blender_demo", {"out_dir": str(tmp_path)})
    assert payload["ok"] is True
    assert payload["evaluations"] == 0


def test_report_renders_a_real_history(tmp_path):
    from model_loop.params import ParamSpec, SearchSpace
    from model_loop.pipeline import Evaluation, LoopResult

    point = Evaluation(params={"width": 1.0}, score=0.5)
    result = LoopResult(
        best=point,
        history=[point],
        space=SearchSpace([ParamSpec("width", 0.4, 2.0, default=1.0)]),
    )
    history = result.save(tmp_path / "history.json")
    out = tmp_path / "report.html"
    payload = _call(
        mcp_server.build_server(), "blender_report", {"history": str(history), "out": str(out)}
    )
    assert payload["ok"] is True
    assert out.exists()


def test_optimize_returns_a_structured_error_when_blender_fails(monkeypatch, tmp_path):
    from model_loop.blender import BlenderError

    target = _target_png(tmp_path / "target.png")

    def boom(*args, **kwargs):
        raise BlenderError("no blender")

    monkeypatch.setattr(mcp_server, "run_script", boom)
    payload = _call(
        mcp_server.build_server(),
        "blender_optimize",
        {
            "script": str(tmp_path / "s.py"),
            "target_png": str(target),
            "space": {"width": [0.4, 2.0]},
            "out_dir": str(tmp_path / "run"),
            "budget": 2,
            "rounds": 1,
        },
    )
    assert payload["ok"] is False
    assert "no blender" in payload["error"]


def test_server_main_explains_a_missing_mcp_extra(monkeypatch, capsys):
    def missing():
        raise ImportError(mcp_server.INSTALL_HINT)

    monkeypatch.setattr(mcp_server, "_new_server", missing)
    with pytest.raises(SystemExit) as ctx:
        mcp_server.server_main()
    assert ctx.value.code == 2
    assert "blender-automation-skill[mcp]" in capsys.readouterr().err
