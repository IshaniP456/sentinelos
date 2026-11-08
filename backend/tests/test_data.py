"""Mocked tests for data.dynamo, using moto's in-memory DynamoDB. No real AWS calls.

Run from backend/:
    uv run --no-project --python 3.12 --with pytest --with boto3 --with 'moto[dynamodb]' \
        python -m pytest tests -v
"""

import re
from decimal import Decimal

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from core.simulator import simulate_plan
from data import dynamo
from data.dynamo import (
    AuditEventExists,
    CorruptRecord,
    DataAccessError,
    InvalidRecord,
    RecordNotFound,
    ResetBlocked,
)
from data.schema import DEMO_AGENT_ID, seed_agent, seed_warehouse, table_definitions, table_names

NO_ACTIVE_WORKFLOWS = lambda: False  # noqa: E731


# ---------------------------------------------------------------------- fixtures


@pytest.fixture
def aws_env(monkeypatch):
    """Fake credentials and Region so nothing can reach a real AWS account."""
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    for var in ("SENTINEL_WAREHOUSE_TABLE", "SENTINEL_AGENTS_TABLE", "SENTINEL_AUDIT_TABLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    dynamo.reset_connection()
    yield
    dynamo.reset_connection()


@pytest.fixture
def no_tables(aws_env):
    """Mocked AWS account where the tables have not been created."""
    with mock_aws():
        yield


@pytest.fixture
def empty_tables(no_tables):
    """Tables exist but hold no records."""
    client = boto3.client("dynamodb")
    for definition in table_definitions():
        client.create_table(**definition)
    yield client


@pytest.fixture
def db(empty_tables):
    """Tables created and seeded per the contract."""
    assert dynamo.seed_if_missing() == {"warehouse": "created", "agent": "created"}
    yield empty_tables


def raw_warehouse_item():
    return boto3.resource("dynamodb").Table(table_names()["warehouse"]).get_item(
        Key={"warehouse_id": "demo-warehouse"}, ConsistentRead=True
    )["Item"]


def put_warehouse(**changes):
    """Write a warehouse item directly, bypassing the data layer (test setup only)."""
    item = {**seed_warehouse(), **changes}
    boto3.resource("dynamodb").Table(table_names()["warehouse"]).put_item(Item=item)


def event(**overrides):
    base = {
        "plan_id": "plan-001",
        "revision": 1,
        "event_type": "SIMULATION_FAILED",
        "outcome": "REJECTED",
        "reason_code": "CAPACITY_EXCEEDED",
        "message": "Projected Zone B inventory is 13, capacity is 10",
    }
    return {**base, **overrides}


# ------------------------------------------------------- 1. warehouse retrieval


def test_get_warehouse_returns_contract_seed_state(db):
    assert dynamo.get_warehouse() == {
        "warehouse_id": "demo-warehouse",
        "version": 1,
        "zones": {
            "A": {"inventory": 20, "capacity": 30},
            "B": {"inventory": 8, "capacity": 10},
            "C": {"inventory": 5, "capacity": 20},
        },
        "restricted_zones": ["HAZMAT"],
    }


def test_get_warehouse_returns_plain_ints_not_decimals(db):
    assert isinstance(raw_warehouse_item()["version"], Decimal)  # what boto3 gives back

    warehouse = dynamo.get_warehouse()

    assert type(warehouse["version"]) is int
    for zone in warehouse["zones"].values():
        assert type(zone["inventory"]) is int
        assert type(zone["capacity"]) is int


def test_get_warehouse_hides_internal_fields(db):
    assert "run_id" in raw_warehouse_item()
    assert set(dynamo.get_warehouse()) == {"warehouse_id", "version", "zones", "restricted_zones"}


# ----------------------------------------------------------- 2. agent retrieval


def test_get_agent_returns_contract_record(db):
    assert dynamo.get_agent(DEMO_AGENT_ID) == {
        "agent_id": "inventory-agent-01",
        "status": "ACTIVE",
        "role": "INVENTORY_MANAGER",
        "max_transfer": 10,
    }
    assert type(dynamo.get_agent(DEMO_AGENT_ID)["max_transfer"]) is int


# ------------------------------------------------------- 3. agent status updates


def test_revoke_then_reactivate_agent(db):
    revoked = dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED", updated_by="admin@sentinel")

    assert revoked["status"] == "REVOKED"
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "REVOKED"
    assert set(revoked) == {"agent_id", "status", "role", "max_transfer"}

    assert dynamo.update_agent_status(DEMO_AGENT_ID, "ACTIVE")["status"] == "ACTIVE"
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"


def test_suspended_status_is_supported(db):
    assert dynamo.update_agent_status(DEMO_AGENT_ID, "SUSPENDED")["status"] == "SUSPENDED"


@pytest.mark.parametrize("bad_status", ["revoked", "DELETED", "", None, 1, True])
def test_invalid_agent_status_is_rejected_and_nothing_changes(db, bad_status):
    with pytest.raises(InvalidRecord):
        dynamo.update_agent_status(DEMO_AGENT_ID, bad_status)

    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"


def test_status_update_keeps_role_and_limit(db):
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    agent = dynamo.get_agent(DEMO_AGENT_ID)
    assert agent["role"] == "INVENTORY_MANAGER"
    assert agent["max_transfer"] == 10


# ----------------------------------------------------- 4. audit-event persistence


def test_audit_event_is_persisted_and_readable_by_plan(db):
    stored = dynamo.record_audit_event(event())

    assert dynamo.list_audit_events("plan-001") == [stored]
    assert stored["plan_id"] == "plan-001"
    assert stored["event_type"] == "SIMULATION_FAILED"
    assert stored["reason_code"] == "CAPACITY_EXCEEDED"
    assert stored["revision"] == 1


def test_generated_event_id_and_timestamp_follow_contract_format(db):
    stored = dynamo.record_audit_event(event())

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z#[0-9a-f]{8}", stored["event_id"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stored["timestamp"])


def test_recent_events_across_plans_newest_first(db):
    first = dynamo.record_audit_event(event(plan_id="plan-001", event_id="2026-11-07T20:00:00.000Z#0001"))
    second = dynamo.record_audit_event(event(plan_id="plan-002", event_id="2026-11-07T20:00:01.000Z#0002"))
    third = dynamo.record_audit_event(event(plan_id="plan-001", event_id="2026-11-07T20:00:02.000Z#0003"))

    assert dynamo.list_audit_events() == [third, second, first]
    assert dynamo.list_audit_events("plan-001") == [third, first]
    assert dynamo.list_audit_events(limit=2) == [third, second]


def test_audit_details_and_admin_round_trip(db):
    stored = dynamo.record_audit_event(
        event(
            event_type="APPROVAL_RECORDED",
            outcome="APPROVED",
            admin="admin@sentinel",
            details={"projected": {"B": 10}, "ratio": 0.5, "zones": ["A", "B"]},
        )
    )

    [read_back] = dynamo.list_audit_events("plan-001")
    assert read_back == stored
    assert read_back["admin"] == "admin@sentinel"
    assert read_back["details"] == {"projected": {"B": 10}, "ratio": 0.5, "zones": ["A", "B"]}


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"plan_id": ""}, id="empty-plan-id"),
        pytest.param({"event_type": "simulation failed"}, id="event-type-not-upper-snake"),
        pytest.param({"revision": -1}, id="negative-revision"),
        pytest.param({"revision": True}, id="bool-revision"),
        pytest.param({"details": "not an object"}, id="details-not-object"),
        pytest.param({"unexpected": 1}, id="unknown-field"),
        pytest.param({"details": {"task_token": "abc"}}, id="secret-task-token"),
        pytest.param({"details": {"nested": [{"aws_secret": "x"}]}}, id="secret-nested"),
    ],
)
def test_invalid_audit_events_are_rejected_and_not_stored(db, bad):
    with pytest.raises(InvalidRecord):
        dynamo.record_audit_event(event(**bad))

    assert dynamo.list_audit_events() == []


@pytest.mark.parametrize("missing", ["plan_id", "event_type", "outcome", "message"])
def test_audit_event_missing_required_field_is_rejected(db, missing):
    bad = event()
    del bad[missing]

    with pytest.raises(InvalidRecord):
        dynamo.record_audit_event(bad)


# ------------------------------------------------------------------ 5. demo reset


def test_reset_restores_seed_warehouse_and_agent(db):
    put_warehouse(version=3, zones={
        "A": {"inventory": 12, "capacity": 30},
        "B": {"inventory": 10, "capacity": 10},
        "C": {"inventory": 11, "capacity": 20},
    })
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    result = dynamo.reset_demo(active_workflow_check=NO_ACTIVE_WORKFLOWS, reset_by="admin@sentinel")

    assert result == seed_warehouse()
    assert dynamo.get_warehouse() == seed_warehouse()
    assert dynamo.get_agent(DEMO_AGENT_ID) == seed_agent()


def test_reset_records_audit_event_and_keeps_previous_evidence(db):
    earlier = dynamo.record_audit_event(event())

    dynamo.reset_demo(active_workflow_check=NO_ACTIVE_WORKFLOWS, reset_by="admin@sentinel")

    assert dynamo.list_audit_events("plan-001") == [earlier]
    [reset_event] = dynamo.list_audit_events("SYSTEM")
    assert reset_event["event_type"] == "DEMO_RESET"
    assert reset_event["admin"] == "admin@sentinel"


def test_each_reset_gets_a_new_run_id(db):
    first_run = raw_warehouse_item()["run_id"]
    dynamo.reset_demo(active_workflow_check=NO_ACTIVE_WORKFLOWS)
    second_run = raw_warehouse_item()["run_id"]
    dynamo.reset_demo(active_workflow_check=NO_ACTIVE_WORKFLOWS)
    third_run = raw_warehouse_item()["run_id"]

    assert len({first_run, second_run, third_run}) == 3
    [latest_reset, _] = dynamo.list_audit_events("SYSTEM")
    assert latest_reset["details"]["run_id"] == third_run


@pytest.mark.parametrize(
    "check",
    [
        pytest.param(lambda: True, id="workflow-active"),
        pytest.param(lambda: None, id="check-returns-none"),
        pytest.param(lambda: 1 / 0, id="check-raises"),
    ],
)
def test_reset_is_blocked_unless_no_workflow_is_confirmed(db, check):
    put_warehouse(version=2, zones={
        "A": {"inventory": 17, "capacity": 30},
        "B": {"inventory": 8, "capacity": 10},
        "C": {"inventory": 8, "capacity": 20},
    })
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    with pytest.raises(ResetBlocked):
        dynamo.reset_demo(active_workflow_check=check)

    assert dynamo.get_warehouse()["version"] == 2
    assert dynamo.get_warehouse()["zones"]["A"]["inventory"] == 17
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "REVOKED"
    assert dynamo.list_audit_events("SYSTEM") == []


def test_reset_requires_an_explicit_workflow_check(db):
    with pytest.raises(TypeError):
        dynamo.reset_demo()  # type: ignore[call-arg]


def test_reset_is_all_or_nothing_when_a_table_is_missing(db):
    put_warehouse(version=2)
    db.delete_table(TableName=table_names()["agents"])

    with pytest.raises(DataAccessError):
        dynamo.reset_demo(active_workflow_check=NO_ACTIVE_WORKFLOWS)

    assert dynamo.get_warehouse()["version"] == 2
    assert dynamo.list_audit_events("SYSTEM") == []


# --------------------------------------------------------------- 6. missing records


def test_missing_warehouse_raises_not_found(empty_tables):
    with pytest.raises(RecordNotFound) as info:
        dynamo.get_warehouse()
    assert info.value.code == "NOT_FOUND"


def test_unknown_warehouse_id_raises_not_found(db):
    with pytest.raises(RecordNotFound):
        dynamo.get_warehouse("other-warehouse")


def test_missing_agent_raises_not_found(db):
    with pytest.raises(RecordNotFound):
        dynamo.get_agent("inventory-agent-99")


def test_updating_unknown_agent_raises_and_does_not_create_it(db):
    with pytest.raises(RecordNotFound):
        dynamo.update_agent_status("inventory-agent-99", "ACTIVE")

    with pytest.raises(RecordNotFound):
        dynamo.get_agent("inventory-agent-99")


def test_warehouse_record_missing_fields_is_reported_as_corrupt(db):
    boto3.resource("dynamodb").Table(table_names()["warehouse"]).put_item(
        Item={"warehouse_id": "demo-warehouse", "zones": {}}
    )

    with pytest.raises(CorruptRecord):
        dynamo.get_warehouse()


def test_audit_for_unknown_plan_is_empty(db):
    assert dynamo.list_audit_events("plan-404") == []


@pytest.mark.parametrize("bad_id", ["", None, 5])
def test_blank_ids_are_rejected(db, bad_id):
    with pytest.raises(InvalidRecord):
        dynamo.get_agent(bad_id)
    with pytest.raises(InvalidRecord):
        dynamo.get_warehouse(bad_id)


# ---------------------------------------------------------------- 7. AWS API errors


def test_missing_tables_raise_data_access_error(no_tables):
    for call in (
        dynamo.get_warehouse,
        lambda: dynamo.get_agent(DEMO_AGENT_ID),
        lambda: dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED"),
        lambda: dynamo.record_audit_event(event()),
        dynamo.list_audit_events,
        lambda: dynamo.reset_demo(active_workflow_check=NO_ACTIVE_WORKFLOWS),
    ):
        with pytest.raises(DataAccessError) as info:
            call()
        assert info.value.aws_code == "ResourceNotFoundException"
        assert info.value.retryable is False
        assert info.value.code == "INTERNAL_ERROR"


def test_throttling_is_reported_as_retryable(db, monkeypatch):
    def throttled(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
            "GetItem",
        )

    table = dynamo._table("agents")
    monkeypatch.setattr(dynamo, "_table", lambda kind: table)
    monkeypatch.setattr(table, "get_item", throttled)

    with pytest.raises(DataAccessError) as info:
        dynamo.get_agent(DEMO_AGENT_ID)
    assert info.value.aws_code == "ProvisionedThroughputExceededException"
    assert info.value.retryable is True


def test_missing_region_is_reported_not_crashed(monkeypatch, aws_env):
    monkeypatch.delenv("AWS_DEFAULT_REGION")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    dynamo.reset_connection()

    with pytest.raises(DataAccessError) as info:
        dynamo.get_warehouse()
    assert info.value.aws_code == "NoRegionError"


def test_raw_boto_errors_never_escape(no_tables):
    with pytest.raises(dynamo.DataError):
        dynamo.get_warehouse()


# -------------------------------------------------------- 8. simulator compatibility


def test_stored_warehouse_feeds_simulator_directly(db):
    plan = {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 3}]}

    result = simulate_plan(plan, dynamo.get_warehouse())

    assert result["passed"] is True
    assert result["warehouse_version"] == 1
    assert result["projected_state"]["A"]["inventory"] == 17
    assert result["projected_state"]["C"]["inventory"] == 8


def test_simulator_rejects_capacity_violation_on_stored_state(db):
    plan = {"actions": [{"type": "move_packages", "from": "A", "to": "B", "count": 5}]}

    result = simulate_plan(plan, dynamo.get_warehouse())

    assert result["passed"] is False
    assert result["violations"][0]["code"] == "CAPACITY_EXCEEDED"
    assert result["violations"][0]["projected"] == 13


def test_simulating_does_not_change_the_stored_warehouse(db):
    plan = {"actions": [{"type": "move_packages", "from": "A", "to": "B", "count": 2}]}
    warehouse = dynamo.get_warehouse()

    simulate_plan(plan, warehouse)

    assert dynamo.get_warehouse() == seed_warehouse()


def test_raw_decimal_item_would_fail_simulator_which_is_why_we_convert(db):
    """Guards the conversion: the simulator rejects Decimal counts by design."""
    raw = raw_warehouse_item()
    plan = {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 3}]}

    assert simulate_plan(plan, raw)["passed"] is False
    assert simulate_plan(plan, dynamo.get_warehouse())["passed"] is True


# ---------------------------------------------- 9. existing warehouse is preserved


def test_seeding_never_overwrites_existing_warehouse_or_agent(empty_tables):
    put_warehouse(version=5, zones={
        "A": {"inventory": 10, "capacity": 30},
        "B": {"inventory": 10, "capacity": 10},
        "C": {"inventory": 13, "capacity": 20},
    })
    boto3.resource("dynamodb").Table(table_names()["agents"]).put_item(
        Item={**seed_agent(), "status": "REVOKED"}
    )

    assert dynamo.seed_if_missing() == {"warehouse": "kept", "agent": "kept"}
    assert dynamo.get_warehouse()["version"] == 5
    assert dynamo.get_warehouse()["zones"]["C"]["inventory"] == 13
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "REVOKED"


def test_reads_status_updates_and_audit_do_not_change_warehouse_version(db):
    put_warehouse(version=4)

    dynamo.get_warehouse()
    dynamo.get_agent(DEMO_AGENT_ID)
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")
    dynamo.record_audit_event(event())
    dynamo.list_audit_events()

    assert dynamo.get_warehouse()["version"] == 4


# ------------------------------------------------ 10. audit records never overwritten


def test_same_event_id_cannot_overwrite_existing_audit_event(db):
    original = dynamo.record_audit_event(event(event_id="2026-11-07T20:00:00.000Z#0001"))

    with pytest.raises(AuditEventExists) as info:
        dynamo.record_audit_event(
            event(event_id="2026-11-07T20:00:00.000Z#0001", outcome="ALLOWED", message="tampered")
        )

    assert info.value.code == "AUDIT_EVENT_EXISTS"
    assert dynamo.list_audit_events("plan-001") == [original]


def test_same_event_id_under_a_different_plan_is_a_separate_record(db):
    dynamo.record_audit_event(event(plan_id="plan-001", event_id="E1"))
    dynamo.record_audit_event(event(plan_id="plan-002", event_id="E1"))

    assert len(dynamo.list_audit_events()) == 2


def test_generated_event_ids_are_unique(db):
    ids = {dynamo.record_audit_event(event())["event_id"] for _ in range(20)}

    assert len(ids) == 20
    assert len(dynamo.list_audit_events("plan-001")) == 20
