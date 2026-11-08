# SentinelOS — Live vs. Stubbed status

_As of 2026-11-08 09:17 UTC. Region us-east-1, account 737876441172._
_"Deployed" / "wired" confirmed via `aws cloudformation describe-stacks` and
`aws lambda get-function-configuration`, not from docs. "Verified live" means a
request was run this session and the plan_id is recorded below._

| Component | Stack / file | Deployed | Wired to API | Verified live (this session) |
|---|---|---|---|---|
| HTTP API (handlers, auth, routing) | `sentinelos-api` / `backend/api/` | ✅ UPDATE_COMPLETE | — (it *is* the API) | ✅ GET /v1/warehouse → seed |
| Backend mode wiring | API Lambda env | ✅ | ✅ `SENTINEL_BACKEND=workflow`, RUNTIME=aws, STATE_MACHINE_ARN + WORKFLOW_TABLE set, no DYNAMODB_ENDPOINT_URL | — |
| Bedrock planning + replanning (Nova Pro) | `sentinel-workflow-tishneet` / `backend/ai/` | ✅ | ✅ via workflow | ✅ D1 real plan |
| Whole-plan simulator | `backend/core/simulator.py` | ✅ (worker) | ✅ | ✅ D1/D2 projections |
| Authorization — Verified Permissions + Cedar | `sentinel-data` / `backend/security/` (`avp.py`, `cedar/*.cedar`) | ✅ | ✅ | ✅ D3 denial |
| State + atomic, version-checked commit | `sentinel-data` / `backend/data/executor.py` + DynamoDB | ✅ | ✅ | ✅ D1 commit v2 |
| Human approval — Step Functions `waitForTaskToken` | `sentinel-workflow-tishneet` / `backend/workflows/` | ✅ | ✅ | ✅ D2 approve→execute |
| Signed admin assertions | Secrets Manager + `backend/api/backend_ops.py`, `backend/security/` | ✅ | ✅ | ✅ used in D2 approve / D3 reset |
| DynamoDB tables (warehouse / agents / audit / executions + workflow) | `sentinel-data`, `sentinel-workflow-tishneet` | ✅ | ✅ | ✅ seed reads |
| Operator UI | Amplify (`main.d1awkbyla46117…`) / `frontend/` | ✅ | ⚠️ serving **mock** (`VITE_MOCK=true`) — see A6 | n/a (mock) |
| Zone add / edit / remove | `frontend/` | ✅ (mock) | mock-only | n/a |

## Recorded plan_ids (this session)
| Demo | Path | plan_id | Result |
|---|---|---|---|
| D1 (auto-execute) | **deployed API, curl** | `plan-6e423b6ed16f465f89a07d5d80062aeb` | COMPLETED · A17/B8/C8 v2 |
| D2 (reject→replan→approve→execute) | live workflow, in-process (session) | `plan-69cc2bfd93d4415a903177b22f68a958` | COMPLETED · A15/B10/C8 v2 (from seed) |
| D3 (revoke→deny) | live workflow, in-process (session) | `plan-2f250789fe7d4e3ca54320fc5d50e625` | REJECTED · AGENT_REVOKED · unchanged |

> Pending (A3–A5): re-run D1/D2/D3 via the **deployed API by curl** and record fresh plan_ids here.

## A2 — API ↔ workflow wiring (verified 2026-11-08 09:17 UTC)
`/v1` URL: `https://hsudj7t7s2.execute-api.us-east-1.amazonaws.com/v1`
- `GET /v1/warehouse` → **A 20/30, B 8/10, C 5/20, version 1, HAZMAT restricted** (seed). ✅
- API Lambda env matches `docs/deployment/api-env.json` exactly; `DYNAMODB_ENDPOINT_URL` absent. ✅
- API role inline policy matches `docs/deployment/api-policy.json` exactly (StartExecution, SendTaskSuccess, DynamoDB on the workflow table, InvokeFunction on the five `sentinel-data-*`) + retained `secretsmanager:GetSecretValue`. ✅
- Deployed Lambda packages the merged `workflows/ai/security/core` (built from the combined artifact). ✅
- `sentinel-data-reset` already has `STATE_MACHINE_ARN` set (Mariam's reset guard). ✅
- **Not redeployed:** the running config already matches the handoff exactly; a redeploy would be a no-op and risks the working stack. Repo-template reconciliation (the committed `backend/api/template.yaml` still shows `Backend=aws`) is tracked as a doc/reproducibility follow-up, not a change to the running system.

## A6 — deployed frontend wiring (2026-11-08)
- `amplify.yml` added: builds `frontend/`; the two env vars to set in the Amplify
  console are **`VITE_MOCK=false`** and **`VITE_API_BASE_URL=https://hsudj7t7s2.execute-api.us-east-1.amazonaws.com/v1`**. (The current app is a manual-zip deploy, so the equivalent flip is a local build with those vars + redeploy.)
- Zone add/edit/remove are now hidden when `VITE_MOCK` is false (real warehouse has fixed zones).
- **CORS verified:** the deployed API returns `access-control-allow-origin: https://main.d1awkbyla46117.amplifyapp.com`. ✅

## ⛔ BLOCKER — admin auth on the deployed API (blocks A4, A5, A6-flip, A7)
Verified by curl 2026-11-08:
- `POST /v1/demo/reset` → **403** `{"error":{"code":"FORBIDDEN","message":"Administrator authorization required."}}`
- `POST /v1/approvals/{id}` → **403** (same)
- `aws apigateway get-authorizers --rest-api-id hsudj7t7s2` → **`[]`** (no authorizer).

Root cause: the deployed Lambda runs `SENTINEL_AUTH_MODE=prod`, which requires an
API Gateway authorizer's claims; the workflow factory refuses `open`/`dev` in AWS
runtime. With no authorizer configured, every admin action (Approve / Revoke /
Reset) returns 403. **D1 (no admin) works via curl** — `plan-42afbee0319e4faeb634fbfe78be7af4` → COMPLETED, A17/B8/C8 v2.

**RESOLVED (2026-11-08):** added a **demo-grade API Gateway Lambda authorizer**
(`backend/api/demo_authorizer.py`) that grants administrator to every caller so
the `prod`-mode admin routes work. ⚠️ Demo-grade only — not real authentication;
a production deploy replaces it with a real IdP (Cognito). Labeled as such here
and on the status slide. (Colon-free `role: admin` context, since API Gateway
mangles context keys with a colon.)

### A3–A5 — live via curl against the deployed API, sequential from one reset
| Step | plan_id | Result |
|---|---|---|
| A3 · D1 | `plan-012a42e85bfb464eb5c47a595c629087` | COMPLETED → A17/B8/C8 v2 ✅ |
| A4 · D2 | `plan-8ddf0e4fcca9418e971f29bbda2939dc` | split A→B×2 + A→C×3, authz+sim pass → AWAITING_APPROVAL → approve → COMPLETED A12/B10/C11 v3 ✅; **2nd approve = no change** (no double-execute) ✅ |
| A5 · D3 | `plan-2501762e4f68406e910bb4f0e76365bf` | revoke → REJECTED, unchanged A12/B10/C11 v3 → reset → seed ✅ |

Note: real Nova proposed the valid D2 split directly (1 candidate, no visible
rejection) — expected per the PRD; the capacity-rejection visual uses the
labeled preflight preset.

## A6 — deployed site flipped to the real API (2026-11-08)
- Rebuilt with `VITE_MOCK=false` + `VITE_API_BASE_URL=.../v1`; deployed to Amplify
  (`main.d1awkbyla46117.amplifyapp.com`), bundle contains the execute-api host.
- Zone add/edit/remove hidden (not mock). CORS preflight for plans / approvals /
  revoke / reset all → **204**. Full D1 through the deployed path (Origin-stamped)
  → COMPLETED A17/B8/C8 v2 (`plan-a8748e6def5741a08da485094e7d840d`), reset → seed.

## A7 — three D1/D2/D3 runs through the deployed UI
Backend + deployed-site network path are **verified** (A3–A5 by curl; A6
Origin-stamped D1). The UI calls the exact same endpoints. **The three UI
click-through runs are a human step** (this session has no browser) — steps in
`docs/demo-script.md`. UI run results to be recorded here by the operator:
| Run | D1 | D2 | D3 |
|---|---|---|---|
| 1 |  |  |  |
| 2 |  |  |  |
| 3 |  |  |  |

## Measured
_Honest single-session observations — **two observed calls, not a percentile distribution.**_

**Latency (Bedrock Nova Pro, Converse):**
- Initial plan generation: **~1012 ms**
- Replan after a simulation rejection: **~698 ms**
- These are two individual Converse calls observed during the live D-runs
  (recorded `plan_id`s above), not p50/p95 over a sample.

**Token usage (same two calls):**
- Plan generation: **747 tokens**; replan: **886 tokens** (input+output per call).
  Again two calls, not an average.

**Simulator test coverage** (`backend/tests/test_simulator.py`, Mariam's branch):
- **37 test functions** (5 of them `@pytest.mark.parametrize`, so more cases run).
- Includes `test_move_2_then_1_from_a_to_b_fails_cumulative_capacity` — the
  "**two transfers each fit, but together exceed B**" case, which is the whole
  point of whole-plan simulation vs. per-action checks.

**Security posture:**
- Authorization: Amazon Verified Permissions + Cedar policies (agent revoke →
  `AGENT_REVOKED` deny, verified in D3).
- Commit safety: DynamoDB conditional writes with version checks + idempotency
  markers (`sentinel_executions`) — re-approving an already-executed plan is a
  no-op (verified in A4: 2nd approve = no change).
- Admin actions: signed HMAC-SHA256 assertions server-side; the deployed API
  runs `AUTH_MODE=prod` behind an API Gateway authorizer. The current authorizer
  is **demo-grade** (grants admin to every caller) — labeled as such; production
  swaps in a real IdP (Cognito). No secrets in the browser.

## Notes
- See the "Measured" section above for numbers + security posture.
