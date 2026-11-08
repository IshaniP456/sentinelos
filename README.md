# SentinelOS

**SentinelOS: preflight security for AI agents. Simulates an agent's whole plan against live state before it executes; blocks, replans, holds for human approval, commits atomically.**

Guardrails check the text. Policy engines check one action. SentinelOS checks what the *whole plan* does to the system — it runs the agent's entire proposed sequence against the live warehouse state before a single action commits, then blocks, replans, holds for a human, or commits atomically.

AWS × A10 SCU Generative AI Hackathon.

## Live vs stubbed

What is actually deployed and verified (vs. reference/mock) is tracked honestly in
[`docs/status.md`](docs/status.md) — component-by-component, confirmed from AWS
(`cloudformation describe-stacks`, `lambda get-function-configuration`), with the
recorded `plan_id`s for every demo run exercised live.

## Run the demo

**Deployed UI:** https://main.d1awkbyla46117.amplifyapp.com (wired to the live API).

**Walkthrough:** see [`docs/demo-script.md`](docs/demo-script.md) — the instruction to
paste, the expected end state, and what to click, for each demo:

- **D1 — auto-execute:** a safe plan (3 packages A→C) simulates clean and commits (A17/B8/C8, version 2).
- **D2 — approval path:** a large move is split to respect capacity and held for human approval before it commits.
- **D2b — hard block:** an over-capacity move (5→B) is refused by the simulation; nothing moves.
- **D3 — revoke → deny:** an admin revokes the agent; the next plan is rejected before any state changes.

**Local (mock, no AWS):**

```bash
cd frontend
npm install
npm run dev        # VITE_MOCK defaults to true — in-browser mock engine, no backend
```

**Local against the real API:**

```bash
cd frontend
VITE_MOCK=false VITE_API_BASE_URL=https://hsudj7t7s2.execute-api.us-east-1.amazonaws.com/v1 npm run dev
```

---

## Standalone backend checks

Start Docker Desktop, then run from this repository's root:

```sh
make test
```

This builds the backend image, starts an isolated persistent DynamoDB Local,
and runs planner, intent, risk, persistence, and setup checks. No AWS credentials
or teammates' source files are required. `make down` stops these services.
`bash scripts/dev.sh up -d` starts only DynamoDB Local on this contribution branch.
The backend Compose setup does not serve the frontend. Docker's PATH adjustment
is scoped to the wrapper; Ishani's frontend has its own setup instructions.

## Integration after the team merge

Mariam's simulator/security contribution must also be merged before running the
complete workflow suite. Ishani's API already selects workflow mode and includes
her auth reconciliation. Review docs/integration.patch with the owners only for
any remaining applicable changes; do not blindly apply already-adopted hunks.
Then test:

```sh
make test-integration
make integration-up
```

The patch contains only Tishneet's workflow-selector, exact administrator-group
matching, and Python annotation compatibility changes. If newer teammates'
files conflict, resolve the hunks with their owners rather than overwrite files.
The integrated API runs at http://localhost:8000/v1; worker/API services use an
explicit integration profile. Ishani owns frontend startup and hosting.
After integration, `make demo` runs D1/D2/D3 through HTTP.

Fixture model/security/data adapters are labeled development fixtures, not real
Bedrock or Verified Permissions. Never deploy open local administrator access.

## AWS preparation and handoff

`make aws-build` lints/builds the Lambda artifact using an isolated Linux
ARM64/Python3.12 tooling container, without deployment. The workflow stack is
already deployed with Mariam's separately packaged gateway; actual outputs,
API environment/IAM additions and live test evidence are in docs/deployment.
Source merges do not automatically redeploy the API or workflow.

- [Contracts and ownership](docs/contracts.md)
- [Branch scope and handoff](docs/handoff.md)
- [Verification history](docs/graph-execution.md)
- [AWS migration](docs/aws-migration.md)
