# SentinelOS — Product Requirements Document

**Version:** 1.0 · **Status:** Draft for team approval · **Date:** November 7, 2026
**Delivery:** AWS × A10 hackathon, November 7–8, 2026
**Owners:** Masha — product and QA; Tishneet — AI and workflow; Mariam — security and inventory integrity; Ishani — user experience and public interface.

SentinelOS helps an operator turn a natural-language inventory request into an authorized, simulated, and traceable action. The first release must demonstrate that an individually permitted action can still produce an invalid warehouse outcome, and that the system prevents that outcome before changing inventory.

Requirements below preserve the integration contract's product rules. Items marked **Proposed** are additions for team review. All targets are release goals, not measured results. Approval remains pending.

## 1 Executive summary

SentinelOS is a controlled execution product for AI-generated warehouse plans. An operator describes a desired package movement; the product generates a candidate, checks each action's permissions, and simulates the complete ordered plan. A valid low-risk plan executes automatically. A valid elevated-risk plan requires an administrator's approval. An unsafe plan is blocked, and the AI may propose an alternative only when the operator's goal permits it.

The hackathon release covers one demonstration warehouse, three inventory zones, one inventory agent, and one operation: moving packages. Success means completing the three agreed demonstrations with exact inventory results, showing why rejected plans were blocked, and proving that stale approvals, revoked permissions, and repeated requests cannot produce unauthorized or duplicate changes.

The main value proposition is safe delegation with visible evidence: operators can see the proposal, the permission decision, the projected effect, the approval decision when required, and the actual committed result.

## 2 Problem statement and opportunity

An AI can produce an action that is permitted by policy but invalid in the current operating state. For example, moving five packages into Zone B meets the agent's per-action transfer limit, but exceeds B's remaining capacity. Several individually valid actions can also become invalid when evaluated together or in sequence.

Operators therefore need more than a plausible AI answer. They need confidence that the full plan respects inventory constraints, preserves their intent, remains authorized at execution time, and leaves an explainable record.

The initial opportunity is to demonstrate these controls in a bounded warehouse workflow. Broader demand, willingness to pay, and measurable labor savings remain hypotheses for later validation.

**Positioning hypothesis:** SentinelOS combines action-level authorization, whole-plan simulation, human approval, and execution traceability in one operator experience. Competitive superiority and market size are not established by this release.

## 3 Target users and core journeys

| Persona | Primary need | Successful outcome |
|---|---|---|
| Inventory operator | Delegate a package movement without manually checking every consequence | The requested goal is completed safely or receives a clear, actionable rejection |
| Operations administrator | Control elevated-risk actions and revoke an agent's authority | Only current, valid, explicitly approved plans execute when approval is required |
| Product reviewer or hackathon judge | Understand and verify the safety claims | Can trace a real request through decisions to exact before-and-after inventory |
| QA owner | Reproduce normal and failure scenarios | Can reset safely, run known cases, and inspect the resulting evidence |

The inventory agent is the acting system identity; it is distinct from the human operator and administrator.

- **Journey A — Routine transfer:** The operator submits "Move three packages from Zone A to Zone C." SentinelOS validates, authorizes, and simulates the plan, determines that approval is unnecessary, rechecks current conditions, and commits the transfer.
- **Journey B — Unsafe preference with an allowed alternative:** The operator requests moving five packages out of A, preferably to B, while permitting another destination. SentinelOS blocks a capacity-violating candidate, explains the violation, proposes a valid alternative, and obtains approval before execution.
- **Journey C — Revocation:** An administrator revokes the agent. A subsequent request, or a previously prepared plan that has not yet executed, is blocked at the next authorization check.
- **Journey D — State changes while waiting:** Another successful plan changes inventory while approval is pending. The old approval cannot authorize execution against the new state; the operator receives a clear re-evaluation outcome.

## 4 Product vision and goals

**Vision:** Make AI-assisted operational changes inspectable and controllable before they affect real state.

| Goal | Required product behavior | Evidence |
|---|---|---|
| Prevent invalid inventory changes | Evaluate every intermediate step of the entire plan before commit | Safety test results and rejected counterfactuals |
| Preserve operator intent | Retain hard constraints when proposing alternatives | Original request and each candidate visible together |
| Keep authority current | Recheck permissions and approval validity immediately before execution | Revocation and stale-approval tests |
| Balance autonomy with oversight | Auto-execute valid low-risk plans; require approval for valid elevated-risk plans | Demonstrations on both sides of the risk threshold |
| Make outcomes explainable | Show decisions, reasons, revisions, and actual inventory changes | Complete per-plan history and recent activity |
| Deliver a reproducible demo | Use fixed seed data and a safe reset | Repeatable expected-state walkthrough |

Commercial outcomes for later discovery: time saved per inventory request, operator trust, adoption frequency, and willingness to pay. Baselines and targets require user research.

## 5 Release scope and product rules

### Scope

- **P0 — Required for the complete hackathon release:** request submission; AI planning; independent validation; per-action authorization; sequential simulation; bounded replanning; deterministic risk classification; administrator approval; execution-time rechecks; safe inventory commit; revocation; audit history; status dashboard; controlled reset.
- **P1 — Add after P0 works:** a clearly labeled preflight test preset to reliably show a capacity rejection, clearer visual before-and-after comparisons, and presentation polish.
- **Future scope:** multiple warehouses, multiple acting agents, additional operation types, configurable business policies, enterprise administration, and production reliability commitments.

The MVP operates on aggregate package counts. SKU-level tracking, physical robot control, purchasing, shipment routing, and automatic policy changes are outside this release.

### Fixed demonstration model

| Zone | Starting inventory | Capacity |
|---|---|---|
| A | 20 | 30 |
| B | 8 | 10 |
| C | 5 | 20 |

The starting warehouse version is 1 and total inventory is 33 packages. HAZMAT is a reserved, restricted destination, not a normal inventory zone.

The acting agent is `inventory-agent-01`, initially ACTIVE, with the INVENTORY_MANAGER role and a maximum of 10 packages per action.

### Binding business rules

1. A candidate contains 1–10 ordered package-movement actions.
2. Each action identifies a distinct source and destination and a positive integer quantity. Zero, negative, fractional, and boolean quantities are invalid.
3. A quantity above 10 is structurally valid but is denied by policy. The 10-package ceiling applies to each action; the source does not define a 10-package ceiling for the whole plan.
4. Every action must be authorized. Any denied action rejects the entire candidate and request; the AI must not replan to evade that denial.
5. Every intermediate state must have nonnegative inventory and remain within each zone's capacity. Total inventory must remain 33 throughout these transfer-only demonstrations.
6. The maximum is three AI candidates per request, including the initial candidate.
7. Risk uses the sum of all action quantities, not net inventory movement or unique packages: totals 1–4 are LOW; totals of 5 or more are ELEVATED.
8. Only a plan that has already passed authorization and simulation can request approval.
9. Approval applies to one exact candidate revision and warehouse state. A plan revision or inventory-state change invalidates it.
10. Failed checks, rejected or expired approvals, and unsuccessful commits must leave actual inventory unchanged.

## 6 Detailed functional requirements

All requirements in this section are P0 unless marked P1. Acceptance criteria define the required behavior; completion must be demonstrated through QA.

### FR01 Submit an inventory goal
*Owner: Ishani; support: Tishneet.*

The operator must be able to enter a natural-language movement request and receive a trackable plan reference.

**Acceptance criteria:** Blank or unusable input returns a clear error without changing inventory. A valid submission displays the original instruction and planning status. The product determines the acting agent from trusted identity; the operator cannot substitute another agent or supply approval or execution authority.

### FR02 Generate and independently validate a candidate
*Owner: Tishneet; reviewer: Mariam.*

AI output must be checked independently before it can proceed to authorization.

**Acceptance criteria:** Only the supported movement operation and its source, destination, and quantity are accepted; unexpected action attributes are rejected. A candidate with no actions, more than 10 actions, identical source and destination, invalid zone-label form, or an invalid quantity cannot proceed. AI-generated claims about identity, authorization, approval, or execution have no authority. Validated actions remain unchanged within that revision.

**Proposed failure disposition:** Invalid AI output ends the request as FAILED with an explanation. Automatic repair of malformed output requires an explicit team decision and must count toward the three-candidate maximum.

### FR03 Authorize every action
*Owner: Mariam.*

Each action must be evaluated using current trusted agent status and the applicable policy.

**Acceptance criteria:** An ACTIVE agent may move up to 10 packages per action to an unrestricted destination. REVOKED agents, SUSPENDED agents if supported, quantities above 10, and HAZMAT destinations are denied. Missing authorization data or an authorization-service error denies execution. One denial blocks the whole plan, produces an action-specific reason, and does not trigger a bypass-oriented replan.

### FR04 Simulate the complete ordered plan
*Owner: Mariam.*

The product must calculate the consequences of the full sequence without changing actual inventory.

**Acceptance criteria:** Each step uses the preceding step's projected state. Unknown zones, insufficient source inventory, restricted destinations, and capacity violations are identified. Any intermediate violation fails the candidate, even if a later action would restore a valid final state. Failure details identify the action, zone, rule, and projected versus permitted quantity where applicable. Counterfactual inventory is visibly distinguished from committed inventory.

### FR05 Replan within the operator's intent
*Owner: Tishneet; reviewer: Masha.*

After a simulation failure, the AI may propose a revised candidate when an alternative is compatible with the original request.

**Acceptance criteria:** The new candidate uses the original instruction and failure details, receives a new revision, and passes validation, authorization, and simulation again. All candidates remain inspectable. No fourth candidate is generated. A request that explicitly requires destination B cannot silently redirect packages to C. If no permitted alternative exists or the candidate limit is reached, the workflow stops with a reason and no inventory change.

### FR06 Classify plan risk
*Owner: Tishneet.*

Risk must be determined consistently from the complete valid candidate.

**Acceptance criteria:** A total of 4 moved packages requires no approval; a total of 5 requires approval. A split of 2 packages to B and 3 to C requires approval. Moving the same packages in successive actions counts every movement. Failed authorization or simulation never produces an approval-eligible plan.

### FR07 Obtain an administrator decision
*Owners: Tishneet and Mariam; UI: Ishani.*

An authorized administrator must be able to approve or deny a valid elevated-risk candidate.

**Acceptance criteria:** The decision view includes the original instruction, exact revision, actions, relevant warehouse version, projected inventory, risk, and validation results. The product records decision identity and time. Denial prevents execution. No decision before the configured deadline causes expiry and prevents execution. Repeated decisions cannot trigger multiple executions. Only an authorized administrator can decide.

**Proposed timeout:** 10 minutes for the demo; confirm before approval-flow acceptance.

### FR08 Invalidate stale approval and recheck execution eligibility
*Owners: Mariam and Tishneet.*

Immediately before execution, SentinelOS must reauthorize the agent, confirm the approved candidate and relevant state are unchanged, and resimulate against current inventory.

**Acceptance criteria:** Revocation after planning or approval blocks execution. A revised candidate requires its own checks and approval when elevated risk applies. A warehouse-state change prevents use of the old approval even if the plan would still fit. A change between the final checks and commit also prevents a stale write. No previous approval is carried forward to a new state.

**Proposed MVP recovery:** End a conflicting request as FAILED with a VERSION_CONFLICT reason and offer a fresh evaluation. Automatic recovery remains an open decision.

### FR09 Apply inventory changes once and completely
*Owner: Mariam.*

Only the controlled workflow may commit a validated plan.

**Acceptance criteria:** All transfers in a successful plan take effect together, with one warehouse-version increment. Failure applies none of them. Repeated execution of the same plan revision returns its prior outcome or "already executed" and changes neither inventory nor version again. The browser cannot invoke an unrestricted execution operation.

### FR10 Revoke an agent
*Owner: Mariam; UI: Ishani.*

An authorized administrator must be able to revoke the current inventory agent and see the resulting status.

**Acceptance criteria:** A subsequent authorization check denies the revoked agent. Pending, unexecuted plans are subject to the same current-status check. Revocation does not reverse already completed transfers. Ordinary operators cannot revoke agents.

### FR11 Display progress and committed outcomes
*Owner: Ishani; workflow support: Tishneet.*

The operator must be able to follow a request through planning, checks, replanning, approval, execution, and its terminal outcome.

**Acceptance criteria:** Progress updates approximately every two seconds while active. The UI shows the current attempt and relevant decision details. Candidate projections appear separately from actual inventory. After completion, the warehouse display refreshes to the committed result. Denied, failed, and expired plans remain available with explanations. A connection error does not falsely display success.

### FR12 Provide an audit history
*Owner: Mariam; workflow support: Tishneet; UI: Ishani.*

Reviewers must be able to inspect the decisions and state changes associated with a plan, as well as recent events across plans.

**Acceptance criteria:** Events identify the plan, candidate revision, timestamp, event type, outcome, and reason; approval events identify the deciding administrator. The history covers candidate generation, validation, authorization, simulation, replanning, approval, execution checks, and final outcome. Events can be ordered consistently. Secrets and credentials are excluded from operator-visible history.

### FR13 Reset the demonstration safely
*Owner: Mariam; QA: Masha.*

An authorized administrator must be able to restore the agreed seed warehouse and demonstration agent for a new walkthrough.

**Acceptance criteria:** Reset is blocked while any workflow is active or awaiting approval. A completed reset restores A=20, B=8, C=5, version=1, and the demo agent to ACTIVE. Old approvals and prior plan references cannot cause execution against the reset state.

**Proposed reset-history rule:** Retain the previous run's evidence and clearly separate it from the new run. Resetting the agent and handling prior runs require confirmation in the decision register.

### FR14 Provide a labeled preflight example
*Priority: P1; owners: Masha and Ishani; support: Tishneet and Mariam.*

A reviewer may run a preset that demonstrates the invalid A-to-B transfer even when the AI initially proposes a valid split.

**Acceptance criteria:** The UI labels the initial candidate as a scripted preflight test. Its failed simulation does not change inventory. Any subsequent AI replan uses the real model or is explicitly labeled otherwise. The demonstration never presents the scripted candidate as an unexpected autonomous model mistake.

## 7 User experience requirements

The primary experience must make four things easy to distinguish: the user's goal, the current candidate, its projected outcome, and the actual warehouse state.

| Surface | Required information and actions |
|---|---|
| Request entry | Instruction field, submit action, validation feedback, acting agent status |
| Warehouse overview | Inventory and capacity for A, B, and C; current version; committed-state label |
| Plan detail | Original instruction, revision and attempt, ordered actions, per-action decisions, simulation violations |
| Approval view | Exact plan and state under review, risk and total movement, administrator approve and deny actions |
| Activity history | Chronological outcomes and reasons for the selected plan; recent cross-plan events |
| Administration | Agent revocation and safe reset, available only to authorized administrators |

Errors must explain what happened and what the user can do next. For example: "Zone B would contain 13 packages, above its capacity of 10" or "Inventory changed after this plan was reviewed. Evaluate it again."

**Workflow vocabulary:** PLANNING, VALIDATING, AUTHORIZING, SIMULATING, REPLANNING, AWAITING_APPROVAL, REAUTHORIZING, REVALIDATING, EXECUTING, COMPLETED, REJECTED, FAILED, and EXPIRED.

| Terminal outcome | Operator meaning |
|---|---|
| COMPLETED | Inventory changes were committed successfully |
| REJECTED | Policy or an administrator denied the requested execution |
| FAILED | Planning, validation, simulation, execution checks, or a service failure prevented completion |
| EXPIRED | Required approval was not received within its allowed window |

Specific failure-to-status mappings beyond the source's explicit rules are proposed and must be frozen at kickoff.

**Proposed usability acceptance:** Core controls work with a keyboard; statuses use text as well as color; the demo layout is readable on the presentation laptop; expired or invalidated approvals cannot still appear actionable.

## 8 Nonfunctional requirements

| ID and owner | Requirement | Acceptance evidence |
|---|---|---|
| NFR01 Security — Mariam | Enforce operator versus administrator permissions; keep credentials and approval-control secrets out of the client; prevent AI output from granting authority | Unauthorized approval, revocation, reset, identity-substitution, and direct-execution attempts cause no state change |
| NFR02 Integrity — Mariam | Preserve total inventory, capacity limits, nonnegative counts, version correctness, and all-or-nothing execution | Sequential, stale-state, duplicate-execution, and competing-plan tests pass |
| NFR03 Durability — Tishneet and Mariam | Keep pending approvals, candidate identity, and prior execution outcomes available across refreshes and service restarts | Resume a pending plan and replay a completed request without losing binding or duplicating movement |
| NFR04 Failure handling — All engineers | Fail closed when authorization or required state is unavailable; expose a recoverable explanation where possible | Dependency-failure cases show no false success and no unsafe inventory change |
| NFR05 Responsiveness — Tishneet and Ishani | Refresh active status about every 2 seconds. Proposed: normal, single-candidate evaluation reaches a decision within 30 seconds at the 95th percentile, excluding human wait | Timestamped demo-environment measurements; proposed latency target requires team confirmation |
| NFR06 Supported scale — Mariam and Tishneet | Support one warehouse, one agent, up to 10 actions per candidate, and three candidates per request; competing plans cannot corrupt shared state | Maximum-size plan and two-competing-plan tests; no production throughput claim |
| NFR07 Traceability — Mariam and Masha | Make plan outcomes and their reasons retrievable without exposing secrets | QA can reconstruct each judged scenario and failed execution attempt |
| NFR08 Operational readiness — All engineers | Provide a reproducible startup, reset, known deployed version, and documented limitations | Another team member can run the full walkthrough from the recorded release |

The demo uses synthetic inventory. Applicable production compliance obligations, retention periods, service availability commitments, and customer data requirements remain future discovery items. No certification or production SLA is claimed.

## 9 Success metrics and KPIs

| Metric | Definition | Release target | Owner |
|---|---|---|---|
| Core demo pass rate | Correctly completed scenarios divided by the three agreed scenarios | 3 of 3, with exact final counts and versions | Masha |
| Unsafe commit count | Commits caused by failed policy, simulation, approval, or stale-state checks | 0 in the defined QA suite | Mariam |
| Duplicate movement count | Extra inventory mutations after replaying a completed revision | 0 | Mariam |
| Approval enforcement | Elevated-risk executions with a valid current approval divided by all elevated-risk executions | 100% in tested flows | Tishneet and Mariam |
| Revocation enforcement | Denied attempts after revocation divided by tested post-revocation attempts | 100% | Mariam |
| Trace completeness | Test plans with all applicable decision and outcome evidence divided by all test plans | 100% | Masha |
| Candidate bound | Maximum number of AI candidates generated for one request | No more than 3 | Tishneet |
| Evaluation latency | Time from accepted request to the first eligible decision or failure, excluding administrator wait | Proposed p95 ≤30 seconds for a single candidate; record actual sample size | Tishneet |
| Presentation freshness | Delay between available workflow status and the next regular UI refresh | Approximately 2-second polling while active | Ishani |

**Proposed repeatability gate:** Three consecutive complete walkthroughs pass after controlled resets.

Record actual AI candidate counts and request costs where measurable. Any cost estimate must be labeled as an estimate. Replanning success outside the controlled demo is an observation to collect, not a validated reliability claim.

## 10 Acceptance scenarios and QA

### Judged walkthrough

Run these scenarios in order on the same warehouse state, starting at A=20, B=8, C=5, version=1.

| Scenario | Request and expected behavior | Required actual outcome |
|---|---|---|
| D1 Low-risk transfer | "Move three packages from Zone A to Zone C." Authorization and simulation pass; no approval required | A=17/30, B=8/10, C=8/20; version=2 |
| D2 Capacity rejection and approved alternative | "Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary." A→B ×5 would project B=13/10 and must fail simulation. A→B ×2 plus A→C ×3 passes and requires approval | Before approval: unchanged from D1. After approval: A=12/30, B=10/10, C=11/20; version=3 |
| D3 Revocation | Administrator revokes inventory-agent-01; a subsequent A→C ×1 request is denied | A=12/30, B=10/10, C=11/20; version remains 3 |

The AI may produce the valid D2 split immediately. Use the labeled P1 preflight preset when a guaranteed rejection demonstration is needed; keep the source of each candidate visible.

### Additional release tests

| Test | Required result | Requirement |
|---|---|---|
| Zero, negative, fractional, and boolean quantities | Validation fails; no authorization or execution | FR02 |
| Empty candidate, 11 actions, unsupported operation, or extra action attributes | Candidate rejected as invalid; inventory unchanged | FR02 |
| One action moves 11 packages | Validation accepts the quantity's integer form; authorization denies the action | FR02–03 |
| HAZMAT destination | Denied as restricted, not treated as an ordinary missing zone | FR03 |
| Unknown normal zone or insufficient source stock | Simulation fails with a specific reason | FR04 |
| Two transfers each fit B separately but exceed its capacity together | Sequential simulation fails the whole plan | FR04 |
| An intermediate step exceeds capacity but a later step would repair it | Candidate still fails | FR04 |
| A request explicitly requires destination B | No unauthorized redirection to C during replanning | FR05 |
| Three unsuccessful candidate evaluations | No fourth candidate and no commit | FR05 |
| Totals of 4 and 5, including split actions | Respect the approval threshold exactly | FR06 |
| Denied or timed-out approval | No movement; clear terminal outcome | FR07 |
| Agent revoked after approval but before execution | Final authorization blocks the commit | FR08, FR10 |
| State changes after simulation or approval | Old evaluation and approval cannot commit | FR08 |
| Two plans compete for the same remaining capacity | At most the currently valid commit succeeds; the other cannot use stale state | FR08–09 |
| Completed plan execution is repeated | Counts and version do not change again | FR09 |
| Unauthorized administrator action or substituted agent | Request denied with no protected mutation | FR01, FR07, FR10, FR13 |
| Reset requested while a plan is active | Reset blocked | FR13 |
| Old plan or approval is replayed after reset | No execution against the new demo state | FR13 |
| Authorization service unavailable or trusted attributes missing | Execution denied | FR03, NFR04 |
| Refresh or restart while approval is pending | Plan binding and approval state remain recoverable | NFR03 |

Masha records expected versus observed results, the tested release, pass or fail, and any limitation. A release target is not marked passed without observed evidence.

## 11 Delivery plan and responsibilities

The source schedule is retained below. **Planning assumption:** event times are local to America/Los_Angeles; confirm with the team. The 12:30 AM freeze falls on Sunday, November 8, not Saturday.

| Milestone | Date and time | Accountable owner | Acceptance deliverable |
|---|---|---|---|
| Kickoff | Sat Nov 7, 11:00 AM | All | Authorized coding window begins; shared scope and ownership confirmed |
| Requirement freeze | Sat, 11:15 AM | All | Seed, business rules, status meanings, and blocking decisions agreed |
| Simulation ready | Sat, 1:00 PM | Mariam | Passing simulator tests, including cumulative invalidity |
| AI and UI foundations | Sat, 2:00 PM | Tishneet and Ishani | Validated AI candidates; local dashboard with clearly labeled sample data |
| Replanning integrated | Sat, 4:00 PM | Tishneet and Mariam | Real plan → simulation failure → permitted replan; stale-write protection verified |
| Authorization ready | Sat, 6:00 PM | Mariam | Live allow, deny, and revocation behavior; current warehouse available |
| Low-risk path complete | Sat, 8:30 PM | Tishneet and Ishani | End-to-end automatic execution with visible status and inventory result |
| Complete walkthrough ready | Sat, 11:00 PM | All engineers; Masha verifies | Approval flow, deployed experience, and known limitations documented |
| Feature freeze | Sun Nov 8, 12:30 AM | All | Stable release, reproducible reset, QA underway |
| Submission | Sun, 8:30 AM | Masha | Demonstration and submission materials match observed functionality |

All implementation, scaffolding, tests, and deployment code must be created within the event's authorized coding window. This PRD is planning documentation.

**Ownership:** Tishneet owns planning and orchestration; Mariam owns authorization, simulation, committed state, and revocation; Ishani owns the operator/admin interface; Masha owns business narrative, acceptance evidence, and submission readiness. Cross-functional decisions require agreement from affected owners.

### Delivery choices

| Choice | Benefit | Limitation | Recommendation |
|---|---|---|---|
| Full controlled execution demo | Demonstrates the complete product promise | Greatest integration effort | Target this release and prioritize P0 flows |
| Simulation-only fallback | Preserves AI planning, rejection, replanning, and visible projections | Does not demonstrate real inventory execution | Use if safe execution cannot be completed; label it clearly |
| Simpler trusted approval experience | Can reduce workflow integration effort | Requires explicit evidence that identity, expiry, and plan binding still work | Accept only if all approval acceptance criteria still pass |
| Additional UI polish | Improves presentation | Does not close correctness gaps | Start after the end-to-end path and safety tests pass |

**Release boundary:** If safe execution or required approval controls are incomplete, disable actual inventory writes for the fallback. Reduced implementation complexity must not weaken the product's mandatory execution rules.

## 12 Dependencies, constraints, and open decisions

### Dependencies and constraints

- Access to the AI service and authorization capabilities needed for the judged experience.
- A trusted administrator identity and an agreed operator-access mechanism.
- Reliable access to current inventory, agent status, pending approvals, and prior execution outcomes.
- A common interpretation of actions, revisions, workflow states, errors, and test fixtures across the team.
- An accessible demo environment, a recorded release, and a repeatable reset.
- A short hackathon delivery window; infrastructure choices must support the product acceptance criteria.
- An external engineering specification for service selection, data structures, interfaces, and deployment details.

AWS Bedrock, Verified Permissions, and the other AWS services named in the integration contract are project dependencies and engineering choices. Their interfaces, storage schemas, and deployment configuration belong in the technical specification.

### Decisions to close

| Decision | Recommendation or current constraint | Owner | Due |
|---|---|---|---|
| Administrator and operator authentication | Use real enforced identities with administrator-only approval, revocation, and reset | Mariam and Ishani | Kickoff |
| Approval duration | Proposed: 10 minutes; show expiry to the administrator | Masha and Tishneet | Before approval acceptance |
| Malformed AI output | Proposed: fail clearly; any repair attempt counts toward the three-candidate limit | Tishneet and Mariam | Requirement freeze |
| Stale-state recovery | Proposed: fail safely and start a fresh evaluation; require fresh elevated-risk approval | Tishneet and Mariam | Before execution integration |
| Hard versus flexible operator constraints | Preserve explicit constraints; reject or request clarification when an alternative would change intent | Masha and Tishneet | Before replanning acceptance |
| Reset and historical evidence | Block active workflows; restore agent and seed; isolate previous plans and preserve labeled evidence | Mariam and Masha | Before walkthrough |
| Aggregate transfer policy | Retain the source's per-action limit of 10; confirm that no separate per-request ceiling is intended | Mariam and Masha | Requirement freeze |
| Performance and repeatability targets | Confirm proposed latency target and three consecutive walkthroughs | All | Before feature freeze |
| Service availability and operating cost | Confirm accessible model and services in one Region; assign a budget and measure actual usage | Tishneet and Mariam | Kickoff |
| Detailed terminal-status mapping | Freeze mappings for validation, exhaustion, conflict, denial, and timeout | Tishneet and Ishani | Requirement freeze |
| Schedule timezone | Confirm America/Los_Angeles assumption and event deadlines | Masha | Kickoff |

No decision in this register is treated as approved merely because a recommendation is present.

## 13 Assumptions and risks

| Risk or assumption | Product consequence | Response and owner |
|---|---|---|
| AI may produce a valid split immediately | The planned rejection moment is not guaranteed | Labeled preflight preset; Tishneet and Masha |
| AI may change the operator's goal while repairing a plan | A technically valid result may still be wrong for the user | Preserve hard constraints and test explicit-destination requests; Tishneet |
| Inventory changes during approval or execution | Prior simulation and approval become stale | Invalidate and re-evaluate; Mariam |
| Approval or execution state is lost or replayed | Unauthorized or duplicate movement becomes possible | Durable binding, execution replay protection, and restart tests; Tishneet and Mariam |
| Authorization integration or model access fails | Full judged flow may be unavailable | Verify access early; use the explicitly labeled simulation-only fallback if necessary; Tishneet and Mariam |
| Team members interpret shared states differently | UI may misrepresent eligibility or completion | Freeze meanings and verify handoffs against acceptance scenarios; Ishani |
| Numerical examples are mixed across different starting states | Demonstration evidence becomes misleading | Use the sequential D1–D3 state table as the canonical walkthrough; Masha |
| Reset reuses seed version 1 | Old approvals may appear to match the new warehouse version | Ensure previous-run references cannot execute after reset; Mariam |
| Product demand and operator value are unvalidated | Hackathon success may not establish commercial viability | Conduct operator interviews and baseline task measurement after the event; Masha |
| Timeline and latency targets prove unrealistic | Safety work may be crowded out by presentation work | Reduce scope through the documented fallback; all owners |

## 14 Release criteria

The complete MVP is ready only when:

- All P0 functional requirements and mandatory integrity/security requirements pass.
- D1, D2, and D3 produce the exact required counts and warehouse versions.
- Elevated-risk transfers require a valid current administrator approval.
- Revocation, stale state, duplicate requests, intermediate violations, and unsafe reset cases cannot cause an invalid commit.
- The UI and audit history show actual outcomes and distinguish projections, scripted tests, and mocks.
- Blocking decisions are resolved; accepted limitations are recorded.
- A stable release, accessible demo, reset procedure, and test evidence are available.
- Each accountable owner signs off on their area and Masha confirms demo readiness.

**Proposed additional gate:** Three consecutive complete walkthroughs pass from controlled resets.

A simulation-only fallback must be described and judged as such. It does not satisfy the complete MVP's real-execution criteria.

## 15 Future considerations

After validating the MVP, prioritize discovery around operator workflow fit and measurable value before expanding the platform.

Potential extensions include multiple warehouses and agents; additional inventory operations; configurable approval thresholds and aggregate transfer limits; richer simulation constraints; notifications and escalation for pending approvals; audit export and retention controls; enterprise access management; and production availability and performance commitments.

Each extension requires its own user need, success measure, authorization boundaries, and acceptance criteria. Changes to risk or approval policy must remain explicitly governed.

## 16 Approval

| Approver | Area | Approval status | Date |
|---|---|---|---|
| Masha | Product scope, demo narrative, QA, and submission readiness | Pending | — |
| Tishneet | AI behavior, candidate limits, orchestration, and approval lifecycle | Pending | — |
| Mariam | Policy, simulation, inventory integrity, and security | Pending | — |
| Ishani | Operator/admin experience, status meanings, and error handling | Pending | — |

Approval confirms the agreed scope and resolved decisions. Subsequent changes affecting requirements, business rules, or acceptance criteria require review by the affected owners.

*Source reference: SentinelOS Team Integration Contract in Pasted markdown.md, version 1.0. The integration contract remains the companion engineering reference.*
