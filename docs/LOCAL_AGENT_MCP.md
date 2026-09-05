# Local Agent MCP Bridge

Local agents should connect to ToolGate through a local MCP bridge, not through raw
CLI calls and not through MemoryGate directly.

## Boundary

- The local agent talks to the ToolGate MCP server.
- The MCP server reads ToolGate's own control-plane state directly.
- The MCP server invokes ToolGate through the same internal execution path used by the API.
- ToolGate remains the only execution boundary.
- MemoryGate stays behind ToolGate as just another approved ToolGate capability.

## Behavior

The bridge dynamically discovers the active ToolGate tools from ToolGate's own
configured control-plane state and exposes them as MCP tools for local agents.

It reads the active ToolGate definitions directly and maps each typed ToolGate
`inputs` definition into MCP `inputSchema`.

MCP tool names are made broad-client-friendly. For example, ToolGate's
`research.search` is exposed to the MCP client as `research_search`, while the original
ToolGate ID remains in the tool description and is used for execution. Set
`TOOLGATE_MCP_PRESERVE_IDS=1` only if the target MCP client accepts dotted tool
names.

When the local agent invokes one of those MCP tools, the bridge calls ToolGate's own
`invoke_tool(...)` logic directly, so validation, policy checks, approvals,
usage limits, and MemoryGate access all stay in the normal ToolGate path.

If a ToolGate tool requires owner approval, retry the exact same MCP tool call
with:

```json
{
  "approval_request_id": "<request-id>"
}
```

The bridge also exposes `toolgate_request_status` so the agent can inspect pending
or approved requests.

## Config

Example config:

```json
{
  "mcpServers": {
    "toolgate": {
      "command": "python",
      "args": ["toolgate/mcp/toolgate_mcp.py"],
      "env": {
        "TOOLGATE_MCP_ACTOR": "Pi MCP",
        "TOOLGATE_MCP_PRESERVE_IDS": "0"
      }
    }
  }
}
```

The same example is included at `integrations/mcp/toolgate.local-agent.mcp.json`.
