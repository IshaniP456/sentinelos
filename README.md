# SentinelOS

**SentinelOS: preflight security for AI agents. Simulates an agent's whole plan against live state before it executes; blocks, replans, holds for human approval, commits atomically.**

Guardrails check the text. Policy engines check one action. SentinelOS checks what the *whole plan* does to the system — it runs the agent's entire proposed sequence against the live warehouse state before a single action commits, then blocks, replans, holds for a human, or commits atomically.

AWS × A10 SCU Generative AI Hackathon.

## Live vs stubbed

What is actually deployed and verified (vs. reference/mock) is tracked honestly in
[`docs/status.md`](docs/status.md) — component-by-component, confirmed from AWS
(`cloudformation describe-stacks`, `lambda get-function-configuration`), with the
recorded `plan_id`s for every demo run exercised live this session.

## Run the demo

**Deployed UI:** https://main.d1awkbyla46117.amplifyapp.com (wired to the live API).

**Walkthrough (three demos):** see [`docs/demo-script.md`](docs/demo-script.md) —
the instruction to paste, the expected end state, and what to click, for each of:

- **D1 — auto-execute:** a safe plan (3 packages A→C) simulates clean and commits (A17/B8/C8, version 2).
- **D2 — reject → replan → approve → execute:** an over-capacity plan is caught in simulation, the agent replans a valid split, and a human approves before it commits.
- **D3 — revoke → deny:** an admin revokes the agent mid-flight; the next plan is rejected before any state changes.

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
