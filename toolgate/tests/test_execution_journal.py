import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from toolgate.api import server
from toolgate.core import control_plane, execution_journal as journal


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setattr(control_plane, "DB_PATH", tmp_path / "gate.db")
    return {"id": "act", "name": "Action", "version": 1, "authorization": "auto",
            "inputs": [], "outputs": [], "execution": {"type": "http_json", "billing": {"mode": "free"}}}


def invoke(tool, **kwargs):
    return server.invoke_tool(tool, kwargs.pop("args", {}), "actor", actor_id="agent",
                              action_id="job.action", **kwargs)


def test_dispatch_is_durable_before_external_effect_and_replay_is_cached(tool, monkeypatch):
    calls = []

    def execute(tool, args):
        with sqlite3.connect(control_plane.DB_PATH) as db:
            assert db.execute("SELECT status FROM v2_actions").fetchone() == ("dispatching",)
        calls.append(args)
        return {"ok": True, "result": {"receipt": "external-123"}}

    monkeypatch.setattr(server, "_dispatch_tool", execute)
    first = invoke(tool)
    assert first["status"] == "completed"
    assert invoke(tool) == first
    assert calls == [{}]
    assert invoke({**tool, "version": 2}) == first


def test_reusing_identity_with_different_arguments_fails(tool, monkeypatch):
    monkeypatch.setattr(server, "_dispatch_tool", lambda *a: {"ok": True, "result": {}})
    invoke(tool)
    with pytest.raises(HTTPException) as caught:
        invoke(tool, args={"changed": True})
    assert caught.value.detail["code"] == "ACTION_CONFLICT"


def test_interruption_after_external_effect_is_unknown_and_never_retried(tool, monkeypatch):
    calls = []

    def crash(*args):
        calls.append("effect happened")
        raise SystemExit("process died before receipt")

    monkeypatch.setattr(server, "_dispatch_tool", crash)
    with pytest.raises(SystemExit):
        invoke(tool)
    assert journal.recover_interrupted() == 1
    assert invoke(tool)["code"] == "OUTCOME_UNKNOWN"
    assert calls == ["effect happened"]


def test_two_callers_cannot_dispatch_same_action(tool, monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def execute(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"ok": True, "result": {}}

    monkeypatch.setattr(server, "_dispatch_tool", execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, tool)
        assert entered.wait(5)
        try:
            assert invoke(tool)["code"] == "IN_PROGRESS"
        finally:
            release.set()
        assert first.result()["status"] == "completed"
    assert calls == [1]


def test_failed_journal_commit_cannot_dispatch_or_consume_approval(tool, monkeypatch):
    tool["authorization"] = "owner_confirmation"
    request = control_plane.create_verification_request("Run", "exact", "actor", "tool",
                                                        "act", {}, 1, actor_id="agent")
    control_plane.decide_request(request["id"], "approved", "owner")
    with control_plane._conn() as db:
        journal.initialize(db)
        db.execute("CREATE TRIGGER reject_dispatch BEFORE INSERT ON v2_actions "
                   "BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    monkeypatch.setattr(server, "_dispatch_tool", lambda *a: pytest.fail("dispatched without record"))
    with pytest.raises(sqlite3.IntegrityError):
        invoke(tool, approval_request_id=request["id"])
    assert control_plane.get("request", request["id"])["payload"]["binding"]["consumed_at"] is None


def test_receipt_write_failure_never_becomes_permission_to_retry(tool, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_dispatch_tool", lambda *a: calls.append(1) or {"ok": True, "result": {}})
    with monkeypatch.context() as patch:
        patch.setattr(journal, "finish", lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError()))
        with pytest.raises(sqlite3.OperationalError):
            invoke(tool)
    assert invoke(tool)["code"] == "IN_PROGRESS"
    journal.recover_interrupted()
    assert invoke(tool)["code"] == "OUTCOME_UNKNOWN"
    assert calls == [1]
