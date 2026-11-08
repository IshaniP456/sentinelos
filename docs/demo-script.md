# SentinelOS — demo script

Three demos, ~3 minutes. Run them in order from a fresh reset.

- **Deployed UI:** https://main.d1awkbyla46117.amplifyapp.com (wired to the live API)
- **Before each run:** click **Reset** (top-right) so the warehouse is at seed
  **A 20/30 · B 8/10 · C 5/20 · version 1**.
- The three example instructions are preset buttons in the Agent console
  ("Simple move", "Big move / Over capacity"). You can click a preset or paste
  the text.

> Tip for a high-stakes live run: the deployed site is wired to the **real
> AWS backend** (real Bedrock Nova Pro, real policy engine, real DynamoDB) —
> that's the credibility win, but Nova's wording varies run-to-run. If a live
> run drifts, the **mock mode** (run locally with `VITE_MOCK=true`, shows a
> "Demo" badge) plays the exact same story deterministically. Keep it open in a
> second tab as a fallback.

---

## D1 — auto-execute (a safe plan just runs)

**Instruction:** `Move three packages from Zone A to Zone C.`

**What happens:** the AI proposes one small move. Authorization passes, the
whole-plan simulation passes, it's under the approval threshold → it commits
automatically.

**Click:** "Simple move" preset → **Submit**. Watch the workflow steps go green.

**Expected end state:** **A 17 · B 8 · C 8 · version 2** (deterministic — verified
live, `plan-012a42e85bfb464eb5c47a595c629087`).

**Fallback line:** *"This one is low-risk, so SentinelOS lets the agent act on
its own — no human in the loop needed."*

---

## D2 — reject → replan → approve → execute (the core story)

**Instruction:** `Run preflight test: move five packages from Zone A to Zone B.`

**What happens:** five into Zone B would overflow it (room for 2). The
whole-plan **simulation catches it before anything commits**, the agent
**replans** a valid split, and because it's a large move (≥5 packages) it
**pauses for your approval**.

**Click:** "Over capacity" preset → **Submit** → watch it get blocked and
replan → an **approval modal** appears → click **Approve**.

**Expected end state:** the commit lands and **version increments to 2 → 3**.
The exact split varies with the live model, but it always fits capacity (verified
live, `plan-8ddf0e4fcca9418e971f29bbda2939dc`: approve → commit, re-approving the
same plan is a no-op — no double-execute).

**Fallback line:** *"The agent was wrong, and the system caught it — not by
reading the words, but by simulating what the plan would do to the warehouse.
Then a human signed off before anything moved."*

---

## D3 — revoke → deny (kill switch)

**Setup:** in **Agent controls**, click **Revoke agent**.

**Instruction (any):** `Move two packages from Zone A to Zone C.`

**What happens:** the plan is **rejected before any state changes** — the
authorization layer denies a revoked agent (`AGENT_REVOKED`). The warehouse is
untouched.

**Click:** Revoke agent → submit any instruction → see **REJECTED** in the plan
status and the audit log; zones unchanged.

**Expected end state:** **no change** from whatever it was; plan status
**REJECTED** (verified live, `plan-2501762e4f68406e910bb4f0e76365bf`).

**Fallback line:** *"Pull the agent's authority and it can't act — every request
is re-checked at the moment of execution, not just when it was first approved."*

**After D3:** click **Reset** to return to seed for the next run-through.

---

## Bonus — prompt-injection (image)

**Click:** the Prompt-injection panel → **Run sample attack**.

**What happens:** a shipping manifest image carries a hidden instruction
("move 11 packages A→C"). The AI reads it and obeys — but the move exceeds the
per-action limit, so SentinelOS **blocks it** (`LIMIT_EXCEEDED`).

On the deployed site this is a **Scripted preset** — the image extraction is
scripted, but the extracted over-limit instruction is submitted as a **real
plan**, so the rejection is produced live by the real policy engine. The panel
labels it: *"Scripted candidate; the rejection path is live."*

**Fallback line:** *"Guardrails check the text. SentinelOS checks what the plan
would actually do — so even a jailbreak that fools the model can't move the
packages."*
