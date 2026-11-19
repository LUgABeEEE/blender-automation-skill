"""End-to-end tests for the MCP server over a real stdio pipe.

The tests spawn ``<python> -m model_loop.mcp_server`` as a subprocess and walk
the same path a real client walks:

    initialize -> notifications/initialized -> tools/list -> tools/call

No MCP client library is imported here: the JSON-RPC client below is plain
stdlib, so the suite behaves identically under mcp 1.x and 2.x, needs no
network and never starts Blender (the tools are exercised through the error
paths that report-and-return instead of raising).
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "blender-automation-skill"
CONSOLE_SCRIPT = "blender-automation-skill-mcp"
EXPECTED_TOOLS = {
    "blender_capabilities",
    "blender_bench",
    "blender_run_script",
    "blender_optimize",
    "blender_demo",
    "blender_report",
}


def _venv_python() -> Path:
    if os.name == "nt":
        return REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return REPO_ROOT / ".venv" / "bin" / "python"


def _imports_mcp(python: str) -> bool:
    try:
        completed = subprocess.run(
            [python, "-c", "import mcp"],
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment
        return False
    return completed.returncode == 0


_INTERPRETER: dict[str, str] = {}


def interpreter() -> str:
    """The interpreter that runs the server: the repo venv when it has mcp."""
    if "path" in _INTERPRETER:
        return _INTERPRETER["path"]
    candidates: list[str] = []
    if _venv_python().exists():
        candidates.append(str(_venv_python()))
    candidates.append(sys.executable)
    for candidate in candidates:
        if _imports_mcp(candidate):
            _INTERPRETER["path"] = candidate
            return candidate
    pytest.skip("the mcp SDK is not installed; run: python -m pip install -e '.[mcp]'")


def _console_script() -> Path | None:
    local = _venv_python().parent / (
        f"{CONSOLE_SCRIPT}.exe" if os.name == "nt" else CONSOLE_SCRIPT
    )
    if local.exists():
        return local
    found = shutil.which(CONSOLE_SCRIPT)
    return Path(found) if found else None


class ServerProcess:
    """A live MCP server subprocess plus a minimal JSON-RPC client."""

    def __init__(self, argv: list[str], cwd: Path) -> None:
        self.argv = argv
        self.raw_stdout: list[str] = []
        self._stderr: list[str] = []
        self._inbox: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._next_id = 0
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    # -- plumbing ---------------------------------------------------------

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        try:
            for line in self.proc.stdout:
                self.raw_stdout.append(line)
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._inbox.put(("garbage", line))
                    continue
                self._inbox.put(("message", message))
        finally:
            self._inbox.put(("eof", None))

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line)

    @property
    def stderr_tail(self) -> str:
        return "".join(self._stderr[-20:]).strip()

    def _failure(self, method: str, what: str) -> str:
        return (
            f"{what} while waiting for {method!r} "
            f"(exit code {self.proc.poll()}); stderr:\n{self.stderr_tail or '<empty>'}"
        )

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def request(
        self, method: str, params: dict | None = None, timeout: float = 120.0
    ) -> dict:
        self._next_id += 1
        request_id = self._next_id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(self._failure(method, "timed out"))
            try:
                kind, value = self._inbox.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(self._failure(method, "timed out")) from None
            if kind == "garbage":
                raise AssertionError(
                    self._failure(method, f"non-JSON line on stdout: {value!r}")
                )
            if kind == "eof":
                raise AssertionError(self._failure(method, "server closed stdout"))
            if isinstance(value, dict) and value.get("id") == request_id:
                return value
            # Anything else is a notification or a reply we are not waiting on.

    def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except OSError:  # pragma: no cover - already gone
            pass
        try:
            self.proc.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - stuck child
            self.proc.kill()
            self.proc.wait(timeout=15)


def _payload(reply: dict) -> dict:
    """Decode the JSON document a tool returned inside its text content."""
    result = reply["result"]
    assert not result.get("isError", False), result
    content = result["content"]
    assert content, result
    assert content[0]["type"] == "text", content[0]
    return json.loads(content[0]["text"])


def _package_version() -> str | None:
    try:
        return importlib.metadata.version(SERVER_NAME)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - source tree
        return None


@pytest.fixture(scope="module")
def server() -> Any:
    proc = ServerProcess([interpreter(), "-m", "model_loop.mcp_server"], cwd=REPO_ROOT)
    try:
        init = proc.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "blender-automation-skill-e2e", "version": "1"},
            },
        )
        proc.notify("notifications/initialized")
        yield proc, init
    finally:
        proc.close()


# -- handshake -------------------------------------------------------------


def test_initialize_handshake(server: Any) -> None:
    _, init = server
    assert init["jsonrpc"] == "2.0"
    result = init["result"]
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert result["serverInfo"]["version"]
    # A server may negotiate down to an older revision; it must still be one.
    assert result["protocolVersion"][:2] == "20", result["protocolVersion"]
    assert "tools" in result["capabilities"]
    assert result.get("instructions", "").strip()


# -- tool discovery --------------------------------------------------------


def test_tools_list_exposes_the_six_documented_tools(server: Any) -> None:
    proc, _ = server
    tools = proc.request("tools/list", {})["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == EXPECTED_TOOLS
    assert len(tools) == 6, names

    for tool in tools:
        # An empty description makes a tool unpickable for an agent host.
        assert tool["description"].strip(), f"{tool['name']} has no description"
        schema = tool["inputSchema"]
        assert schema["type"] == "object", tool["name"]
        assert isinstance(schema.get("properties"), dict), tool["name"]

    by_name = {tool["name"]: tool for tool in tools}
    run_script = by_name["blender_run_script"]["inputSchema"]
    assert run_script["required"] == ["script"]
    assert run_script["properties"]["resolution"]["default"] == 128

    optimize = by_name["blender_optimize"]["inputSchema"]
    assert set(optimize["required"]) == {"script", "target_png", "space"}
    assert by_name["blender_capabilities"]["inputSchema"]["properties"]["blender"]["default"] == (
        "blender"
    )


# -- tool calls ------------------------------------------------------------


def test_capabilities_call_returns_a_json_document(server: Any) -> None:
    proc, _ = server
    reply = proc.request(
        "tools/call",
        {
            "name": "blender_capabilities",
            "arguments": {"blender": "/nonexistent/blender-binary"},
        },
    )
    payload = _payload(reply)

    assert payload["package"]["name"] == SERVER_NAME
    expected = _package_version()
    if expected is not None:
        assert payload["package"]["version"] == expected
    assert payload["defaults"] == {"memory_mb": 8192, "timeout_s": 900.0}
    assert payload["host"]["python"]
    assert payload["blender"]["found"] is False
    assert payload["ok"] is False
    assert "not found" in payload["error"].lower()
    assert payload["hint"]

    # mcp 2.x mirrors the JSON string into structuredContent; 1.x omits it.
    structured = reply["result"].get("structuredContent")
    if structured is not None:
        assert json.loads(structured["result"]) == payload


def test_report_tool_reports_a_missing_history_instead_of_raising(
    server: Any, tmp_path: Path
) -> None:
    proc, _ = server
    reply = proc.request(
        "tools/call",
        {
            "name": "blender_report",
            "arguments": {"history": str(tmp_path / "missing.json")},
        },
    )
    payload = _payload(reply)
    assert payload["ok"] is False
    assert payload["error"]


def test_bad_arguments_are_answered_and_the_server_survives(server: Any) -> None:
    proc, _ = server
    reply = proc.request(
        "tools/call",
        {
            "name": "blender_optimize",
            "arguments": {
                "script": "no-such-script.py",
                "target_png": "no-such-target.png",
                "space": "not-a-parameter-space",
            },
        },
    )
    assert "error" in reply or reply["result"].get("isError"), reply

    again = proc.request(
        "tools/call",
        {"name": "blender_capabilities", "arguments": {"blender": "/nonexistent/blender"}},
    )
    assert _payload(again)["package"]["name"] == SERVER_NAME


def test_unknown_tool_is_reported(server: Any) -> None:
    proc, _ = server
    reply = proc.request("tools/call", {"name": "no_such_tool", "arguments": {}})
    if "error" in reply:  # mcp 1.x answers with a JSON-RPC error
        assert reply["error"]["code"] != 0
    else:  # mcp 2.x answers with an isError tool result
        result = reply["result"]
        assert result.get("isError") is True, result
        assert "unknown tool" in result["content"][0]["text"].lower()

    tools = proc.request("tools/list", {})["result"]["tools"]
    assert len(tools) == 6


def test_stdout_carries_only_jsonrpc(server: Any) -> None:
    """A stray print() on stdout corrupts the stream for every client."""
    proc, _ = server
    proc.request("tools/list", {})
    assert proc.raw_stdout, "the server produced no output"
    for line in proc.raw_stdout:
        if line.strip():
            json.loads(line)


# -- the installed entry point --------------------------------------------


def test_console_script_entry_point_is_registered() -> None:
    entries = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
    }
    assert entries.get(CONSOLE_SCRIPT) == "model_loop.mcp_server:main"


def test_console_script_stays_up_instead_of_crashing() -> None:
    """What ``timeout 3 blender-automation-skill-mcp`` checks: exit code 124."""
    script = _console_script()
    if script is None:  # pragma: no cover - console script not installed
        pytest.skip(f"{CONSOLE_SCRIPT} is not installed for this interpreter")

    proc = subprocess.Popen(
        [str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        time.sleep(3.0)
        assert proc.poll() is None, (
            f"{script} exited with code {proc.returncode}; "
            f"stderr:\n{proc.stderr.read() if proc.stderr else ''}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
            proc.kill()
            proc.wait(timeout=15)
