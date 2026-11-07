# SentinelOS — Frontend-facing HTTP API

Ishani owns these trusted HTTP entry points (integration contract §5). They
connect the React dashboard to the backend AWS services. This layer parses
requests, authenticates admins, sets CORS, and returns contract-shaped JSON —
it does **not** implement authorization or execution logic. Those live behind
the `BackendOps` seam and are owned by Mariam (security/data/execution) and
Tishneet (planning workflow / Step Functions).

Pure Python standard library — no `pip install` needed.

## Endpoints (contract §5)

| Method | Path | Handler | Admin? | Success |
|--------|------|---------|--------|---------|
| POST | `/v1/plans` | `submit_plan` | – | 202 `{plan_id, status}` |
| GET | `/v1/plans/{plan_id}` | `get_plan` | – | 200 `PlanStatus` |
| GET | `/v1/warehouse` | `get_warehouse` | – | 200 `WarehouseState` |
| GET | `/v1/agents/current` | `get_agent` | – | 200 `AgentRecord` |
| GET | `/v1/audit?plan_id=…` | `get_audit` | – | 200 `{events:[…]}` |
| POST | `/v1/approvals/{approval_id}` | `decide_approval` | ✅ | 202 `{approval_id, status}` |
| POST | `/v1/agents/current/revoke` | `revoke_agent` | ✅ | 200 `AgentRecord` |
| POST | `/v1/demo/reset` | `reset_demo` | ✅ | 200 `WarehouseState` |

Errors use the standard error object (contract §3.6):
`{"error": {"code", "message", "retryable"}}`.

## Run locally

```bash
# from repo root
python3 -m backend.api.test_api          # unit test: runs D1/D2/D3 through the handlers

# live server (real handler code, no AWS):
SENTINEL_AUTH_MODE=open python3 -m backend.api.local_server   # http://localhost:8000/v1
```

Point the frontend at it (`frontend/.env.local`):

```
VITE_MOCK=false
VITE_API_BASE_URL=http://localhost:8000/v1
```

Now the dashboard talks to the real HTTP handlers instead of the in-browser
mock. Behavior and numbers are identical (same contract), which is exactly the
point — the swap is invisible to the UI.

## Configuration (env vars)

| Var | Values | Meaning |
|-----|--------|---------|
| `SENTINEL_BACKEND` | `local` (default) / `aws` | reference backend vs production seam |
| `SENTINEL_AUTH_MODE` | `prod` (default) / `dev` / `open` | admin auth mechanism |
| `SENTINEL_ADMIN_TOKEN` | string | required in `dev` mode (`X-Admin-Token` header) |
| `SENTINEL_CORS_ORIGIN` | URL | allowed browser origin (default `http://localhost:5173`) |
| `SENTINEL_API_PORT` | int | local server port (default `8000`) |

### Auth modes

- **`prod`** — real mechanism: an API Gateway authorizer (Cognito user-pool or
  Lambda authorizer) authenticates the caller; we require an `admin`
  claim/group. The browser sends only its session cookie; no secret ever
  reaches JS (contract §0, NFR01). **This is a kickoff decision to finalize
  with Mariam.**
- **`dev`** — curl/test stand-in: `X-Admin-Token: <SENTINEL_ADMIN_TOKEN>`.
- **`open`** — local browser UI testing only; every caller is treated as
  admin. **Never deploy this.**

## Integration seam — `backend_ops.py`

Handlers call a `BackendOps` instance; they never touch Bedrock, Step
Functions, DynamoDB, or Verified Permissions directly.

- `LocalBackendOps` — self-contained reference that mirrors the contract and
  reproduces D1/D2/D3 with exact inventory outcomes. Used for all local runs
  and tests today.
- `AwsBackendOps` — production stub. Each method documents the trusted
  operation it must invoke (e.g. `start_plan` → Step Functions `StartExecution`;
  `get_warehouse` → Mariam's DynamoDB read; `record_approval` → resume Step
  Functions with the stored task token, server-side only). Fill these in as
  teammates' pieces land — **the HTTP layer and the frontend do not change.**

## Deploying to AWS (API Gateway + Lambda)

`handler(event, context)` in `handlers.py` is the single Lambda proxy entry
point; it routes all eight endpoints internally (the timeline permits sharing
one Lambda). Wire API Gateway with Lambda-proxy integration for the routes in
the table above, pointing every route at this one function — or split the
per-endpoint functions into separate Lambdas later if preferred.

> The shared `template.yaml` / IAM resources are edited by one integration
> editor at a time, coordinated by Tishneet (contract §9.2). Hand this route
> table + the `prod` authorizer requirement to that process rather than
> editing the shared template unilaterally.

## Security notes honored

- Browser submits only the instruction; backend assigns plan_id/agent/revisions
  (contract §2.4).
- Admin routes fail closed without a verified admin identity (NFR01).
- No Step Functions task tokens or AWS credentials ever returned to the client
  (contract §8).
- Idempotent approval: repeat decisions can't double-execute (contract §3.5).
- Reset refused while any workflow is active (FR13).
- Unexpected errors return a generic `INTERNAL_ERROR` — internals never leak
  (NFR04).
