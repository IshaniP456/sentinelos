"""DynamoDB data access for SentinelOS: warehouse, agents, and audit log.

Every function returns plain Python values shaped exactly like the Team
Integration Contract v1.0 (sections 2.1, 2.2, 5.2). DynamoDB numbers are
converted back to ``int``, so ``get_warehouse()`` can be passed straight to
``core.simulator.simulate_plan`` (which rejects ``Decimal`` and ``float``).

All errors are raised as subclasses of ``DataError`` with a ``code`` and a
``retryable`` flag. Raw boto3 exceptions never leak to callers.

This module does not execute plans or change inventory counts; that is the
executor's job (Phase 3). The only inventory write here is ``reset_demo``.
"""

import json
import re
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

from data.schema import (
    AGENT_STATUSES,
    AUDIT_FEED_INDEX,
    AUDIT_FEED_KEY,
    AUDIT_FEED_SORT_KEY,
    AUDIT_FEED_VALUE,
    DEFAULT_WAREHOUSE_ID,
    SYSTEM_PLAN_ID,
    seed_agent,
    seed_warehouse,
    table_names,
)

WAREHOUSE_FIELDS = ("warehouse_id", "version", "zones", "restricted_zones")
AGENT_FIELDS = ("agent_id", "status", "role", "max_transfer")
AUDIT_REQUIRED = ("plan_id", "event_type", "outcome", "message")
AUDIT_OPTIONAL = ("event_id", "timestamp", "revision", "reason_code", "details", "admin")
AUDIT_FIELDS = AUDIT_REQUIRED + AUDIT_OPTIONAL
SECRET_KEY_PATTERN = re.compile(r"token|secret|password|credential|api[_-]?key", re.IGNORECASE)
EVENT_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
MAX_AUDIT_LIMIT = 200

RETRYABLE_AWS_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "RequestLimitExceeded",
        "InternalServerError",
        "ServiceUnavailable",
        "TransactionConflictException",
    }
)


# ----------------------------------------------------------------------- errors


class DataError(Exception):
    """Base class. ``code`` is machine-readable; ``retryable`` tells callers if a retry may help."""

    code = "INTERNAL_ERROR"
    retryable = False


class DataAccessError(DataError):
    """DynamoDB or AWS SDK call failed (missing table, throttling, no credentials, ...)."""

    def __init__(self, message: str, *, aws_code: str, retryable: bool) -> None:
        super().__init__(message)
        self.aws_code = aws_code
        self.retryable = retryable


class RecordNotFound(DataError):
    """The requested warehouse or agent does not exist."""

    code = "NOT_FOUND"


class CorruptRecord(DataError):
    """A stored record is missing required contract fields."""

    code = "INTERNAL_ERROR"


class InvalidRecord(DataError, ValueError):
    """The caller supplied invalid input (bad status, malformed audit event, ...)."""

    code = "INVALID_REQUEST"


class AuditEventExists(DataError):
    """An audit event with this (plan_id, event_id) already exists. Audit is append-only."""

    code = "AUDIT_EVENT_EXISTS"


class ResetBlocked(DataError):
    """Reset refused because a workflow may still be active (PRD FR13)."""

    code = "RESET_BLOCKED"
    retryable = True


# ------------------------------------------------------------------- connection

_resource: Any = None


def _dynamodb() -> Any:
    """Lazily create one boto3 DynamoDB resource (standard credential/region chain)."""
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource


def reset_connection() -> None:
    """Drop the cached boto3 resource. Tests call this when switching AWS mocks."""
    global _resource
    _resource = None


def _table(kind: str) -> Any:
    return _dynamodb().Table(table_names()[kind])


@contextmanager
def _aws(operation: str) -> Iterator[None]:
    """Translate boto3/botocore exceptions into ``DataAccessError``."""
    try:
        yield
    except ClientError as exc:
        aws_code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise DataAccessError(
            f"{operation} failed: {aws_code}",
            aws_code=aws_code,
            retryable=aws_code in RETRYABLE_AWS_CODES,
        ) from exc
    except BotoCoreError as exc:
        raise DataAccessError(
            f"{operation} failed: {type(exc).__name__}",
            aws_code=type(exc).__name__,
            retryable=False,
        ) from exc


def _aws_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


# ------------------------------------------------------------- type conversion


def _from_dynamo(value: Any) -> Any:
    """Convert DynamoDB ``Decimal`` values back to ``int`` (or ``float`` if fractional)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def _to_dynamo(value: Any) -> Any:
    """Make a JSON-compatible value storable (floats become ``Decimal``)."""
    def already_decimal(obj: Any) -> Any:
        if isinstance(obj, Decimal):  # safe to apply twice
            return int(obj) if obj == obj.to_integral_value() else float(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    try:
        return json.loads(json.dumps(value, default=already_decimal), parse_float=Decimal)
    except (TypeError, ValueError) as exc:
        raise InvalidRecord(f"Value is not JSON-serializable: {exc}") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_seconds(moment: datetime) -> str:
    """Contract timestamp format, e.g. 2026-11-07T20:00:00Z."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_millis(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRecord(f"{name} must be a non-empty string.")
    return value


# -------------------------------------------------------------------- warehouse


def get_warehouse(warehouse_id: str = DEFAULT_WAREHOUSE_ID) -> dict[str, Any]:
    """Return the current WarehouseState (contract 2.1) using a strongly consistent read.

    The result can be passed directly to ``simulate_plan(plan, warehouse_state)``.

    Raises:
        RecordNotFound: no warehouse with this id.
        CorruptRecord: the stored item lacks version or zones.
        DataAccessError: DynamoDB call failed.
    """
    state, _run_id = get_warehouse_record(warehouse_id)
    return state


def get_warehouse_record(warehouse_id: str = DEFAULT_WAREHOUSE_ID) -> tuple[dict[str, Any], str | None]:
    """Return ``(WarehouseState, run_id)`` from one strongly consistent read.

    ``run_id`` is internal (not part of WarehouseState). It changes on every
    reset so the executor can reject plans and approvals from an earlier run.
    """
    _require_text("warehouse_id", warehouse_id)
    with _aws("get_warehouse"):
        response = _table("warehouse").get_item(
            Key={"warehouse_id": warehouse_id}, ConsistentRead=True
        )
    item = response.get("Item")
    if item is None:
        raise RecordNotFound(f"Warehouse {warehouse_id} does not exist.")
    item = _from_dynamo(item)
    if "version" not in item or "zones" not in item:
        raise CorruptRecord(f"Warehouse {warehouse_id} is missing version or zones.")
    state = {
        "warehouse_id": item["warehouse_id"],
        "version": item["version"],
        "zones": item["zones"],
        "restricted_zones": item.get("restricted_zones", []),
    }
    return state, item.get("run_id")


def get_run_id(warehouse_id: str = DEFAULT_WAREHOUSE_ID) -> str:
    """Return the current demo-run identity. Raises CorruptRecord if it is missing."""
    _state, run_id = get_warehouse_record(warehouse_id)
    if not isinstance(run_id, str) or not run_id:
        raise CorruptRecord(f"Warehouse {warehouse_id} has no run_id.")
    return run_id


# ----------------------------------------------------------------------- agents


def get_agent(agent_id: str) -> dict[str, Any]:
    """Return the AgentRecord (contract 2.2) using a strongly consistent read.

    Callers doing authorization must treat any exception as DENY (fail closed).

    Raises:
        RecordNotFound: no agent with this id.
        DataAccessError: DynamoDB call failed.
    """
    _require_text("agent_id", agent_id)
    with _aws("get_agent"):
        response = _table("agents").get_item(Key={"agent_id": agent_id}, ConsistentRead=True)
    item = response.get("Item")
    if item is None:
        raise RecordNotFound(f"Agent {agent_id} does not exist.")
    return _agent_record(_from_dynamo(item))


def update_agent_status(
    agent_id: str, status: str, *, updated_by: str | None = None
) -> dict[str, Any]:
    """Set an existing agent's status to ACTIVE, REVOKED, or SUSPENDED.

    Never creates an agent: updating an unknown agent raises ``RecordNotFound``.
    Does not touch the warehouse or its version.

    Returns:
        The updated AgentRecord.
    """
    _require_text("agent_id", agent_id)
    if status not in AGENT_STATUSES:
        raise InvalidRecord(f"status must be one of {sorted(AGENT_STATUSES)}, got {status!r}.")

    expression = "SET #status = :status, updated_at = :now"
    values: dict[str, Any] = {":status": status, ":now": _iso_seconds(_now())}
    if updated_by is not None:
        expression += ", updated_by = :by"
        values[":by"] = _require_text("updated_by", updated_by)

    with _aws("update_agent_status"):
        try:
            response = _table("agents").update_item(
                Key={"agent_id": agent_id},
                UpdateExpression=expression,
                ConditionExpression="attribute_exists(agent_id)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if _aws_code(exc) == "ConditionalCheckFailedException":
                raise RecordNotFound(f"Agent {agent_id} does not exist.") from exc
            raise
    return _agent_record(_from_dynamo(response["Attributes"]))


def _agent_record(item: Mapping[str, Any]) -> dict[str, Any]:
    return {field: item.get(field) for field in AGENT_FIELDS}


# ------------------------------------------------------------------------ audit


def record_audit_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Append one AuditEvent (contract 5.2). Existing events are never overwritten.

    Required: plan_id, event_type (UPPER_SNAKE_CASE), outcome, message.
    Optional: event_id, timestamp, revision (int >= 0, default 0), reason_code,
    details (object), admin (deciding administrator for approval events).
    Use plan_id ``"SYSTEM"`` for events not tied to a plan.

    If event_id is omitted, one is generated as ``<UTC millis>Z#<random>`` so
    events sort by time. Supplying a stable event_id makes retries safe: a
    repeat raises ``AuditEventExists`` instead of writing a duplicate.

    Raises:
        InvalidRecord: missing/unknown fields, bad types, or secret-looking keys.
        AuditEventExists: (plan_id, event_id) already stored.
        DataAccessError: DynamoDB call failed.

    Returns:
        The event exactly as stored.
    """
    stored = _build_audit_event(event)
    item = audit_item(stored)
    with _aws("record_audit_event"):
        try:
            _table("audit").put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(plan_id) AND attribute_not_exists(event_id)",
            )
        except ClientError as exc:
            if _aws_code(exc) == "ConditionalCheckFailedException":
                raise AuditEventExists(
                    f"Audit event {stored['event_id']} for plan {stored['plan_id']} already exists."
                ) from exc
            raise
    return stored


def list_audit_events(plan_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return audit events newest first, for one plan or across all plans.

    Uses a Query on the table (one plan) or on the ``recent_events`` index
    (all plans). Never scans the table.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_AUDIT_LIMIT:
        raise InvalidRecord(f"limit must be an integer from 1 to {MAX_AUDIT_LIMIT}.")
    with _aws("list_audit_events"):
        if plan_id is None:
            response = _table("audit").query(
                IndexName=AUDIT_FEED_INDEX,
                KeyConditionExpression=Key(AUDIT_FEED_KEY).eq(AUDIT_FEED_VALUE),
                ScanIndexForward=False,
                Limit=limit,
            )
        else:
            response = _table("audit").query(
                KeyConditionExpression=Key("plan_id").eq(_require_text("plan_id", plan_id)),
                ScanIndexForward=False,
                Limit=limit,
                ConsistentRead=True,
            )
    return [_audit_record(_from_dynamo(item)) for item in response.get("Items", [])]


def audit_item(stored: Mapping[str, Any]) -> dict[str, Any]:
    """DynamoDB item for a validated audit event, with the time-ordered feed keys."""
    return _to_dynamo({
        **stored,
        AUDIT_FEED_KEY: AUDIT_FEED_VALUE,
        AUDIT_FEED_SORT_KEY: f"{stored['timestamp']}#{stored['event_id']}",
    })


def _build_audit_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an audit event and fill in event_id, timestamp, and revision."""
    if not isinstance(event, Mapping):
        raise InvalidRecord("Audit event must be an object.")
    unknown = sorted(set(event) - set(AUDIT_FIELDS), key=str)
    if unknown:
        raise InvalidRecord(f"Audit event has unknown fields {unknown}; put extras in 'details'.")
    for field in AUDIT_REQUIRED:
        _require_text(field, event.get(field))
    if not EVENT_TYPE_PATTERN.match(event["event_type"]):
        raise InvalidRecord("event_type must be UPPER_SNAKE_CASE.")

    revision = event.get("revision", 0)
    if type(revision) is not int or revision < 0:
        raise InvalidRecord("revision must be an integer >= 0.")
    reason_code = event.get("reason_code")
    if reason_code is not None:
        _require_text("reason_code", reason_code)
    admin = event.get("admin")
    if admin is not None:
        _require_text("admin", admin)
    details = event.get("details")
    if details is not None and not isinstance(details, Mapping):
        raise InvalidRecord("details must be an object.")
    _reject_secrets(details or {}, "details")

    moment = _now()
    stored: dict[str, Any] = {
        "plan_id": event["plan_id"],
        "event_id": event.get("event_id") or f"{_iso_millis(moment)}#{uuid.uuid4().hex[:8]}",
        "timestamp": event.get("timestamp") or _iso_seconds(moment),
        "revision": revision,
        "event_type": event["event_type"],
        "outcome": event["outcome"],
        "reason_code": reason_code,
        "message": event["message"],
    }
    _require_text("event_id", stored["event_id"])
    _require_text("timestamp", stored["timestamp"])
    if details is not None:
        stored["details"] = _from_dynamo(_to_dynamo(details))
    if admin is not None:
        stored["admin"] = admin
    return stored


def _reject_secrets(value: Any, path: str) -> None:
    """Refuse audit details whose keys look like credentials or tokens (PRD FR12)."""
    if isinstance(value, Mapping):
        for key, inner in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                raise InvalidRecord(f"Audit events must not contain secrets ({path}.{key}).")
            _reject_secrets(inner, f"{path}.{key}")
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            _reject_secrets(inner, f"{path}[{index}]")


def _audit_record(item: Mapping[str, Any]) -> dict[str, Any]:
    return {k: item[k] for k in AUDIT_FIELDS if k in item}


# ------------------------------------------------------------------- seed/reset


def seed_if_missing() -> dict[str, str]:
    """Create the seed warehouse and agent only if they do not already exist.

    Never overwrites: an existing warehouse keeps its inventory and version,
    and an existing agent keeps its status.

    Returns:
        ``{"warehouse": "created" | "kept", "agent": "created" | "kept"}``.
    """
    outcome: dict[str, str] = {}
    targets = (
        ("warehouse", {**seed_warehouse(), "run_id": uuid.uuid4().hex}, "warehouse_id"),
        ("agent", seed_agent(), "agent_id"),
    )
    for kind, item, key in targets:
        table = "warehouse" if kind == "warehouse" else "agents"
        with _aws(f"seed {kind}"):
            try:
                _table(table).put_item(
                    Item=_to_dynamo(item), ConditionExpression=f"attribute_not_exists({key})"
                )
                outcome[kind] = "created"
            except ClientError as exc:
                if _aws_code(exc) != "ConditionalCheckFailedException":
                    raise
                outcome[kind] = "kept"
    return outcome


def reset_demo(
    *, active_workflow_check: Callable[[], bool], reset_by: str | None = None
) -> dict[str, Any]:
    """Restore the seed warehouse (A=20, B=8, C=5, version 1) and set the agent to ACTIVE.

    PRD FR13 rules:
      * Refuses (``ResetBlocked``) if ``active_workflow_check()`` returns True,
        or if it raises (fail closed). The caller must supply this check, since
        workflow state is owned by the orchestration layer.
      * Writes the warehouse, the agent, and a DEMO_RESET audit event in one
        DynamoDB transaction: all three happen or none do.
      * Keeps all previous audit events.
      * Stores a new random ``run_id`` on the warehouse item so later phases can
        tell approvals from before a reset apart from the new run, even though
        the version is back to 1. ``run_id`` is not part of WarehouseState and is
        not returned by ``get_warehouse``.

    Returns:
        The new WarehouseState (contract 2.1).
    """
    try:
        active = active_workflow_check()
    except Exception as exc:
        raise ResetBlocked("Could not confirm that no workflow is active; reset refused.") from exc
    if active is not False:
        raise ResetBlocked("A workflow is active or awaiting approval; reset refused.")

    moment = _now()
    run_id = uuid.uuid4().hex
    names = table_names()
    warehouse = seed_warehouse()
    agent = {**seed_agent(), "updated_at": _iso_seconds(moment)}
    if reset_by is not None:
        agent["updated_by"] = _require_text("reset_by", reset_by)
    audit = _build_audit_event(
        {
            "plan_id": SYSTEM_PLAN_ID,
            "event_type": "DEMO_RESET",
            "outcome": "COMPLETED",
            "message": "Demo reset: warehouse restored to seed state and agent set to ACTIVE.",
            "details": {"run_id": run_id},
            **({"admin": reset_by} if reset_by is not None else {}),
        }
    )

    # The resource's client converts plain Python values to DynamoDB types itself,
    # so items are passed as plain dicts (serializing here would double-encode them).
    def put(table: str, item: Mapping[str, Any], condition: str | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {"TableName": table, "Item": _to_dynamo(item)}
        if condition:
            request["ConditionExpression"] = condition
        return {"Put": request}

    with _aws("reset_demo"):
        _dynamodb().meta.client.transact_write_items(
            TransactItems=[
                put(names["warehouse"], {**warehouse, "run_id": run_id, "reset_at": _iso_seconds(moment)}),
                put(names["agents"], agent),
                put(
                    names["audit"],
                    audit_item(audit),
                    "attribute_not_exists(plan_id) AND attribute_not_exists(event_id)",
                ),
            ]
        )
    return {field: warehouse[field] for field in WAREHOUSE_FIELDS}
