"""Table names, table definitions, and seed records for SentinelOS DynamoDB.

Follows Team Integration Contract v1.0:
  * section 2.1 WarehouseState and 2.2 AgentRecord (seed values)
  * section 5.2 AuditEvent and section 6 (table keys)

One addition the contract asks for in section 5.2: a global secondary index on
sentinel_audit so recent events across all plans can be read with a Query
instead of a full table scan.
"""

import copy
import os
from typing import Any

DEFAULT_WAREHOUSE_ID = "demo-warehouse"
DEMO_AGENT_ID = "inventory-agent-01"
SYSTEM_PLAN_ID = "SYSTEM"  # plan_id for events not tied to a plan (revoke, reset)

AGENT_STATUSES = frozenset({"ACTIVE", "REVOKED", "SUSPENDED"})

# Global secondary indexes for "recent events across plans" (contract 5.2).
# recent_events_by_time sorts by "<timestamp>#<event_id>" so events from every
# writer (workflow, executor, admin actions) interleave in time order.
# recent_events (sorted by event_id) is kept only because DynamoDB cannot swap
# an index in place on the live table; nothing reads it.
LEGACY_AUDIT_FEED_INDEX = "recent_events"
AUDIT_FEED_INDEX = "recent_events_by_time"
AUDIT_FEED_KEY = "feed"
AUDIT_FEED_VALUE = "ALL"
AUDIT_FEED_SORT_KEY = "feed_at"

_SEED_WAREHOUSE: dict[str, Any] = {
    "warehouse_id": DEFAULT_WAREHOUSE_ID,
    "version": 1,
    "zones": {
        "A": {"inventory": 20, "capacity": 30},
        "B": {"inventory": 8, "capacity": 10},
        "C": {"inventory": 5, "capacity": 20},
    },
    "restricted_zones": ["HAZMAT"],
}

_SEED_AGENT: dict[str, Any] = {
    "agent_id": DEMO_AGENT_ID,
    "status": "ACTIVE",
    "role": "INVENTORY_MANAGER",
    "max_transfer": 10,
}


def seed_warehouse() -> dict[str, Any]:
    """Return a fresh copy of the contract section 2.1 seed warehouse."""
    return copy.deepcopy(_SEED_WAREHOUSE)


def seed_agent() -> dict[str, Any]:
    """Return a fresh copy of the contract section 2.2 seed agent."""
    return copy.deepcopy(_SEED_AGENT)


def table_names() -> dict[str, str]:
    """Table names, overridable with environment variables (read at call time)."""
    return {
        "warehouse": os.environ.get("SENTINEL_WAREHOUSE_TABLE", "sentinel_warehouse"),
        "agents": os.environ.get("SENTINEL_AGENTS_TABLE", "sentinel_agents"),
        "audit": os.environ.get("SENTINEL_AUDIT_TABLE", "sentinel_audit"),
        "executions": os.environ.get("SENTINEL_EXECUTIONS_TABLE", "sentinel_executions"),
    }


def table_definitions() -> list[dict[str, Any]]:
    """``create_table`` arguments for all three tables (on-demand billing)."""
    names = table_names()
    return [
        {
            "TableName": names["warehouse"],
            "KeySchema": [{"AttributeName": "warehouse_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "warehouse_id", "AttributeType": "S"}],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": names["agents"],
            "KeySchema": [{"AttributeName": "agent_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "agent_id", "AttributeType": "S"}],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": names["audit"],
            "KeySchema": [
                {"AttributeName": "plan_id", "KeyType": "HASH"},
                {"AttributeName": "event_id", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "plan_id", "AttributeType": "S"},
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": AUDIT_FEED_KEY, "AttributeType": "S"},
                {"AttributeName": AUDIT_FEED_SORT_KEY, "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": LEGACY_AUDIT_FEED_INDEX,
                    "KeySchema": [
                        {"AttributeName": AUDIT_FEED_KEY, "KeyType": "HASH"},
                        {"AttributeName": "event_id", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": AUDIT_FEED_INDEX,
                    "KeySchema": [
                        {"AttributeName": AUDIT_FEED_KEY, "KeyType": "HASH"},
                        {"AttributeName": AUDIT_FEED_SORT_KEY, "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            # One item per committed (plan_id, revision): the executor's replay guard.
            "TableName": names["executions"],
            "KeySchema": [{"AttributeName": "execution_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "execution_id", "AttributeType": "S"}],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]
