import { useState } from 'react'
import { TONE } from '../lib/format.js'

// Administration surface (PRD FR10). Revocation is an admin-only action; the
// frontend forwards it to the trusted backend, which performs the real
// revocation. Disabling a button is NOT proof of revocation — the backend must
// deny subsequent actions (timeline Phase 4). We surface the live agent status
// so judges can see the post-revocation denial take effect.
export default function AgentControls({ agent, onRevoke, busy }) {
  const [confirming, setConfirming] = useState(false)
  const revoked = agent?.status !== 'ACTIVE'
  const tone = TONE[revoked ? 'red' : 'green']

  return (
    <section className="card card-pad">
      <h2 className="label mb-3">Administration · Agent Controls</h2>

      <div className="flex items-center justify-between rounded-lg bg-ink-700 p-3">
        <div>
          <div className="text-sm font-semibold text-white">{agent?.agent_id || '—'}</div>
          <div className="text-xs text-slate-500">{agent?.role}</div>
        </div>
        <span className={`flex items-center gap-2 text-sm font-bold ${tone.text}`}>
          <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} />
          {agent?.status || '—'}
        </span>
      </div>

      <div className="mt-3">
        {revoked ? (
          <p className="text-xs text-status-red">
            Agent revoked. The backend now denies every subsequent authorization check.
          </p>
        ) : confirming ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Revoke {agent?.agent_id}?</span>
            <button
              className="btn-danger px-3 py-1.5 text-xs"
              onClick={() => {
                setConfirming(false)
                onRevoke()
              }}
              disabled={busy}
            >
              Confirm revoke
            </button>
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        ) : (
          <button className="btn-danger" onClick={() => setConfirming(true)} disabled={busy}>
            Revoke Agent
          </button>
        )}
      </div>
    </section>
  )
}
