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

## Notes
- Measured numbers + security posture: see the "Measured" section (added in B2).
