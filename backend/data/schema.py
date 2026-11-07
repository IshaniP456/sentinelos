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

# Global secondary index for "recent events across plans" (contract 5.2).
AUDIT_FEED_INDEX = "recent_events"
AUDIT_FEED_KEY = "feed"
AUDIT_FEED_VALUE = "ALL"

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
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": AUDIT_FEED_INDEX,
                    "KeySchema": [
                        {"AttributeName": AUDIT_FEED_KEY, "KeyType": "HASH"},
                        {"AttributeName": "event_id", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]
