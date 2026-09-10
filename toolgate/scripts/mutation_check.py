"""Prove boundary tests detect broken authority, archival and approval integrity, in disposable copies.

Run from the repository root: python toolgate/scripts/mutation_check.py
No live source, database, vault, or gate configuration is modified.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP = "toolgate/tests/test_mcp_adapter.py::"
ARCHIVE = "toolgate/tests/test_execution_boundary.py::"
INTEGRITY = "toolgate/tests/test_approval_integrity.py::"

# A mutant counts as caught only when its named behavioral test fails, never
# when collection fails or the subprocess cannot start.
MUTANTS = [
    (
        "catalogue scope bypass",
        "toolgate/api/server.py",
        'if tool.get("status") == "active" and control_plane.is_scoped(agent, tool["id"])]',
        'if tool.get("status") == "active"]',
        MCP + "test_scoped_catalogue_and_direct_call_cannot_escape",
    ),
    (
        "invocation scope bypass",
        "toolgate/api/server.py",
        'if tool.get("status") != "active" or not control_plane.is_scoped(agent, tool_id):',
        'if tool.get("status") != "active":',
        MCP + "test_scoped_catalogue_and_direct_call_cannot_escape",
    ),
    (
        "request identity bypass",
        "toolgate/api/server.py",
        'if not request or request.get("payload", {}).get("created_by_agent_key") != agent["id"]:',
        "if not request:",
        MCP + "test_approvals_keep_identity_arguments_and_single_consumption",
    ),
    (
        "partial archive commit",
        "toolgate/core/legacy_archive.py",
        "        for row in retired:\n",
        "        for row in retired:\n            conn.commit()\n",
        ARCHIVE + "test_archive_failure_rolls_back_every_retained_record",
    ),
    (
        "lossy archive",
        "toolgate/core/legacy_archive.py",
        "original = json.dumps(row, ensure_ascii=False, sort_keys=True)",
        'original = json.dumps({**row, "body": "{}"}, ensure_ascii=False, sort_keys=True)',
        ARCHIVE + "test_archive_export_is_lossless_idempotent_and_owner_only",
    ),
    (
        "AI route restored",
        "toolgate/api/server.py",
        '@app.get("/v2/archives/ai")',
        '@app.post("/v2/ai/conversation")\n@app.get("/v2/archives/ai")',
        ARCHIVE + "test_startup_retires_ai_routes_and_preserves_other_tools",
    ),
    (
        "credential redirect enabled",
        "toolgate/mcp/toolgate_mcp.py",
        "follow_redirects=False",
        "follow_redirects=True",
        MCP + "test_transport_never_follows_redirects_or_retries[302]",
    ),
    (
        "forged verification accepted through generic requests",
        "toolgate/core/control_plane.py",
        "if kind not in INFORMATIONAL_REQUEST_KINDS:",
        'if kind not in INFORMATIONAL_REQUEST_KINDS and kind != "verification":',
        INTEGRITY + "test_execution_key_cannot_forge_approval_text_or_binding",
    ),
    (
        "stale decision overwrites consumption",
        "toolgate/core/control_plane.py",
        """    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM v2_objects WHERE kind='request' AND id=?", (request_id,)).fetchone()
        if not row:
            return None
        record = _row(row)
        if record.get("status") != "pending":""",
        """    record = get("request", request_id)
    if not record:
        return None
    with _conn() as conn:
        if record.get("status") != "pending":""",
        INTEGRITY + "test_late_decision_cannot_restore_a_consumed_token",
    ),
    (
        "bootstrap resurrects revoked authority",
        "toolgate/core/control_plane.py",
        "            return public_agent_key(existing)",
        """            conn.execute("UPDATE v2_agent_keys SET scopes=?,status='active' WHERE id=?",
                         (json.dumps(normalized_scopes), existing["id"]))
            return public_agent_key(conn.execute("SELECT * FROM v2_agent_keys WHERE id=?", (existing["id"],)).fetchone())""",
        INTEGRITY + "test_restart_never_widens_or_revives_bootstrap_key",
    ),
]


def run_tests(root: Path, tests: list[str], name: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *tests,
            "-q",
            "--tb=short",
            "-p",
            "no:cacheprovider",
            f"--basetemp={root / name}",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="toolgate-mutations-") as directory:
        root = Path(directory)
        for source in (ROOT / "toolgate").rglob("*.py"):
            destination = root / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        baseline = run_tests(root, sorted({m[4] for m in MUTANTS}), "baseline")
        if baseline.returncode:
            print(baseline.stdout + baseline.stderr)
            print("Baseline failed; fix the behavior before testing mutations.")
            return 1
        print("Baseline passed", flush=True)
        for index, (label, file, before, after, test) in enumerate(MUTANTS):
            path = root / file
            original = path.read_text(encoding="utf-8")
            if original.count(before) != 1:
                raise RuntimeError(
                    f"Mutation anchor changed: {label}. Update the drill before relying on it."
                )
            path.write_text(original.replace(before, after), encoding="utf-8")
            try:
                result = run_tests(root, [test], f"mutant-{index}")
            finally:
                path.write_text(original, encoding="utf-8")
            if result.returncode != 1 or f"FAILED {test}" not in result.stdout:
                print(result.stdout + result.stderr)
                print(f"NOT CAUGHT: {label}")
                return 1
            print(f"Caught: {label}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
