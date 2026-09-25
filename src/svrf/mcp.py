"""`svrf mcp`: a minimal MCP (Model Context Protocol) server over stdio, so a coding agent
can ask why its own pull request is held and fix it without leaving its tool loop.

Newline-delimited JSON-RPC 2.0 on stdin/stdout, exactly the messages `initialize`,
`tools/list` and `tools/call` need; nothing else is implemented because nothing else is
used by the three tools below.

Every tool is read-only except `requeue`, and `requeue` only clears a hold record from
local state so svrf reads that pull request again next round — it never merges, gates,
or pushes anything by itself.
"""

from __future__ import annotations

import json
import sys
from typing import IO

from . import __version__
from .cli import status as queue_status
from .cli import why as why_held
from .config import Config

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "queue_status",
        "description": "Held pull requests and the outcome of the last round, from local state only (no network call).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "why_held",
        "description": "Why one pull request is held or where it sits in the queue, with its failing lines and a "
                       "plain next step.",
        "inputSchema": {
            "type": "object",
            "properties": {"pr": {"type": "integer", "description": "the pull request number"}},
            "required": ["pr"],
        },
    },
    {
        "name": "requeue",
        "description": "Clear a pull request's hold record so svrf reads it again next round. Never merges, gates, "
                       "or pushes anything; use it after you believe you have fixed what held it.",
        "inputSchema": {
            "type": "object",
            "properties": {"pr": {"type": "integer", "description": "the pull request number"}},
            "required": ["pr"],
        },
    },
]


def _text_result(value: dict, *, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(value, indent=1, sort_keys=True, default=str)}]}
    if is_error:
        result["isError"] = True
    return result


def _requeue(config: Config, number: int) -> dict:
    """Drop `number`'s hold record. A local, offline write: no clone, no GitHub call."""
    from .locks import owner_lock

    with owner_lock(config.lock) as owned:
        if not owned:
            return {"tick": "LOCKED"}
        try:
            state = json.loads((config.state_dir / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"forgot": []}
        dropped = state.get("held", {}).pop(str(number), None)
        if dropped is None:
            return {"forgot": []}
        config.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = (config.state_dir / "state.json").with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(config.state_dir / "state.json")
        return {"forgot": [number]}


def call_tool(config: Config, name: str, arguments: dict) -> dict:
    if name == "queue_status":
        return _text_result(queue_status(config))
    if name == "why_held":
        return _text_result(why_held(config, int(arguments["pr"])))
    if name == "requeue":
        return _text_result(_requeue(config, int(arguments["pr"])))
    return _text_result({"error": f"unknown tool: {name}"}, is_error=True)


def handle(config: Config, message: dict) -> dict | None:
    """One JSON-RPC request handled; `None` for a notification (no reply expected)."""
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                           "serverInfo": {"name": "svrf", "version": __version__}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(config, params.get("name"), params.get("arguments") or {})
        except Exception as error:  # a tool error is a result the agent reads, not a crash
            result = _text_result({"error": str(error)}, is_error=True)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(config: Config, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(config, message)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
