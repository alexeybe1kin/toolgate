# Authenticated MCP transport

Compose does not start MCP. To opt in, install `httpx` from the pinned ToolGate
requirements, mint a separate agent execution key in the owner interface, and
configure `TOOLGATE_EXECUTION_KEY` and `TOOLGATE_URL` in your MCP client's secret
configuration. Invoke `python toolgate/mcp/toolgate_mcp.py` explicitly. Resolve
that script path against this checkout, or use an absolute path in client config.
Never commit the real key. No local owner state needs to be mounted or shared.

The old single-operator console no longer exists. Its module path now runs only
the authenticated transport. Old configurations without a key exit with code 2.
There is no operator bypass, feature flag or admin-key fallback. Pi can attach
with its own scoped key; it cannot obtain more authority through this transport.

Every catalogue read, invocation and status lookup authenticates at the API.
The bridge calls `/v2/agent/tools`, `/v2/tools/{id}/invoke`,
`/v2/agent/status` and `/v2/agent/requests/{id}`. Key revocation and scope changes
apply immediately. The API supplies audit identity and binds approvals to it.
An owner approval is retried with the same `args` and `approval_request_id`;
changed arguments, another caller and replay fail at the ordinary action boundary.

MCP names always use a stable hash suffix, avoiding
aliases when scopes change. Refresh `tools/list` after upgrading. Tool calls have
an envelope: `{"args":{"value":"hello"},"approval_request_id":"optional"}`.
The separate `toolgate_request_status` helper takes `{"request_id":"..."}`.
An approval-required result is a successful transport result requiring owner
review; rejected executions return an MCP tool result with `isError: true`.

Only HTTPS origins and loopback HTTP origins are accepted. Redirects and
implicit environment proxies are disabled so credentials cannot follow them.
The bridge never retries requests: a missing response may follow a completed
action. Check execution records before retrying an uncertain outcome.

Memory retrieval and skill injection are not transport responsibilities. They
belong in Pi; the bridge reads neither the ToolGate vault nor MemoryGate keys.


Outbound invocation envelopes must now include a caller-persisted `action_id` and,
for paid routes, the owner's `job_id`, alongside `args` and any
`approval_request_id`. Reuse the same ID when checking/retrying a logical action;
never turn an `OUTCOME_UNKNOWN` response into a new invocation. See
[durability and spending](DURABLE_EXECUTION_AND_SPENDING.md) for the full contract.
