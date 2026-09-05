# Single-Operator Console Bridge (stdio MCP)

`toolgate/mcp/toolgate_mcp.py` is a convenience for **one trusted human driving
their own machine**. It lets you talk to your own ToolGate from an MCP client
without minting a key first.

It is not an agent integration, and it never became one.

## Read this before you attach anything

**This bridge bypasses identity and scope entirely.**

- It reads **no execution key**. There is no caller to authenticate.
- It **never calls `is_scoped`**. Every tool with `status: active` is listed and
  callable, regardless of what the owner scoped anyone to.
- Every call is attributed to one hardcoded actor, `local-mcp`. The audit trail
  cannot tell two callers apart, and the approval binding's originating-agent
  check is a no-op across everything that arrives here.
- It imports the control plane in-process and needs local file access to
  `toolgate.db` and `.env`, so it only works on the host holding that state.

**Never expose this bridge to an autonomous agent.** An agent attached here
holds the whole active catalogue with no scope and no attributable identity —
including anything you later add to the catalogue and never meant it to have.

An agent uses the **keyed HTTP API** instead:

```
POST /v2/tools/{tool_id}/invoke
X-ToolGate-Execution-Key: tgx_...
```

That path authenticates the caller, filters `/v2/agent/tools` by scope, refuses
an out-of-scope invoke with `POLICY_DENIED`, and binds each approval to the
execution key that asked for it. None of that happens over stdio.

## What the bridge does still enforce

The bridge calls the same `invoke_tool` the HTTP route calls, so everything
below the identity layer is unchanged:

- lockdown
- deterministic input validation against the tool's typed `inputs`
- `authorization: blocked`
- the approval binding — exact object, version, argument digest, nonce, expiry,
  consumed once
- per-minute, per-hour and cooldown usage limits
- the restricted executor set (no arbitrary code path)
- output schema validation and append-only audit events

So the bridge is not a hole in policy. It is a hole in *who is asking*.

## Behaviour

The bridge discovers active ToolGate tools from the control-plane state and maps
each typed `inputs` definition into an MCP `inputSchema`.

MCP tool names are made broad-client-friendly: ToolGate's `research.search` is
exposed as `research_search`, with the original ToolGate id kept in the tool
description and used for execution. Set `TOOLGATE_MCP_PRESERVE_IDS=1` only if
your MCP client accepts dotted tool names.

Automations are **not** exposed. Only `kind == "tool"` objects, plus the
synthetic `toolgate_request_status` tool.

If a tool requires owner approval, the call returns a `CONFIRMATION_REQUIRED`
payload with a `request_id`. Approve it in the dashboard, then retry the
identical call with:

```json
{ "approval_request_id": "<request-id>" }
```

`toolgate_request_status` reports whether a request is still pending.

### Optional skill injection

With `TOOLGATE_SKILL_INJECTION=1` the bridge fetches MemoryGate's
`GET /context/skills?tool=<id>` and appends the returned text to the MCP tool
description. That text is stored MemoryGate content being placed where a model
reads it as instruction, so it crosses MemoryGate's untrusted-data boundary into
a trusted position. It is **off by default**; leave it off unless you know what
is in your skills table.

## Config

```json
{
  "mcpServers": {
    "toolgate": {
      "command": "python",
      "args": ["toolgate/mcp/toolgate_mcp.py"],
      "env": {
        "TOOLGATE_MCP_ACTOR": "Operator console",
        "TOOLGATE_MCP_PRESERVE_IDS": "0"
      }
    }
  }
}
```

`TOOLGATE_MCP_ACTOR` only sets the display name in the audit trail. It is not a
credential and it grants nothing; the actor id stays `local-mcp` either way.

The same example is at `integrations/mcp/toolgate.single-operator.mcp.json`.
