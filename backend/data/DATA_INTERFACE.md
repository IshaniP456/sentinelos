# Data-access layer — interface

Owner: Mariam · Consumers: Ishani (`AwsBackendOps`), Tishneet (workflow Lambdas), Phase 3 executor.
Follows Team Integration Contract v1.0, §2.1, §2.2, §5.2, §6.

```python
from data.dynamo import (
    get_warehouse, get_agent, update_agent_status,
    record_audit_event, list_audit_events, reset_demo, seed_if_missing,
)
```

## Functions

| Function | Returns | Notes |
|---|---|---|
| `get_warehouse(warehouse_id="demo-warehouse")` | WarehouseState (§2.1) | Strongly consistent read. Plain `int`s, so it goes straight into `simulate_plan(plan, get_warehouse())`. |
| `get_agent(agent_id)` | AgentRecord (§2.2) | Strongly consistent read. Authorization callers must treat **any** exception as DENY. |
| `update_agent_status(agent_id, status, *, updated_by=None)` | AgentRecord | `ACTIVE`, `REVOKED`, `SUSPENDED`. Never creates an agent. Revoke = `update_agent_status("inventory-agent-01", "REVOKED", updated_by=admin)`. |
| `record_audit_event(event)` | stored AuditEvent (§5.2) | Append-only. Required: `plan_id`, `event_type` (UPPER_SNAKE), `outcome`, `message`. Optional: `event_id`, `timestamp`, `revision` (default 0), `reason_code`, `details` (object), `admin`. Use `plan_id="SYSTEM"` for revoke/reset events. Keys that look like secrets (`token`, `secret`, `password`, ...) are rejected. |
| `list_audit_events(plan_id=None, *, limit=50)` | list of AuditEvent, newest first | One plan, or recent events across all plans via the `recent_events` index. Never scans. Max limit 200. |
| `reset_demo(*, active_workflow_check, reset_by=None)` | WarehouseState | **`active_workflow_check` is required**: a function returning exactly `False` when no plan is active or awaiting approval. Anything else, or an exception, blocks the reset (FR13). Warehouse, agent, and a `DEMO_RESET` audit event are written in one transaction. Audit history is kept. |
| `seed_if_missing()` | `{"warehouse": "created"/"kept", "agent": ...}` | First-time setup. Never overwrites existing records. |

## Errors

All errors subclass `data.dynamo.DataError` with `.code` and `.retryable`. Raw boto3 exceptions never escape.

| Exception | `.code` | When |
|---|---|---|
| `RecordNotFound` | `NOT_FOUND` | Unknown warehouse or agent |
| `InvalidRecord` | `INVALID_REQUEST` | Bad status, malformed audit event, blank id |
| `AuditEventExists` | `AUDIT_EVENT_EXISTS` | Same `(plan_id, event_id)` written twice. Safe to ignore on a retry. |
| `ResetBlocked` | `RESET_BLOCKED` | A workflow may be active (retryable) |
| `CorruptRecord` | `INTERNAL_ERROR` | Stored warehouse missing version or zones |
| `DataAccessError` | `INTERNAL_ERROR` | AWS failure. `.aws_code` has the AWS error; `.retryable` is true for throttling. |

## Tables (contract §6)

| Table | Keys | Attributes |
|---|---|---|
| `sentinel_warehouse` | `warehouse_id` (S) | `version`, `zones`, `restricted_zones`, plus internal `run_id`, `reset_at` |
| `sentinel_agents` | `agent_id` (S) | `status`, `role`, `max_transfer`, plus `updated_at`, `updated_by` |
| `sentinel_audit` | `plan_id` (S), `event_id` (S) | AuditEvent fields, plus `feed` = `"ALL"` for the `recent_events` index (`feed`, `event_id`) |

`run_id` changes on every reset. It is stored for the Phase 3 executor so an approval from before a reset cannot match the new run, even though the version is back to 1. It is not returned by `get_warehouse`.

Table names can be overridden with `SENTINEL_WAREHOUSE_TABLE`, `SENTINEL_AGENTS_TABLE`, `SENTINEL_AUDIT_TABLE`. Region and credentials come from the standard AWS chain (`AWS_REGION`, profile, or the Lambda role).

### SAM resources (Mariam's own data stack)

Agreed with Ishani: Mariam owns these tables and the data Lambdas in her own SAM stack. Other stacks reference the tables by name; they do not define them.

```yaml
  WarehouseTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: sentinel_warehouse
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions: [{AttributeName: warehouse_id, AttributeType: S}]
      KeySchema: [{AttributeName: warehouse_id, KeyType: HASH}]
  AgentsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: sentinel_agents
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions: [{AttributeName: agent_id, AttributeType: S}]
      KeySchema: [{AttributeName: agent_id, KeyType: HASH}]
  AuditTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: sentinel_audit
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - {AttributeName: plan_id, AttributeType: S}
        - {AttributeName: event_id, AttributeType: S}
        - {AttributeName: feed, AttributeType: S}
      KeySchema:
        - {AttributeName: plan_id, KeyType: HASH}
        - {AttributeName: event_id, KeyType: RANGE}
      GlobalSecondaryIndexes:
        - IndexName: recent_events
          KeySchema:
            - {AttributeName: feed, KeyType: HASH}
            - {AttributeName: event_id, KeyType: RANGE}
          Projection: {ProjectionType: ALL}
```

Lambdas using this layer need `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query` on these tables and the index, plus `dynamodb:ConditionCheckItem`/`PutItem` for `TransactWriteItems` (reset).

## Setup and tests

From `backend/`:

```
# Mocked tests (moto, no AWS):
uv run --no-project --python 3.12 --with pytest --with boto3 --with 'moto[dynamodb]' python -m pytest tests -v

# Inspect real AWS (dry run, changes nothing):
uv run --no-project --python 3.12 --with boto3 python -m data.setup_tables

# Create missing tables + seed (only if the tables are NOT deployed by Mariam's SAM stack):
uv run --no-project --python 3.12 --with boto3 python -m data.setup_tables --apply

# Real DynamoDB tests (non-destructive):
SENTINEL_AWS_TESTS=1 uv run --no-project --python 3.12 --with pytest --with boto3 python -m pytest tests/test_data_aws.py -v
```

## Executor (Phase 3) — `data.executor.execute_plan`

Lambda: `sentinel-data-execute` (invoke from the workflow only). Run identity: `sentinel-data-runid` → `{"run_id": str}`.

```python
execute_plan(*, plan_id, revision, plan, warehouse_version, run_id, approval=None)
```

Exact keyword inputs of the workflow gateway. `approval` is `None` for totals of 1–4. For totals ≥ 5 it must be
`{"status": "APPROVED", "revision", "fingerprint", "warehouse_version", "run_id", "admin", ...}` where
`fingerprint = sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True))`
(same as `backend/ai/validation.py::fingerprint`; see `core/fingerprint.py`).

Order of checks, all against current trusted state: replay marker → run_id → warehouse version → plan structure →
authorization with the current agent (local policy, labeled `LOCAL_POLICY` until Verified Permissions) →
approval binding (elevated only) → simulation. Then one transaction: zones + version+1 (conditional on version
and run_id), agent still `ACTIVE`, unique `(plan_id, revision)` marker in `sentinel_executions`, `PLAN_EXECUTED` audit.

| Result | Meaning |
|---|---|
| ExecutionResult (`executed: true`, contract §3.5) | Committed. Replays of the same `(plan_id, revision)` return this exact object. |
| `{"executed": false, "no_commit": true, "status", "error": {code, message, retryable}}` | Guaranteed nothing written. Codes: `INVALID_REQUEST`, `RUN_MISMATCH`, `VERSION_CONFLICT` (retryable), `PLAN_VALIDATION_FAILED`, `AUTHORIZATION_DENIED`, `APPROVAL_REQUIRED`, `APPROVAL_INVALID`, `SIMULATION_FAILED`. Denials may include `authorization` or `violations`. |
| Bare `{"error": {...}}` (no `no_commit`) | **Unconfirmed.** Replay the same `(plan_id, revision)` to learn the outcome. |

## Workflow gateway — `backend.security.gateway`

`SENTINEL_TRUSTED_ADAPTER_MODULE=backend.security.gateway`; the workflow calls `create_gateway(store)`.
Building it makes no AWS calls and never loads the signing key.

| Method | Implementation |
|---|---|
| `get_warehouse()`, `get_agent()` | invoke `sentinel-data-warehouse` / `sentinel-data-agent` |
| `get_run_id()` | invoke `sentinel-data-runid`, returns a non-empty string |
| `authorize_plan(plan)` | invoke `sentinel-security-authorize` → Amazon Verified Permissions (`engine: VERIFIED_PERMISSIONS`) with the current agent record; any failure or malformed reply denies every action |
| `simulate_plan(plan, warehouse)` | in-process `backend.core.simulator` |
| `execute_plan(**six fields)` | invoke `sentinel-data-execute`; response returned unchanged; transport failure raises |
| `append_audit(event)` | invoke `sentinel-data-audit-append` → `{"recorded": true, "duplicate": bool}` |
| `revoke_agent(admin)` | signs `REVOKE_AGENT` at call time (API process only), invokes `sentinel-data-revoke` |
| `reset_demo(control_version, control, admin)` | signs `RESET_DEMO`, invokes `sentinel-data-reset`, returns WarehouseState; never writes CONTROL; call `get_run_id()` after |

Errors from read/admin calls raise `security.gateway.GatewayError(code, message, retryable)`.
Function names can be overridden with `SENTINEL_FN_<WAREHOUSE|AGENT|RUNID|EXECUTE|AUDIT_APPEND|REVOKE|RESET>`.

Invoke permissions: the workflow role needs warehouse, agent, runid, execute, audit-append, and `sentinel-security-authorize`.
Ishani's API role (where revoke/reset/approval run) needs warehouse, agent, audit, runid, revoke, reset, and the secret.

## Authorization (Phase 4) — Amazon Verified Permissions + Cedar

Policies and schema live in `backend/security/cedar/` (single source; the template embeds the same text and a test checks they match).

| Policy | Rule |
|---|---|
| `allow_active_within_limit` | permit `MovePackages` when status is `ACTIVE` and 1 ≤ count ≤ 10 and count ≤ the agent's `max_transfer` |
| `forbid_restricted_destination` | forbid when destination is `HAZMAT` or a restricted zone |
| `forbid_inactive_agent` | forbid unless status is `ACTIVE` (revoked/suspended) |

Principal `Sentinel::Agent::"inventory-agent-01"` with `status`/`max_transfer` read from DynamoDB at call time; resource `Sentinel::Warehouse::"demo-warehouse"`; context `count`, `destination`, `restricted_destination`.
One `BatchIsAuthorized` call per plan. The deployed executor and `sentinel-security-authorize` run with
`SENTINEL_AUTHZ_ENGINE=VERIFIED_PERMISSIONS`; errors, missing attributes or mismatched results deny every action
(no fallback). Reason codes (`POLICY_ALLOWED`, `LIMIT_EXCEEDED`, `RESTRICTED_DESTINATION`, `AGENT_REVOKED`, `AGENT_SUSPENDED`,
`AUTHORIZATION_ERROR`) come from the local policy's explanation; if Verified Permissions ever allows what the local policy
denies, the action is denied. Tests evaluate the real policy files with cedarpy (`--with cedarpy`; skipped if absent).
