# ToolGate

ToolGate is a local, single-owner control plane for AI agent capabilities. It keeps provider credentials outside the agent, exposes only typed capabilities, enforces deterministic policy before execution, and records a redacted audit trail for every important decision.

The project is designed for one owner and one primary local agent. ToolGate is the only capability boundary the agent needs: providers, local services, MemoryGate, approvals, and emergency controls remain behind it.

## Control Plane

| Object | Purpose |
| --- | --- |
| **Service** | Provider identity, write-only secret references, destination policy, health, and linked capabilities. |
| **Tool** | One atomic typed operation using a restricted executor. Tools cannot orchestrate other tools. |
| **Automation** | A versioned deterministic workflow composed from tools and bounded control blocks. |
| **Request** | Owner-reviewable verification, warning, proposal, update, or historical decision. |

The dashboard includes a command center, live execution and AI activity, services, tool and automation editors, persistent ToolGate AI design sessions, requests, verification adapters, security controls, secrets, and settings.

## What Is In This Repository

- `toolgate/api/`: FastAPI owner and agent API, restricted executors, automation runtime, verification callbacks, built-in research tool sync, and ToolGate AI planning endpoints.
- `toolgate/core/`: SQLite control-plane storage, policy helpers, vault integration, planner helpers, research adapters, and runtime paths.
- `toolgate/cli/`: standard-library agent CLI for scoped execution keys.
- `toolgate/mcp/`: stdio MCP bridge that exposes active ToolGate tools as native MCP tools for Pi and other local agents.
- `dashboard/`: React and Vite owner dashboard for services, tools, automations, requests, secrets, security controls, and ToolGate AI sessions.
- `integrations/mcp/`: example MCP client configuration.
- `docs/`: integration notes and dashboard screenshots.
- `toolgate/tests/`: deterministic tests for the control plane, security model, workflow engine, research adapters, and MCP adapter.
- `toolgate/scripts/`: live verification utilities for a running local stack.

## Dashboard Screenshots

| Command Center | ToolGate AI |
| --- | --- |
| ![ToolGate Command Center](docs/screenshots/dashboard-command-center.png) | ![ToolGate AI builder](docs/screenshots/dashboard-ai-builder.png) |

| Security Center | Secrets |
| --- | --- |
| ![ToolGate Security Center](docs/screenshots/dashboard-security-center.png) | ![ToolGate Secrets screen](docs/screenshots/dashboard-secrets.png) |

## Security Model

- Agents authenticate with rotatable execution keys and explicit `tool:*`, `tool:<id>`, `automation:*`, or `automation:<id>` scopes.
- Management endpoints require the separate admin key. Agent keys cannot manage services, secrets, policies, verification methods, or requests.
- Vault values are write-only. ToolGate lists reference names but has no API for revealing stored values.
- Inputs are validated deterministically by type, range, length, pattern, and allowed values before execution.
- Rate, cooldown, runtime, workflow-step, destination, response-size, loop, retry, and delay ceilings are enforced in code.
- Sensitive actions bind approval to the exact object type, object ID, version, argument digest, nonce, and expiry.
- An approval is atomically consumed once. Replays and changed arguments fail closed.
- Signed verification callbacks use HMAC-SHA256, a 60-second timestamp window, a per-request nonce, and immutable action binding.
- Lockdown blocks agent execution, new agent requests, planner work, verification callbacks, and ToolGate-mediated MemoryGate access.
- Logs and API responses contain references and redacted outcomes, never injected secret values.
- Browser access is restricted to configured local dashboard origins.

ToolGate reduces agent and prompt-injection risk, but it cannot protect a host that is already fully compromised. Keep the API private, protect the admin key, and use OS/container isolation as the outer security boundary.

## Bounded Web Research

Research tools accept typed queries and fixed source names, not arbitrary URLs. Search results become short-lived server-issued handles; the fetch tool resolves only those handles, revalidates every HTTPS redirect and public destination, restricts content types, and stops while streaming once 512 KiB of decompressed content is reached.

HTML is reduced before model use: scripts, styles, SVG, hidden elements, navigation, forms, page chrome, cookie prompts, subscription prompts, and repeated lines are removed. Unicode control characters are normalized, search-provider markup is stripped, long encoded blobs and instruction/exfiltration patterns are blocked, and surviving text is enclosed in an explicit untrusted-content boundary. These controls reduce both tokens and attack surface, but retrieved content must still be treated as hostile evidence rather than instructions.

Product Hunt can be used as an optional read-only competition provider. Because Product Hunt requires separate permission for commercial API use, ToolGate keeps it disabled until the owner confirms that approval in Settings and stores `PRODUCTHUNT_TOKEN` through Secrets. The token remains in ToolGate; Emolga receives only locally filtered, redacted product metadata. SearXNG remains the automatic fallback.

Business research is exposed as small reusable tools instead of one monolithic
search action. Atomic tools cover broad web search, Reddit, Hacker News, GitHub
issues, Stack Overflow, YouTube comments, and Product Hunt. Bounded composition
tools combine them into pain, developer, and competition scans while preserving
the source report and failures from every provider.

`TAVILY_API_KEY` powers broad discovery, `GOOGLE_API_KEY` powers bounded YouTube
video and public-comment retrieval, `GITHUB_TOKEN` raises GitHub search limits,
and `STACKEXCHANGE_KEY` raises Stack Overflow limits. Reddit uses its public
read-only JSON search endpoint. Source APIs fall back first to domain-scoped
Tavily and then local SearXNG when direct access is unavailable. Product Hunt
remains permission-gated and uses the same bounded fallback chain. Every result
is normalized, HTML-stripped, injection-scanned,
deduplicated, and represented by a short-lived provenance handle. Invalid or
missing optional credentials fail closed or fall back without exposing values.

## Restricted Executors

Tool definitions can use these first-class executors:

- `echo`: returns validated arguments for local deterministic capabilities and testing.
- `http_json`: bounded GET or owner-confirmed POST requests to exact public HTTPS hosts; redirects and private destinations are denied.
- `memorygate`: fixed-host, read-only `context` or `ask` operations using a vault-held MemoryGate credential.
- `ollama_generate`: bounded generation through the internal Ollama service with declared prompt inputs and no secret access.

Arbitrary agent-supplied Python and legacy script execution are intentionally unsupported.

## Automation Engine

Automations use a typed JSON workflow as their source of truth. The dashboard presents the same definition as a roadmap, layer map, draggable block editor, and editable code view.

Supported blocks are `tool_call`, `set`, `calculation`, `condition`, `switch`, bounded `loop`, bounded `retry`, `delay`, `notification`, and `return`. Expressions may reference `$args.<name>`, `$vars.<name>`, and `$last.<path>`. A tool's declared output is available as `$last.result.<output-name>` and its raw value remains available as `$last.result.result`. Nested depth, total steps, runtime, loop iterations, retry attempts, and delay duration are all capped.

## Agent CLI

The CLI reads its execution credential from `~/.config/toolgate/credentials.env` by default:

```dotenv
TOOLGATE_URL=http://127.0.0.1:8010
TOOLGATE_EXECUTION_KEY=tgx_replace_with_scoped_key
```

The CLI uses only the Python standard library, so agents do not need to install ToolGate's API dependencies. It reads only the scoped credentials file and never loads the owner vault file.

Core commands:

```text
toolgate status
toolgate tool list
toolgate tool <name> info
toolgate tool <name> --argument value
toolgate automation list
toolgate automation <name> info
toolgate automation <name> run --argument value
toolgate request create-tool "Describe the capability needed"
toolgate request status <id>
toolgate update
toolgate watch
```

Add `--json` to any command for a stable machine-readable contract. Values such as integers, arrays, objects, booleans, and `null` are coerced from JSON. Confirmation responses include a `request_id` and exact retry command using `--approval-request-id`.

## Local Agent MCP Bridge

ToolGate includes a local stdio MCP bridge for Pi and similar agents. The
bridge discovers the active ToolGate tools from ToolGate's own configured
state, maps their typed inputs to MCP JSON Schema, and invokes ToolGate
through its internal execution path. Tool IDs are exposed with MCP-friendly
names such as `research_search` while still executing the original ToolGate
tool IDs.

The agent sees these as normal MCP tools through `tools/list` and calls them
through `tools/call`. ToolGate responses are returned as JSON text inside MCP
tool content. Approval-required tools return ToolGate's normal
`CONFIRMATION_REQUIRED` payload, including `request_id`; retry the same MCP tool
call with `approval_request_id` after owner approval.

The bridge is local and in-repo. It reads active ToolGate tool definitions from
the control-plane state, syncs built-in research tools before listing, and uses
ToolGate's own `invoke_tool(...)` path for validation, rate limits, approval
binding, restricted executors, audit events, and MemoryGate access.

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

Set `TOOLGATE_MCP_PRESERVE_IDS=1` only if the MCP client accepts dotted tool
names such as `research.search`. See `docs/LOCAL_AGENT_MCP.md` and
`integrations/mcp/toolgate.local-agent.mcp.json`.

## Local Deployment

1. Create the local environment file:

```powershell
Copy-Item toolgate\.env.example toolgate\.env
```

2. Start the API and dashboard:

```powershell
Set-Location toolgate
docker compose up -d --build
```

3. Open `http://localhost:8011`. The API is available at `http://localhost:8010`.

Blank control keys are generated and persisted on first API startup, but their values are intentionally never printed to logs. Read the local `toolgate/.env` file once to sign into the dashboard, then protect that file with host permissions.

## MemoryGate

MemoryGate is registered as an internal service on the shared `conker_net` Docker network. ToolGate stores a dedicated MemoryGate read credential under `MEMORYGATE_READ_KEY` and exposes only approved read tools. The agent never receives direct MemoryGate credentials.

ToolGate AI retrieves a bounded set of high-confidence memories and a redacted catalog of active tools while drafting. Raw evidence is excluded, all retrieved text is marked as untrusted reference data, generated tool references are checked against the live catalog, and trusted owner limits may only tighten a generated policy. Every AI proposal is revalidated again when it is submitted and approved.

The default internal endpoints are:

- MemoryGate API: `http://memorygate-api:8020`
- Ollama: `http://memorygate-ollama:11434`

They can be changed with owner-controlled environment settings without exposing the destination to agent arguments.

## Verification Callback

Create a write-only vault secret and register a callback method in the Verification screen. A phone, ring, or home adapter signs the canonical JSON body:

```text
HMAC_SHA256(secret, "<unix_timestamp>.<canonical_json_body>")
```

Send the digest as `X-ToolGate-Signature: sha256=<hex>` and the Unix timestamp as `X-ToolGate-Timestamp`. The body contains `method_id`, `request_id`, `decision`, and the request nonce. Five invalid callback signatures within five minutes automatically enable lockdown.

## Verification

Run the deterministic unit suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s toolgate\tests -v
```

Run only the MCP adapter tests:

```powershell
python -m unittest toolgate.tests.test_mcp_adapter -v
```

With both Docker stacks running, execute the live boundary verifier:

```powershell
.\.venv\Scripts\python.exe toolgate\scripts\verify_v2.py
```

The live verifier creates temporary namespaced capabilities and keys, tests executors, workflows, scope isolation, exact approvals, callback replay resistance, redaction, and lockdown, then removes its temporary objects.

## Project Layout

```text
dashboard/                 React and Vite owner dashboard
dashboard/server.py        Local dashboard static server
docs/LOCAL_AGENT_MCP.md    Local-agent MCP bridge behavior and configuration
docs/screenshots/          Dashboard screenshots used by this README
integrations/mcp/          Example MCP client configuration
toolgate/api/              FastAPI control-plane, agent API, and execution runtime
toolgate/cli/              Agent-facing CLI
toolgate/core/             Vault, policy, persistence, research, and planner modules
toolgate/mcp/              MCP bridge for Pi and other local agents
toolgate/scripts/          Operational verification utilities
toolgate/searxng/          Local SearXNG configuration used by research fallback
toolgate/tests/            Deterministic security, workflow, research, and MCP tests
```

ToolGate v2 deliberately starts from a clean control-plane model. Deprecated legacy registries, unrestricted scripts, and old execution paths are not migrated.
