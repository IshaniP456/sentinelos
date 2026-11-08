import { formatTime } from '../lib/format.js'

// Audit history (PRD FR12) — a record of every decision the system made.

// Plain-English names for the backend event codes.
const FRIENDLY = {
  PLAN_SUBMITTED: 'Request received',
  BEDROCK_PLAN_GENERATED: 'AI drafted a plan',
  AUTHORIZATION_ALLOWED: 'Actions allowed',
  AUTHORIZATION_DENIED: 'Action denied',
  SIMULATION_FAILED: 'Simulation failed',
  SIMULATION_PASSED: 'Simulation passed',
  REPLAN_GENERATED: 'AI revised the plan',
  AWAITING_APPROVAL: 'Waiting for approval',
  PLAN_EXECUTED: 'Changes applied',
  APPROVAL_DENIED: 'Approval denied',
  AGENT_REVOKED: 'Agent revoked',
  ZONE_ADDED: 'Zone added',
  ZONE_EDITED: 'Zone edited',
  ZONE_REMOVED: 'Zone removed',
}

const OUTCOME_TONE = {
  ALLOWED: 'text-status-green',
  COMPLETED: 'text-status-green',
  PENDING: 'text-status-amber',
  REJECTED: 'text-status-red',
  REVOKED: 'text-status-red',
}

const friendly = (t) => FRIENDLY[t] || t.replace(/_/g, ' ').toLowerCase()

export default function AuditLog({ events, onClear }) {
  return (
    <section className="card card-pad">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="label">Activity log</h2>
          <p className="mb-3 mt-1 text-xs text-slate-500">Every decision the system made, newest first.</p>
        </div>
        {onClear && events?.length > 0 && (
          <button className="btn-ghost px-3 py-1 text-xs" onClick={onClear}>Clear</button>
        )}
      </div>

      {!events || events.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing yet — submit a request to see it fill up.</p>
      ) : (
        <ul className="max-h-80 space-y-2 overflow-y-auto pr-1">
          {events.map((e) => (
            <li key={e.event_id} className="rounded-xl border border-ink-600 bg-ink-700/50 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white">{friendly(e.event_type)}</span>
                <span className={`text-[11px] font-bold ${OUTCOME_TONE[e.outcome] || 'text-slate-400'}`}>
                  {e.outcome}
                </span>
              </div>
              <div className="mt-0.5 break-words text-xs text-slate-400">{e.message}</div>
              <div className="mt-1 font-mono text-[11px] text-slate-600">{formatTime(e.timestamp)}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
