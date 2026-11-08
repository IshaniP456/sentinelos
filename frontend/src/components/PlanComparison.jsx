import { describeActions, TONE } from '../lib/format.js'

// Render a simulation violation. The real simulator (Mariam's simulate_plan)
// attaches a human-readable `message` to every violation written for display —
// prefer it. Otherwise reconstruct text, handling both CAPACITY_EXCEEDED
// (projected/capacity) and INSUFFICIENT_INVENTORY (available/requested) shapes.
function violationText(v) {
  if (v.message) return v.message
  const where = typeof v.action_index === 'number' ? ` (action ${v.action_index + 1})` : ''
  if (v.code === 'INSUFFICIENT_INVENTORY' || v.code === 'INSUFFICIENT_SOURCE') {
    return `${v.code} — Zone ${v.zone} has ${v.available ?? v.projected}, needs ${v.requested ?? ''}${where}`
  }
  if (v.capacity != null) {
    return `${v.code} — Zone ${v.zone} would reach ${v.projected} / ${v.capacity}${where}`
  }
  return `${v.code} — Zone ${v.zone ?? ''}${where}`
}

// The most important surface (timeline §4.3 / PRD FR04, FR11): shows each AI
// candidate with its authorization + simulation result, side by side, so a
// judge can see WHY a plan was rejected and HOW the revision fixed it.
//
// Projected inventory is always labeled as a counterfactual and never
// presented as committed state (PRD §5 product rules, contract §3.3).

function CandidatePanel({ candidate, isActive }) {
  const sim = candidate.simulation
  const auth = candidate.authorization
  const passed = sim?.passed && auth?.allowed
  const tone = TONE[passed ? 'green' : 'red']

  return (
    <div className={`card card-pad ${isActive ? 'ring-1 ring-status-blue/50' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-white">
          {candidate.revision === 1 ? 'AI’s first plan' : `AI’s revised plan${candidate.revision > 2 ? ` (try ${candidate.revision})` : ''}`}
          {isActive && <span className="ml-2 text-xs text-status-blue">← chosen</span>}
        </h4>
        <span className={`text-xs font-bold ${tone.text}`}>
          {passed ? '✓ Safe to run' : '✗ Would break a zone'}
        </span>
      </div>

      <div className="mt-2 font-mono text-sm text-slate-200">
        {describeActions(candidate.plan.actions)}
      </div>

      {/* Authorization decisions */}
      <div className="mt-3">
        <div className="label mb-1">Authorization</div>
        <ul className="space-y-1">
          {auth?.decisions.map((d) => (
            <li key={d.action_index} className="flex items-center gap-2 text-xs">
              <span className={d.allowed ? 'text-status-green' : 'text-status-red'}>
                {d.allowed ? '✓' : '✗'}
              </span>
              <span className="text-slate-400">
                Action {d.action_index + 1}: {d.reason_code}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* Simulation result */}
      <div className="mt-3">
        <div className="label mb-1">Simulation</div>
        {sim?.passed ? (
          <p className="text-xs text-status-green">Projected inventory respects all zone capacities.</p>
        ) : (
          <ul className="space-y-1">
            {sim?.violations.map((v, i) => (
              <li key={i} className="rounded-md border border-status-red/30 bg-status-red/10 p-2 text-xs text-status-red">
                {violationText(v)}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Projected state — explicitly a counterfactual */}
      {sim?.projected_state && (
        <div className="mt-3">
          <div className="label mb-1">
            Projected state <span className="text-slate-500">(not committed)</span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(sim.projected_state).map(([z, zone]) => {
              const over = zone.inventory > zone.capacity
              return (
                <div key={z} className="rounded-md bg-ink-700 p-2 text-center">
                  <div className="text-xs text-slate-500">Zone {z}</div>
                  <div className={`font-mono text-sm font-semibold ${over ? 'text-status-red' : 'text-slate-200'}`}>
                    {zone.inventory}/{zone.capacity}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default function PlanComparison({ plan }) {
  if (!plan || !plan.candidates?.length) {
    return (
      <section className="card card-pad text-sm text-slate-500">
        No active plan. Submit an instruction to see the AI proposal, authorization, and simulation.
      </section>
    )
  }

  const activeRevision = plan.approval?.revision ?? plan.execution?.revision ?? plan.candidates.length

  return (
    <section>
      <h2 className="label">What the AI proposed</h2>
      <p className="mb-3 mt-1 text-xs text-slate-500">
        If the AI’s first plan is unsafe, it gets blocked and the AI tries again. Here’s each attempt.
      </p>

      <div className="mb-3 rounded-xl border border-ink-600 bg-ink-800 p-3">
        <div className="label mb-1">You asked for</div>
        <p className="text-sm italic text-slate-300">“{plan.instruction}”</p>
      </div>

      {/* FR14: label a scripted preflight so the initial rejection is never
          mistaken for an unexpected autonomous model mistake. */}
      {/preflight/i.test(plan.instruction) && (
        <div className="mb-3 rounded-lg border border-status-amber/40 bg-status-amber/10 p-2.5 text-xs text-status-amber">
          <span className="font-semibold">Scripted preflight test.</span> The initial candidate is
          intentionally scripted to demonstrate the capacity rejection; the replan is real.
        </div>
      )}

      <div className={`grid grid-cols-1 gap-4 ${plan.candidates.length > 1 ? 'lg:grid-cols-2' : ''}`}>
        {plan.candidates.map((c) => (
          <CandidatePanel key={c.revision} candidate={c} isActive={c.revision === activeRevision} />
        ))}
      </div>
    </section>
  )
}
