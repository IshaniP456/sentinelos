"""AWS Lambda entry points for Mariam's data stack (invoked by Ishani's API).

Five handlers, matching Ishani's ``AwsBackendOps`` exactly:

    warehouse_handler  {}                          -> WarehouseState
    agent_handler      {}                          -> AgentRecord (server-chosen agent)
    audit_handler      {"plan_id": str | None}     -> {"events": [AuditEvent, ...]}
    revoke_handler     {"admin_assertion": {...}}  -> AgentRecord (status REVOKED)
    reset_handler      {"admin_assertion": {...}}  -> WarehouseState (seed)

Handlers never raise. Every failure returns the contract's standard error
object ``{"error": {"code", "message", "retryable"}}`` using codes Ishani's API
maps to HTTP statuses (FORBIDDEN, NOT_FOUND, INVALID_REQUEST, VERSION_CONFLICT,
INTERNAL_ERROR). Internal details go to CloudWatch logs, never to the caller.

Security:
  * The acting agent comes from the SENTINEL_AGENT_ID environment variable; any
    agent id in the event is ignored (contract section 1).
  * Revoke and reset require a signed admin assertion (security.admin_assertion).
    A plain "admin" string is ignored. Each assertion's nonce is recorded in the
    audit log with a conditional write, so it cannot be replayed.
  * Reset asks Step Functions whether any plan execution is RUNNING (which
    includes plans waiting for approval). If that cannot be confirmed, reset is
    refused (fail closed).
"""

import logging
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import boto3

from data import dynamo
from data.dynamo import AuditEventExists, DataError, InvalidRecord, RecordNotFound, ResetBlocked
from data.schema import DEFAULT_WAREHOUSE_ID, DEMO_AGENT_ID, SYSTEM_PLAN_ID
from security.admin_assertion import AssertionInvalid, verify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GENERIC_FAILURE = "The warehouse service could not complete this request."
UNVERIFIED_ADMIN = "Administrator authorization could not be verified."


class Forbidden(Exception):
    """Caller is not a verified administrator for this action."""


_clients: dict[str, Any] = {}
_signing_key: bytes | None = None


def reset_clients() -> None:
    """Drop cached AWS clients and the cached signing key (used by tests)."""
    global _signing_key
    _clients.clear()
    _signing_key = None
    dynamo.reset_connection()


def _client(service: str) -> Any:
    if service not in _clients:
        _clients[service] = boto3.client(service)
    return _clients[service]


def _agent_id() -> str:
    return os.environ.get("SENTINEL_AGENT_ID", DEMO_AGENT_ID)


def _warehouse_id() -> str:
    return os.environ.get("SENTINEL_WAREHOUSE_ID", DEFAULT_WAREHOUSE_ID)


# ---------------------------------------------------------------------- handlers


def warehouse_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Return the current WarehouseState. Takes no arguments."""
    return _run("warehouse", lambda: dynamo.get_warehouse(_warehouse_id()))


def agent_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Return the AgentRecord for the server-configured agent. Takes no arguments."""
    return _run("agent", lambda: dynamo.get_agent(_agent_id()))


def audit_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Return ``{"events": [...]}`` newest first, for one plan or across all plans."""

    def work() -> dict[str, Any]:
        plan_id = _payload(event).get("plan_id")
        if plan_id == "":
            plan_id = None
        if plan_id is not None and not isinstance(plan_id, str):
            raise InvalidRecord("plan_id must be a string.")
        return {"events": dynamo.list_audit_events(plan_id)}

    return _run("audit", work)


def revoke_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Revoke the configured agent. Requires a signed REVOKE_AGENT admin assertion."""

    def work() -> dict[str, Any]:
        admin = _verified_admin(event, "REVOKE_AGENT")
        agent = dynamo.update_agent_status(_agent_id(), "REVOKED", updated_by=admin)
        dynamo.record_audit_event(
            {
                "plan_id": SYSTEM_PLAN_ID,
                "event_type": "AGENT_REVOKED",
                "outcome": "REVOKED",
                "reason_code": "ADMIN_REVOCATION",
                "message": f"Administrator revoked {agent['agent_id']}.",
                "admin": admin,
            }
        )
        return agent

    return _run("revoke", work)


def reset_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Restore the demo seed state. Requires a signed RESET_DEMO admin assertion
    and confirmation from Step Functions that no plan is running."""

    def work() -> dict[str, Any]:
        admin = _verified_admin(event, "RESET_DEMO")
        return dynamo.reset_demo(active_workflow_check=_any_running_workflow, reset_by=admin)

    return _run("reset", work)


# ---------------------------------------------------------------------- security


def _verified_admin(event: Any, action: str) -> str:
    """Verify the signed assertion and burn its nonce. Returns the admin identity."""
    try:
        claims = verify(
            _payload(event).get("admin_assertion"), key=_load_signing_key(), expected_action=action
        )
    except AssertionInvalid as exc:
        logger.warning("Rejected %s: %s", action, exc)
        raise Forbidden(UNVERIFIED_ADMIN) from exc

    issued = datetime.fromtimestamp(claims["issued_at"], tz=timezone.utc)
    try:
        dynamo.record_audit_event(
            {
                "plan_id": SYSTEM_PLAN_ID,
                "event_id": issued.strftime("%Y-%m-%dT%H:%M:%S.000Z") + f"#adm-{claims['nonce']}",
                "timestamp": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event_type": "ADMIN_ACTION_AUTHORIZED",
                "outcome": "ALLOWED",
                "message": f"{action} authorized for administrator {claims['admin']}.",
                "admin": claims["admin"],
            }
        )
    except AuditEventExists as exc:
        logger.warning("Rejected %s: assertion nonce already used", action)
        raise Forbidden("This administrator authorization was already used.") from exc
    return claims["admin"]


def _load_signing_key() -> bytes:
    """Fetch the HMAC key from Secrets Manager once per container. Missing config fails closed."""
    global _signing_key
    if _signing_key is None:
        secret_arn = os.environ.get("ADMIN_SECRET_ARN")
        if not secret_arn:
            raise AssertionInvalid("ADMIN_SECRET_ARN is not configured.")
        try:
            value = _client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
        except Exception as exc:
            raise AssertionInvalid(f"Could not read signing key: {type(exc).__name__}") from exc
        _signing_key = value.encode()
    return _signing_key


def _any_running_workflow() -> bool:
    """True if Tishneet's state machine has a RUNNING execution. Raises if unknown."""
    arn = os.environ.get("STATE_MACHINE_ARN")
    if not arn:
        raise RuntimeError("STATE_MACHINE_ARN is not configured; cannot confirm no plan is active.")
    response = _client("stepfunctions").list_executions(
        stateMachineArn=arn, statusFilter="RUNNING", maxResults=1
    )
    return bool(response.get("executions"))


# ---------------------------------------------------------------------- plumbing


def _payload(event: Any) -> Mapping[str, Any]:
    return event if isinstance(event, Mapping) else {}


def _error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _run(name: str, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a handler body and convert every failure into a standard error object."""
    try:
        return work()
    except Forbidden as exc:
        return _error("FORBIDDEN", str(exc))
    except RecordNotFound as exc:
        return _error("NOT_FOUND", str(exc))
    except InvalidRecord as exc:
        return _error("INVALID_REQUEST", str(exc))
    except ResetBlocked as exc:
        cause = f" ({exc.__cause__})" if exc.__cause__ else ""
        logger.warning("%s: reset blocked%s", name, cause)
        return _error("VERSION_CONFLICT", str(exc), retryable=True)
    except DataError as exc:
        logger.exception("%s: data error (%s)", name, getattr(exc, "aws_code", exc.code))
        return _error("INTERNAL_ERROR", GENERIC_FAILURE, retryable=exc.retryable)
    except Exception:
        logger.exception("%s: unexpected error", name)
        return _error("INTERNAL_ERROR", GENERIC_FAILURE)
