"""Mariam's trusted gateway for Tishneet's workflow.

Load with ``SENTINEL_TRUSTED_ADAPTER_MODULE=backend.security.gateway``; the
workflow calls ``create_gateway(store)``.

Design (agreed with Tishneet and Ishani):
  * Privileged operations go through Mariam's Lambdas. The workflow's role can
    invoke them but has no access to the inventory tables or the signing key.
  * ``simulate_plan`` runs in-process (pure function, no AWS).
  * ``revoke_agent`` and ``reset_demo`` sign an admin assertion at call time.
    They only run inside Ishani's API process, whose role can read the key.
    Constructing the gateway never touches Secrets Manager, so the workflow
    Lambda never loads the key.
  * ``execute_plan`` returns the executor's response unchanged. Anything other
    than ``executed: true`` or ``no_commit: true`` is unconfirmed by contract;
    transport failures raise.
  * CONTROL records belong to the workflow. ``reset_demo`` does not write them.

Function names come from environment variables (defaults are the deployed
names in us-east-1).
"""

import json
import os
import secrets
import time
from collections.abc import Mapping
from typing import Any

try:  # imported as backend.security.gateway (workflow Lambda, repository root)
    from ..core.simulator import simulate_plan as _simulate_plan
except ImportError:  # imported as security.gateway (backend/ on the path)
    from core.simulator import simulate_plan as _simulate_plan

from .admin_assertion import sign

FUNCTIONS = {
    "warehouse": ("SENTINEL_FN_WAREHOUSE", "sentinel-data-warehouse"),
    "agent": ("SENTINEL_FN_AGENT", "sentinel-data-agent"),
    "runid": ("SENTINEL_FN_RUNID", "sentinel-data-runid"),
    "authorize": ("SENTINEL_FN_AUTHORIZE", "sentinel-security-authorize"),
    "execute": ("SENTINEL_FN_EXECUTE", "sentinel-data-execute"),
    "audit_append": ("SENTINEL_FN_AUDIT_APPEND", "sentinel-data-audit-append"),
    "revoke": ("SENTINEL_FN_REVOKE", "sentinel-data-revoke"),
    "reset": ("SENTINEL_FN_RESET", "sentinel-data-reset"),
}
EXECUTE_FIELDS = ("plan_id", "revision", "plan", "warehouse_version", "run_id", "approval")


class GatewayError(Exception):
    """A gateway call failed. ``code``/``retryable`` mirror the standard error object.

    ``no_commit`` is True only when nothing can have changed (refused before any
    write). False means the outcome is unconfirmed: reconcile, don't assume.
    """

    def __init__(self, code: str, message: str, retryable: bool = False, no_commit: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.no_commit = no_commit


# Error codes my revoke/reset Lambdas return only BEFORE any write. INTERNAL_ERROR
# (or a transport failure) can happen after a commit, so it is never guaranteed.
GUARANTEED_REFUSAL_CODES = frozenset({"FORBIDDEN", "VERSION_CONFLICT", "NOT_FOUND", "INVALID_REQUEST"})


def create_gateway(store: Any = None) -> "TrustedGateway":
    """Factory the workflow imports. ``store`` is accepted for interface compatibility."""
    return TrustedGateway()


class TrustedGateway:
    """Workflow-facing facade over Mariam's Lambdas. Creating it makes no AWS calls."""

    name = "LAMBDA_GATEWAY"

    def __init__(self, invoke: Any = None) -> None:
        self._invoke_override = invoke  # tests inject an in-process invoker
        self._lambda_client: Any = None
        self._signing_key: bytes | None = None

    # ------------------------------------------------------------- reads

    def get_warehouse(self) -> dict[str, Any]:
        return self._call("warehouse", {})

    def get_agent(self) -> dict[str, Any]:
        return self._call("agent", {})

    def get_run_id(self) -> str:
        run_id = self._call("runid", {}).get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise GatewayError("INTERNAL_ERROR", "Run identity is missing.", retryable=True)
        return run_id

    # ------------------------------------------------- decisions (no writes)

    def authorize_plan(self, plan: Any) -> dict[str, Any]:
        """Per-action decisions from Amazon Verified Permissions, via sentinel-security-authorize.

        Uses the CURRENT trusted agent record. Any failure or malformed response
        denies every action. The executor re-authorizes at commit time regardless.
        """
        actions = plan.get("actions") if isinstance(plan, Mapping) else None
        try:
            result = self._invoke("authorize", {"plan": plan})
        except Exception:
            result = None
        if (isinstance(result, dict) and isinstance(result.get("allowed"), bool)
                and isinstance(result.get("decisions"), list) and result["decisions"]):
            return result
        count = len(actions) if isinstance(actions, list) and actions else 1
        return {
            "allowed": False,
            "decisions": [{"action_index": i, "allowed": False, "reason_code": "AUTHORIZATION_ERROR"}
                          for i in range(count)],
            "engine": "UNAVAILABLE",
        }

    def simulate_plan(self, plan: Any, warehouse: Any) -> dict[str, Any]:
        return _simulate_plan(plan, warehouse)

    # ---------------------------------------------------------- execution

    def execute_plan(self, **kwargs: Any) -> Any:
        """Invoke the executor with exactly the six contract fields; return its response as-is."""
        unknown = sorted(set(kwargs) - set(EXECUTE_FIELDS))
        if unknown:
            raise TypeError(f"execute_plan got unexpected arguments {unknown}")
        payload = {field: kwargs.get(field) for field in EXECUTE_FIELDS}
        return self._invoke("execute", payload)  # never interpreted here

    # -------------------------------------------------------------- audit

    def append_audit(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Idempotent on (plan_id, event_id): a duplicate is acknowledged, not an error."""
        return self._call("audit_append", {"event": dict(event)})

    # --------------------------------------- admin actions (API process only)

    def revoke_agent(self, admin: str) -> dict[str, Any]:
        """Revoke the agent. Refusals before any write raise GatewayError(no_commit=True)."""
        return self._admin_call("revoke", "REVOKE_AGENT", admin)

    def reset_demo(self, control_version: Any = None, control: Any = None, admin: str | None = None) -> dict[str, Any]:
        """Restore the seed warehouse. The workflow holds its CONTROL fence; this never writes CONTROL.

        Returns WarehouseState. Call ``get_run_id()`` afterwards for the new run identity.
        """
        if admin is None:
            raise GatewayError("FORBIDDEN", "reset_demo requires the authenticated administrator.",
                               no_commit=True)
        return self._admin_call("reset", "RESET_DEMO", admin)

    # ----------------------------------------------------------- plumbing

    def _admin_call(self, function: str, action: str, admin: Any) -> dict[str, Any]:
        """Sign, invoke, and classify failures as guaranteed refusal vs unconfirmed."""
        assertion = self._assertion(action, admin)  # raises with no_commit=True; nothing invoked
        try:
            return self._call(function, {"admin_assertion": assertion})
        except GatewayError as exc:
            exc.no_commit = exc.code in GUARANTEED_REFUSAL_CODES
            raise

    def _assertion(self, action: str, admin: Any) -> dict[str, Any]:
        if not isinstance(admin, str) or not admin.strip() or len(admin) > 256 or "|" in admin:
            raise GatewayError("FORBIDDEN", "Invalid administrator identity.", no_commit=True)
        key = self._key()
        issued_at, nonce = int(time.time()), secrets.token_hex(16)
        return {"admin": admin, "action": action, "issued_at": issued_at, "nonce": nonce,
                "signature": sign(key, action, admin, issued_at, nonce)}

    def _key(self) -> bytes:
        """Load the signing key on first admin action. Fails closed outside the API process."""
        if self._signing_key is None:
            secret_arn = os.environ.get("ADMIN_SECRET_ARN")
            if not secret_arn:
                raise GatewayError("INTERNAL_ERROR", "Admin signing is not configured in this process.",
                                   no_commit=True)
            import boto3

            try:
                value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
            except Exception as exc:
                raise GatewayError("INTERNAL_ERROR", "Admin signing key is unavailable.",
                                   no_commit=True) from exc
            self._signing_key = value.encode("utf-8")
        return self._signing_key

    def _call(self, function: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke and unwrap: a standard error object becomes GatewayError."""
        data = self._invoke(function, payload)
        if not isinstance(data, dict):
            raise GatewayError("INTERNAL_ERROR", f"{function} returned no object.", retryable=True)
        if "error" in data and isinstance(data["error"], Mapping):
            err = data["error"]
            raise GatewayError(str(err.get("code", "INTERNAL_ERROR")), str(err.get("message", "")),
                               bool(err.get("retryable", False)))
        return data

    def _invoke(self, function: str, payload: dict[str, Any]) -> Any:
        if self._invoke_override is not None:
            return self._invoke_override(function, payload)
        env_var, default = FUNCTIONS[function]
        name = os.environ.get(env_var, default)
        if self._lambda_client is None:
            import boto3

            self._lambda_client = boto3.client("lambda")
        response = self._lambda_client.invoke(FunctionName=name, Payload=json.dumps(payload).encode())
        raw = response["Payload"].read()
        if response.get("FunctionError"):
            raise GatewayError("INTERNAL_ERROR", f"{name} failed.", retryable=True)
        return json.loads(raw) if raw else None
