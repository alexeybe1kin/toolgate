"""Typed v2 control-plane storage and enforcement helpers.

This module deliberately keeps ToolGate's owner data in SQLite and exposes a
small declarative model.  Generated executors may consume these definitions,
but agents never get write access to them directly.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from toolgate.core.paths import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS v2_objects (
      kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY (kind, id)
    );
    CREATE TABLE IF NOT EXISTS v2_agent_keys (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
      scopes TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
      last_used_at TEXT
    );
    CREATE TABLE IF NOT EXISTS v2_events (
      id TEXT PRIMARY KEY, event_type TEXT NOT NULL, severity TEXT NOT NULL,
      subject_type TEXT, subject_id TEXT, actor TEXT, payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    """)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def purge_legacy_state() -> None:
    """Remove pre-v2 runtime tables from a reused local database.

    ToolGate v2 is intentionally a fresh control plane; old script approvals and
    audit data must not survive as hidden operational state.
    """
    with _conn() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for row in rows:
            name = row["name"]
            if name.startswith("v2_") or name.startswith("sqlite_"):
                continue
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')


def _row(row: sqlite3.Row) -> dict:
    value = json.loads(row["body"])
    value.setdefault("id", row["id"])
    value.setdefault("created_at", row["created_at"])
    value.setdefault("updated_at", row["updated_at"])
    return value


def _put(kind: str, obj_id: str, body: dict) -> dict:
    now = _now()
    body = {**body, "id": obj_id}
    with _conn() as conn:
        existing = conn.execute("SELECT created_at FROM v2_objects WHERE kind=? AND id=?", (kind, obj_id)).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            "INSERT INTO v2_objects(kind,id,body,created_at,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at",
            (kind, obj_id, json.dumps(body), created, now),
        )
    return {**body, "created_at": created, "updated_at": now}


def get(kind: str, obj_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM v2_objects WHERE kind=? AND id=?", (kind, obj_id)).fetchone()
    return _row(row) if row else None


def list_objects(kind: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM v2_objects WHERE kind=? ORDER BY updated_at DESC", (kind,)).fetchall()
    return [_row(row) for row in rows]


def remove(kind: str, obj_id: str) -> bool:
    with _conn() as conn:
        return conn.execute("DELETE FROM v2_objects WHERE kind=? AND id=?", (kind, obj_id)).rowcount > 0


def cache_research_result(result: dict, expires_at: str) -> dict:
    """Store a short-lived search result for provenance-bound page fetching."""
    result_id = "rr_" + secrets.token_urlsafe(18)
    return _put("research_result", result_id, {
        "title": result.get("title", ""),
        "url": result["url"],
        "source": result.get("source", "general"),
        "published_at": result.get("published_at"),
        "document": str(result.get("document", ""))[:20000] if result.get("document") else None,
        "expires_at": expires_at,
    })


def get_research_result(result_id: str) -> dict | None:
    if not isinstance(result_id, str) or not re.fullmatch(r"rr_[A-Za-z0-9_-]{20,40}", result_id):
        return None
    return get("research_result", result_id)


def purge_expired_research_results(now: datetime | None = None) -> int:
    cutoff = now or datetime.now(timezone.utc)
    removed = 0
    for record in list_objects("research_result"):
        try:
            expired = datetime.fromisoformat(record["expires_at"]) <= cutoff
        except (KeyError, TypeError, ValueError):
            expired = True
        if expired and remove("research_result", record["id"]):
            removed += 1
    return removed


def event(event_type: str, severity: str = "info", subject_type: str | None = None,
          subject_id: str | None = None, actor: str | None = None, payload: dict | None = None) -> dict:
    record = {"id": str(uuid.uuid4()), "event_type": event_type, "severity": severity,
              "subject_type": subject_type, "subject_id": subject_id, "actor": actor,
              "payload": payload or {}, "created_at": _now()}
    with _conn() as conn:
        conn.execute("INSERT INTO v2_events VALUES(?,?,?,?,?,?,?,?)", (
            record["id"], record["event_type"], record["severity"], record["subject_type"],
            record["subject_id"], record["actor"], json.dumps(record["payload"]), record["created_at"],
        ))
    return record


def events(limit: int = 100, event_type: str | None = None) -> list[dict]:
    query, params = "SELECT * FROM v2_events", []
    if event_type:
        query += " WHERE event_type=?"
        params.append(event_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(min(max(limit, 1), 500))
    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]


def event_count_since(event_type: str, subject_type: str, subject_id: str, seconds: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(seconds, 0))).isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM v2_events "
            "WHERE event_type=? AND subject_type=? AND subject_id=? AND created_at>=?",
            (event_type, subject_type, subject_id, cutoff),
        ).fetchone()
    return int(row["count"])


def latest_event_at(event_type: str, subject_type: str, subject_id: str) -> datetime | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT created_at FROM v2_events WHERE event_type=? AND subject_type=? AND subject_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (event_type, subject_type, subject_id),
        ).fetchone()
    return datetime.fromisoformat(row["created_at"]) if row else None


def settings() -> dict:
    return get("settings", "control-plane") or {"id": "control-plane", "lockdown": False}


def set_lockdown(enabled: bool, actor: str, reason: str = "") -> dict:
    state = {**settings(), "lockdown": enabled, "reason": reason, "changed_by": actor}
    state = _put("settings", "control-plane", state)
    event("lockdown_enabled" if enabled else "lockdown_disabled", "critical" if enabled else "info",
          "settings", "control-plane", actor, {"reason": reason})
    return state


def update_settings(changes: dict, actor: str) -> dict:
    protected = {"id", "created_at", "updated_at", "lockdown", "changed_by", "reason"}
    state = settings()
    state.update({key: value for key, value in changes.items() if key not in protected})
    state = _put("settings", "control-plane", state)
    event("settings_updated", "info", "settings", "control-plane", actor, {"keys": sorted(changes)})
    return state


def issue_agent_key(name: str, scopes: list[str]) -> tuple[dict, str]:
    raw = "tgx_" + secrets.token_urlsafe(32)
    record = {"id": str(uuid.uuid4()), "name": name, "key_hash": hashlib.sha256(raw.encode()).hexdigest(),
              "scopes": scopes or [], "status": "active", "created_at": _now()}
    with _conn() as conn:
        conn.execute("INSERT INTO v2_agent_keys(id,name,key_hash,scopes,status,created_at) VALUES(?,?,?,?,?,?)",
                     (record["id"], record["name"], record["key_hash"], json.dumps(record["scopes"]),
                      record["status"], record["created_at"]))
    event("agent_key_created", "info", "agent_key", record["id"], "admin", {"name": name, "scopes": scopes})
    return public_agent_key(record), raw


def ensure_bootstrap_agent_key(raw: str, scopes: list[str], name: str = "AgentGate Pi") -> dict:
    """Seed one explicit deployment key without ever persisting its raw value."""
    if not raw.startswith("tgx_") or len(raw) < 20:
        raise ValueError("TOOLGATE_BOOTSTRAP_EXECUTION_KEY must start with tgx_ and be at least 20 characters")
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    normalized_scopes = scopes or []
    updated_record: sqlite3.Row | None = None
    created_record: dict | None = None
    with _conn() as conn:
        existing = conn.execute("SELECT * FROM v2_agent_keys WHERE key_hash=?", (hashed,)).fetchone()
        if existing:
            current = json.loads(existing["scopes"]) if isinstance(existing["scopes"], str) else existing["scopes"]
            if current != normalized_scopes:
                conn.execute(
                    "UPDATE v2_agent_keys SET scopes=?, status='active' WHERE id=?",
                    (json.dumps(normalized_scopes), existing["id"]),
                )
                existing = conn.execute("SELECT * FROM v2_agent_keys WHERE id=?", (existing["id"],)).fetchone()
                updated_record = existing
            result = public_agent_key(existing)
        else:
            record = {
                "id": str(uuid.uuid4()),
                "name": name,
                "key_hash": hashed,
                "scopes": normalized_scopes,
                "status": "active",
                "created_at": _now(),
            }
            conn.execute(
                "INSERT INTO v2_agent_keys(id,name,key_hash,scopes,status,created_at) VALUES(?,?,?,?,?,?)",
                (record["id"], record["name"], record["key_hash"], json.dumps(record["scopes"]), record["status"], record["created_at"]),
            )
            created_record = record
            result = public_agent_key(record)
    if updated_record:
        event(
            "agent_key_bootstrap_scopes_updated",
            "info",
            "agent_key",
            updated_record["id"],
            "deployment",
            {"name": name, "scopes": normalized_scopes},
        )
    if created_record:
        event("agent_key_bootstrapped", "info", "agent_key", created_record["id"], "deployment", {"name": name, "scopes": normalized_scopes})
    return result


def public_agent_key(record: dict | sqlite3.Row) -> dict:
    value = dict(record)
    value.pop("key_hash", None)
    if isinstance(value.get("scopes"), str):
        value["scopes"] = json.loads(value["scopes"])
    return value


def list_agent_keys() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM v2_agent_keys ORDER BY created_at DESC").fetchall()
    return [public_agent_key(row) for row in rows]


def update_agent_key_scopes(key_id: str, scopes: list[str], actor: str = "admin") -> dict | None:
    normalized = [str(scope).strip() for scope in scopes if str(scope).strip()]
    with _conn() as conn:
        row = conn.execute("SELECT * FROM v2_agent_keys WHERE id=?", (key_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE v2_agent_keys SET scopes=?, status='active' WHERE id=?",
            (json.dumps(normalized), key_id),
        )
        updated = conn.execute("SELECT * FROM v2_agent_keys WHERE id=?", (key_id,)).fetchone()
    event("agent_key_scopes_updated", "info", "agent_key", key_id, actor, {"scopes": normalized})
    return public_agent_key(updated)


def authenticate_agent(raw: str | None) -> dict | None:
    if not raw:
        return None
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM v2_agent_keys WHERE key_hash=? AND status='active'", (hashed,)).fetchone()
        if row:
            conn.execute("UPDATE v2_agent_keys SET last_used_at=? WHERE id=?", (_now(), row["id"]))
    return public_agent_key(row) if row else None


def revoke_agent_key(key_id: str, actor: str = "admin") -> bool:
    with _conn() as conn:
        changed = conn.execute("UPDATE v2_agent_keys SET status='revoked' WHERE id=?", (key_id,)).rowcount
    if changed:
        event("agent_key_revoked", "warning", "agent_key", key_id, actor)
    return bool(changed)


def is_scoped(agent: dict, capability: str) -> bool:
    scopes = agent.get("scopes", [])
    if "*" in scopes or capability in scopes:
        return True
    if any(isinstance(scope, str) and scope.endswith("*") and capability.startswith(scope[:-1]) for scope in scopes):
        return True
    if capability.startswith("automation:"):
        return "automation:*" in scopes
    tool_id = capability.removeprefix("tool:")
    return (
        "tool:*" in scopes
        or f"tool:{tool_id}" in scopes
        or tool_id in scopes
        or any(isinstance(scope, str) and scope.endswith("*") and tool_id.startswith(scope[:-1]) for scope in scopes)
        or any(isinstance(scope, str) and scope.startswith("tool:") and scope.endswith("*") and tool_id.startswith(scope[5:-1]) for scope in scopes)
    )


def validate_inputs(schema: list[dict], args: dict) -> list[str]:
    errors: list[str] = []
    known = {field.get("name") for field in schema}
    for key in args:
        if key not in known:
            errors.append(f"'{key}' is not an allowed argument")
    for field in schema:
        name, value = field.get("name"), args.get(field.get("name"))
        if field.get("required") and name not in args:
            errors.append(f"'{name}' is required")
            continue
        if value is None:
            continue
        kind = field.get("type", "string")
        if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"'{name}' must be an integer")
        elif kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            errors.append(f"'{name}' must be a number")
        elif kind == "boolean" and not isinstance(value, bool):
            errors.append(f"'{name}' must be true or false")
        elif kind == "string" and not isinstance(value, str):
            errors.append(f"'{name}' must be text")
        elif kind == "array" and not isinstance(value, list):
            errors.append(f"'{name}' must be an array")
        if isinstance(value, (int, float)):
            if field.get("minimum") is not None and value < field["minimum"]:
                errors.append(f"'{name}' must be at least {field['minimum']}")
            if field.get("maximum") is not None and value > field["maximum"]:
                errors.append(f"'{name}' must be at most {field['maximum']}")
        if isinstance(value, str):
            if field.get("min_length") is not None and len(value) < field["min_length"]:
                errors.append(f"'{name}' is too short")
            if field.get("max_length") is not None and len(value) > field["max_length"]:
                errors.append(f"'{name}' is too long")
            if field.get("pattern") and not re.search(field["pattern"], value):
                errors.append(f"'{name}' does not match the required format")
        if isinstance(value, list):
            if field.get("min_items") is not None and len(value) < field["min_items"]:
                errors.append(f"'{name}' must contain at least {field['min_items']} items")
            if field.get("max_items") is not None and len(value) > field["max_items"]:
                errors.append(f"'{name}' must contain at most {field['max_items']} items")
            if field.get("unique_items") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
                errors.append(f"'{name}' must not contain duplicate items")
            if field.get("item_type") == "string" and any(not isinstance(item, str) for item in value):
                errors.append(f"'{name}' items must be text")
            pattern = field.get("item_pattern")
            if pattern and any(not isinstance(item, str) or not re.fullmatch(pattern, item) for item in value):
                errors.append(f"'{name}' contains an invalid item")
        allowed = field.get("allowed_values") or []
        if allowed and value not in allowed:
            errors.append(f"'{name}' must be one of: {', '.join(map(str, allowed))}")
    return errors


def create_service(body: dict) -> dict:
    service_id = body.get("id") or body["name"].lower().replace(" ", "-")
    return _put("service", service_id, {"name": body["name"], "description": body.get("description", ""),
        "secret_refs": body.get("secret_refs", []), "health": body.get("health", "unknown"),
        "destination_policy": body.get("destination_policy", {}), "status": body.get("status", "active")})


def update_service(service_id: str, changes: dict) -> dict | None:
    service = get("service", service_id)
    if not service:
        return None
    service.update({key: value for key, value in changes.items()
                    if key not in {"id", "created_at", "updated_at"}})
    return _put("service", service_id, service)


def create_verification_method(body: dict) -> dict:
    method_id = body.get("id") or str(uuid.uuid4())
    return _put("verification_method", method_id, {
        "name": body.get("name", "Verification adapter"),
        "method_type": body.get("method_type", "signed_callback"),
        "secret_ref": body.get("secret_ref"),
        "status": body.get("status", "active"),
        "last_seen_at": body.get("last_seen_at"),
    })


def update_verification_method(method_id: str, changes: dict) -> dict | None:
    method = get("verification_method", method_id)
    if not method:
        return None
    method.update({key: value for key, value in changes.items()
                   if key not in {"id", "created_at", "updated_at"}})
    return _put("verification_method", method_id, method)


def create_tool(body: dict) -> dict:
    tool_id = body["id"]
    return _put("tool", tool_id, {"name": body.get("name", tool_id), "description": body.get("description", ""),
        "service_id": body.get("service_id"), "category": body.get("category", "controlled"),
        "inputs": body.get("inputs", []), "outputs": body.get("outputs", []),
        "execution": body.get("execution", {}), "policy": body.get("policy", {}),
        "authorization": body.get("authorization", "auto"), "version": body.get("version", 1), "status": body.get("status", "active")})


def update_tool(tool_id: str, body: dict) -> dict | None:
    if not get("tool", tool_id):
        return None
    return create_tool({**body, "id": tool_id, "version": int(body.get("version", 1)) + 1})


def create_automation(body: dict) -> dict:
    automation_id = body["id"]
    return _put("automation", automation_id, {"name": body.get("name", automation_id),
        "description": body.get("description", ""), "inputs": body.get("inputs", []),
        "workflow": body.get("workflow", []), "policy": body.get("policy", {}),
        "authorization": body.get("authorization", "auto"), "schedule": body.get("schedule"),
        "version": body.get("version", 1), "status": body.get("status", "draft")})


def update_automation(automation_id: str, body: dict) -> dict | None:
    if not get("automation", automation_id):
        return None
    return create_automation({**body, "id": automation_id, "version": int(body.get("version", 1)) + 1})


def create_ai_session(target_kind: str) -> dict:
    session_id = str(uuid.uuid4())
    label = "tool" if target_kind == "tool" else "automation"
    return _put("ai_session", session_id, {
        "title": f"New {label} design",
        "target_kind": target_kind,
        "status": "clarifying",
        "messages": [{
            "role": "assistant",
            "content": f"Tell me what the {label} should accomplish. I will clarify the inputs, execution path, and safety limits before creating a draft.",
            "created_at": _now(),
        }],
        "draft": None,
        "proposal_request_id": None,
        "stages": [
            {"id": "requirements", "label": "Clarifying requirements", "status": "active"},
            {"id": "contract", "label": "Defining inputs and outputs", "status": "queued"},
            {"id": "execution", "label": "Creating executable layer", "status": "queued"},
            {"id": "safety", "label": "Creating safety policy", "status": "queued"},
            {"id": "limits", "label": "Applying deterministic limits", "status": "queued"},
            {"id": "review", "label": "Preparing owner review", "status": "queued"},
        ],
        "activity": [{
            "phase": "Session created",
            "detail": f"Started a persistent {label} design workspace.",
            "status": "completed",
            "created_at": _now(),
        }],
    })


def update_ai_session(session_id: str, changes: dict) -> dict | None:
    session = get("ai_session", session_id)
    if not session:
        return None
    protected = {"id", "created_at", "updated_at"}
    session.update({key: value for key, value in changes.items() if key not in protected})
    return _put("ai_session", session_id, session)


def create_request(kind: str, title: str, details: str, actor: str, payload: dict | None = None,
                   severity: str = "info") -> dict:
    request_id = str(uuid.uuid4())
    record = _put("request", request_id, {"kind": kind, "title": title, "details": details,
        "actor": actor, "payload": payload or {}, "severity": severity, "status": "pending"})
    event("request_created", severity, "request", request_id, actor, {"kind": kind, "title": title})
    return record


def action_digest(subject_type: str, subject_id: str, args: dict, version: int | None = None) -> str:
    canonical = json.dumps({"subject_type": subject_type, "subject_id": subject_id,
                            "version": version, "args": args}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_verification_request(title: str, details: str, actor: str, subject_type: str,
                                subject_id: str, args: dict, version: int | None,
                                expiry_seconds: int = 60, actor_id: str | None = None) -> dict:
    expiry = datetime.now(timezone.utc) + timedelta(seconds=max(15, min(expiry_seconds, 900)))
    binding = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "version": version,
        "args_digest": action_digest(subject_type, subject_id, args, version),
        "nonce": secrets.token_urlsafe(24),
        "expires_at": expiry.isoformat(),
        "consumed_at": None,
    }
    return create_request("verification", title, details, actor,
                          {"subject_type": subject_type, "subject_id": subject_id,
                           "args": args, "binding": binding,
                           "created_by_agent_key": actor_id}, "warning")


def consume_verification(request_id: str, subject_type: str, subject_id: str,
                         args: dict, version: int | None, actor: str,
                         actor_id: str | None = None) -> tuple[bool, str]:
    """Atomically consume an approved action binding exactly once."""
    now = datetime.now(timezone.utc)
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM v2_objects WHERE kind='request' AND id=?", (request_id,)).fetchone()
        if not row:
            return False, "Approval request was not found"
        record = _row(row)
        binding = record.get("payload", {}).get("binding", {})
        if record.get("kind") != "verification" or record.get("status") != "approved":
            return False, f"Approval request is {record.get('status', 'invalid')}"
        created_by = record.get("payload", {}).get("created_by_agent_key")
        if created_by and actor_id != created_by:
            return False, "Approval request belongs to a different originating agent"
        if binding.get("consumed_at"):
            return False, "Approval request has already been consumed"
        try:
            expires_at = datetime.fromisoformat(binding["expires_at"])
        except (KeyError, TypeError, ValueError):
            return False, "Approval request has an invalid expiry"
        if expires_at <= now:
            return False, "Approval request has expired"
        expected = action_digest(subject_type, subject_id, args, version)
        if not secrets.compare_digest(str(binding.get("args_digest", "")), expected):
            return False, "Approval does not match this exact action"
        binding["consumed_at"] = now.isoformat()
        binding["consumed_by"] = actor
        record["payload"]["binding"] = binding
        conn.execute("UPDATE v2_objects SET body=?,updated_at=? WHERE kind='request' AND id=?",
                     (json.dumps({key: value for key, value in record.items()
                                  if key not in {"created_at", "updated_at"}}), now.isoformat(), request_id))
    event("verification_consumed", "info", "request", request_id, actor,
          {"subject_type": subject_type, "subject_id": subject_id})
    return True, "approved"


def decide_request(request_id: str, status: str, actor: str, note: str = "") -> dict | None:
    record = get("request", request_id)
    if not record:
        return None
    if record.get("status") != "pending":
        raise ValueError(f"request is already {record.get('status')}")
    record["status"] = status
    record["decision"] = {"actor": actor, "note": note, "at": _now()}
    record = _put("request", request_id, record)
    event("request_decided", "info" if status == "approved" else "warning", "request", request_id, actor,
          {"status": status})
    return record
