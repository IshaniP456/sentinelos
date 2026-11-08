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

## D2 — large move → safe split → human approval → execute (the core story)

**Instruction:** `Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary.`

**What happens:** Zone B can't take all five (room for 2). The agent plans a
**safe split** that respects every zone's capacity, and because it's a large
move (≥5 packages) it **pauses for your approval** before committing.

> Note on the live model: real Nova usually proposes the safe split directly
> (it self-corrects), so you may not see a visible "rejected first attempt" —
> that dramatic reject-then-replan is shown deterministically in **mock mode**.
> On live, the guardrail you *see* is the **approval gate**.

**Click:** "Big move" preset → **Submit** → an **approval modal** appears →
click **Approve** → watch the workflow steps finish green.

**Expected end state:** commit lands, **version 1 → 2** (verified live,
`plan-d5267916045a44f4b4a26d13b4e1eb69`: approve → COMPLETED, A 15 · B 10 · C 8;
re-approving the same plan is a no-op — no double-execute).

**Fallback line:** *"The agent wanted to overfill a zone; SentinelOS made it
plan a safe split and held it for a human to sign off before anything moved."*

---

## D2b (bonus) — hard block: the guardrail refuses

**Instruction:** `Move five packages from Zone A to Zone B.` (the "Over capacity" preset)

**What happens:** the agent proposes putting all 5 into Zone B. Authorization
*allows* it (policy-wise it's fine), but the **whole-plan simulation refuses**:
Zone B would reach **13 / 10**. With the instruction pinned to B there's no safe
alternative, so the plan is **blocked and nothing moves** — the warehouse is
untouched.

**What you'll see:** in "What the AI proposed," the candidate shows **✗ Would
break a zone**, Authorization ✓, and the simulation violation *"Zone B would
reach 13 / 10."* The workflow panel shows Authorization ✓ → Simulation ✗.

**Fallback line:** *"Here the agent couldn't be saved — the only move it was
told to make was unsafe, so SentinelOS simply refused. Nothing moved."*

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
