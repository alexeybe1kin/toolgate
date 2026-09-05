"""ToolGate v2 API: a typed, owner-controlled agent capability boundary."""
import ipaddress
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from toolgate.core import control_plane, planner, research, vault

app = FastAPI(title="ToolGate v2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get(
        "TOOLGATE_DASHBOARD_ORIGINS", "http://localhost:8011,http://127.0.0.1:8011"
    ).split(",") if origin.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-ToolGate-Key", "X-ToolGate-Execution-Key",
                   "X-ToolGate-Timestamp", "X-ToolGate-Signature"],
)


def require_admin(x_toolgate_key: str | None = Header(None, alias="X-ToolGate-Key")) -> str:
    key = vault.get_control_key("TOOLGATE_ADMIN_KEY")
    if not key or not x_toolgate_key or not secrets.compare_digest(key, x_toolgate_key):
        raise HTTPException(401, "requires TOOLGATE_ADMIN_KEY")
    return "admin"


def require_agent(x_toolgate_execution_key: str | None = Header(None, alias="X-ToolGate-Execution-Key")) -> dict:
    agent = control_plane.authenticate_agent(x_toolgate_execution_key)
    if not agent:
        raise HTTPException(401, "missing or invalid X-ToolGate-Execution-Key")
    return agent


@app.on_event("startup")
def startup():
    control_plane.purge_legacy_state()
    generated = vault.ensure_control_keys()
    for name in generated:
        print(f"[toolgate] generated and persisted {name}; value intentionally not logged")
    bootstrap_key = os.environ.get("TOOLGATE_BOOTSTRAP_EXECUTION_KEY", "").strip()
    if bootstrap_key:
        scopes = [scope.strip() for scope in os.environ.get("TOOLGATE_BOOTSTRAP_SCOPES", "tool:*,automation:*").split(",") if scope.strip()]
        control_plane.ensure_bootstrap_agent_key(bootstrap_key, scopes)
    ensure_builtin_research_capabilities()


def ensure_builtin_research_capabilities() -> None:
    source_values = ["appstore_catalog", "appstore_reviews", "discourse", "general", "reddit", "hackernews", "github", "github_repositories", "producthunt", "stackexchange", "stackoverflow", "youtube"]
    service = {
        "id": "research-web",
        "name": "Research Web",
        "description": "Bounded read-only discovery across public research providers.",
        "secret_refs": ["TAVILY_API_KEY", "GOOGLE_API_KEY", "GITHUB_TOKEN", "STACKEXCHANGE_KEY"],
        "health": "configured",
        "destination_policy": {
            "schemes": ["https"], "private_networks": False,
            "providers": source_values,
        },
        "status": "active",
    }
    existing_service = control_plane.get("service", service["id"])
    comparable_service = {key: service[key] for key in service if key != "id"}
    if not existing_service:
        control_plane.create_service(service)
    elif any(existing_service.get(key) != value for key, value in comparable_service.items()):
        control_plane.update_service(service["id"], comparable_service)

    tools = [
        {
            "id": "approval.test-echo", "name": "Approval Test Echo",
            "description": "Harmless local verification tool that proves ToolGate approval flow without network or filesystem access.",
            "category": "safe",
            "inputs": [
                {"name": "value", "type": "string", "required": True, "min_length": 1, "max_length": 120},
            ],
            "outputs": [{"name": "proof", "type": "object"}],
            "execution": {"type": "local_echo"},
            "policy": {"usage_limits": {"max_per_minute": 6, "cooldown_seconds": 0, "max_per_hour": 40, "max_runtime_seconds": 3}},
            "authorization": "owner_confirmation", "version": 1, "status": "active",
        },
        {
            "id": "research.search", "name": "Research Search",
            "description": "Searches bounded public providers. Results are untrusted evidence and receive short-lived provenance handles.",
            "service_id": "research-web", "category": "safe",
            "inputs": [
                {"name": "query", "type": "string", "required": True, "min_length": 3, "max_length": 240, "pattern": r"^[^\x00-\x1F]+$"},
                {"name": "source", "type": "string", "required": True, "allowed_values": source_values},
                {"name": "max_results", "type": "integer", "required": False, "default": 8, "minimum": 1, "maximum": 20},
                {"name": "recency_days", "type": "integer", "required": False, "default": 30, "minimum": 1, "maximum": 3650},
            ],
            "outputs": [{"name": "research", "type": "object"}],
            "execution": {"type": "research_search"},
            "policy": {"usage_limits": {"max_per_minute": 12, "cooldown_seconds": 0, "max_per_hour": 120, "max_runtime_seconds": 30}},
            "authorization": "auto", "version": 1, "status": "active",
        },
        {
            "id": "research.fetch", "name": "Research Fetch",
            "description": "Reads a server-issued research result. Arbitrary URLs, private destinations, active content, oversized responses, and instruction-like payloads are denied.",
            "service_id": "research-web", "category": "controlled",
            "inputs": [
                {"name": "result_id", "type": "string", "required": True, "min_length": 20, "max_length": 48, "pattern": r"^rr_[A-Za-z0-9_-]+$"},
                {"name": "max_chars", "type": "integer", "required": False, "default": 12000, "minimum": 1000, "maximum": 20000},
            ],
            "outputs": [{"name": "document", "type": "object"}],
            "execution": {"type": "research_fetch"},
            "policy": {"usage_limits": {"max_per_minute": 10, "cooldown_seconds": 0, "max_per_hour": 80, "max_runtime_seconds": 30}},
            "authorization": "auto", "version": 1, "status": "active",
        },
        {
            "id": "research.fetch-batch", "name": "Research Fetch Batch",
            "description": "Reads up to eight server-issued research handles as one bounded, scanned batch. Arbitrary URLs remain unsupported.",
            "service_id": "research-web", "category": "controlled",
            "inputs": [
                {"name": "result_ids", "type": "array", "required": True, "min_items": 1, "max_items": 8,
                 "unique_items": True, "item_type": "string", "item_pattern": r"rr_[A-Za-z0-9_-]{20,40}"},
                {"name": "max_chars", "type": "integer", "required": False, "default": 3500, "minimum": 1000, "maximum": 5000},
            ],
            "outputs": [{"name": "documents", "type": "object"}],
            "execution": {"type": "research_fetch_batch"},
            "policy": {"usage_limits": {"max_per_minute": 4, "cooldown_seconds": 0, "max_per_hour": 120, "max_runtime_seconds": 30}},
            "authorization": "auto", "version": 1, "status": "active",
        },
    ]
    atomic_sources = {
        "research.appstore-catalog": ("Apple App Store Catalog", "appstore_catalog"),
        "research.appstore-reviews": ("Apple App Store Reviews", "appstore_reviews"),
        "research.discourse": ("Automation Community Search", "discourse"),
        "research.web": ("Web Search", "general"),
        "research.reddit": ("Reddit Search", "reddit"),
        "research.hackernews": ("Hacker News Search", "hackernews"),
        "research.github-issues": ("GitHub Issue Search", "github"),
        "research.github-repositories": ("GitHub Repository Search", "github_repositories"),
        "research.stackexchange": ("Stack Exchange Search", "stackexchange"),
        "research.stackoverflow": ("Stack Overflow Search", "stackoverflow"),
        "research.youtube-comments": ("YouTube Comment Search", "youtube"),
        "research.producthunt": ("Product Hunt Search", "producthunt"),
    }
    atomic_inputs = [
        {"name": "query", "type": "string", "required": True, "min_length": 3, "max_length": 240, "pattern": r"^[^\x00-\x1F]+$"},
        {"name": "max_results", "type": "integer", "required": False, "default": 8, "minimum": 1, "maximum": 20},
        {"name": "recency_days", "type": "integer", "required": False, "default": 30, "minimum": 1, "maximum": 3650},
    ]
    for tool_id, (name, source) in atomic_sources.items():
        tools.append({
            "id": tool_id, "name": name,
            "description": f"Searches the bounded {name.removesuffix(' Search')} adapter and returns provenance-bound untrusted evidence.",
            "service_id": "research-web", "category": "safe", "inputs": atomic_inputs,
            "outputs": [{"name": "research", "type": "object"}],
            "execution": {"type": "research_search", "fixed_source": source},
            "policy": {"usage_limits": {"max_per_minute": 12, "cooldown_seconds": 0, "max_per_hour": 120, "max_runtime_seconds": 30}},
            "authorization": "auto", "version": 1, "status": "active",
        })
    bundle_profiles = {
        "research.scan-pain": ("Pain Signal Scan", ["discourse", "reddit", "hackernews", "youtube", "general"]),
        "research.scan-developer": ("Developer Friction Scan", ["github", "stackoverflow", "stackexchange", "hackernews", "general"]),
        "research.scan-competition": ("Competition Scan", ["general", "producthunt", "github_repositories"]),
    }
    bundle_inputs = [
        {"name": "query", "type": "string", "required": True, "min_length": 3, "max_length": 240, "pattern": r"^[^\x00-\x1F]+$"},
        {"name": "max_per_source", "type": "integer", "required": False, "default": 5, "minimum": 1, "maximum": 10},
        {"name": "recency_days", "type": "integer", "required": False, "default": 90, "minimum": 1, "maximum": 3650},
    ]
    for tool_id, (name, sources) in bundle_profiles.items():
        tools.append({
            "id": tool_id, "name": name,
            "description": "Runs a bounded reusable multi-source research profile while preserving per-result provenance and failures.",
            "service_id": "research-web", "category": "safe", "inputs": bundle_inputs,
            "outputs": [{"name": "research", "type": "object"}],
            "execution": {"type": "research_bundle", "sources": sources},
            "policy": {"usage_limits": {"max_per_minute": 4, "cooldown_seconds": 0, "max_per_hour": 40, "max_runtime_seconds": 60}},
            "authorization": "auto", "version": 1, "status": "active",
        })
    managed_fields = ("name", "description", "service_id", "category", "inputs", "outputs", "execution", "policy", "authorization", "status")
    for definition in tools:
        existing = control_plane.get("tool", definition["id"])
        if existing and all(existing.get(key) == definition.get(key) for key in managed_fields):
            continue
        if existing:
            definition = {**definition, "version": int(existing.get("version", 1)) + 1}
        control_plane.create_tool(definition)
        control_plane.event("builtin_tool_synced", "info", "tool", definition["id"], "system", {"version": definition["version"]})


@app.get("/health")
def health():
    return {"status": "ok", "version": "v2"}


@app.get("/auth/check")
def auth_check(_tier: str = Depends(require_admin)):
    return {"tier": "admin"}


class SecretCreate(BaseModel):
    name: str
    value: str


class SecretUpdate(BaseModel):
    value: str


@app.get("/vault/secrets")
def list_secrets(_tier: str = Depends(require_admin)):
    return vault.list_placeholders()


@app.post("/vault/secrets")
def create_secret(payload: SecretCreate, _tier: str = Depends(require_admin)):
    try:
        vault.set_secret(payload.name, payload.value, allow_existing=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    control_plane.event("secret_created", "info", "secret", payload.name, "admin")
    return {"name": payload.name}


@app.put("/vault/secrets/{name}")
def update_secret(name: str, payload: SecretUpdate, _tier: str = Depends(require_admin)):
    try:
        vault.set_secret(name, payload.value, allow_existing=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    control_plane.event("secret_updated", "warning", "secret", name, "admin")
    return {"name": name}


@app.delete("/vault/secrets/{name}")
def delete_secret(name: str, _tier: str = Depends(require_admin)):
    try:
        vault.delete_secret(name)
    except KeyError:
        raise HTTPException(404, "secret not found")
    control_plane.event("secret_deleted", "warning", "secret", name, "admin")
    return {"name": name}


@app.post("/settings/keys/admin/rotate")
def rotate_control_key(_tier: str = Depends(require_admin)):
    return {"which": "admin", "key": vault.rotate_control_key("TOOLGATE_ADMIN_KEY")}


class AgentKeyCreate(BaseModel):
    name: str
    scopes: list[str] = []


class AgentKeyScopes(BaseModel):
    scopes: list[str] = []


class V2Service(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    secret_refs: list[str] = []
    health: str = "unknown"
    destination_policy: dict = {}
    status: str = "active"


class V2Tool(BaseModel):
    id: str
    name: str | None = None
    description: str = ""
    service_id: str | None = None
    category: str = "controlled"
    inputs: list[dict] = []
    outputs: list[dict] = []
    execution: dict = {}
    policy: dict = {}
    authorization: str = "auto"
    version: int = 1
    status: str = "active"


class V2Automation(BaseModel):
    id: str
    name: str | None = None
    description: str = ""
    inputs: list[dict] = []
    workflow: list[dict] = []
    policy: dict = {}
    authorization: str = "auto"
    schedule: str | None = None
    version: int = 1
    status: str = "draft"


class V2Request(BaseModel):
    kind: str
    title: str
    details: str
    payload: dict = {}
    severity: str = "info"


class V2RequestDecision(BaseModel):
    status: str
    note: str = ""


class V2AiConversation(BaseModel):
    target_kind: str
    messages: list[dict]


class V2AiProposal(BaseModel):
    target_kind: str
    draft: dict
    conversation: list[dict]


class V2AiSessionCreate(BaseModel):
    target_kind: str


class V2AiSessionMessage(BaseModel):
    content: str


class V2Invoke(BaseModel):
    args: dict = {}
    approval_request_id: str | None = None


class V2Settings(BaseModel):
    planner_model: str = "qwen3:4b"
    event_retention_days: int = 90
    default_confirmation_expiry_seconds: int = 60
    producthunt_commercial_use_approved: bool = False


class VerificationMethodCreate(BaseModel):
    name: str
    secret_ref: str


class VerificationCallback(BaseModel):
    method_id: str
    request_id: str
    decision: str
    nonce: str


def deny(code: str, message: str, status: int = 403, next_action: str = ""):
    raise HTTPException(status, {"code": code, "message": message, "next_action": next_action})


SUPPORTED_TOOL_EXECUTORS = {
    "echo", "local_echo", "http_json", "memorygate", "ollama_generate", "gemini_generate",
    "research_search", "research_bundle", "research_fetch", "research_fetch_batch",
}
AUTHORIZATION_MODES = {"auto", "ai_review", "owner_confirmation", "blocked"}
CAPABILITY_STATUSES = {"draft", "active", "disabled"}
INPUT_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
GEMINI_MODELS = {"gemini-3.5-flash-lite", "gemini-2.5-flash-lite"}
AI_CONFIRMATIONS = {
    "approve", "approved", "correct", "done", "good", "looks good", "perfect",
    "ship it", "that is correct", "that works", "yes",
}


def input_schema_errors(inputs) -> list[str]:
    if not isinstance(inputs, list):
        return ["inputs must be a list"]
    if len(inputs) > 64:
        return ["inputs cannot contain more than 64 fields"]
    errors, names = [], set()
    for index, field in enumerate(inputs):
        prefix = f"input {index + 1}"
        if not isinstance(field, dict):
            errors.append(f"{prefix} must be an object")
            continue
        name = field.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            errors.append(f"{prefix} needs a valid identifier name")
        elif name in names:
            errors.append(f"input name '{name}' is duplicated")
        else:
            names.add(name)
        if field.get("type", "string") not in INPUT_TYPES:
            errors.append(f"{prefix} type must be one of: {', '.join(sorted(INPUT_TYPES))}")
        if "required" in field and not isinstance(field["required"], bool):
            errors.append(f"{prefix} required must be true or false")
        minimum, maximum = field.get("minimum"), field.get("maximum")
        if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, (int, float))):
            errors.append(f"{prefix} minimum must be numeric")
        if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, (int, float))):
            errors.append(f"{prefix} maximum must be numeric")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
            errors.append(f"{prefix} minimum cannot exceed maximum")
        min_length, max_length = field.get("min_length"), field.get("max_length")
        if min_length is not None and (not isinstance(min_length, int) or not 0 <= min_length <= 100000):
            errors.append(f"{prefix} min_length must be between 0 and 100000")
        if max_length is not None and (not isinstance(max_length, int) or not 0 <= max_length <= 100000):
            errors.append(f"{prefix} max_length must be between 0 and 100000")
        if isinstance(min_length, int) and isinstance(max_length, int) and min_length > max_length:
            errors.append(f"{prefix} min_length cannot exceed max_length")
        pattern = field.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or len(pattern) > 500:
                errors.append(f"{prefix} pattern must be text no longer than 500 characters")
            else:
                try:
                    re.compile(pattern)
                except re.error:
                    errors.append(f"{prefix} pattern is not valid regular expression syntax")
        allowed = field.get("allowed_values")
        if allowed is not None and (not isinstance(allowed, list) or len(allowed) > 100):
            errors.append(f"{prefix} allowed_values must be a list with at most 100 values")
    return errors


def capability_metadata_errors(capability: dict) -> list[str]:
    errors = []
    if not isinstance(capability.get("id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,79}", capability["id"]):
        errors.append("id must be 2-80 lowercase letters, numbers, dots, or hyphens")
    if not isinstance(capability.get("name"), str) or not capability["name"].strip():
        errors.append("name is required")
    if not isinstance(capability.get("description"), str) or not capability["description"].strip():
        errors.append("description is required")
    if capability.get("authorization") not in AUTHORIZATION_MODES:
        errors.append(f"authorization must be one of: {', '.join(sorted(AUTHORIZATION_MODES))}")
    if capability.get("status") not in CAPABILITY_STATUSES:
        errors.append(f"status must be one of: {', '.join(sorted(CAPABILITY_STATUSES))}")
    errors.extend(input_schema_errors(capability.get("inputs")))
    return errors


def tool_definition_errors(tool: dict) -> list[str]:
    errors = capability_metadata_errors(tool)
    inputs = tool.get("inputs")
    if not isinstance(inputs, list):
        inputs = []
    input_names = {field.get("name") for field in inputs if isinstance(field, dict)}
    execution = tool.get("execution")
    if not isinstance(execution, dict) or execution.get("type") not in SUPPORTED_TOOL_EXECUTORS:
        errors.append(f"execution.type must be one of: {', '.join(sorted(SUPPORTED_TOOL_EXECUTORS))}")
        return errors
    if execution["type"] == "http_json":
        method = str(execution.get("method", "")).upper()
        if method not in {"GET", "POST"}:
            errors.append("http_json supports GET and POST only")
        if method == "POST" and tool.get("authorization") != "owner_confirmation":
            errors.append("http_json POST tools require owner_confirmation")
        template = execution.get("url")
        parsed = urlsplit(template) if isinstance(template, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname:
            errors.append("http_json.url must be an absolute HTTPS URL")
        allowed_hosts = execution.get("allowed_hosts")
        if not isinstance(allowed_hosts, list) or not allowed_hosts:
            errors.append("http_json.allowed_hosts must contain at least one exact host")
        elif parsed and parsed.hostname and parsed.hostname.lower() not in {str(host).lower() for host in allowed_hosts}:
            errors.append("the URL host must be present in http_json.allowed_hosts")
        placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template or ""))
        missing = placeholders - input_names
        if missing:
            errors.append(f"URL placeholders need declared inputs: {', '.join(sorted(missing))}")
        if not isinstance(execution.get("result_path"), str) or not execution["result_path"].strip():
            errors.append("http_json.result_path is required")
        timeout = execution.get("timeout_seconds", 10)
        if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
            errors.append("http_json.timeout_seconds must be between 1 and 30")
        max_bytes = execution.get("max_response_bytes", 262144)
        if not isinstance(max_bytes, int) or not 1024 <= max_bytes <= 1048576:
            errors.append("http_json.max_response_bytes must be between 1024 and 1048576")
        secret_headers = execution.get("secret_headers", {})
        forbidden_headers = {"host", "content-length", "connection", "transfer-encoding",
                             "proxy-authorization", "proxy-authenticate", "upgrade"}
        if not isinstance(secret_headers, dict) or any(
                not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", name)
                or name.lower() in forbidden_headers
                or not isinstance(ref, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", ref)
                for name, ref in secret_headers.items()):
            errors.append("http_json.secret_headers must map safe header names to vault references")
    elif execution["type"] == "memorygate":
        operation = execution.get("operation")
        if operation not in {"context", "ask"}:
            errors.append("memorygate.operation must be context or ask")
        required_input = "query" if operation == "context" else "question"
        if operation in {"context", "ask"} and required_input not in input_names:
            errors.append(f"memorygate.{operation} requires a declared '{required_input}' input")
        if not isinstance(execution.get("secret_ref"), str) or not re.fullmatch(
                r"[A-Z][A-Z0-9_]*", execution.get("secret_ref", "")):
            errors.append("memorygate.secret_ref must name a ToolGate vault secret")
    elif execution["type"] == "ollama_generate":
        prompt_template = execution.get("prompt_template")
        if not isinstance(prompt_template, str) or not prompt_template.strip():
            errors.append("ollama_generate.prompt_template is required")
        else:
            placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", prompt_template))
            missing = placeholders - input_names
            if missing:
                errors.append(f"prompt placeholders need declared inputs: {', '.join(sorted(missing))}")
        max_tokens = execution.get("max_tokens", 256)
        if not isinstance(max_tokens, int) or not 8 <= max_tokens <= 1024:
            errors.append("ollama_generate.max_tokens must be between 8 and 1024")
        temperature = execution.get("temperature", 0.0)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            errors.append("ollama_generate.temperature must be between 0 and 2")
    elif execution["type"] == "gemini_generate":
        prompt_template = execution.get("prompt_template")
        if not isinstance(prompt_template, str) or not prompt_template.strip():
            errors.append("gemini_generate.prompt_template is required")
        else:
            placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", prompt_template))
            missing = placeholders - input_names
            if missing:
                errors.append(f"prompt placeholders need declared inputs: {', '.join(sorted(missing))}")
        if execution.get("model") not in GEMINI_MODELS:
            errors.append(f"gemini_generate.model must be one of: {', '.join(sorted(GEMINI_MODELS))}")
        if not isinstance(execution.get("secret_ref"), str) or not re.fullmatch(
                r"[A-Z][A-Z0-9_]*", execution.get("secret_ref", "")):
            errors.append("gemini_generate.secret_ref must name a ToolGate vault secret")
        max_tokens = execution.get("max_tokens", 800)
        if not isinstance(max_tokens, int) or not 128 <= max_tokens <= 2048:
            errors.append("gemini_generate.max_tokens must be between 128 and 2048")
        temperature = execution.get("temperature", 0.0)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 1:
            errors.append("gemini_generate.temperature must be between 0 and 1")
        timeout = execution.get("timeout_seconds", 60)
        if not isinstance(timeout, (int, float)) or not 5 <= timeout <= 120:
            errors.append("gemini_generate.timeout_seconds must be between 5 and 120")
    elif execution["type"] == "research_search":
        fixed_source = execution.get("fixed_source")
        if fixed_source is not None and fixed_source not in research.SOURCE_DOMAINS:
            errors.append("research_search.fixed_source is unsupported")
        required = {"query", "max_results", "recency_days"}
        if fixed_source is None:
            required.add("source")
        missing = required - input_names
        if missing:
            errors.append(f"research_search requires declared inputs: {', '.join(sorted(missing))}")
    elif execution["type"] == "research_bundle":
        sources = execution.get("sources")
        if not isinstance(sources, list) or not sources or len(sources) > 7 or any(source not in research.SOURCE_DOMAINS for source in sources):
            errors.append("research_bundle.sources must contain one to seven supported sources")
        required = {"query", "max_per_source", "recency_days"}
        missing = required - input_names
        if missing:
            errors.append(f"research_bundle requires declared inputs: {', '.join(sorted(missing))}")
    elif execution["type"] == "research_fetch":
        if "result_id" not in input_names:
            errors.append("research_fetch requires a declared 'result_id' input")
    elif execution["type"] == "research_fetch_batch":
        if "result_ids" not in input_names:
            errors.append("research_fetch_batch requires a declared 'result_ids' input")
    return errors


def require_valid_tool_definition(tool: dict):
    errors = tool_definition_errors(tool)
    if errors:
        raise HTTPException(422, {
            "code": "INVALID_TOOL_DEFINITION",
            "message": "; ".join(errors),
            "next_action": "Complete the tool Workflow definition before saving or approving it",
        })


def _public_destination(host: str) -> bool:
    if host.lower() == "localhost":
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            return False
    return bool(addresses)


def _render_template(value, args: dict):
    if isinstance(value, str):
        rendered = value
        for name in set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", value)):
            if name not in args:
                deny("VALIDATION_ERROR", f"Missing template argument '{name}'", 422)
            rendered = rendered.replace(f"{{{name}}}", str(args[name]))
        return rendered
    if isinstance(value, list):
        return [_render_template(item, args) for item in value]
    if isinstance(value, dict):
        return {key: _render_template(item, args) for key, item in value.items()}
    return value


def _extract_result(value, result_path: str | None):
    if not result_path:
        return value
    for part in result_path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            deny("UPSTREAM_SCHEMA_ERROR", "The configured result field was absent from the upstream response", 502)
    return value


def _execute_http_json(execution: dict, args: dict) -> dict:
    template = execution["url"]
    placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template))
    url = template
    for name in placeholders:
        url = url.replace(f"{{{name}}}", quote(str(args[name]), safe=""))
    parsed = urlsplit(url)
    allowed_hosts = {str(host).lower() for host in execution["allowed_hosts"]}
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        deny("DESTINATION_DENIED", "The rendered destination is outside this tool's exact host allowlist")
    if not _public_destination(parsed.hostname):
        deny("DESTINATION_DENIED", "Public HTTP tools cannot reach private or unresolved network destinations")
    headers = {"Accept": "application/json", "User-Agent": "ToolGate/2.0"}
    for header, secret_ref in execution.get("secret_headers", {}).items():
        try:
            headers[header] = vault.get_key(secret_ref)
        except KeyError:
            deny("SECRET_UNAVAILABLE", f"Required vault reference '{secret_ref}' is not configured", 503)
    timeout = min(float(execution.get("timeout_seconds", 10)), 30)
    max_bytes = min(int(execution.get("max_response_bytes", 262144)), 1048576)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            response = client.request(str(execution.get("method", "GET")).upper(), url,
                                      json=_render_template(execution.get("body"), args)
                                      if execution.get("body") is not None else None)
        if 300 <= response.status_code < 400:
            deny("DESTINATION_DENIED", "The upstream attempted an unapproved redirect", 502)
        if response.status_code >= 400:
            deny("UPSTREAM_ERROR", f"The upstream returned HTTP {response.status_code}", 502)
        if len(response.content) > max_bytes:
            deny("RESPONSE_TOO_LARGE", "The upstream response exceeded this tool's byte limit", 502)
        value = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        deny("UPSTREAM_ERROR", f"The public API request failed: {type(exc).__name__}", 502)
    return {"ok": True, "result": _extract_result(value, execution.get("result_path"))}


def _execute_memorygate(execution: dict, args: dict) -> dict:
    operation = execution["operation"]
    base_url = os.environ.get("MEMORYGATE_URL", "http://memorygate-api:8020").rstrip("/")
    try:
        access_key = vault.get_key(execution["secret_ref"])
    except KeyError:
        deny("SECRET_UNAVAILABLE", "MemoryGate read credential is not configured", 503)
    agent_id = str(execution.get("agent_id", "default"))
    headers = {"X-MemoryGate-Key": access_key, "X-Agent-Id": agent_id}
    if operation == "context":
        body = {"query": args["query"], "max_items": args.get("max_items", 12),
                "include_evidence": args.get("include_evidence", False)}
    else:
        body = {"question": args["question"], "include_evidence": args.get("include_evidence", False)}
    try:
        response = httpx.post(f"{base_url}/runtime/{operation}", json=body, headers=headers, timeout=45)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        deny("MEMORYGATE_UNAVAILABLE", f"MemoryGate {operation} failed: {type(exc).__name__}", 502)
    return {"ok": True, "result": result}


def _execute_ollama(execution: dict, args: dict) -> dict:
    url = control_plane.settings().get("planner_url", "http://memorygate-ollama:11434").rstrip("/")
    prompt = _render_template(execution["prompt_template"], args)
    try:
        response = httpx.post(f"{url}/api/generate", json={
            "model": execution.get("model") or control_plane.settings().get("planner_model", "qwen3:4b"),
            "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": float(execution.get("temperature", 0.0)),
                        "num_predict": int(execution.get("max_tokens", 256)), "num_ctx": 4096},
        }, timeout=180)
        response.raise_for_status()
        text = response.json()["response"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        deny("AI_UNAVAILABLE", f"Local AI tool failed: {type(exc).__name__}", 502)
    return {"ok": True, "result": text.strip()}


def _execute_gemini(execution: dict, args: dict) -> dict:
    model = execution["model"]
    if model not in GEMINI_MODELS:
        deny("AI_MODEL_DENIED", "The configured hosted model is not allowlisted", 422)
    prompt = _render_template(execution["prompt_template"], args)
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 20000:
        deny("VALIDATION_ERROR", "Hosted AI prompt must contain 1-20,000 characters", 422)
    try:
        api_key = vault.get_key(execution["secret_ref"])
    except KeyError:
        deny("SECRET_UNAVAILABLE", "Hosted AI credential is not configured", 503)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(execution.get("temperature", 0.0)),
            "maxOutputTokens": int(execution.get("max_tokens", 800)),
            "responseMimeType": "application/json",
        },
    }
    try:
        response = httpx.post(
            url, json=body,
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-goog-api-key": api_key},
            timeout=min(float(execution.get("timeout_seconds", 60)), 120),
        )
        response.raise_for_status()
        payload = response.json()
        parts = payload["candidates"][0]["content"]["parts"]
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        if not text:
            raise ValueError("empty model response")
        usage = payload.get("usageMetadata", {})
    except httpx.HTTPStatusError as exc:
        deny("AI_UNAVAILABLE", f"Hosted AI upstream returned HTTP {exc.response.status_code}", 502)
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        deny("AI_UNAVAILABLE", f"Hosted AI tool failed: {type(exc).__name__}", 502)
    return {
        "ok": True,
        "result": {
            "text": text,
            "usage": {
                "prompt_tokens": int(usage.get("promptTokenCount") or 0),
                "completion_tokens": int(usage.get("candidatesTokenCount") or 0),
                "total_tokens": int(usage.get("totalTokenCount") or 0),
            },
            "model": model,
        },
    }


def _execute_research_search(execution: dict, args: dict) -> dict:
    try:
        result = research.search(
            args["query"], execution.get("fixed_source") or args.get("source", "general"),
            args.get("max_results", 8), args.get("recency_days", 30),
        )
    except research.ResearchError as exc:
        deny("RESEARCH_UNAVAILABLE", str(exc), 502, "Try another source or a narrower query")
    return {"ok": True, "result": result}


def _execute_research_bundle(execution: dict, args: dict) -> dict:
    try:
        result = research.search_bundle(
            args["query"], execution["sources"],
            args.get("max_per_source", 5), args.get("recency_days", 90),
        )
    except research.ResearchError as exc:
        deny("RESEARCH_UNAVAILABLE", str(exc), 502, "Try a narrower query or an atomic source tool")
    return {"ok": True, "result": result}


def _execute_research_fetch(args: dict) -> dict:
    try:
        result = research.fetch(args["result_id"], args.get("max_chars", 12000))
    except research.ResearchError as exc:
        deny("RESEARCH_FETCH_DENIED", str(exc), 422, "Run research.search and use a fresh result_id")
    return {"ok": True, "result": result}


def _execute_research_fetch_batch(args: dict) -> dict:
    try:
        result = research.fetch_batch(args["result_ids"], args.get("max_chars", 3500))
    except research.ResearchError as exc:
        deny("RESEARCH_FETCH_DENIED", str(exc), 422, "Run research.search and use fresh result IDs")
    return {"ok": True, "result": result}


def _execute_local_echo(args: dict) -> dict:
    value = str(args.get("value", ""))
    return {
        "ok": True,
        "result": {
            "digest": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "length": len(value),
        },
    }


def enforce_usage_limits(subject_type: str, subject: dict, event_type: str):
    limits = subject.get("policy", {}).get("usage_limits", {})
    per_minute = limits.get("max_per_minute")
    if per_minute is not None and control_plane.event_count_since(event_type, subject_type, subject["id"], 60) >= int(per_minute):
        deny("RATE_LIMITED", f"{subject['name']} reached its per-minute limit", 429, "Wait before retrying")
    per_hour = limits.get("max_per_hour")
    if per_hour is not None and control_plane.event_count_since(event_type, subject_type, subject["id"], 3600) >= int(per_hour):
        deny("RATE_LIMITED", f"{subject['name']} reached its hourly limit", 429, "Wait before retrying")
    cooldown = limits.get("cooldown_seconds")
    if cooldown:
        latest = control_plane.latest_event_at(event_type, subject_type, subject["id"])
        if latest and (datetime.now(timezone.utc) - latest).total_seconds() < int(cooldown):
            deny("RATE_LIMITED", f"{subject['name']} is in cooldown", 429, "Wait before retrying")


def _shape_tool_result(tool: dict, result: dict) -> dict:
    if not result.get("ok") or "result" not in result:
        return result
    outputs = [item for item in tool.get("outputs", []) if isinstance(item, dict) and item.get("name")]
    value = result["result"]
    for output in outputs:
        if isinstance(value, dict) and output["name"] in value:
            result.setdefault(output["name"], value[output["name"]])
        elif len(outputs) == 1:
            result.setdefault(output["name"], value)
    output_values = {item["name"]: result[item["name"]] for item in outputs if item["name"] in result}
    output_schema = [{**item, "required": True} for item in outputs]
    errors = control_plane.validate_inputs(output_schema, output_values)
    if errors:
        deny("UPSTREAM_SCHEMA_ERROR", "; ".join(errors), 502)
    return result


def invoke_tool(tool: dict, args: dict, actor: str, *, approval_request_id: str | None = None,
                approval_granted: bool = False, actor_id: str | None = None) -> dict:
    if control_plane.settings().get("lockdown"):
        control_plane.event("execution_blocked", "critical", "tool", tool["id"], actor, {"code": "LOCKED_DOWN"})
        deny("LOCKED_DOWN", "ToolGate is in lockdown mode", 423, "Ask the owner to unlock ToolGate")
    errors = control_plane.validate_inputs(tool.get("inputs", []), args)
    if errors:
        control_plane.event("validation_failed", "warning", "tool", tool["id"], actor, {"errors": errors})
        deny("VALIDATION_ERROR", "; ".join(errors), 422, "Run `toolgate tool <name> info`")
    authorization = tool.get("authorization", "auto")
    if authorization == "blocked":
        control_plane.event("execution_blocked", "warning", "tool", tool["id"], actor, {"code": "POLICY_DENIED"})
        deny("POLICY_DENIED", "This tool is permanently blocked by its owner policy")
    if authorization in {"owner_confirmation", "ai_review"} and not approval_granted:
        if approval_request_id:
            approved, reason = control_plane.consume_verification(
                approval_request_id, "tool", tool["id"], args, tool.get("version"), actor, actor_id)
            if not approved:
                deny("APPROVAL_INVALID", reason, 409, "Request a new confirmation for this exact action")
        else:
            expiry = int(control_plane.settings().get("default_confirmation_expiry_seconds", 60))
            request = control_plane.create_verification_request(
                f"Run {tool['name']}",
                "Owner confirmation is required for this exact immutable tool invocation.",
                actor, "tool", tool["id"], args, tool.get("version"), expiry, actor_id)
            return {"code": "CONFIRMATION_REQUIRED", "message": "This exact action is queued for owner review.",
                    "request_id": request["id"], "expires_at": request["payload"]["binding"]["expires_at"],
                    "next_action": f"After approval, retry with --approval-request-id {request['id']}"}
    enforce_usage_limits("tool", tool, "tool_executed")
    # v2 executes only typed, declared executors. Arbitrary Python is intentionally unsupported.
    executor_type = tool.get("execution", {}).get("type")
    if executor_type == "echo":
        result = {"ok": True, "result": args}
    elif executor_type == "local_echo":
        result = _execute_local_echo(args)
    elif executor_type == "http_json":
        result = _execute_http_json(tool["execution"], args)
    elif executor_type == "memorygate":
        result = _execute_memorygate(tool["execution"], args)
    elif executor_type == "ollama_generate":
        result = _execute_ollama(tool["execution"], args)
    elif executor_type == "gemini_generate":
        result = _execute_gemini(tool["execution"], args)
    elif executor_type == "research_search":
        result = _execute_research_search(tool["execution"], args)
    elif executor_type == "research_bundle":
        result = _execute_research_bundle(tool["execution"], args)
    elif executor_type == "research_fetch":
        result = _execute_research_fetch(args)
    elif executor_type == "research_fetch_batch":
        result = _execute_research_fetch_batch(args)
    else:
        result = {"ok": False, "error": "No restricted executor is configured for this typed tool."}
    result = _shape_tool_result(tool, result)
    control_plane.event("tool_executed", "info" if result["ok"] else "warning", "tool", tool["id"], actor, {"ok": result["ok"]})
    return {"code": "OK" if result["ok"] else "TOOL_UNAVAILABLE", "message": "Tool completed" if result["ok"] else result["error"], "result": result}


SUPPORTED_WORKFLOW_BLOCKS = {
    "tool_call", "condition", "switch", "loop", "calculation", "set",
    "delay", "retry", "notification", "return",
}


def workflow_definition_errors(workflow: list, depth: int = 0) -> list[str]:
    if not isinstance(workflow, list):
        return ["workflow must be a list"]
    if depth > 4:
        return ["workflow nesting cannot exceed four levels"]
    errors = []
    for index, step in enumerate(workflow):
        prefix = f"step {index + 1}"
        if not isinstance(step, dict) or step.get("type") not in SUPPORTED_WORKFLOW_BLOCKS:
            errors.append(f"{prefix} has an unsupported block type")
            continue
        kind = step["type"]
        if kind == "tool_call":
            if not step.get("tool_id"):
                errors.append(f"{prefix} needs tool_id")
            if not isinstance(step.get("args", {}), dict):
                errors.append(f"{prefix} args must be an object")
        if kind == "set":
            if not isinstance(step.get("name"), str) or not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]{0,79}", step.get("name", "")):
                errors.append(f"{prefix} set name must be a variable identifier")
            if "value" not in step:
                errors.append(f"{prefix} set requires value")
        if kind == "calculation":
            if step.get("operation", "add") not in {"add", "subtract", "multiply", "divide", "min", "max"}:
                errors.append(f"{prefix} has an unsupported calculation operation")
            if not isinstance(step.get("values"), list) or not step.get("values"):
                errors.append(f"{prefix} calculation requires values")
        if kind == "condition":
            if "left" not in step and not step.get("field"):
                errors.append(f"{prefix} condition requires left or field")
            if step.get("operator", "equals") not in {
                    "equals", "not_equals", "contains", "in", "gte", "lte", "gt", "lt"}:
                errors.append(f"{prefix} has an unsupported condition operator")
            if "right" not in step and "value" not in step:
                errors.append(f"{prefix} condition requires right or value")
        if kind == "loop":
            if not isinstance(step.get("max_iterations"), int) or not 1 <= step["max_iterations"] <= 20:
                errors.append(f"{prefix} max_iterations must be between 1 and 20")
            if "items" not in step:
                errors.append(f"{prefix} loop requires items")
            errors.extend(workflow_definition_errors(step.get("steps", []), depth + 1))
        if kind == "retry":
            if not isinstance(step.get("max_attempts"), int) or not 1 <= step["max_attempts"] <= 3:
                errors.append(f"{prefix} max_attempts must be between 1 and 3")
            if not isinstance(step.get("step"), dict):
                errors.append(f"{prefix} retry requires one step object")
            errors.extend(workflow_definition_errors([step.get("step")], depth + 1))
        if kind == "condition":
            errors.extend(workflow_definition_errors(step.get("then", []), depth + 1))
            errors.extend(workflow_definition_errors(step.get("else", []), depth + 1))
        if kind == "switch":
            if "value" not in step:
                errors.append(f"{prefix} switch requires value")
            cases = step.get("cases", {})
            if not isinstance(cases, dict) or len(cases) > 10:
                errors.append(f"{prefix} cases must be an object with at most 10 branches")
            else:
                for branch in cases.values():
                    errors.extend(workflow_definition_errors(branch, depth + 1))
            errors.extend(workflow_definition_errors(step.get("default", []), depth + 1))
        if kind == "delay" and (not isinstance(step.get("seconds", 0), (int, float))
                                or not 0 <= step.get("seconds", 0) <= 30):
            errors.append(f"{prefix} delay must be between 0 and 30 seconds")
        if kind == "return" and "value" not in step:
            errors.append(f"{prefix} return requires value")
    return errors


def workflow_tool_ids(workflow: list) -> list[str]:
    ids = []
    if not isinstance(workflow, list):
        return ids
    for step in workflow:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "tool_call" and isinstance(step.get("tool_id"), str):
            ids.append(step["tool_id"])
        for key in ("steps", "then", "else", "default"):
            ids.extend(workflow_tool_ids(step.get(key, [])))
        if isinstance(step.get("step"), dict):
            ids.extend(workflow_tool_ids([step["step"]]))
        cases = step.get("cases", {})
        if isinstance(cases, dict):
            for branch in cases.values():
                ids.extend(workflow_tool_ids(branch))
    return ids


def automation_definition_errors(automation: dict) -> list[str]:
    errors = capability_metadata_errors(automation)
    errors.extend(workflow_definition_errors(automation.get("workflow", [])))
    for tool_id in dict.fromkeys(workflow_tool_ids(automation.get("workflow", []))):
        tool = control_plane.get("tool", tool_id)
        if not tool or tool.get("status") != "active":
            errors.append(f"workflow references unavailable tool '{tool_id}'")
        elif automation.get("authorization") == "auto" and tool.get("authorization") != "auto":
            errors.append(f"auto automation cannot call '{tool_id}' because it requires {tool.get('authorization')}")
    max_steps = automation.get("policy", {}).get("usage_limits", {}).get("max_steps", 100)
    if not isinstance(max_steps, int) or not 1 <= max_steps <= 500:
        errors.append("policy.usage_limits.max_steps must be between 1 and 500")
    return errors


def _planner_tool_catalog() -> list[dict]:
    catalog = []
    for tool in control_plane.list_objects("tool"):
        if tool.get("status") != "active":
            continue
        catalog.append({
            "id": tool["id"],
            "description": str(tool.get("description", ""))[:300],
            "inputs": tool.get("inputs", [])[:20],
            "outputs": tool.get("outputs", [])[:20],
            "authorization": tool.get("authorization", "owner_confirmation"),
            "executor": tool.get("execution", {}).get("type"),
        })
    return catalog[:50]


def _planner_memory_context(query: str) -> dict:
    try:
        access_key = vault.get_key("MEMORYGATE_READ_KEY")
    except KeyError:
        return {"available": False, "memories": [], "entities": []}
    base_url = os.environ.get("MEMORYGATE_URL", "http://memorygate-api:8020").rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/runtime/context",
            json={"query": query[:2000], "max_items": 8, "include_evidence": False},
            headers={"X-MemoryGate-Key": access_key, "X-Agent-Id": "default"},
            timeout=20,
        )
        response.raise_for_status()
        raw = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return {"available": False, "memories": [], "entities": []}
    memories = []
    for item in raw.get("memories", []):
        if not isinstance(item, dict) or item.get("confidence") != "high":
            continue
        memories.append({
            "text": str(item.get("text") or item.get("summary") or "")[:600],
            "type": str(item.get("type", "fact"))[:40],
            "confidence": "high",
            "source_type": str(item.get("source_type", ""))[:60],
        })
    entities = []
    for item in raw.get("entities", [])[:8]:
        if not isinstance(item, dict):
            continue
        entities.append({
            "name": str(item.get("name", ""))[:120],
            "type": str(item.get("type", ""))[:60],
            "description": str(item.get("description") or item.get("summary") or "")[:500],
        })
    return {"available": True, "memories": memories[:8], "entities": entities}


def _planner_inputs(target_kind: str, messages: list[dict]) -> tuple[dict, list[dict]]:
    owner_messages = [str(item.get("content", "")) for item in messages if item.get("role") == "user"]
    query = "\n".join(owner_messages[-3:])[:2000] if owner_messages else f"owner preferences for this {target_kind}"
    return _planner_memory_context(query), _planner_tool_catalog()


def _tighten_draft_limits_from_memory(draft: dict, memory_context: dict) -> dict:
    if not isinstance(draft, dict) or not isinstance(memory_context, dict):
        return draft
    patterns = {
        "max_per_hour": r"at most\s+(\d+)\s+runs?\s+per\s+hour",
        "max_runtime_seconds": r"(\d+)\s+seconds?\s+runtime",
        "max_steps": r"(\d+)\s+workflow\s+steps?",
    }
    ceilings = {}
    for memory in memory_context.get("memories", []):
        if not isinstance(memory, dict) or memory.get("source_type") not in {"owner", "owner_validation", "user"}:
            continue
        text = str(memory.get("text", "")).lower()
        for name, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                value = int(match.group(1))
                if value > 0:
                    ceilings[name] = min(value, ceilings.get(name, value))
    if not ceilings:
        return draft
    policy = {**(draft.get("policy") or {})}
    limits = {**(policy.get("usage_limits") or {})}
    for name, ceiling in ceilings.items():
        current = limits.get(name)
        limits[name] = min(current, ceiling) if isinstance(current, int) and current > 0 else ceiling
    if "max_per_hour" in ceilings and isinstance(limits.get("max_per_minute"), int):
        limits["max_per_minute"] = min(limits["max_per_minute"], limits["max_per_hour"])
    policy["usage_limits"] = limits
    return {**draft, "policy": policy}


def require_valid_automation_definition(automation: dict):
    errors = automation_definition_errors(automation)
    if errors:
        raise HTTPException(422, {"code": "INVALID_AUTOMATION_DEFINITION",
                                  "message": "; ".join(errors),
                                  "next_action": "Correct the typed workflow before saving"})


def _lookup_path(value, path: str):
    for part in path.split(".") if path else []:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _workflow_value(value, state: dict):
    if isinstance(value, str) and value.startswith("$args."):
        return _lookup_path(state["args"], value[6:])
    if isinstance(value, str) and value.startswith("$vars."):
        return _lookup_path(state["vars"], value[6:])
    if isinstance(value, str) and value.startswith("$last"):
        return _lookup_path(state.get("last"), value[6:] if value.startswith("$last.") else "")
    if isinstance(value, list):
        return [_workflow_value(item, state) for item in value]
    if isinstance(value, dict):
        return {key: _workflow_value(item, state) for key, item in value.items()}
    return value


def _workflow_compare(actual, operator: str, expected) -> bool:
    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "contains":
        return expected in actual
    if operator in {"gte", "lte", "gt", "lt"}:
        left, right = float(actual), float(expected)
        return {"gte": left >= right, "lte": left <= right, "gt": left > right, "lt": left < right}[operator]
    raise ValueError(f"unsupported operator {operator}")


def _run_workflow_steps(steps: list, state: dict, actor: str, approval_granted: bool):
    for step in steps:
        state["count"] += 1
        if state["count"] > state["max_steps"]:
            deny("POLICY_DENIED", "Automation exceeded its total step ceiling")
        if time.monotonic() - state["started_at"] > state["runtime_ceiling"]:
            deny("POLICY_DENIED", "Automation exceeded its runtime ceiling")
        kind = step["type"]
        result = None
        if kind == "tool_call":
            tool = control_plane.get("tool", step["tool_id"])
            if not tool or tool.get("status") != "active":
                deny("TOOL_UNAVAILABLE", f"Workflow references unavailable tool '{step['tool_id']}'")
            if tool.get("authorization") != "auto" and not approval_granted:
                deny("POLICY_DENIED", f"Automation must require confirmation before calling '{tool['id']}'")
            call_args = {field["name"]: state["args"][field["name"]]
                         for field in tool.get("inputs", []) if field.get("name") in state["args"]}
            call_args.update(_workflow_value(step.get("args", {}), state))
            result = invoke_tool(tool, call_args, actor, approval_granted=approval_granted)
        elif kind == "set":
            state["vars"][step.get("name", "value")] = _workflow_value(step.get("value"), state)
            result = {"code": "VALUE_SET", "name": step.get("name", "value")}
        elif kind == "calculation":
            values = [_workflow_value(value, state) for value in step.get("values", [])]
            operation = step.get("operation", "add")
            if not values or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
                deny("VALIDATION_ERROR", "Calculation values must resolve to numbers", 422)
            calculated = {
                "add": lambda: sum(values), "subtract": lambda: values[0] - sum(values[1:]),
                "multiply": lambda: __import__("math").prod(values),
                "divide": lambda: values[0] / __import__("math").prod(values[1:]),
                "min": lambda: min(values), "max": lambda: max(values),
            }.get(operation)
            if not calculated:
                deny("VALIDATION_ERROR", f"Unsupported calculation '{operation}'", 422)
            try:
                value = calculated()
            except ZeroDivisionError:
                deny("VALIDATION_ERROR", "Calculation divided by zero", 422)
            state["vars"][step.get("save_as", "calculation")] = value
            result = {"code": "CALCULATED", "result": value}
        elif kind == "condition":
            actual = _workflow_value(step.get("left", f"$args.{step.get('field', '')}"), state)
            expected = _workflow_value(step.get("right", step.get("value")), state)
            try:
                matches = _workflow_compare(actual, step.get("operator", "equals"), expected)
            except (TypeError, ValueError):
                deny("VALIDATION_ERROR", "Condition could not compare its configured values", 422)
            branch = step.get("then", []) if matches else step.get("else", [])
            result = {"code": "CONDITION_MET" if matches else "CONDITION_NOT_MET"}
            final = _run_workflow_steps(branch, state, actor, approval_granted)
            if final is not None:
                return final
            if not matches and not branch and step.get("on_false", "stop") == "stop":
                deny("POLICY_DENIED", "Automation condition was not met")
        elif kind == "switch":
            selected = str(_workflow_value(step.get("value"), state))
            branch = step.get("cases", {}).get(selected, step.get("default", []))
            result = {"code": "SWITCH_SELECTED", "case": selected}
            final = _run_workflow_steps(branch, state, actor, approval_granted)
            if final is not None:
                return final
        elif kind == "loop":
            items = _workflow_value(step.get("items"), state)
            if not isinstance(items, list):
                deny("VALIDATION_ERROR", "Loop items must resolve to an array", 422)
            if len(items) > step["max_iterations"]:
                deny("POLICY_DENIED", "Loop input exceeds its deterministic iteration ceiling")
            previous = state["vars"].get(step.get("item_name", "item"))
            for item in items:
                state["vars"][step.get("item_name", "item")] = item
                final = _run_workflow_steps(step.get("steps", []), state, actor, approval_granted)
                if final is not None:
                    return final
            if previous is not None:
                state["vars"][step.get("item_name", "item")] = previous
            result = {"code": "LOOP_COMPLETE", "iterations": len(items)}
        elif kind == "retry":
            last_error = None
            for attempt in range(step["max_attempts"]):
                try:
                    final = _run_workflow_steps([step["step"]], state, actor, approval_granted)
                    if final is not None:
                        return final
                    last_error = None
                    break
                except HTTPException as exc:
                    last_error = exc
                    if exc.status_code not in {429, 502, 503} or attempt + 1 >= step["max_attempts"]:
                        raise
                    time.sleep(min(float(step.get("delay_seconds", 0)), 5))
            result = {"code": "RETRY_COMPLETE", "attempts": step["max_attempts"] if last_error else attempt + 1}
        elif kind == "delay":
            time.sleep(float(step.get("seconds", 0)))
            result = {"code": "DELAY_COMPLETE", "seconds": step.get("seconds", 0)}
        elif kind == "notification":
            notification = control_plane.create_request("update", step.get("title", "Automation update"),
                str(_workflow_value(step.get("message", "Automation notification"), state)), actor,
                {"automation_id": state["automation_id"]}, "info")
            result = {"code": "NOTIFICATION_CREATED", "request_id": notification["id"]}
        elif kind == "return":
            return {"code": "OK", "result": _workflow_value(step.get("value"), state)}
        state["last"] = result
        state["results"].append({"type": kind, "result": result})
    return None


@app.get("/v2/status")
def status(_tier: str = Depends(require_admin)):
    requests = control_plane.list_objects("request")
    return {"lockdown": control_plane.settings().get("lockdown", False),
            "tools": len(control_plane.list_objects("tool")), "automations": len(control_plane.list_objects("automation")),
            "services": len(control_plane.list_objects("service")), "pending_requests": sum(r.get("status") == "pending" for r in requests)}


@app.post("/v2/settings/lockdown")
def set_lockdown(enabled: bool, reason: str = "", _tier: str = Depends(require_admin)):
    return control_plane.set_lockdown(enabled, "admin", reason)


@app.get("/v2/settings")
def get_settings(_tier: str = Depends(require_admin)):
    return {"planner_model": "qwen3:4b", "event_retention_days": 90,
            "default_confirmation_expiry_seconds": 60,
            "producthunt_commercial_use_approved": False, **control_plane.settings()}


@app.put("/v2/settings")
def update_settings(payload: V2Settings, _tier: str = Depends(require_admin)):
    return control_plane.update_settings(payload.model_dump(), "admin")


@app.get("/v2/verification-methods")
def list_verification_methods(_tier: str = Depends(require_admin)):
    return control_plane.list_objects("verification_method")


@app.post("/v2/verification-methods")
def create_verification_method(payload: VerificationMethodCreate, _tier: str = Depends(require_admin)):
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", payload.secret_ref):
        raise HTTPException(422, "secret_ref must be a vault reference name")
    try:
        vault.get_key(payload.secret_ref)
    except KeyError:
        raise HTTPException(422, "secret_ref is not configured in ToolGate")
    method = control_plane.create_verification_method(payload.model_dump())
    control_plane.event("verification_method_created", "info", "verification_method", method["id"], "admin")
    return method


@app.delete("/v2/verification-methods/{method_id}")
def delete_verification_method(method_id: str, _tier: str = Depends(require_admin)):
    if not control_plane.remove("verification_method", method_id):
        raise HTTPException(404, "verification method not found")
    control_plane.event("verification_method_deleted", "warning", "verification_method", method_id, "admin")
    return {"deleted": True, "id": method_id}


@app.post("/v2/verification/callback")
def verification_callback(payload: VerificationCallback,
                          x_toolgate_timestamp: str | None = Header(None, alias="X-ToolGate-Timestamp"),
                          x_toolgate_signature: str | None = Header(None, alias="X-ToolGate-Signature")):
    if control_plane.settings().get("lockdown"):
        deny("LOCKED_DOWN", "ToolGate is in lockdown mode", 423)
    method = control_plane.get("verification_method", payload.method_id)
    if not method or method.get("status") != "active" or method.get("method_type") != "signed_callback":
        deny("VERIFICATION_METHOD_INVALID", "Verification method is unavailable", 401)
    try:
        timestamp = int(x_toolgate_timestamp or "")
    except ValueError:
        timestamp = 0
    canonical = json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    try:
        secret = vault.get_key(method["secret_ref"])
    except KeyError:
        deny("VERIFICATION_METHOD_INVALID", "Verification method secret is unavailable", 503)
    expected = hmac.new(secret.encode(), f"{timestamp}.{canonical}".encode(), hashlib.sha256).hexdigest()
    valid = abs(int(time.time()) - timestamp) <= 60 and bool(x_toolgate_signature) and hmac.compare_digest(
        x_toolgate_signature.removeprefix("sha256="), expected)
    if not valid:
        control_plane.event("verification_callback_rejected", "critical", "verification_method",
                            method["id"], "callback", {"reason": "invalid signature or timestamp"})
        failures = control_plane.event_count_since("verification_callback_rejected", "verification_method",
                                                   method["id"], 300)
        if failures >= 5:
            control_plane.set_lockdown(True, "system", "repeated invalid verification callbacks")
        deny("CALLBACK_SIGNATURE_INVALID", "Callback signature or timestamp is invalid", 401)
    request = control_plane.get("request", payload.request_id)
    binding = request.get("payload", {}).get("binding", {}) if request else {}
    if not request or request.get("kind") != "verification" or request.get("status") != "pending":
        deny("REQUEST_NOT_PENDING", "Verification request is not pending", 409)
    if not hmac.compare_digest(str(binding.get("nonce", "")), payload.nonce):
        deny("CALLBACK_NONCE_INVALID", "Callback nonce does not match this request", 409)
    if payload.decision not in {"approved", "rejected"}:
        raise HTTPException(422, "decision must be approved or rejected")
    record = control_plane.decide_request(payload.request_id, payload.decision,
                                          f"callback:{method['name']}")
    control_plane.update_verification_method(method["id"], {"last_seen_at": datetime.now(timezone.utc).isoformat()})
    control_plane.event("verification_callback_accepted", "info", "verification_method",
                        method["id"], "callback", {"request_id": payload.request_id,
                                                    "decision": payload.decision})
    return {"status": record["status"], "request_id": record["id"]}


@app.post("/v2/ai/conversation")
def ai_conversation(payload: V2AiConversation, _tier: str = Depends(require_admin)):
    if payload.target_kind not in {"tool", "automation"}:
        raise HTTPException(400, "target_kind must be tool or automation")
    if control_plane.settings().get("lockdown"):
        deny("LOCKED_DOWN", "ToolGate is in lockdown mode", 423)
    try:
        memory_context, tool_catalog = _planner_inputs(payload.target_kind, payload.messages)
        result = planner.chat(payload.target_kind, payload.messages,
                              memory_context=memory_context, tool_catalog=tool_catalog)
    except RuntimeError as exc:
        control_plane.event("ai_planner_failed", "warning", "planner", payload.target_kind, "admin", {"error": str(exc)})
        raise HTTPException(503, str(exc))
    control_plane.event("ai_planner_message", "info", "planner", payload.target_kind, "admin", {
        "target_kind": payload.target_kind, "ready": result["ready"], "reply": result["reply"]})
    return result


@app.post("/v2/ai/proposals")
def ai_proposal(payload: V2AiProposal, _tier: str = Depends(require_admin)):
    if payload.target_kind not in {"tool", "automation"} or not payload.draft.get("id"):
        raise HTTPException(400, "proposal needs a target_kind and typed draft id")
    request = control_plane.create_request("ai_draft", f"Create {payload.target_kind}: {payload.draft.get('name', payload.draft['id'])}",
        "ToolGate AI produced this typed draft after an owner conversation.", "admin",
        {"target_kind": payload.target_kind, "draft": payload.draft, "conversation": payload.conversation[-12:]}, "info")
    control_plane.event("ai_proposal_created", "info", "request", request["id"], "admin", {"target_kind": payload.target_kind})
    return request


def _ai_activity(phase: str, detail: str, status: str = "completed") -> dict:
    return {"phase": phase, "detail": detail, "status": status, "created_at": datetime.now(timezone.utc).isoformat()}


def _prepare_ai_draft(target_kind: str, draft: dict) -> dict:
    allowed_fields = (
        {"id", "name", "description", "service_id", "category", "inputs", "outputs",
         "execution", "policy", "authorization"}
        if target_kind == "tool" else
        {"id", "name", "description", "inputs", "workflow", "policy",
         "authorization", "schedule"}
    )
    prepared = {key: value for key, value in draft.items() if key in allowed_fields}
    prepared.update({"status": "draft", "version": 1})
    policy = {**(prepared.get("policy") or {})}
    limits = {**(policy.get("usage_limits") or {})}
    limits.setdefault("max_per_minute", 10)
    limits.setdefault("max_per_hour", 100)
    limits.setdefault("cooldown_seconds", 1)
    limits.setdefault("max_runtime_seconds", 30)
    if target_kind == "automation":
        limits.setdefault("max_steps", 20)
        prepared.setdefault("workflow", [])
        prepared.setdefault("inputs", [])
    else:
        prepared.setdefault("execution", {"type": "planned"})
        prepared.setdefault("inputs", [])
        prepared.setdefault("outputs", [])
        prepared.setdefault("category", "controlled")
    policy["usage_limits"] = limits
    prepared["policy"] = policy
    if prepared.get("authorization") not in {"auto", "ai_review", "owner_confirmation", "blocked"}:
        prepared["authorization"] = "owner_confirmation"
    if prepared.get("category") in {"sensitive", "dangerous"}:
        prepared["authorization"] = "owner_confirmation"
    return prepared


@app.get("/v2/ai/sessions")
def list_ai_sessions(_tier: str = Depends(require_admin)):
    return control_plane.list_objects("ai_session")


@app.post("/v2/ai/sessions")
def create_ai_session(payload: V2AiSessionCreate, _tier: str = Depends(require_admin)):
    if payload.target_kind not in {"tool", "automation"}:
        raise HTTPException(400, "target_kind must be tool or automation")
    if control_plane.settings().get("lockdown"):
        deny("LOCKED_DOWN", "ToolGate is in lockdown mode", 423)
    session = control_plane.create_ai_session(payload.target_kind)
    control_plane.event("ai_session_created", "info", "ai_session", session["id"], "admin",
                        {"target_kind": payload.target_kind})
    return session


@app.get("/v2/ai/sessions/{session_id}")
def get_ai_session(session_id: str, _tier: str = Depends(require_admin)):
    session = control_plane.get("ai_session", session_id)
    if not session:
        raise HTTPException(404, "AI session not found")
    return session


@app.delete("/v2/ai/sessions/{session_id}")
def delete_ai_session(session_id: str, _tier: str = Depends(require_admin)):
    if not control_plane.remove("ai_session", session_id):
        raise HTTPException(404, "AI session not found")
    control_plane.event("ai_session_deleted", "warning", "ai_session", session_id, "admin")
    return {"deleted": True, "id": session_id}


@app.post("/v2/ai/sessions/{session_id}/messages")
def send_ai_session_message(session_id: str, payload: V2AiSessionMessage, _tier: str = Depends(require_admin)):
    if control_plane.settings().get("lockdown"):
        deny("LOCKED_DOWN", "ToolGate is in lockdown mode", 423)
    session = control_plane.get("ai_session", session_id)
    if not session:
        raise HTTPException(404, "AI session not found")
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "message cannot be empty")
    now = datetime.now(timezone.utc).isoformat()
    messages = [*session.get("messages", []), {"role": "user", "content": content[:8000], "created_at": now}]
    normalized = re.sub(r"[^a-z0-9 ]+", "", content.lower()).strip()
    if session.get("draft") and normalized in AI_CONFIRMATIONS:
        messages.append({
            "role": "assistant",
            "content": "The current draft is confirmed without rebuilding it. Submit it for owner approval when you are ready.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        activity = [*session.get("activity", []),
                    _ai_activity("Draft confirmed", "Owner confirmed the current typed draft; no planner rebuild was run.")]
        updated = control_plane.update_ai_session(session_id, {
            "messages": messages,
            "activity": activity[-100:],
            "status": "submitted" if session.get("proposal_request_id") else "draft_ready",
        })
        control_plane.event("ai_draft_confirmed", "info", "ai_session", session_id, "admin")
        return updated
    activity = [*session.get("activity", []), _ai_activity("Understanding request", "Reading the new owner message.", "running")]
    title = session.get("title", "")
    if title.startswith("New "):
        title = content[:64].rstrip() + ("..." if len(content) > 64 else "")
    session = control_plane.update_ai_session(session_id, {
        "messages": messages, "activity": activity[-100:], "title": title, "status": "planning",
    })
    try:
        planner_messages = [{"role": item["role"], "content": item["content"]} for item in messages]
        memory_context, tool_catalog = _planner_inputs(session["target_kind"], planner_messages)
        result = planner.chat(session["target_kind"], planner_messages,
                              memory_context=memory_context, tool_catalog=tool_catalog)
    except RuntimeError as exc:
        activity[-1] = _ai_activity("Understanding request", "Planner could not complete this step.", "failed")
        control_plane.update_ai_session(session_id, {"activity": activity[-100:], "status": "failed"})
        control_plane.event("ai_planner_failed", "warning", "ai_session", session_id, "admin", {"error": str(exc)})
        raise HTTPException(503, str(exc))
    messages.append({"role": "assistant", "content": result["reply"], "created_at": datetime.now(timezone.utc).isoformat()})
    activity[-1] = _ai_activity("Understanding request", "Interpreted the requested outcome and current constraints.")
    if result["ready"]:
        draft = _prepare_ai_draft(session["target_kind"], result["draft"])
        draft = _tighten_draft_limits_from_memory(draft, memory_context)
        definition_errors = (tool_definition_errors(draft) if session["target_kind"] == "tool"
                             else automation_definition_errors(draft))
        if definition_errors:
            previous_draft = session.get("draft")
            previous_errors = ((tool_definition_errors(previous_draft)
                                if session["target_kind"] == "tool"
                                else automation_definition_errors(previous_draft))
                               if isinstance(previous_draft, dict) else definition_errors)
            if previous_draft and not previous_errors:
                draft = previous_draft
                messages[-1]["content"] = (
                    "I could not safely apply that revision, so I preserved the last valid draft. "
                    f"The proposed change was incomplete: {'; '.join(definition_errors)}."
                )
                activity.append(_ai_activity("Draft validation", "Rejected an incomplete revision and preserved the valid draft.", "failed"))
            else:
                draft = None
                messages[-1]["content"] = (
                    "I could not produce an executable typed draft yet. "
                    f"The draft was rejected because {'; '.join(definition_errors)}. Please clarify the intended execution."
                )
                activity.append(_ai_activity("Draft validation", "Rejected an incomplete or unsupported tool definition.", "failed"))
                stages = [
                    {"id": "requirements", "label": "Clarifying requirements", "status": "active"},
                    {"id": "contract", "label": "Defining inputs and outputs", "status": "queued"},
                    {"id": "execution", "label": "Creating executable layer", "status": "queued"},
                    {"id": "safety", "label": "Creating safety policy", "status": "queued"},
                    {"id": "limits", "label": "Applying deterministic limits", "status": "queued"},
                    {"id": "review", "label": "Preparing owner review", "status": "queued"},
                ]
                updated = control_plane.update_ai_session(session_id, {
                    "messages": messages, "activity": activity[-100:], "stages": stages,
                    "status": "clarifying", "draft": None,
                })
                control_plane.event("ai_draft_rejected", "warning", "ai_session", session_id, "admin",
                                    {"errors": definition_errors})
                return updated
        stages = [
            {"id": "requirements", "label": "Clarifying requirements", "status": "completed"},
            {"id": "contract", "label": "Defining inputs and outputs", "status": "completed"},
            {"id": "execution", "label": "Creating executable layer", "status": "completed"},
            {"id": "safety", "label": "Creating safety policy", "status": "completed"},
            {"id": "limits", "label": "Applying deterministic limits", "status": "completed"},
            {"id": "review", "label": "Preparing owner review", "status": "active"},
        ]
        activity.extend([
            _ai_activity("Input contract", f"Defined {len(draft.get('inputs', []))} typed input fields."),
            _ai_activity("Executable layer", "Drafted the restricted executor." if session["target_kind"] == "tool" else f"Drafted {len(draft.get('workflow', []))} workflow blocks."),
            _ai_activity("Safety policy", f"Selected {draft.get('authorization', 'owner_confirmation').replace('_', ' ')} authorization."),
            _ai_activity("Deterministic limits", "Applied bounded rate, cooldown, runtime, and step defaults."),
            _ai_activity("Owner review", "Draft is ready to submit as an owner request.", "waiting"),
        ])
        status = "draft_ready"
    else:
        draft = session.get("draft")
        stages = [
            {"id": "requirements", "label": "Clarifying requirements", "status": "active"},
            {"id": "contract", "label": "Defining inputs and outputs", "status": "queued"},
            {"id": "execution", "label": "Creating executable layer", "status": "queued"},
            {"id": "safety", "label": "Creating safety policy", "status": "queued"},
            {"id": "limits", "label": "Applying deterministic limits", "status": "queued"},
            {"id": "review", "label": "Preparing owner review", "status": "queued"},
        ]
        activity.append(_ai_activity("Clarifying requirements", "Waiting for the owner's answer.", "waiting"))
        status = "clarifying"
    updated = control_plane.update_ai_session(session_id, {
        "messages": messages, "activity": activity[-100:], "stages": stages,
        "status": status, "draft": draft,
    })
    control_plane.event("ai_planner_message", "info", "ai_session", session_id, "admin",
                        {"target_kind": session["target_kind"], "ready": result["ready"]})
    return updated


@app.post("/v2/ai/sessions/{session_id}/submit")
def submit_ai_session(session_id: str, _tier: str = Depends(require_admin)):
    session = control_plane.get("ai_session", session_id)
    if not session:
        raise HTTPException(404, "AI session not found")
    if not session.get("draft"):
        raise HTTPException(409, "This session has no completed draft")
    if session.get("proposal_request_id"):
        raise HTTPException(409, "This draft has already been submitted")
    planner_messages = [{"role": item["role"], "content": item["content"]}
                        for item in session.get("messages", []) if item.get("role") in {"user", "assistant"}]
    memory_context, _tool_catalog = _planner_inputs(session["target_kind"], planner_messages)
    draft = _tighten_draft_limits_from_memory(_prepare_ai_draft(session["target_kind"], session["draft"]),
                                               memory_context)
    if session["target_kind"] == "tool":
        require_valid_tool_definition(draft)
    else:
        require_valid_automation_definition(draft)
    if draft != session["draft"]:
        session = control_plane.update_ai_session(session_id, {"draft": draft})
    request = control_plane.create_request(
        "ai_draft", f"Create {session['target_kind']}: {draft.get('name', draft['id'])}",
        "ToolGate AI produced this typed draft after a persistent owner conversation.", "admin",
        {"target_kind": session["target_kind"], "draft": draft,
         "conversation": session.get("messages", [])[-12:], "ai_session_id": session_id}, "info",
    )
    activity = [*session.get("activity", []), _ai_activity("Owner review", "Proposal submitted to Requests.", "completed")]
    updated = control_plane.update_ai_session(session_id, {
        "proposal_request_id": request["id"], "status": "submitted", "activity": activity[-100:],
        "stages": [{**stage, "status": "completed"} for stage in session.get("stages", [])],
    })
    control_plane.event("ai_proposal_created", "info", "ai_session", session_id, "admin",
                        {"target_kind": session["target_kind"], "request_id": request["id"]})
    return {"session": updated, "request": request}


@app.get("/v2/agent-keys")
def list_agent_keys(_tier: str = Depends(require_admin)):
    return control_plane.list_agent_keys()


@app.post("/v2/agent-keys")
def create_agent_key(payload: AgentKeyCreate, _tier: str = Depends(require_admin)):
    record, raw = control_plane.issue_agent_key(payload.name, payload.scopes)
    return {"key": raw, "record": record}


@app.patch("/v2/agent-keys/{key_id}/scopes")
def update_agent_key_scopes(key_id: str, payload: AgentKeyScopes, _tier: str = Depends(require_admin)):
    record = control_plane.update_agent_key_scopes(key_id, payload.scopes)
    if not record:
        raise HTTPException(404, "agent key not found")
    return record


@app.delete("/v2/agent-keys/{key_id}")
def revoke_agent_key(key_id: str, _tier: str = Depends(require_admin)):
    if not control_plane.revoke_agent_key(key_id):
        raise HTTPException(404, "agent key not found")
    return {"ok": True}


@app.get("/v2/services")
def list_services(_tier: str = Depends(require_admin)):
    tools = control_plane.list_objects("tool")
    automations = control_plane.list_objects("automation")
    return [{**service,
             "linked_tools": [tool["id"] for tool in tools if tool.get("service_id") == service["id"]],
             "linked_automations": [item["id"] for item in automations
                                    if any(step.get("tool_id") in {tool["id"] for tool in tools
                                           if tool.get("service_id") == service["id"]}
                                           for step in item.get("workflow", []) if isinstance(step, dict))]}
            for service in control_plane.list_objects("service")]


@app.post("/v2/services")
def create_service(payload: V2Service, _tier: str = Depends(require_admin)):
    service = control_plane.create_service(payload.model_dump())
    control_plane.event("service_saved", "info", "service", service["id"], "admin")
    return service


@app.post("/v2/services/{service_id}/check")
def check_service(service_id: str, _tier: str = Depends(require_admin)):
    service = control_plane.get("service", service_id)
    if not service:
        raise HTTPException(404, "service not found")
    health_url = service.get("destination_policy", {}).get("health_url")
    if not isinstance(health_url, str):
        raise HTTPException(422, "service has no health_url")
    parsed = urlsplit(health_url)
    allowed_internal = parsed.hostname in {"memorygate-api", "memorygate-ollama"} and parsed.scheme == "http"
    allowed_public = parsed.scheme == "https" and parsed.hostname and _public_destination(parsed.hostname)
    if not (allowed_internal or allowed_public):
        deny("DESTINATION_DENIED", "Service health destination is not allowed")
    try:
        response = httpx.get(health_url, timeout=10, follow_redirects=False)
        healthy = response.status_code < 400
    except httpx.HTTPError:
        healthy = False
    updated = control_plane.update_service(service_id, {
        "health": "healthy" if healthy else "unhealthy",
        "last_health_check_at": datetime.now(timezone.utc).isoformat(),
    })
    control_plane.event("service_health_checked", "info" if healthy else "warning",
                        "service", service_id, "admin", {"healthy": healthy})
    return updated


@app.get("/v2/tools")
def list_tools(_tier: str = Depends(require_admin)):
    return control_plane.list_objects("tool")


@app.get("/v2/tools/{tool_id}")
def get_tool(tool_id: str, _tier: str = Depends(require_admin)):
    tool = control_plane.get("tool", tool_id)
    if not tool:
        raise HTTPException(404, "tool not found")
    return tool


@app.get("/v2/agent/tools")
def agent_tools(agent: dict = Depends(require_agent)):
    return [tool for tool in control_plane.list_objects("tool") if tool.get("status") == "active" and control_plane.is_scoped(agent, tool["id"])]


@app.get("/v2/agent/status")
def agent_status(agent: dict = Depends(require_agent)):
    return {"code": "OK", "message": "ToolGate is online", "id": agent["id"], "agent": agent["name"],
            "scopes": agent.get("scopes", []), "lockdown": control_plane.settings().get("lockdown", False)}


@app.get("/v2/agent/tools/{tool_id}")
def agent_tool_info(tool_id: str, agent: dict = Depends(require_agent)):
    tool = control_plane.get("tool", tool_id)
    if not tool or tool.get("status") != "active" or not control_plane.is_scoped(agent, tool_id):
        raise HTTPException(404, "tool not found or not permitted")
    return tool


@app.post("/v2/tools")
def create_tool(payload: V2Tool, _tier: str = Depends(require_admin)):
    body = payload.model_dump()
    require_valid_tool_definition(body)
    tool = control_plane.create_tool(body)
    control_plane.event("tool_saved", "info", "tool", tool["id"], "admin")
    return tool


@app.put("/v2/tools/{tool_id}")
def update_tool(tool_id: str, payload: V2Tool, _tier: str = Depends(require_admin)):
    body = payload.model_dump()
    require_valid_tool_definition(body)
    tool = control_plane.update_tool(tool_id, body)
    if not tool:
        raise HTTPException(404, "tool not found")
    control_plane.event("tool_updated", "info", "tool", tool_id, "admin", {"version": tool["version"]})
    return tool


@app.delete("/v2/tools/{tool_id}")
def delete_tool(tool_id: str, _tier: str = Depends(require_admin)):
    if not control_plane.remove("tool", tool_id):
        raise HTTPException(404, "tool not found")
    control_plane.event("tool_deleted", "warning", "tool", tool_id, "admin")
    return {"deleted": True, "id": tool_id}


@app.post("/v2/tools/{tool_id}/invoke")
def run_tool(tool_id: str, payload: V2Invoke, agent: dict = Depends(require_agent)):
    tool = control_plane.get("tool", tool_id)
    if not tool:
        deny("TOOL_UNAVAILABLE", f"Tool '{tool_id}' was not found", 404, "Run `toolgate tool list`")
    if tool.get("status") != "active" or not control_plane.is_scoped(agent, tool_id):
        deny("POLICY_DENIED", "Your agent key is not allowed to use this tool", 403, "Ask the owner for scope")
    return invoke_tool(tool, payload.args, agent["name"], approval_request_id=payload.approval_request_id,
                       actor_id=agent["id"])


@app.get("/v2/automations")
def list_automations(_tier: str = Depends(require_admin)):
    return control_plane.list_objects("automation")


@app.get("/v2/automations/{automation_id}")
def get_automation(automation_id: str, _tier: str = Depends(require_admin)):
    automation = control_plane.get("automation", automation_id)
    if not automation:
        raise HTTPException(404, "automation not found")
    return automation


@app.get("/v2/agent/automations")
def agent_automations(agent: dict = Depends(require_agent)):
    return [item for item in control_plane.list_objects("automation") if item.get("status") == "active" and control_plane.is_scoped(agent, f"automation:{item['id']}")]


@app.get("/v2/agent/automations/{automation_id}")
def agent_automation_info(automation_id: str, agent: dict = Depends(require_agent)):
    item = control_plane.get("automation", automation_id)
    if not item or item.get("status") != "active" or not control_plane.is_scoped(agent, f"automation:{automation_id}"):
        raise HTTPException(404, "automation not found or not permitted")
    return item


@app.post("/v2/automations")
def create_automation(payload: V2Automation, _tier: str = Depends(require_admin)):
    body = payload.model_dump()
    require_valid_automation_definition(body)
    automation = control_plane.create_automation(body)
    control_plane.event("automation_saved", "info", "automation", automation["id"], "admin")
    return automation


@app.put("/v2/automations/{automation_id}")
def update_automation(automation_id: str, payload: V2Automation, _tier: str = Depends(require_admin)):
    body = payload.model_dump()
    require_valid_automation_definition(body)
    automation = control_plane.update_automation(automation_id, body)
    if not automation:
        raise HTTPException(404, "automation not found")
    control_plane.event("automation_updated", "info", "automation", automation_id, "admin", {"version": automation["version"]})
    return automation


@app.delete("/v2/automations/{automation_id}")
def delete_automation(automation_id: str, _tier: str = Depends(require_admin)):
    if not control_plane.remove("automation", automation_id):
        raise HTTPException(404, "automation not found")
    control_plane.event("automation_deleted", "warning", "automation", automation_id, "admin")
    return {"deleted": True, "id": automation_id}


@app.post("/v2/automations/{automation_id}/run")
def run_automation(automation_id: str, payload: V2Invoke, agent: dict = Depends(require_agent)):
    automation = control_plane.get("automation", automation_id)
    if not automation or automation.get("status") != "active":
        deny("TOOL_UNAVAILABLE", "Automation is not active", 404)
    if not control_plane.is_scoped(agent, f"automation:{automation_id}"):
        deny("POLICY_DENIED", "Your agent key is not allowed to run this automation")
    errors = control_plane.validate_inputs(automation.get("inputs", []), payload.args)
    if errors:
        deny("VALIDATION_ERROR", "; ".join(errors), 422)
    authorization = automation.get("authorization", "auto")
    if authorization == "blocked":
        control_plane.event("execution_blocked", "warning", "automation", automation_id, agent["name"], {"code": "POLICY_DENIED"})
        deny("POLICY_DENIED", "This automation is permanently blocked by its owner policy")
    approval_granted = False
    if authorization != "auto":
        if payload.approval_request_id:
            approval_granted, reason = control_plane.consume_verification(
                payload.approval_request_id, "automation", automation_id, payload.args,
                automation.get("version"), agent["name"], agent["id"])
            if not approval_granted:
                deny("APPROVAL_INVALID", reason, 409, "Request a new confirmation for this exact automation run")
        else:
            expiry = int(control_plane.settings().get("default_confirmation_expiry_seconds", 60))
            request = control_plane.create_verification_request(
                f"Run {automation['name']}",
                "Owner confirmation is required for this exact immutable automation run.",
                agent["name"], "automation", automation_id, payload.args,
                automation.get("version"), expiry, agent["id"])
            return {"code": "CONFIRMATION_REQUIRED", "message": "Automation queued for owner review",
                    "request_id": request["id"], "expires_at": request["payload"]["binding"]["expires_at"],
                    "next_action": f"After approval, retry with --approval-request-id {request['id']}"}
    enforce_usage_limits("automation", automation, "automation_executed")
    limits = automation.get("policy", {}).get("usage_limits", {})
    state = {"automation_id": automation_id, "args": payload.args, "vars": {}, "last": None,
             "results": [], "count": 0, "max_steps": int(limits.get("max_steps", 100)),
             "started_at": time.monotonic(),
             "runtime_ceiling": min(int(limits.get("max_runtime_seconds", 30) or 30), 120)}
    final = _run_workflow_steps(automation.get("workflow", []), state, agent["name"], approval_granted)
    control_plane.event("automation_executed", "info", "automation", automation_id, agent["name"],
                        {"steps": state["count"], "version": automation.get("version")})
    return {"code": "OK", "message": "Automation completed", "result": final,
            "steps": state["results"], "variables": state["vars"]}


@app.get("/v2/requests")
def list_requests(_tier: str = Depends(require_admin)):
    return control_plane.list_objects("request")


@app.post("/v2/requests")
def create_agent_request(payload: V2Request, agent: dict = Depends(require_agent)):
    if control_plane.settings().get("lockdown"):
        deny("LOCKED_DOWN", "ToolGate is in lockdown mode", 423)
    return control_plane.create_request(payload.kind, payload.title, payload.details, agent["name"],
                                        {**payload.payload, "created_by_agent_key": agent["id"]}, payload.severity)


@app.get("/v2/agent/requests/{request_id}")
def agent_request_status(request_id: str, agent: dict = Depends(require_agent)):
    request = control_plane.get("request", request_id)
    if not request or request.get("payload", {}).get("created_by_agent_key") != agent["id"]:
        raise HTTPException(404, "request not found")
    return {"id": request["id"], "kind": request["kind"], "status": request["status"],
            "title": request["title"], "created_at": request["created_at"],
            "decision": request.get("decision")}


@app.post("/v2/admin/requests")
def create_admin_request(payload: V2Request, _tier: str = Depends(require_admin)):
    return control_plane.create_request(payload.kind, payload.title, payload.details, "admin", payload.payload, payload.severity)


@app.post("/v2/requests/{request_id}/decision")
def decide_request(request_id: str, payload: V2RequestDecision, _tier: str = Depends(require_admin)):
    if payload.status not in {"approved", "rejected", "dismissed"}:
        raise HTTPException(400, "status must be approved, rejected, or dismissed")
    try:
        record = control_plane.decide_request(request_id, payload.status, "admin", payload.note)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not record:
        raise HTTPException(404, "request not found")
    if record["kind"] == "ai_draft" and payload.status == "approved":
        proposal = record.get("payload", {})
        target_kind, draft = proposal.get("target_kind"), proposal.get("draft", {})
        try:
            # Approval accepts the planner's proposal into the owner workspace.
            # A separate owner edit is required before the capability becomes active.
            draft["status"] = "draft"
            if target_kind == "tool":
                require_valid_tool_definition(draft)
                created = control_plane.create_tool(draft)
            elif target_kind == "automation":
                require_valid_automation_definition(draft)
                created = control_plane.create_automation(draft)
            else:
                raise ValueError("AI proposal has no valid target kind")
        except (KeyError, ValueError) as exc:
            raise HTTPException(409, f"Could not promote approved AI proposal: {exc}")
        control_plane.event("ai_proposal_promoted", "info", target_kind, created["id"], "admin", {"request_id": request_id})
        record["created"] = created
    return record


@app.get("/v2/events")
def list_events(limit: int = 100, _tier: str = Depends(require_admin)):
    return control_plane.events(limit)


@app.get("/v2/agent/events")
def agent_events(limit: int = 50, _agent: dict = Depends(require_agent)):
    return [{key: event[key] for key in ("id", "event_type", "severity", "subject_type", "subject_id", "created_at")} for event in control_plane.events(limit)]
