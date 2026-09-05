#!/usr/bin/env python3
"""stdio MCP server that exposes active ToolGate tools through ToolGate internals."""
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolgate.core import control_plane  # noqa: E402
from toolgate.core import vault  # noqa: E402


SERVER_NAME = "toolgate"
SERVER_VERSION = "0.3.0"
_BOOTSTRAPPED = False
_SKILL_CACHE_SECONDS = 300
_MAX_SKILL_TEXT_BYTES = 2048
_SKILL_CACHE: dict[str, tuple[float, str]] = {}


def _bootstrap() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _server_module().ensure_builtin_research_capabilities()
    _BOOTSTRAPPED = True


def _server_module():
    from toolgate.api import server  # local import keeps the adapter lightweight in test contexts
    return server


def _local_actor() -> dict:
    return {"id": "local-mcp", "name": os.environ.get("TOOLGATE_MCP_ACTOR", "Pi MCP")}


def _visible_tools() -> list[dict]:
    return [
        tool
        for tool in control_plane.list_objects("tool")
        if tool.get("status") == "active"
    ]


def _json_type(field_type: str) -> str:
    return field_type if field_type in {"string", "integer", "number", "boolean", "array", "object"} else "string"


def _mcp_tool_name(tool_id: str, all_ids: list[str] | None = None) -> str:
    """Return a broad-client-compatible MCP name while preserving ToolGate IDs internally."""
    if os.environ.get("TOOLGATE_MCP_PRESERVE_IDS") == "1":
        return tool_id
    name = re.sub(r"[^A-Za-z0-9_-]", "_", tool_id).strip("_") or "toolgate_tool"
    if not re.match(r"^[A-Za-z_]", name):
        name = f"tool_{name}"
    name = name[:64]
    if all_ids:
        collisions = [item for item in all_ids if re.sub(r"[^A-Za-z0-9_-]", "_", item).strip("_")[:64] == name]
        if len(collisions) > 1:
            suffix = hashlib.sha1(tool_id.encode("utf-8")).hexdigest()[:8]
            name = f"{name[:55]}_{suffix}"
    return name


def _schema_for_field(field: dict) -> dict:
    schema: dict[str, Any] = {"type": _json_type(str(field.get("type", "string")))}
    if field.get("description"):
        schema["description"] = field["description"]
    if "default" in field:
        schema["default"] = field["default"]
    if field.get("allowed_values"):
        schema["enum"] = list(field["allowed_values"])
    if schema["type"] == "string":
        if field.get("min_length") is not None:
            schema["minLength"] = field["min_length"]
        if field.get("max_length") is not None:
            schema["maxLength"] = field["max_length"]
        if field.get("pattern"):
            schema["pattern"] = field["pattern"]
    if schema["type"] in {"integer", "number"}:
        if field.get("minimum") is not None:
            schema["minimum"] = field["minimum"]
        if field.get("maximum") is not None:
            schema["maximum"] = field["maximum"]
    if schema["type"] == "array":
        item_schema: dict[str, Any] = {}
        if field.get("item_type"):
            item_schema["type"] = _json_type(str(field["item_type"]))
        if field.get("item_pattern"):
            item_schema["pattern"] = field["item_pattern"]
        if item_schema:
            schema["items"] = item_schema
        if field.get("min_items") is not None:
            schema["minItems"] = field["min_items"]
        if field.get("max_items") is not None:
            schema["maxItems"] = field["max_items"]
        if field.get("unique_items") is not None:
            schema["uniqueItems"] = bool(field["unique_items"])
    return schema


def _tool_input_schema(tool: dict) -> dict:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in tool.get("inputs", []):
        name = field.get("name")
        if not name:
            continue
        properties[name] = _schema_for_field(field)
        if field.get("required"):
            required.append(name)
    properties["approval_request_id"] = {
        "type": "string",
        "description": "Optional ToolGate approval request id for retrying an owner-approved action.",
    }
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _skill_injection_enabled() -> bool:
    return os.environ.get("TOOLGATE_SKILL_INJECTION") == "1"


def _memorygate_setting(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        return vault.get_key(name)
    except KeyError:
        return default


def _truncate_bytes(value: str, limit: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= limit:
        return value
    return raw[:limit].decode("utf-8", errors="ignore").rstrip() + "\n[truncated]"


def _request_memorygate_skills(tool_id: str) -> list[dict]:
    base_url = (_memorygate_setting("MEMORYGATE_URL", "http://memorygate-api:8020") or "").rstrip("/")
    read_key = _memorygate_setting("MEMORYGATE_READ_KEY")
    if not base_url or not read_key:
        return []
    agent_id = _memorygate_setting("TOOLGATE_MEMORYGATE_AGENT_ID", os.environ.get("X_AGENT_ID", "pi-agent")) or "pi-agent"
    query = urllib.parse.urlencode({"tool": tool_id})
    request = urllib.request.Request(
        f"{base_url}/context/skills?{query}",
        headers={
            "Accept": "application/json",
            "X-Agent-Id": agent_id,
            "X-MemoryGate-Key": read_key,
        },
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        body = json.loads(response.read().decode("utf-8"))
    return list(body.get("results", []))


def _linked_skill_text(tool_id: str) -> str:
    if not _skill_injection_enabled():
        return ""
    now = time.time()
    cached = _SKILL_CACHE.get(tool_id)
    if cached and now - cached[0] < _SKILL_CACHE_SECONDS:
        return cached[1]
    try:
        skills = _request_memorygate_skills(tool_id)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        skills = []
    if not skills:
        _SKILL_CACHE[tool_id] = (now, "")
        return ""
    blocks = []
    for skill in skills:
        title = str(skill.get("title") or "Untitled skill")
        version = str(skill.get("version") or "1")
        body = str(skill.get("body") or "").strip()
        if body:
            blocks.append(f"{title} (v{version})\n{body}")
    text = "\n\nLinked MemoryGate skills:\n" + "\n\n".join(blocks) if blocks else ""
    text = _truncate_bytes(text, _MAX_SKILL_TEXT_BYTES)
    _SKILL_CACHE[tool_id] = (now, text)
    return text


def _tool_to_mcp(tool: dict, all_ids: list[str] | None = None) -> dict:
    description = tool.get("description") or f"Invoke ToolGate tool '{tool.get('id', 'unknown')}'."
    if tool.get("authorization") == "owner_confirmation":
        description += " Owner approval may be required."
    description += f" ToolGate id: {tool['id']}."
    description += _linked_skill_text(str(tool["id"]))
    return {
        "name": _mcp_tool_name(str(tool["id"]), all_ids),
        "description": description,
        "inputSchema": _tool_input_schema(tool),
    }


def list_tools() -> list[dict]:
    _bootstrap()
    visible = _visible_tools()
    all_ids = [str(tool["id"]) for tool in visible]
    tools = [_tool_to_mcp(tool, all_ids) for tool in visible]
    tools.append({
        "name": "toolgate_request_status",
        "description": "Check the status of a ToolGate request or approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The ToolGate request id to inspect."},
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
    })
    return tools


def _resolve_tool(tool_name: str) -> dict | None:
    direct = control_plane.get("tool", tool_name)
    if direct and direct.get("status") == "active":
        return direct
    visible = _visible_tools()
    all_ids = [str(tool["id"]) for tool in visible]
    for tool in visible:
        if _mcp_tool_name(str(tool["id"]), all_ids) == tool_name:
            return tool
    return None


def _request_status(request_id: str) -> dict:
    request = control_plane.get("request", request_id)
    if not request:
        raise RuntimeError("request not found")
    return {
        "id": request["id"],
        "kind": request["kind"],
        "status": request["status"],
        "title": request["title"],
        "created_at": request["created_at"],
        "decision": request.get("decision"),
    }


def _invoke(tool_name: str, arguments: dict) -> dict:
    _bootstrap()
    actor = _local_actor()
    if tool_name == "toolgate_request_status":
        return _request_status(str(arguments["request_id"]))
    tool = _resolve_tool(tool_name)
    if not tool:
        raise RuntimeError(f"Tool '{tool_name}' was not found")
    args = dict(arguments)
    approval_request_id = args.pop("approval_request_id", None)
    try:
        return _server_module().invoke_tool(tool, args, actor["name"], approval_request_id=approval_request_id, actor_id=actor["id"])
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        detail = detail if isinstance(detail, dict) else {"code": "REQUEST_FAILED", "message": str(detail or exc)}
        raise RuntimeError(json.dumps(detail, ensure_ascii=True))


def respond(message_id: Any, result: Any | None = None, error: Exception | str | None = None) -> None:
    body = {"jsonrpc": "2.0", "id": message_id}
    if error is None:
        body["result"] = result
    else:
        body["error"] = {"code": -32000, "message": str(error)}
    print(json.dumps(body), flush=True)


def _handle_request(request: dict) -> None:
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        _bootstrap()
        respond(request.get("id"), {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
        return
    if method == "tools/list":
        respond(request.get("id"), {"tools": list_tools()})
        return
    if method == "tools/call":
        name = params.get("name")
        if not name:
            raise RuntimeError("tool name is required")
        value = _invoke(str(name), params.get("arguments", {}))
        respond(request.get("id"), {"content": [{"type": "text", "text": json.dumps(value)}]})
        return
    if "id" in request:
        respond(request.get("id"), {})


def main() -> int:
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            _handle_request(request)
        except Exception as exc:  # pragma: no cover - protocol boundary
            respond(request.get("id") if isinstance(request, dict) else None, error=exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
