import { formatTime } from '../lib/format.js'

// Audit history (PRD FR12). Events originate from the backend — never
// hard-coded as a fake "successful" trail (timeline Phase 4). Shows plan,
// revision, timestamp, event type, outcome, and reason.

const OUTCOME_TONE = {
  ALLOWED: 'text-status-green',
  COMPLETED: 'text-status-green',
  PENDING: 'text-status-amber',
  REJECTED: 'text-status-red',
  REVOKED: 'text-status-red',
}

export default function AuditLog({ events }) {
  return (
    <section className="card card-pad">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label">Audit Log</h2>
        <span className="text-xs text-slate-500">{events?.length || 0} events</span>
      </div>

      {!events || events.length === 0 ? (
        <p className="text-sm text-slate-500">No events yet.</p>
      ) : (
        <ul className="max-h-80 space-y-2 overflow-y-auto pr-1">
          {events.map((e) => (
            <li key={e.event_id} className="rounded-lg border border-ink-600 bg-ink-700/50 p-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-200">
                  {e.event_type.replace(/_/g, ' ')}
                </span>
                <span className={`text-xs font-bold ${OUTCOME_TONE[e.outcome] || 'text-slate-400'}`}>
                  {e.outcome}
                </span>
              </div>
              <div className="mt-1 break-words text-xs text-slate-400">{e.message}</div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-600">
                <span className="font-mono">{formatTime(e.timestamp)}</span>
                {e.plan_id !== '—' && <span>· {e.plan_id}</span>}
                {e.revision > 0 && <span>· rev {e.revision}</span>}
                {e.reason_code && <span>· {e.reason_code}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
