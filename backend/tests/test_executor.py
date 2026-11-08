"""Mocked tests for data.executor.execute_plan (moto DynamoDB; no real AWS)."""

import json

import boto3
import pytest
from moto import mock_aws

from core.fingerprint import plan_fingerprint
from data import dynamo, executor
from data.executor import execute_plan
from data.schema import DEMO_AGENT_ID, table_definitions, table_names
from security.authorization import authorize_plan

NO_ACTIVE = lambda: False  # noqa: E731


@pytest.fixture
def db(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "SENTINEL_WAREHOUSE_TABLE", "SENTINEL_AGENTS_TABLE",
                "SENTINEL_AUDIT_TABLE", "SENTINEL_EXECUTIONS_TABLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    dynamo.reset_connection()
    with mock_aws():
        client = boto3.client("dynamodb")
        for definition in table_definitions():
            client.create_table(**definition)
        dynamo.seed_if_missing()
        yield client
    dynamo.reset_connection()


def move(source, destination, count):
    return {"type": "move_packages", "from": source, "to": destination, "count": count}


def plan(*actions):
    return {"actions": list(actions)}


def run_id():
    return dynamo.get_run_id()


def inventory():
    return {zone: z["inventory"] for zone, z in dynamo.get_warehouse()["zones"].items()}


def version():
    return dynamo.get_warehouse()["version"]


def approval_for(p, rev, wh_version, run, /, plan_id="plan-1", **overrides):
    """The agreed executor envelope, exactly as the workflow's execution_approval builds it."""
    record = {
        "approval_id": "approval-1",
        "plan_id": plan_id,
        "revision": rev,
        "fingerprint": plan_fingerprint(p),
        "warehouse_version": wh_version,
        "run_id": run,
        "decision": "APPROVED",
        "admin": "alice@scu.edu",
        "decided_at": "2026-11-07T23:30:00Z",
    }
    record.update(overrides)
    return record


def execute(p, *, plan_id="plan-1", revision=1, warehouse_version=None, run=None, approval=None):
    return execute_plan(
        plan_id=plan_id,
        revision=revision,
        plan=p,
        warehouse_version=version() if warehouse_version is None else warehouse_version,
        run_id=run_id() if run is None else run,
        approval=approval,
    )


def assert_no_commit(result, code, before_inventory, before_version):
    assert result["executed"] is False
    assert result["no_commit"] is True
    assert result["error"]["code"] == code, result
    assert inventory() == before_inventory
    assert version() == before_version


def markers():
    return boto3.client("dynamodb").scan(TableName=table_names()["executions"])["Count"]


# ------------------------------------------------------- judged walkthrough D1-D3


def test_d1_d2_d3_walkthrough_exact_states(db):
    # D1: low risk, no approval needed.
    d1 = execute(plan(move("A", "C", 3)), plan_id="plan-d1")
    assert d1["executed"] is True and d1["status"] == "COMPLETED"
    assert (d1["warehouse_version_before"], d1["warehouse_version_after"]) == (1, 2)
    assert inventory() == {"A": 17, "B": 8, "C": 8} and version() == 2

    # D2: the 5-package split needs approval bound to this exact plan/version/run.
    split = plan(move("A", "B", 2), move("A", "C", 3))
    unapproved = execute(split, plan_id="plan-d2", revision=2)
    assert_no_commit(unapproved, "APPROVAL_REQUIRED", {"A": 17, "B": 8, "C": 8}, 2)
    d2 = execute(split, plan_id="plan-d2", revision=2, approval=approval_for(split, 2, 2, run_id(), plan_id="plan-d2"))
    assert d2["executed"] is True
    assert inventory() == {"A": 12, "B": 10, "C": 11} and version() == 3
    assert d2["warehouse"]["zones"]["B"] == {"inventory": 10, "capacity": 10}

    # D3: revoked agent is denied; nothing changes.
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")
    d3 = execute(plan(move("A", "C", 1)), plan_id="plan-d3")
    assert_no_commit(d3, "AUTHORIZATION_DENIED", {"A": 12, "B": 10, "C": 11}, 3)
    assert d3["status"] == "REJECTED"
    assert d3["authorization"]["decisions"][0]["reason_code"] == "AGENT_REVOKED"
    assert sum(inventory().values()) == 33


def test_execution_result_matches_contract_shape(db):
    result = execute(plan(move("A", "C", 3)))

    assert set(result) == {"plan_id", "revision", "executed", "status", "warehouse_version_before",
                           "warehouse_version_after", "warehouse"}
    assert result["warehouse"] == dynamo.get_warehouse()
    assert json.loads(json.dumps(result)) == result


def test_commit_writes_marker_and_audit_event(db):
    execute(plan(move("A", "C", 3)), plan_id="plan-x")

    assert markers() == 1
    [event] = dynamo.list_audit_events("plan-x")
    assert event["event_type"] == "PLAN_EXECUTED"
    assert event["details"]["authorization_engine"] == "LOCAL_POLICY"


def test_approved_execution_audit_names_the_admin(db):
    split = plan(move("A", "B", 2), move("A", "C", 3))
    execute(split, plan_id="plan-a", approval=approval_for(split, 1, 1, run_id(), plan_id="plan-a"))

    [event] = dynamo.list_audit_events("plan-a")
    assert event["admin"] == "alice@scu.edu"


# ------------------------------------------------------------- replay / idempotency


def test_replay_returns_original_result_without_second_commit(db):
    p = plan(move("A", "C", 3))
    first = execute(p, plan_id="plan-r", warehouse_version=1)
    second = execute(p, plan_id="plan-r", warehouse_version=1)

    assert second == first
    assert inventory() == {"A": 17, "B": 8, "C": 8} and version() == 2
    assert markers() == 1


def test_replay_returns_original_even_after_warehouse_moved_on(db):
    p = plan(move("A", "C", 3))
    first = execute(p, plan_id="plan-r", warehouse_version=1)
    execute(plan(move("A", "B", 1)), plan_id="plan-other")

    assert execute(p, plan_id="plan-r", warehouse_version=1) == first
    assert version() == 3


def test_concurrent_duplicate_returns_prior_result_not_a_second_commit(db, monkeypatch):
    """A duplicate slips past the replay check (simulated race); the marker condition
    in the transaction stops it, and the caller gets the original result."""
    p = plan(move("A", "C", 3))
    seed_snapshot = (dynamo.get_warehouse(), run_id(), dynamo.get_agent(DEMO_AGENT_ID))
    first = execute(p, plan_id="plan-dup", warehouse_version=1)

    real_read_marker = executor._read_marker
    calls = {"n": 0}

    def racing_read_marker(execution_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_read_marker(execution_id)

    monkeypatch.setattr(executor, "_read_marker", racing_read_marker)
    monkeypatch.setattr(executor, "_read_state", lambda *a: seed_snapshot)

    again = execute_plan(plan_id="plan-dup", revision=1, plan=p, warehouse_version=1,
                         run_id=seed_snapshot[1], approval=None)

    assert again == first
    assert version() == 2 and markers() == 1
    assert inventory() == {"A": 17, "B": 8, "C": 8}


# ------------------------------------------------------------- stale state / races


def test_stale_version_is_rejected(db):
    execute(plan(move("A", "C", 1)), plan_id="plan-first")

    stale = execute(plan(move("A", "C", 1)), plan_id="plan-stale", warehouse_version=1)

    assert_no_commit(stale, "VERSION_CONFLICT", {"A": 19, "B": 8, "C": 6}, 2)
    assert stale["error"]["retryable"] is True
    assert stale["status"] == "FAILED"


def test_two_plans_competing_for_zone_b_only_one_commits(db):
    p = plan(move("A", "B", 2))
    winner = execute(p, plan_id="plan-1", warehouse_version=1)
    loser = execute(p, plan_id="plan-2", warehouse_version=1)

    assert winner["executed"] is True
    assert_no_commit(loser, "VERSION_CONFLICT", {"A": 18, "B": 10, "C": 5}, 2)


def test_version_change_between_checks_and_commit_cancels_transaction(db, monkeypatch):
    """Snapshot says version 1 but another commit lands first: the conditional write refuses."""
    snapshot = (dynamo.get_warehouse(), run_id(), dynamo.get_agent(DEMO_AGENT_ID))
    execute(plan(move("A", "B", 2)), plan_id="plan-fast")  # B=10, v2
    monkeypatch.setattr(executor, "_read_state", lambda *a: snapshot)

    slow = execute_plan(plan_id="plan-slow", revision=1, plan=plan(move("A", "B", 2)),
                        warehouse_version=1, run_id=snapshot[1], approval=None)

    assert_no_commit(slow, "VERSION_CONFLICT", {"A": 18, "B": 10, "C": 5}, 2)
    assert dynamo.get_warehouse()["zones"]["B"]["inventory"] == 10  # never 12


def test_revocation_between_checks_and_commit_cancels_transaction(db, monkeypatch):
    snapshot = (dynamo.get_warehouse(), run_id(), dynamo.get_agent(DEMO_AGENT_ID))  # agent ACTIVE
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")
    monkeypatch.setattr(executor, "_read_state", lambda *a: snapshot)

    result = execute_plan(plan_id="plan-race", revision=1, plan=plan(move("A", "C", 1)),
                          warehouse_version=1, run_id=snapshot[1], approval=None)

    assert_no_commit(result, "AUTHORIZATION_DENIED", {"A": 20, "B": 8, "C": 5}, 1)
    assert markers() == 0


def test_reset_between_checks_and_commit_reports_run_mismatch(db, monkeypatch):
    snapshot = (dynamo.get_warehouse(), run_id(), dynamo.get_agent(DEMO_AGENT_ID))
    dynamo.reset_demo(active_workflow_check=NO_ACTIVE)
    monkeypatch.setattr(executor, "_read_state", lambda *a: snapshot)

    result = execute_plan(plan_id="plan-r", revision=1, plan=plan(move("A", "C", 1)),
                          warehouse_version=1, run_id=snapshot[1], approval=None)

    assert_no_commit(result, "RUN_MISMATCH", {"A": 20, "B": 8, "C": 5}, 1)


def test_plan_from_before_reset_is_rejected(db):
    old_run = run_id()
    dynamo.reset_demo(active_workflow_check=NO_ACTIVE)  # version is 1 again, new run

    result = execute(plan(move("A", "C", 1)), warehouse_version=1, run=old_run)

    assert_no_commit(result, "RUN_MISMATCH", {"A": 20, "B": 8, "C": 5}, 1)


# -------------------------------------------------------------------- approvals


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"decision": "PENDING"}, id="pending"),
        pytest.param({"decision": "DENIED"}, id="denied"),
        pytest.param({"decision": None}, id="no-decision"),
        pytest.param({"admin": ""}, id="no-admin"),
        pytest.param({"decided_at": ""}, id="no-decided-at"),
        pytest.param({"decided_at": None}, id="null-decided-at"),
        pytest.param({"plan_id": "plan-other"}, id="other-plan-id"),
        pytest.param({"revision": 2}, id="other-revision"),
        pytest.param({"fingerprint": "0" * 64}, id="other-plan"),
        pytest.param({"warehouse_version": 2}, id="other-version"),
        pytest.param({"run_id": "old-run"}, id="other-run"),
    ],
)
def test_mismatched_approval_never_executes(db, overrides):
    split = plan(move("A", "B", 2), move("A", "C", 3))
    result = execute(split, approval=approval_for(split, 1, 1, run_id(), **overrides))

    assert_no_commit(result, "APPROVAL_INVALID", {"A": 20, "B": 8, "C": 5}, 1)
    assert result["status"] == "REJECTED"


def test_approval_for_a_different_plan_cannot_be_reused(db):
    approved = plan(move("A", "B", 2), move("A", "C", 3))
    other = plan(move("A", "C", 5))

    result = execute(other, approval=approval_for(approved, 1, 1, run_id()))

    assert_no_commit(result, "APPROVAL_INVALID", {"A": 20, "B": 8, "C": 5}, 1)


def test_revoked_after_approval_is_blocked(db):
    split = plan(move("A", "B", 2), move("A", "C", 3))
    approval = approval_for(split, 1, 1, run_id())
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    result = execute(split, approval=approval)

    assert_no_commit(result, "AUTHORIZATION_DENIED", {"A": 20, "B": 8, "C": 5}, 1)


def test_total_of_four_needs_no_approval_and_five_does(db):
    four = execute(plan(move("A", "C", 2), move("A", "C", 2)), plan_id="p4")
    five = execute(plan(move("A", "C", 2), move("A", "C", 3)), plan_id="p5")

    assert four["executed"] is True
    assert five["error"]["code"] == "APPROVAL_REQUIRED"


# ------------------------------------------------------- policy and simulation


def test_capacity_violation_never_commits(db):
    result = execute(plan(move("A", "B", 5)), approval=None)

    # 5 packages is elevated: approval is checked before the simulation verdict.
    assert result["error"]["code"] == "APPROVAL_REQUIRED"
    p = plan(move("A", "B", 5))
    approved = execute(p, approval=approval_for(p, 1, 1, run_id()))
    assert_no_commit(approved, "SIMULATION_FAILED", {"A": 20, "B": 8, "C": 5}, 1)
    assert approved["violations"][0]["code"] == "CAPACITY_EXCEEDED"


def test_cumulative_capacity_violation_never_commits(db):
    result = execute(plan(move("A", "B", 2), move("A", "B", 1)))

    assert_no_commit(result, "SIMULATION_FAILED", {"A": 20, "B": 8, "C": 5}, 1)


def test_more_than_ten_in_one_action_is_denied_by_policy(db):
    p = plan(move("A", "C", 11))
    result = execute(p, approval=approval_for(p, 1, 1, run_id()))

    assert_no_commit(result, "AUTHORIZATION_DENIED", {"A": 20, "B": 8, "C": 5}, 1)
    assert result["authorization"]["decisions"][0]["reason_code"] == "LIMIT_EXCEEDED"


def test_hazmat_destination_is_denied(db):
    result = execute(plan(move("A", "HAZMAT", 1)))

    assert_no_commit(result, "AUTHORIZATION_DENIED", {"A": 20, "B": 8, "C": 5}, 1)
    assert result["authorization"]["decisions"][0]["reason_code"] == "RESTRICTED_DESTINATION"


@pytest.mark.parametrize("bad_plan", [None, {}, plan(), plan(move("A", "C", 0)), plan(move("A", "A", 1)),
                                      {"actions": [move("A", "C", 1)], "approved": True}])
def test_malformed_plans_never_commit(db, bad_plan):
    result = execute(bad_plan)

    assert_no_commit(result, "PLAN_VALIDATION_FAILED", {"A": 20, "B": 8, "C": 5}, 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"plan_id": ""}, id="empty-plan-id"),
        pytest.param({"plan_id": "a#b"}, id="hash-in-plan-id"),
        pytest.param({"revision": 0}, id="revision-zero"),
        pytest.param({"revision": True}, id="revision-bool"),
        pytest.param({"warehouse_version": "1"}, id="version-string"),
        pytest.param({"run_id": ""}, id="empty-run"),
        pytest.param({"approval": "yes"}, id="approval-not-object"),
    ],
)
def test_invalid_inputs_never_commit(db, kwargs):
    base = {"plan_id": "plan-1", "revision": 1, "plan": plan(move("A", "C", 1)),
            "warehouse_version": 1, "run_id": run_id(), "approval": None}
    result = execute_plan(**{**base, **kwargs})

    assert_no_commit(result, "INVALID_REQUEST", {"A": 20, "B": 8, "C": 5}, 1)


def test_infrastructure_failure_raises_instead_of_claiming_no_commit(db):
    db.delete_table(TableName=table_names()["executions"])

    with pytest.raises(dynamo.DataAccessError):
        execute(plan(move("A", "C", 1)))


# ------------------------------------------------------- fingerprint and policy


def test_fingerprint_matches_workflow_algorithm_and_ignores_key_order():
    a = {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 3}]}
    b = {"actions": [{"count": 3, "to": "C", "from": "A", "type": "move_packages"}]}
    expected = __import__("hashlib").sha256(
        json.dumps(a, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()

    assert plan_fingerprint(a) == plan_fingerprint(b) == expected
    assert plan_fingerprint(a) != plan_fingerprint(plan(move("A", "C", 4)))


@pytest.mark.parametrize(
    "agent, action, code",
    [
        ({"status": "ACTIVE", "max_transfer": 10}, move("A", "C", 10), "POLICY_ALLOWED"),
        ({"status": "ACTIVE", "max_transfer": 10}, move("A", "C", 11), "LIMIT_EXCEEDED"),
        ({"status": "ACTIVE", "max_transfer": 10}, move("A", "HAZMAT", 1), "RESTRICTED_DESTINATION"),
        ({"status": "REVOKED", "max_transfer": 10}, move("A", "C", 1), "AGENT_REVOKED"),
        ({"status": "SUSPENDED", "max_transfer": 10}, move("A", "C", 1), "AGENT_SUSPENDED"),
        ({"status": None, "max_transfer": 10}, move("A", "C", 1), "AGENT_NOT_ACTIVE"),
        ({"status": "ACTIVE"}, move("A", "C", 1), "AUTHORIZATION_ERROR"),
        (None, move("A", "C", 1), "AGENT_NOT_ACTIVE"),
    ],
)
def test_local_policy_decisions(agent, action, code):
    result = authorize_plan(plan(action), agent)

    assert result["decisions"][0]["reason_code"] == code
    assert result["allowed"] is (code == "POLICY_ALLOWED")
    assert result["engine"] == "LOCAL_POLICY"


def test_one_denied_action_denies_whole_plan():
    result = authorize_plan(plan(move("A", "C", 1), move("A", "HAZMAT", 1)), {"status": "ACTIVE", "max_transfer": 10})

    assert result["allowed"] is False
    assert [d["allowed"] for d in result["decisions"]] == [True, False]


def test_fingerprint_matches_tishneets_function_when_available():
    """On the integration branch, compare against backend/ai/validation.py directly."""
    try:
        from backend.ai.validation import fingerprint as workflow_fingerprint
    except ImportError:
        try:
            from ai.validation import fingerprint as workflow_fingerprint
        except ImportError:
            pytest.skip("Tishneet's backend/ai is not on this branch; runs after the team merge")
    plans = [
        plan(move("A", "C", 3)),
        plan(move("A", "B", 2), move("A", "C", 3)),
        plan(move("C", "A", 1), move("B", "C", 10)),
    ]
    for p in plans:
        assert plan_fingerprint(p) == workflow_fingerprint(p)


def test_legacy_status_only_envelope_is_rejected(db):
    """The agreed field is 'decision'; an envelope with only 'status' must not execute."""
    split = plan(move("A", "B", 2), move("A", "C", 3))
    legacy = approval_for(split, 1, 1, run_id())
    legacy["status"] = legacy.pop("decision")
    legacy["decision_at"] = legacy.pop("decided_at")

    result = execute(split, approval=legacy)

    assert_no_commit(result, "APPROVAL_INVALID", {"A": 20, "B": 8, "C": 5}, 1)


def test_approved_replay_is_still_idempotent(db):
    split = plan(move("A", "B", 2), move("A", "C", 3))
    approval = approval_for(split, 1, 1, run_id())
    first = execute(split, approval=approval, warehouse_version=1)

    again = execute(split, approval=approval, warehouse_version=1)

    assert again == first and first["executed"] is True
    assert version() == 2 and markers() == 1
