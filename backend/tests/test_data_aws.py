"""REAL AWS integration tests for data.dynamo. Skipped unless explicitly enabled.

These talk to the actual DynamoDB tables in whatever account/Region your AWS
credentials point at. Run them only after the tables exist and you have
approved touching them:

    SENTINEL_AWS_TESTS=1 AWS_REGION=<team region> \
      uv run --no-project --python 3.12 --with pytest --with boto3 \
      python -m pytest tests/test_data_aws.py -v

Non-destructive by design: reads the warehouse and agent, and appends audit
events under plan_id "INTEGRATION-TEST". It never revokes the agent, resets
the demo, or changes inventory.
"""

import os
import uuid

import pytest

from core.simulator import simulate_plan
from data import dynamo
from data.schema import DEMO_AGENT_ID

pytestmark = pytest.mark.skipif(
    os.environ.get("SENTINEL_AWS_TESTS") != "1",
    reason="real AWS tests disabled; set SENTINEL_AWS_TESTS=1 to run against real DynamoDB",
)


@pytest.fixture(autouse=True)
def fresh_connection():
    dynamo.reset_connection()
    yield
    dynamo.reset_connection()


def test_real_warehouse_matches_contract_shape_and_feeds_simulator():
    warehouse = dynamo.get_warehouse()

    assert set(warehouse) == {"warehouse_id", "version", "zones", "restricted_zones"}
    assert type(warehouse["version"]) is int
    plan = {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 1}]}
    assert "passed" in simulate_plan(plan, warehouse)
    assert dynamo.get_warehouse() == warehouse  # simulation changed nothing


def test_real_agent_is_readable():
    agent = dynamo.get_agent(DEMO_AGENT_ID)

    assert agent["agent_id"] == DEMO_AGENT_ID
    assert agent["status"] in {"ACTIVE", "REVOKED", "SUSPENDED"}


def test_real_audit_append_read_and_no_overwrite():
    event_id = f"integration-{uuid.uuid4().hex}"
    stored = dynamo.record_audit_event(
        {
            "plan_id": "INTEGRATION-TEST",
            "event_id": event_id,
            "event_type": "INTEGRATION_TEST",
            "outcome": "COMPLETED",
            "message": "Real DynamoDB write check",
        }
    )

    assert stored in dynamo.list_audit_events("INTEGRATION-TEST", limit=200)
    with pytest.raises(dynamo.AuditEventExists):
        dynamo.record_audit_event({**stored, "message": "overwrite attempt"})
