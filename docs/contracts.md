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
| `get_run_id()` | Stable run identity; changes on reset |
| `authorize_plan(plan)` | Per-action decisions from current trusted agent/policy; fail closed |
| `simulate_plan(plan, warehouse)` | Mariam's pure sequential simulator result |
| `execute_plan(**kwargs)` | Exact keyword inputs below; atomic current checks and idempotent commit |
| `revoke_agent(admin)` | Trusted revocation, atomic against execution |
| `reset_demo(control_version, control)` | Atomically fence starts using CONTROL CAS and rotate run identity |
| `append_audit(event)` | Idempotent by `(plan_id,event_id)`; no credentials or tokens |

Executor keyword inputs are `plan_id`, `revision`, immutable `plan`,
`warehouse_version`, `run_id`, and trusted `approval`. Elevated approval includes
its revision, fingerprint, version, run, deciding identity, and time.

An executor must atomically recheck authorization/current state, write all inventory
changes, increment the warehouse version once, and record a unique execution
marker. Replay returns the original `ExecutionResult` before treating a changed
warehouse as a new conflict. A reset must also fence the run identity.

A complete success acknowledgment identifies the exact plan/revision and before/
after versions. A typed business rejection must guarantee no commit. A network
failure, empty/malformed acknowledgment, or generic dependency error is
**unconfirmed**, not proof that inventory was unchanged. Explicit non-commit
responses may use `{"executed":false,"no_commit":true}`.

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
Use `VITE_MOCK=false`; Compose already supplies the live local base URL.

The optional existing preflight button sends an instruction prefix that the strict
intent parser deliberately does not treat as authority. It currently returns a
clarification error. A later labeled preset must use an explicit allowlisted
selector and preserve the original flexible goal, with a coordinated contract
change; this P1 UI enhancement is not part of required execution paths.
