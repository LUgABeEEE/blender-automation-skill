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

    explicit = mcp_server._space(
        [{"name": "depth", "low": 0.0, "high": 4.0, "default": 1.5}]
    )
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
