# Tishneet: graph execution and acceptance ledger

Author: Tishneet. Branch: `feature/ai-workflow--Tishneet`.

## Contribution-history correction

This feature branch is rebuilt from the original shared base with only
Tishneet's backend/support files. It excludes frontend/, backend/api/,
backend/core/, Mariam's simulator tests/PRD, and teammate feature commits.
Small integration edits are retained as docs/integration.patch for later review.

Standalone checks and full temporary-integration checks are separate evidence.
The results below describe the historical combined checkout; they do not mean
teammates' source belongs to this feature branch. Correction results follow below.

## Historical graph and checks

The planner and persistence nodes run independently. Workflow assembly requires
both. AWS migration requires the runtime interface. Independent verification
checks all outputs, followed by the combined test suite and demo walkthrough.
All join dependencies are required; unsuccessful nodes are not counted as passed.
Repairs return to the owning node. A repeated underlying failure triggers contract
review; a six-attempt ceiling per node prevents an unbounded repair chain.

| Node | Weight | Contract | Check | State |
|---|---:|---|---|---|
| Foundation | 10% | Branch integration, Docker, documented module boundaries | Git inspection and running four-service stack | Passed after environment repair |
| Planner | 20% | Validated generation, intent preservation, bounded provider behavior, risk | Independent execution of planner tests | Passed first node check |
| Persistence | 15% | Durable CAS documents and atomic transactions | Independent concurrency checks and actual DynamoDB Local tests | Passed first node check; live local gate passed |
| Workflow | 25% | Durable stages, approvals, current checks, audit, HTTP adapter | Acceptance tests and adversarial independent review | Passed after ambiguity/audit repairs |
| AWS migration preparation | 15% | Provider, Lambda adapter, ASL, infrastructure, callback handling | SAM lint/build/imports plus client-stub tests | Passed locally after packaging repair; live AWS pending |
| Verification and handoff | 15% | Independent review, reproducible demo, docs, branch commits | Combined suite and three walkthroughs | Passed local verification; see handoff |

Progress measures verified implementation deliverables. Docker execution and live
AWS verification are separate evidence gates and never inferred from unit tests.

## Historical integrated evidence — November 7, 2026

Local implementation and verification deliverables: 100%. Live AWS migration is
not complete and is not included in that percentage.

* Docker Desktop engine29.9.2, Compose5.6.1; Python3.12 API/worker, Node22 frontend,
  DynamoDB Local2.6.1 with persistent named volume, all exposed ports loopback.
* Final combined suite **184 passed, zero skipped inside Docker**. Includes actual
  DynamoDB Local request/persistence checks, moto recreation tests, API contracts,
  planner behavior, approvals, execution recovery, and audit concurrency.
* Last independent host suite **183 passed,1 skipped**: the skipped test required
  the DynamoDB Local endpoint; the Docker suite above executed it successfully.
* Three consecutive full HTTP D1/D2/D3 walkthroughs passed with exact counts
  A12/B10/C11 and warehouse version3; duplicate approval did not duplicate movement.
* A pending approval survived actual DynamoDB/API/worker container restarts and
  resumed once. Replayed approval caused no extra movement.
* Frontend production build passed; Ishani's legacy API tests passed in their
  intended isolated reference mode. Attempting those reference tests against a
  revoked durable fixture state initially failed; mode-isolated rerun corrected
  the test setup rather than weakening the real workflow.
* SAM lint, LinuxARM64/Python3.12 custom build, packaged module imports, and
  artifact-content exclusion checks passed. Unsupported host builds fail before
  writing an artifact. No AWS deployment or real-model invocation occurred.
* Interactive browser automation was attempted but its browser host was
  unavailable. No visual/browser interaction pass is claimed. Frontend build
  and all operator actions through actual HTTP were verified.

## Repair history and independent checks

The planner and persistence implementations passed their separate checks. The
assembled result required localized repairs; already-passing nodes were retained.

| Node / check | Failure | Repair and observed result |
|---|---|---|
| Python assembly | Import path and Python3.9 annotations | Explicit test path and postponed annotations; full suite passes |
| Docker environment | Fresh-volume write permissions and missing credential-helper PATH | Local emulator volume access and scoped Docker wrapper; real services run |
| Persistence tests in Docker | Unit AWS-case inherited local endpoint | Make that unit case explicit; real local integration remains enabled |
| Workflow ambiguity | Lost/typed/malformed executor replies could falsely report FAILED after commit | Nonterminal EXECUTING, bounded same-ID retries, manual reconciliation; one-commit regressions pass |
| AWS/API start | Uncertain start/client initialization hid original plan ID | HTTP202 preserves original ID for reconciliation; regressions pass |
| Approval transport | Decision could arrive before callback registration | Persist then bind/deliver same decision; approve/deny race tests pass |
| Audit delivery | Delivery cursor CAS collided with leased PLAN writes | Separate AUDIT_CURSOR record; concurrent model/executor/flusher tests pass |
| SAM packaging | Wrong relative source path, generic host-venv staging, incompatible native wheels | Correct root, controlled in-source builder, explicit LinuxARM64/Python3.12 guard; actual lint/build/import check passes |

Historical integrated commits were `fa4337f` and `528bf59`. They are superseded
by the backend-only history, rather than retained as parents. The original
untracked PDF and Graph Engineering installation are excluded from the commits.

Final independent review disposition: PASS for implemented local/runtime and
packaging scope. No node ended stagnant. Live AWS and interactive browser
verification remain explicitly unrun; neither is represented as a local pass.

## Shared implementation contracts

* `Planner(provider).generate_plan(instruction, warehouse)` returns PlanActions;
  `replan(instruction, failed_plan, simulation_result, warehouse, attempt)` likewise.
* Providers return PlanActions, expose `name`, and optionally `metrics`.
* `validate_plan` and `check_intent` return `{valid, errors}`; invalid intent
  parsing raises `ValueError`. `classify_risk` is deterministic.
* Stores implement `read(key) -> (version, document)`, `write(key, document,
  expected_version) -> version`, `transact([(key, document, expected_version)])`,
  and `list(prefix) -> [(key, version, document)]`.
* `WorkflowService` owns `start_plan`, `get_plan_status`, `record_approval`, and
  `tick`. Status reads never advance execution. Worker steps use CAS leases.
* Local fixture security/data adapters are explicitly labeled. Mariam's actual
  simulator is reused; her future executor and authorizer plug into the same seam.
* API integration goes through Ishani's BackendOps seam, retaining her handlers.
* All source authored in this graph is credited to Tishneet; teammates' merged
  files retain their own authorship.
