# AI and workflow integration contracts

Author: Tishneet. Companion to the PDF's Team Integration Contract v1.0.

This contribution excludes teammates' implementations. The interfaces below
target the later integration merge. Review/apply `docs/integration.patch` after
merging API and simulator branches; do not vendor their source here.

## Ownership

Tishneet owns `backend/ai` and `backend/workflows`. Mariam owns `backend/core`,
data, authorization, execution, and revocation. Ishani owns HTTP handlers and UI.
The durable `WorkflowBackendOps` adapter implements her existing method surface;
select it with `SENTINEL_BACKEND=workflow`. Her reference backend remains available
as `local`; the older `aws` stub is not the new workflow implementation.

## Module interfaces

`Planner(provider).generate_plan(instruction, warehouse)` and
`replan(instruction, failed_plan, simulation_result, warehouse, attempt)` return
only `{"actions":[{"type":"move_packages","from":"A","to":"C","count":3}]}`.
The workflow independently validates structure and operator intent. Providers
expose `name` and safe per-call `metrics`. `classify_risk(plan)` sums every count.

`WorkflowService` exposes:

| Method | Behavior |
|---|---|
| `start_plan(instruction)` | Persist request and trusted identity; return plan ID and PLANNING |
| `tick(plan_id=None, owner='worker')` | Claim and advance one durable stage |
| `get_plan_status(plan_id)` | Read-only public projection, no authority or tokens |
| `record_approval(approval_id, decision, admin)` | Trusted identity required; conditional durable decision |
| `register_callback(plan_id, token)` | Backend-only binding; handles decision-before-registration race |
| `expire_approval(plan_id)` | Expire an undecided approval after its deadline |
| `get_audit(plan_id=None)` | Recent durable workflow evidence, ordered newest first |
| `flush_audit(plan_id=None)` | Retry durable evidence delivery to Mariam's idempotent sink |
| `reconcile_execution(plan_id)` | Trusted recovery of the same executor identity; no public execute route |
| `reset_demo(admin)` | Persist a CONTROL fence, then invoke the gateway reset with verified identity |
| `reconcile_reset(reset_id, admin)` | Trusted recovery by current-state reads only; never resend reset |

Public statuses remain PLANNING, VALIDATING, AUTHORIZING, SIMULATING, REPLANNING,
AWAITING_APPROVAL, REAUTHORIZING, REVALIDATING, EXECUTING, COMPLETED, REJECTED,
FAILED, EXPIRED. Status responses preserve instruction, candidates, attempt,
warehouse version, risk, approval, execution, updated time, and structured errors.
Optional fields include provider/gateway labels, approval expiry, latency,
and `reconciliation_required`. Revisions are immutable after validation.

## Mariam's trusted gateway

AWS imports `SENTINEL_TRUSTED_ADAPTER_MODULE.create_gateway(store)`. This is an
explicit dependency, not permission to silently use local fixtures. The gateway
must supply:

| Method | Required contract |
|---|---|
| `get_warehouse()` / `get_agent()` | Current trusted records |
| `get_run_id()` | Nonempty string that changes on reset; workflow also normalizes `{run_id: str}` |
| `authorize_plan(plan)` | Per-action decisions from current trusted agent/policy; fail closed |
| `simulate_plan(plan, warehouse)` | Mariam's pure sequential simulator result |
| `execute_plan(**kwargs)` | Exact keyword inputs below; atomic current checks and idempotent commit |
| `revoke_agent(admin)` | Trusted revocation, atomic against execution |
| `reset_demo(control_version, control, admin)` | Invoke signed reset in the API process; CONTROL is a read-only fenced snapshot |
| `append_audit(event)` | Idempotent by `(plan_id,event_id)`; no credentials or tokens |

Executor keyword inputs are `plan_id`, `revision`, immutable `plan`,
`warehouse_version`, `run_id`, and trusted `approval`. Elevated approval includes
exactly `approval_id`, `plan_id`, `revision`, `fingerprint`, `warehouse_version`,
`run_id`, `decision`, `admin`, `decided_at`. Low-risk approval is null. Public and
stored approvals retain `status` and `decision_at`; only the outbound executor
envelope is normalized. Callback tokens and internal expiry fields are excluded.

Reuse `backend.ai.validation.fingerprint` on the complete validated PlanActions
object. It uses sorted JSON keys, compact separators, ensure_ascii=True, UTF-8
and SHA-256. Action order is significant.

An executor must atomically recheck authorization/current state, write all inventory
changes, increment the warehouse version once, and record a unique execution
marker. Replay returns the original `ExecutionResult` before treating a changed
warehouse as a new conflict. A reset must also fence the run identity.

A complete success acknowledgment identifies the exact plan/revision and before/
after versions. A typed business rejection must guarantee no commit. A network
failure, empty/malformed acknowledgment, or generic dependency error is
**unconfirmed**, not proof that inventory was unchanged. Explicit non-commit
responses may use `{"executed":false,"no_commit":true}`.

Agreed no-commit codes are VERSION_CONFLICT, RUN_MISMATCH, AUTHORIZATION_DENIED,
SIMULATION_FAILED, APPROVAL_REQUIRED, APPROVAL_INVALID, INVALID_REQUEST and
PLAN_VALIDATION_FAILED. The workflow preserves
these codes and their boolean retry flags; operator messages are sanitized.
AUTHORIZATION_DENIED is REJECTED; other guaranteed rejections are FAILED. A bare
error, timeout or malformed acknowledgement remains unconfirmed and replays the
same (plan_id, revision), as before.

The production adapter module is `backend.security.gateway` (owned by Mariam).
It wraps her Lambdas and imports `backend.core.simulator` in-process. Workflow
IAM invokes only warehouse, agent, runid, execute, audit-append, authorize in
account737876441172/us-east-1. It has no inventory-table, admin-Lambda, signing-key
or secrets permissions. The API role separately signs revoke/reset assertions;
loading or constructing the gateway in the workflow must not load that secret.

## Reset fence protocol

The orchestrator conditionally persists `CONTROL.reset` before the remote call.
Every start checks the fence and participates in CONTROL CAS, so either the new
start wins and reset is refused, or reset wins and the start cannot commit its
old snapshot. An active plan, including uncertain execution, blocks reset.

The gateway receives `(control_version, control, admin)`; it must not write
CONTROL. The current response contract expects WarehouseState and a fresh run-ID
read different from the prior run, as confirmed by Mariam. Only then does the
service update CONTROL.run_id and clear the fence. Unconfirmed gateway errors,
missing run rotation, invalid responses or failed completion writes keep it durable. It has no automatic expiry or reset retry.

Trusted recovery uses `reconcile_reset(reset_id, admin)`, reads current run and
warehouse, and clears only the matching fence after run rotation is confirmed.
It never invokes the reset Lambda again. An agreed GatewayError with exact
`no_commit=True` from the reset mutation itself releases only the matching fence
and persists a refusal marker. Refusal codes retain their HTTP status and boolean
retry flag; raw messages are never exposed. A later read failure cannot undo a
successful reset or clear its fence. Unknown outcomes stay fenced.

Published gateway756401f invokes sentinel-security-authorize, which Mariam
reports deployed with Verified Permissions. The workflow role needs no direct
Verified Permissions access. Executor fix e4fa706 now checks the agreed
approval.decision/decided_at/plan_id bindings. See integration-readiness.md for
separate local integration and live evidence.

## Durable storage and audit

Store methods: `read(key)->(version,document)`, conditional
`write(key,document,expected_version)`, atomic `transact(mutations)`, and paginated
`list(prefix)`. Records use PLAN#, APPROVAL#, CONTROL, and local-only WORLD keys.
The local WORLD item atomically binds synthetic inventory, agent status, run,
and execution markers; it is not Mariam's production warehouse implementation.

Events are durably appended with plan transitions. Delivery has a persisted
cursor; an external sink must tolerate redelivery after lost acknowledgments.
Audit sink failures never cause a second inventory commit or relabel a completed
execution. An AWS schedule retries outstanding delivery once per minute.

Recent cross-plan audit uses a paginated filtered scan for this bounded demo.
Replace scan-based discovery and bounded aggregate records with indexes and
separate records before expanding scale.

## Ishani handoff

HTTP shapes and routes stay unchanged. The adapter converts workflow errors to
her standard error response. Approval/revoke/reset need authenticated admin
identity supplied by her handler. JWT group membership is matched exactly.

An uncertain AWS start returns HTTP202 with the original `plan_id`, PLANNING,
and `start_confirmed:false`; poll/reconcile that ID rather than resubmitting.
The local worker is independent of polling. Refresh should recover the same ID.
Use `VITE_MOCK=false` and configure the frontend API base separately after the
team merge; this backend contribution does not provide frontend orchestration.

The actual fixture-backed completed GET sample is committed at
`docs/examples/plan-status.fixture.completed.json`; see its adjacent README for
capture provenance. No task/callback token is present.

The optional existing preflight button sends an instruction prefix that the strict
intent parser deliberately does not treat as authority. It currently returns a
clarification error. A later labeled preset must use an explicit allowlisted
selector and preserve the original flexible goal, with a coordinated contract
change; this P1 UI enhancement is not part of required execution paths.
