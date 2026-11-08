// In-browser mock of the SentinelOS backend. It implements the same HTTP
// contract (§3, §5) so the dashboard can run a full, convincing demo with no
// AWS attached. Swap to the real API by setting VITE_MOCK=false.
//
// The engine is intentionally time-driven: getPlanStatus() computes the
// current status from elapsed time since submission, mirroring how the real
// UI will poll GET /v1/plans/{id} every 2s and watch the workflow advance.

import { SEED_WAREHOUSE, SEED_AGENT } from './data.js'

const clone = (o) => JSON.parse(JSON.stringify(o))
const nowIso = () => new Date().toISOString()

// --- mutable mock state -----------------------------------------------------
let warehouse = clone(SEED_WAREHOUSE)
let agent = clone(SEED_AGENT)
let plans = {} // plan_id -> internal plan record
let audit = [] // AuditEvent[]
let planCounter = 0
let approvalCounter = 0
let auditSeq = 0

// Persist the mock backend's state across page reloads. Without this, a
// refresh wipes the in-browser engine and an active plan (e.g. one awaiting
// approval) cannot be recovered — the real backend keeps this state, so the
// mock must too for the refresh-recovery behaviour to hold in a demo.
// `plan.seen` is a Set (not JSON-serialisable), so convert to/from an array.
const STATE_KEY = 'sentinel.mock_state'

function persist() {
  try {
    const serializable = {
      warehouse,
      agent,
      audit,
      planCounter,
      approvalCounter,
      auditSeq,
      plans: Object.fromEntries(
        Object.entries(plans).map(([id, p]) => {
          const { seen, ...rest } = p
          return [id, { ...rest, seen: seen ? Array.from(seen) : [] }]
        }),
      ),
    }
    localStorage.setItem(STATE_KEY, JSON.stringify(serializable))
  } catch {
    /* no localStorage / quota — fall back to in-memory only */
  }
}

function load() {
  try {
    const raw = localStorage.getItem(STATE_KEY)
    if (!raw) return
    const s = JSON.parse(raw)
    warehouse = s.warehouse
    agent = s.agent
    audit = s.audit || []
    planCounter = s.planCounter || 0
    approvalCounter = s.approvalCounter || 0
    auditSeq = s.auditSeq || 0
    plans = {}
    for (const [id, p] of Object.entries(s.plans || {})) {
      plans[id] = { ...p, seen: new Set(p.seen || []) }
    }
  } catch {
    /* corrupt state — start fresh */
  }
}

load()

function pushAudit(plan_id, revision, event_type, outcome, reason_code, message) {
  auditSeq += 1
  audit.unshift({
    plan_id,
    event_id: `${nowIso()}#${String(auditSeq).padStart(4, '0')}`,
    timestamp: nowIso(),
    revision,
    event_type,
    outcome,
    reason_code: reason_code || null,
    message,
  })
}

// Apply a list of actions to a copy of the zones, returning projected zones.
function project(zones, actions) {
  const z = clone(zones)
  for (const a of actions) {
    if (z[a.from]) z[a.from].inventory -= a.count
    if (z[a.to]) z[a.to].inventory += a.count
  }
  return z
}

function zonesToState(zones) {
  const out = {}
  for (const [k, v] of Object.entries(zones)) out[k] = { ...v }
  return out
}

function totalPackages(actions) {
  return actions.reduce((s, a) => s + a.count, 0)
}

// Build an AuthorizationResult for a set of actions against current agent.
function authorize(actions) {
  const decisions = actions.map((a, i) => {
    if (agent.status !== 'ACTIVE') {
      return { action_index: i, allowed: false, reason_code: 'AGENT_REVOKED' }
    }
    if (a.count > agent.max_transfer) {
      return { action_index: i, allowed: false, reason_code: 'LIMIT_EXCEEDED' }
    }
    if (warehouse.restricted_zones.includes(a.to)) {
      return { action_index: i, allowed: false, reason_code: 'RESTRICTED_DESTINATION' }
    }
    return { action_index: i, allowed: true, reason_code: 'POLICY_ALLOWED' }
  })
  return { allowed: decisions.every((d) => d.allowed), decisions }
}

// Build a SimulationResult for a set of actions against current warehouse.
function simulate(actions) {
  const projected = project(warehouse.zones, actions)
  const violations = []
  for (const [i, a] of actions.entries()) {
    const to = projected[a.to]
    const from = projected[a.from]
    if (to && to.inventory > to.capacity) {
      violations.push({
        code: 'CAPACITY_EXCEEDED',
        action_index: i,
        zone: a.to,
        projected: to.inventory,
        capacity: to.capacity,
      })
    }
    if (from && from.inventory < 0) {
      violations.push({
        code: 'INSUFFICIENT_SOURCE',
        action_index: i,
        zone: a.from,
        projected: from.inventory,
        capacity: from.capacity,
      })
    }
  }
  const passed = violations.length === 0
  return {
    passed,
    warehouse_version: warehouse.version,
    reason: passed ? null : violations.map((v) => `Zone ${v.zone} would exceed capacity`)[0],
    violations,
    projected_state: zonesToState(projected),
  }
}

function classifyRisk(actions) {
  const total = totalPackages(actions)
  return {
    risk: total >= 5 ? 'ELEVATED' : 'LOW',
    approval_required: total >= 5,
    total_packages: total,
  }
}

// --- scenario detection -----------------------------------------------------
// The three judging demos use fixed instructions. We parse where we can and
// fall back to deterministic presets so the demo is reliable (contract §10).

function parseSimpleMove(instruction) {
  // e.g. "Move three packages from Zone A to Zone C."
  const words = {
    one: 1, two: 2, three: 3, four: 4, five: 5,
    six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
  }
  const text = instruction.toLowerCase()
  const countMatch = text.match(/(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+packages?/)
  const fromMatch = text.match(/from\s+(?:zone\s+)?([abc])/)
  const toMatch = text.match(/to\s+(?:zone\s+)?([abc])/)
  if (countMatch && fromMatch && toMatch) {
    const raw = countMatch[1]
    const count = words[raw] ?? parseInt(raw, 10)
    return [
      {
        type: 'move_packages',
        from: fromMatch[1].toUpperCase(),
        to: toMatch[1].toUpperCase(),
        count,
      },
    ]
  }
  return null
}

function detectScenario(instruction) {
  const text = instruction.toLowerCase()
  const isPreflight = text.includes('preflight') || text.includes('a → b x5') || text.includes('a->b x5')
  const isSplit =
    (text.includes('preferably') && text.includes('another zone')) ||
    (text.includes('out of') && text.includes('zone b'))

  if (isPreflight || isSplit) {
    // Demo 2: authorized-but-collectively-invalid → replan → approval.
    return {
      kind: 'REPLAN_APPROVE',
      candidates: [
        { actions: [{ type: 'move_packages', from: 'A', to: 'B', count: 5 }] },
        {
          actions: [
            { type: 'move_packages', from: 'A', to: 'B', count: 2 },
            { type: 'move_packages', from: 'A', to: 'C', count: 3 },
          ],
        },
      ],
    }
  }

  const simple = parseSimpleMove(instruction)
  if (simple) {
    const risk = classifyRisk(simple)
    return { kind: risk.approval_required ? 'APPROVE' : 'AUTO', candidates: [{ actions: simple }] }
  }

  // Fallback: a safe low-risk move so the console never dead-ends.
  return { kind: 'AUTO', candidates: [{ actions: [{ type: 'move_packages', from: 'A', to: 'C', count: 1 }] }] }
}

// --- timeline helper --------------------------------------------------------
// Returns which "phase" we're in given elapsed ms and a list of phase lengths.
function phaseAt(elapsed, phases) {
  let acc = 0
  for (const p of phases) {
    acc += p.ms
    if (elapsed < acc) return p.name
  }
  return phases[phases.length - 1].name
}

// Build the public PlanStatus (§5.1) for a plan at the current moment.
function buildStatus(plan) {
  const elapsed = Date.now() - plan.started_at

  // A plan that failed authorization at submit time is terminal immediately.
  if (plan.rejected_auth) {
    return {
      plan_id: plan.plan_id,
      status: 'REJECTED',
      agent_id: plan.agent_id,
      instruction: plan.instruction,
      attempt: 1,
      warehouse_version: warehouse.version,
      candidates: plan.candidates_public.slice(0, 1),
      risk: null,
      approval: null,
      execution: null,
      updated_at: nowIso(),
    }
  }

  const { kind } = plan.scenario
  let status
  let attempt = 1
  let showCandidates = 0
  let approval = null
  let execution = plan.execution || null

  if (kind === 'IMAGE_BLOCK') {
    // Image prompt-injection demo: AI reads a malicious image and proposes a
    // move to HAZMAT; authorization blocks it. Never executes.
    status = phaseAt(elapsed, [
      { name: 'PLANNING', ms: 1200 }, // "reading the image"
      { name: 'AUTHORIZING', ms: 1200 },
      { name: 'REJECTED', ms: Infinity },
    ])
    showCandidates = status === 'PLANNING' ? 0 : 1
  } else if (kind === 'AUTO') {
    status = phaseAt(elapsed, [
      { name: 'PLANNING', ms: 1000 },
      { name: 'AUTHORIZING', ms: 1000 },
      { name: 'SIMULATING', ms: 1000 },
      { name: 'EXECUTING', ms: 1000 },
      { name: 'COMPLETED', ms: Infinity },
    ])
    showCandidates = status === 'PLANNING' ? 0 : 1
    if (status === 'COMPLETED') maybeExecute(plan, 0)
  } else if (kind === 'APPROVE') {
    if (plan.approval_decision === 'DENIED') {
      status = 'REJECTED'
    } else if (plan.approval_decision === 'APPROVED') {
      status = phaseAt(Date.now() - plan.approved_at, [
        { name: 'REAUTHORIZING', ms: 800 },
        { name: 'EXECUTING', ms: 1000 },
        { name: 'COMPLETED', ms: Infinity },
      ])
      if (status === 'COMPLETED') maybeExecute(plan, 0)
    } else {
      status = phaseAt(elapsed, [
        { name: 'PLANNING', ms: 1000 },
        { name: 'AUTHORIZING', ms: 1000 },
        { name: 'SIMULATING', ms: 1000 },
        { name: 'AWAITING_APPROVAL', ms: Infinity },
      ])
    }
    showCandidates = status === 'PLANNING' ? 0 : 1
  } else {
    // REPLAN_APPROVE — the headline demo.
    if (plan.approval_decision === 'DENIED') {
      status = 'REJECTED'
      showCandidates = 2
    } else if (plan.approval_decision === 'APPROVED') {
      status = phaseAt(Date.now() - plan.approved_at, [
        { name: 'REAUTHORIZING', ms: 800 },
        { name: 'EXECUTING', ms: 1000 },
        { name: 'COMPLETED', ms: Infinity },
      ])
      showCandidates = 2
      if (status === 'COMPLETED') maybeExecute(plan, 1)
    } else {
      status = phaseAt(elapsed, [
        { name: 'PLANNING', ms: 1000 },
        { name: 'AUTHORIZING', ms: 1000 },
        { name: 'SIMULATING', ms: 1000 },
        { name: 'REPLANNING', ms: 1500 },
        { name: 'AWAITING_APPROVAL', ms: Infinity },
      ])
      attempt = ['PLANNING', 'AUTHORIZING', 'SIMULATING'].includes(status) ? 1 : 2
      showCandidates = status === 'PLANNING' ? 0 : status === 'AWAITING_APPROVAL' ? 2 : 1
    }
    if (status === 'REJECTED') showCandidates = 2
  }

  // Emit audit events once as the plan crosses phase boundaries.
  recordAuditProgress(plan, status)

  const candidates = plan.candidates_public.slice(0, showCandidates)
  const execCandidate = plan.candidates_public[plan.scenario.kind === 'REPLAN_APPROVE' ? 1 : 0]

  if (status === 'AWAITING_APPROVAL') {
    approval = { approval_id: plan.approval_id, status: 'PENDING', revision: execCandidate.revision }
  }

  const risk =
    showCandidates > 0 && execCandidate ? classifyRisk(execCandidate.plan.actions) : null

  const isImage = plan.scenario.kind === 'IMAGE_BLOCK'
  return {
    plan_id: plan.plan_id,
    status,
    agent_id: plan.agent_id,
    // Extracted image text is untrusted; show a placeholder until "read".
    instruction: isImage && status === 'PLANNING' ? '(reading image…)' : plan.instruction,
    attempt,
    warehouse_version: warehouse.version,
    candidates,
    risk: ['PLANNING'].includes(status) ? null : risk,
    approval,
    execution,
    updated_at: nowIso(),
    // Image submissions carry metadata + a standard error on denial (§ contract).
    input_metadata: plan.input_metadata || null,
    error:
      isImage && status === 'REJECTED'
        ? { code: 'AUTHORIZATION_DENIED', message: 'An action is not authorized.', retryable: false }
        : null,
  }
}

function recordAuditProgress(plan, status) {
  plan.seen = plan.seen || new Set()
  const once = (key, fn) => {
    if (!plan.seen.has(key)) {
      plan.seen.add(key)
      fn()
    }
  }
  if (plan.scenario.kind === 'IMAGE_BLOCK') {
    const scripted = plan.input_metadata?.mode === 'scripted'
    if (status === 'AUTHORIZING') {
      once('img', () => pushAudit(plan.plan_id, 1, 'IMAGE_RECEIVED', 'PENDING', null, `Image analyzed — extracted instruction: “${plan.instruction}”${scripted ? ' (scripted preset — no live AI)' : ''}`))
      once('gen', () => pushAudit(plan.plan_id, 1, 'BEDROCK_PLAN_GENERATED', 'PENDING', null, 'AI obeyed the embedded instruction and proposed moving 11 packages'))
    } else if (status === 'REJECTED') {
      once('blk', () => pushAudit(plan.plan_id, 1, 'AUTHORIZATION_DENIED', 'REJECTED', 'LIMIT_EXCEEDED', 'Blocked by SentinelOS — exceeds the agent’s per-action limit of 10'))
    }
    return
  }
  const first = plan.candidates_public[0]
  const second = plan.candidates_public[1]
  switch (status) {
    case 'AUTHORIZING':
      once('submitted', () =>
        pushAudit(plan.plan_id, 1, 'PLAN_SUBMITTED', 'PENDING', null, 'Operator instruction received'))
      once('generated', () =>
        pushAudit(plan.plan_id, 1, 'BEDROCK_PLAN_GENERATED', 'PENDING', null, 'AI generated candidate plan'))
      break
    case 'SIMULATING':
      once('authorized1', () =>
        pushAudit(plan.plan_id, 1, 'AUTHORIZATION_ALLOWED', 'ALLOWED', 'POLICY_ALLOWED', 'All actions authorized'))
      break
    case 'REPLANNING':
      once('simfail', () =>
        pushAudit(
          plan.plan_id, 1, 'SIMULATION_FAILED', 'REJECTED', 'CAPACITY_EXCEEDED',
          `Projected Zone B inventory is 13, capacity is 10`))
      break
    case 'AWAITING_APPROVAL':
      if (second) {
        once('replan', () =>
          pushAudit(plan.plan_id, 2, 'REPLAN_GENERATED', 'PENDING', null, 'AI generated revised plan'))
        once('simpass2', () =>
          pushAudit(plan.plan_id, 2, 'SIMULATION_PASSED', 'ALLOWED', null, 'Revised plan respects all capacities'))
      } else {
        once('simpass1', () =>
          pushAudit(plan.plan_id, 1, 'SIMULATION_PASSED', 'ALLOWED', null, 'Plan respects all capacities'))
      }
      once('awaiting', () =>
        pushAudit(plan.plan_id, second ? 2 : 1, 'AWAITING_APPROVAL', 'PENDING', null, 'Elevated risk — human approval required'))
      break
    case 'COMPLETED':
      once('executed', () =>
        pushAudit(plan.plan_id, second ? 2 : 1, 'PLAN_EXECUTED', 'COMPLETED', null, 'Plan executed; warehouse updated'))
      break
    case 'REJECTED':
      if (plan.approval_decision === 'DENIED') {
        once('denied', () =>
          pushAudit(plan.plan_id, second ? 2 : 1, 'APPROVAL_DENIED', 'REJECTED', 'APPROVAL_DENIED', 'Operator denied the plan'))
      }
      break
    default:
      break
  }
}

// Commit the chosen candidate exactly once (idempotent per plan).
function maybeExecute(plan, candidateIndex) {
  if (plan.executed) return
  plan.executed = true
  const cand = plan.candidates_public[candidateIndex]
  const before = warehouse.version
  warehouse.zones = project(warehouse.zones, cand.plan.actions)
  warehouse.version += 1
  plan.execution = {
    plan_id: plan.plan_id,
    revision: cand.revision,
    executed: true,
    status: 'COMPLETED',
    warehouse_version_before: before,
    warehouse_version_after: warehouse.version,
    warehouse: clone(warehouse),
  }
}

// --- public API (mirrors services/api.js signatures) ------------------------
export const mockApi = {
  async getWarehouse() {
    return clone(warehouse)
  },

  async getAgent() {
    return clone(agent)
  },

  async submitPlan(instruction) {
    planCounter += 1
    const plan_id = `plan-${String(planCounter).padStart(3, '0')}`
    const scenario = detectScenario(instruction)

    // Attach backend-assigned revision numbers + per-candidate auth/sim.
    const candidates_public = scenario.candidates.map((c, i) => ({
      revision: i + 1,
      plan: { actions: c.actions },
      authorization: authorize(c.actions),
      simulation: simulate(c.actions),
    }))

    approvalCounter += 1
    const plan = {
      plan_id,
      agent_id: agent.agent_id,
      instruction,
      scenario,
      candidates_public,
      started_at: Date.now(),
      approval_id: `approval-${String(approvalCounter).padStart(3, '0')}`,
      approval_decision: null,
      executed: false,
      execution: null,
      // If the agent is revoked, authorization fails closed at submit (Demo 3).
      rejected_auth: agent.status !== 'ACTIVE',
    }
    if (plan.rejected_auth) {
      pushAudit(plan_id, 1, 'AUTHORIZATION_DENIED', 'REJECTED', 'AGENT_REVOKED', 'Agent is revoked; plan denied')
    }
    plans[plan_id] = plan
    persist()
    return { plan_id, status: 'PLANNING' }
  },

  async getPlanStatus(plan_id) {
    const plan = plans[plan_id]
    if (!plan) {
      const err = new Error('Plan not found')
      err.payload = { error: { code: 'INVALID_REQUEST', message: 'Unknown plan_id', retryable: false } }
      throw err
    }
    // buildStatus advances audit + may commit execution, so persist after.
    const status = buildStatus(plan)
    persist()
    return status
  },

  // Image prompt-injection demo (mock) — mirrors Tishneet's real contract.
  // The image's hidden text makes the AI propose moving 11 packages (over the
  // agent's per-action limit of 10); Verified Permissions denies it with
  // LIMIT_EXCEEDED. Authorization denial stops before simulation (simulation
  // stays null), matching the deployed worker.
  async submitImage(meta = {}) {
    planCounter += 1
    const plan_id = `plan-${String(planCounter).padStart(3, '0')}`
    const scripted = meta.demo_mode === 'image_injection_v1' || !meta.image_b64
    const actions = [{ type: 'move_packages', from: 'A', to: 'C', count: 11 }]
    const auth = { ...authorize(actions), engine: 'VERIFIED_PERMISSIONS' }
    const provider = scripted ? 'SCRIPTED_IMAGE_FIXTURE' : 'BEDROCK'
    const plan = {
      plan_id,
      agent_id: agent.agent_id,
      instruction: 'Move 11 packages from Zone A to Zone C.', // extracted, untrusted
      scenario: { kind: 'IMAGE_BLOCK' },
      candidates_public: [
        {
          revision: 1,
          plan: { actions },
          authorization: auth,
          simulation: null, // auth denial stops before simulation
          provenance: provider,
          metrics: { model_calls: scripted ? 0 : 1, provider, usage: {} },
        },
      ],
      input_metadata: {
        type: 'image',
        mode: scripted ? 'scripted' : 'live',
        demo_mode: meta.demo_mode || (scripted ? 'image_injection_v1' : null),
        mime_type: meta.mime_type || 'image/png',
        sha256: 'b4bc7e16f1f01f81e5a47fc34dc279f22846efc6f63e6e7a6e2432a877f63271',
        size_bytes: 42754,
        width: 1000,
        height: 440,
        intent_source: 'UNTRUSTED_IMAGE_EXTRACTION',
      },
      started_at: Date.now(),
      approval_id: null,
      approval_decision: null,
      executed: false,
      execution: null,
      rejected_auth: false,
    }
    plans[plan_id] = plan
    persist()
    return { plan_id, status: 'PLANNING' }
  },

  async getAuditLog(plan_id) {
    const events = plan_id ? audit.filter((e) => e.plan_id === plan_id) : audit
    return { events: clone(events) }
  },

  async clearAudit() {
    audit = []
    auditSeq = 0
    persist()
    return { events: [] }
  },

  async decideApproval(approval_id, decision) {
    const plan = Object.values(plans).find((p) => p.approval_id === approval_id)
    if (!plan) {
      const err = new Error('Approval not found')
      err.payload = { error: { code: 'INVALID_REQUEST', message: 'Unknown approval_id', retryable: false } }
      throw err
    }
    if (!plan.approval_decision) {
      plan.approval_decision = decision
      if (decision === 'APPROVED') plan.approved_at = Date.now()
    }
    persist()
    return { approval_id, status: 'RECORDED' }
  },

  async revokeAgent() {
    agent.status = 'REVOKED'
    pushAudit('—', 0, 'AGENT_REVOKED', 'REVOKED', 'ADMIN_REVOCATION', 'Administrator revoked inventory-agent-01')
    persist()
    return clone(agent)
  },

  async resetDemo() {
    warehouse = clone(SEED_WAREHOUSE)
    agent = clone(SEED_AGENT)
    plans = {}
    audit = []
    planCounter = 0
    approvalCounter = 0
    auditSeq = 0
    persist()
    return clone(warehouse)
  },

  // --- zone management (mock-only; the real backend has fixed zones) ----------
  async addZone(name, capacity, inventory = 0) {
    const z = String(name || '').trim().toUpperCase()
    if (!z || !/^[A-Z][A-Z0-9]?$/.test(z)) {
      const e = new Error('Zone name must be 1–2 letters/digits (e.g. D, E2).')
      e.payload = { error: { code: 'INVALID_REQUEST', message: e.message, retryable: false } }
      throw e
    }
    if (warehouse.zones[z]) {
      const e = new Error(`Zone ${z} already exists.`)
      e.payload = { error: { code: 'INVALID_REQUEST', message: e.message, retryable: false } }
      throw e
    }
    const cap = Math.max(1, Math.floor(Number(capacity) || 0))
    const inv = Math.max(0, Math.min(cap, Math.floor(Number(inventory) || 0)))
    warehouse.zones[z] = { inventory: inv, capacity: cap }
    warehouse.version += 1
    pushAudit('—', 0, 'ZONE_ADDED', 'COMPLETED', null, `Zone ${z} created (${inv}/${cap})`)
    persist()
    return clone(warehouse)
  },

  async editZone(name, { inventory, capacity } = {}) {
    const z = String(name || '').toUpperCase()
    const zone = warehouse.zones[z]
    if (!zone) {
      const e = new Error(`Unknown zone ${z}.`)
      e.payload = { error: { code: 'NOT_FOUND', message: e.message, retryable: false } }
      throw e
    }
    if (capacity != null) zone.capacity = Math.max(1, Math.floor(Number(capacity)))
    if (inventory != null) zone.inventory = Math.max(0, Math.min(zone.capacity, Math.floor(Number(inventory))))
    warehouse.version += 1
    pushAudit('—', 0, 'ZONE_EDITED', 'COMPLETED', null, `Zone ${z} set to ${zone.inventory}/${zone.capacity}`)
    persist()
    return clone(warehouse)
  },

  async removeZone(name) {
    const z = String(name || '').toUpperCase()
    if (!warehouse.zones[z]) return clone(warehouse)
    delete warehouse.zones[z]
    warehouse.version += 1
    pushAudit('—', 0, 'ZONE_REMOVED', 'COMPLETED', null, `Zone ${z} removed`)
    persist()
    return clone(warehouse)
  },
}
