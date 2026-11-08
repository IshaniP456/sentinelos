# SentinelOS — Presentation Deck

> AWS × A10 SCU Generative AI Hackathon · "Safe AI Operations"
> Slide delimiters are `---`. Speaker notes are in _italics_ under each slide.
> Paste into Google Slides / Marp / Slidev, one block per slide.

---

## 1 · Title

# SentinelOS
### An execution firewall for autonomous AI agents

Live: https://main.d1awkbyla46117.amplifyapp.com

_Team: Ishani (frontend + API) · Tishneet (AI + workflow) · Mariam (security + data) · Masha (product + QA)_

---

## 2 · The problem — why we built this

**Companies want to hand operations to AI agents. But an AI agent can take an action that is *allowed* and still *wrong*.**

- "Move 5 packages into Zone B" is within the agent's limit — but if B only has room for 2, it **overflows the warehouse.**
- Several individually-valid actions can be **invalid together.**
- The AI can be **manipulated** (a hidden instruction in an image) into proposing something harmful.
- The AI can be **wrong** — LLMs miscount, hallucinate, and don't track live state.

_Say: "The question isn't 'is the AI smart?' It's 'what happens when it's wrong — and it will be?' Operations can't run on 'usually safe.'"_

---

## 3 · The insight

### Model safety is bypassable. Action safety doesn't have to be.

> Content filters and refusals try to stop the AI from *saying* something bad.
> Someone always finds a prompt — or an image — that gets through.

**SentinelOS doesn't trust the AI at all.** It independently governs every **action** against real policy and real state — *before* anything commits.

**"AI proposes. The backend decides."**

---

## 4 · The solution

### SentinelOS = a preflight safety layer around any AI agent

The AI drafts a plan. Before it can touch reality, SentinelOS:

1. **Authorizes** every action (is this agent allowed?)
2. **Simulates** the whole plan against live state (would anything break?)
3. **Pauses for human approval** on risky plans
4. **Re-checks and commits once**, atomically — then audits everything

_Say: "Even a fully jailbroken AI can only ever *propose*. It can never *execute* something unsafe."_

---

## 5 · How it works (the pipeline)

```
You: "move 3 from A to C"
        │
        ▼
  AI drafts plan  ── Amazon Bedrock (Nova Pro)
        │
        ▼
  Authorize each action ── Verified Permissions (Cedar)
        │
        ▼
  Simulate full plan vs live state ── whole-plan simulator
        │
   unsafe? → AI replans (max 3 tries)
        │
   risky? → wait for human approval
        │
        ▼
  Re-check, commit once, atomically ── DynamoDB (version-checked)
        │
        ▼
  Audit every step
```

_Orchestrated by AWS Step Functions; served to the UI by API Gateway + Lambda._

---

## 6 · Live demo — the three scenarios

- **D1 · Safe move** — "move 3 from A to C" → authorized, simulated, **auto-executes** (A17/B8/C8).
- **D2 · The headline** — "move 5 out of A, prefer B" → first plan would make B 13/10 → **rejected** → AI **replans** (2→B, 3→C) → **needs approval** → approve → executes (A12/B10/C11).
- **D3 · Revocation** — revoke the agent → next action **denied** by the backend, inventory unchanged.
- **Finale · Image injection** — a shipping image with hidden text tells the AI to break the rules → the AI **obeys** → SentinelOS **blocks the action anyway.**

_All three validated end-to-end on real AWS._

---

## 7 · What we used — and why the project breaks without each

| We used | For | Without it… |
|---|---|---|
| **Amazon Bedrock (Nova Pro)** | The AI that turns language → a plan; reads the attack image (multimodal) | No AI agent at all — the entire "delegate to AI" premise collapses |
| **Amazon Verified Permissions + Cedar** | Independent, deterministic authorization per action | You'd be trusting the AI's own judgment — the exact failure we exist to prevent |
| **Whole-plan simulator** | Catches collectively-invalid plans before commit | The core insight (allowed-but-invalid) couldn't be caught; zones overflow |
| **AWS Step Functions** | Durable orchestration of the multi-step pipeline + human-approval wait (`waitForTaskToken`) | Approval-wait and re-checks would be fragile/in-memory and lost on any failure |
| **DynamoDB (conditional writes)** | Source-of-truth state + atomic, version-checked, idempotent commit | Race conditions, double-execution, stale writes — no safe commit |
| **Secrets Manager (signed assertions)** | Cryptographic admin auth for approve/revoke/reset | Admin actions could be forged; "human approval" would be meaningless |
| **Lambda + API Gateway** | Serverless trusted boundary between UI and backend | Secrets land in the browser (insecure) or you run servers (overkill) |
| **Amplify Hosting** | Public, deployed operator UI | No accessible product — "a working localhost isn't enough" |
| **React / Vite UI** | Makes the safety visible: projected vs committed, reason text, approval | The guardrails would be invisible — the value is in *seeing* the decisions |
| **IAM (least-privilege)** | Scopes the API role to exactly what it needs | The safety layer itself becomes an attack surface |

---

## 8 · Why this architecture (the design principles)

- **AI proposes; backend decides** — the AI never writes real state.
- **The model cannot certify its own output** — authorization + simulation are independent of the AI.
- **An allowed action can still be collectively invalid** — so we authorize *every* action *and* simulate the *whole* plan.
- **Re-authorize and re-simulate at execution** — with an atomic, idempotent commit, so stale approvals and races can't cause damage.
- **No secrets in the browser** — credentials and approval tokens stay server-side.

---

## 9 · Defense in depth

Content filters are **one layer** — and a bypassable one. SentinelOS is the layer underneath:

- **Per-action authorization** (Verified Permissions)
- **Whole-plan simulation** against live state
- **Risk-based human approval**, bound to one plan + one state
- **Execution-time re-check** + **one-time atomic commit**
- **Full audit trail**

_Say: "Bedrock Guardrails asks 'is this text safe to say?' We ask 'is this action safe to take, given the world right now?'"_

---

## 10 · What's real vs. what's next (honesty slide)

**Real and deployed on AWS (us-east-1):**
- Real Nova Pro planning + replanning · Verified Permissions authorization · whole-plan simulation · atomic version-checked commit to DynamoDB · Step Functions orchestration + approval · signed admin auth · deployed API + hosted UI. All 3 demos validated end-to-end.

**Honest limitations / next:**
- One warehouse, one agent, one operation (move packages) — by design for the demo.
- The judged walkthrough uses a labeled, deterministic path for reliability; the live AI stack is real underneath.
- Next: multi-warehouse, multiple agents, more operations, and a production auth provider.

---

## 11 · The build (process)

- **Froze one contract first** — shared JSON shapes for plans, status, auth, errors — so four people could build in parallel without stepping on each other.
- **Mock-first frontend** — a full in-browser simulation of the backend, so the UI was demo-ready before any AWS existed, then swapped to the real services with no UI changes.
- **Independent ownership, clean seams** — frontend/API (Ishani), AI/workflow (Tishneet), security/data (Mariam), product/QA (Masha); each owned disjoint modules and integrated through the frozen contract.
- **Continuous integration watch** — every teammate push was checked against the contract and tested before merge.

---

## 12 · Impact / close

### SentinelOS makes it safe for an AI agent to be wrong.

- The shift: from "make the AI never fail" (impossible) → "make failure harmless."
- Governs **actions, not words** — so it holds even when the AI is jailbroken.
- Built entirely on AWS serverless + GenAI, deployed and demonstrable today.

**"We jailbroke our own AI with a picture — and it still couldn't do any damage."**

---

## Appendix · Q&A prep

- **"Why would the AI overfill in the first place?"** — It reasons locally ("5 is within my limit, user prefers B") without computing B's live remaining space; it can also be fed stale state, manipulated, or simply miscount. We can't *guarantee* it won't — so we put a deterministic firewall around it.
- **"Isn't this just a content filter / Bedrock Guardrails?"** — No. A filter tries to catch bad *text*; it's bypassable. We judge the *action* against real state, so it works even when the filter is bypassed. They're complementary layers.
- **"How do you stop a stale approval from executing?"** — The approval is bound to a plan fingerprint + warehouse version; at execution we re-authorize, re-simulate, and commit with a version condition. If anything changed, it fails closed with VERSION_CONFLICT and writes nothing.
