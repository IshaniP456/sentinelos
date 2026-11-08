import { WORKFLOW_STEPS, TERMINAL_STATUSES } from '../mock/data.js'

// Visualizes the multi-check pipeline so judges see that SentinelOS performs
// several independent checks (PRD FR11). Driven entirely by backend status —
// no arbitrary timers in the UI (contract §5.5 / timeline Phase 5).

// Rank of each status in the pipeline, used to decide which steps are done.
const ORDER = {
  PLANNING: 0,
  VALIDATING: 0,
  AUTHORIZING: 1,
  SIMULATING: 2,
  REPLANNING: 3,
  AWAITING_APPROVAL: 4,
  REAUTHORIZING: 5,
  REVALIDATING: 5,
  EXECUTING: 5,
  COMPLETED: 6,
}

function stepState(stepKey, plan) {
  const status = plan.status
  const rank = ORDER[status] ?? 0
  const stepRank = ORDER[stepKey] ?? 0
  const terminal = TERMINAL_STATUSES.includes(status)
  const rejected = status === 'REJECTED' || status === 'FAILED' || status === 'EXPIRED'

  // The replanning step only applies when there is more than one candidate.
  if (stepKey === 'REPLANNING' && (plan.candidates?.length ?? 0) < 2) {
    return { icon: '·', tone: 'text-slate-600', note: 'not needed' }
  }
  // The simulation step: if the first candidate failed, mark the simulate
  // step as failed when a replan happened.
  if (stepKey === 'SIMULATING' && (plan.candidates?.length ?? 0) >= 2 && rank > 2) {
    return { icon: '✗', tone: 'text-status-red', note: 'capacity exceeded → replanned' }
  }
  if (stepKey === 'AWAITING_APPROVAL') {
    if (status === 'AWAITING_APPROVAL') return { icon: '🟡', tone: 'text-status-amber', note: 'waiting' }
    if (!plan.risk?.approval_required) return { icon: '·', tone: 'text-slate-600', note: 'not required' }
  }

  if (rejected && stepRank >= rank) return { icon: '○', tone: 'text-slate-600' }
  if (status === stepKey) return { icon: '▸', tone: 'text-status-blue', note: 'in progress', pulse: true }
  if (stepRank < rank || (terminal && status === 'COMPLETED')) return { icon: '✓', tone: 'text-status-green' }
  return { icon: '○', tone: 'text-slate-600' }
}

export default function WorkflowStatus({ plan }) {
  if (!plan) {
    return (
      <section className="card card-pad text-sm text-slate-500">
        Workflow status appears here once a plan is submitted.
      </section>
    )
  }

  return (
    <section className="card card-pad">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label">Workflow Status</h2>
        <span className="text-xs font-mono text-slate-500">{plan.status}</span>
      </div>
      <ol className="space-y-2">
        {WORKFLOW_STEPS.map((step) => {
          const s = stepState(step.key, plan)
          return (
            <li key={step.key} className="flex items-center gap-3">
              <span className={`w-5 text-center ${s.tone} ${s.pulse ? 'animate-pulse' : ''}`}>{s.icon}</span>
              <span className="flex-1 text-sm text-slate-200">{step.label}</span>
              {s.note && <span className={`text-xs ${s.tone}`}>{s.note}</span>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
