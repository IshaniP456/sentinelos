# SentinelOS — Frontend & Public API Client

Operator/admin console for SentinelOS (AWS × A10 Hackathon). React + Vite +
Tailwind. Owns the user-facing experience and the single API client that every
component talks through.

## Run

```bash
cd frontend
npm install
cp .env.example .env.local   # VITE_MOCK=true by default
npm run dev                  # http://localhost:5173
npm run build                # production build -> dist/
```

## Mock vs real backend

All backend calls live in `src/services/api.js`. Components never call `fetch`
directly (integration contract §5.3).

- `VITE_MOCK=true` (default) runs an in-browser engine (`src/mock/engine.js`)
  that implements the same HTTP contract, so the whole dashboard is interactive
  with no AWS attached. It reproduces the three judged demos exactly:
  - **D1** low-risk `A→C×3` auto-executes → A=17, B=8, C=8, v2
  - **D2** `A→B×5` fails simulation (B=13/10) → AI revises to `A→B×2, A→C×3`
    → requires approval → A=12, B=10, C=11, v3
  - **D3** revoked agent → next request denied (`AGENT_REVOKED`), inventory unchanged
- Flip to the live API: set `VITE_MOCK=false` and
  `VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com/v1`.
  No component changes required.

## Structure

```
src/
├── App.jsx                 # owns state, 2s polling, routes all actions through api.js
├── services/api.js         # the ONLY place HTTP lives (8 endpoints, contract §5)
├── mock/
│   ├── data.js             # frozen seed state, status enums
│   └── engine.js           # in-browser backend mock (same contract)
├── lib/format.js           # status/utilization/tone helpers
└── components/
    ├── Header.jsx          # branding, warehouse version, reset
    ├── WarehouseOverview.jsx + ZoneCard.jsx   # actual vs projected inventory
    ├── AgentConsole.jsx    # NL instruction input + demo presets
    ├── PlanComparison.jsx  # original vs revised, authz + sim + violations
    ├── WorkflowStatus.jsx  # multi-check pipeline, backend-driven (no fake timers)
    ├── ApprovalModal.jsx   # human approval (FR07), double-submit guarded
    ├── AuditLog.jsx        # backend event history (FR12)
    └── AgentControls.jsx   # admin revocation (FR10)
```

## Contract notes honored

- Browser submits **only** the instruction string; backend assigns
  plan_id / agent / revisions (contract §2.4).
- Projected inventory is always labeled a counterfactual, never shown as
  committed state (contract §3.3, PRD FR04).
- No Step Functions task tokens or AWS credentials in the client (contract §0,
  NFR01). Approval/revoke/reset are admin-only and forwarded to trusted backend.
- Polls `GET /v1/plans/{id}` every 2s while non-terminal; refreshes warehouse
  after `COMPLETED` (PRD FR11).
- Network/HTTP errors surface the standard error object and never display a
  false success (PRD FR11, NFR04).

## Not yet wired (next up)

- `backend/api/` Lambda handlers + API Gateway config (Ishani owns; timeline
  Phase 3). The mock engine defines the exact response shapes they must return.
- Admin authentication mechanism (kickoff decision with Mariam).
- Amplify Hosting deploy (timeline Phase 7).
