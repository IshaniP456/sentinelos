import { useEffect, useRef } from 'react'
import { describeActions } from '../lib/format.js'

// Human-approval interface (PRD FR07). The modal shows the exact revision,
// warehouse version, projected inventory, and risk under review. Approve/Deny
// forward the approval_id to the trusted backend — the browser never sees or
// sends a Step Functions task token (contract §8, NFR01).
export default function ApprovalModal({ plan, onApprove, onDeny, busy }) {
  // Blocks a repeat click within one decision cycle. It resets as soon as the
  // decision settles: on success the plan advances and this modal unmounts; on
  // error `busy` clears, re-enabling the buttons so the admin can retry (fixes
  // "buttons stay disabled after a decision"). The backend is also idempotent,
  // so even a race cannot double-execute (contract §3.5).
  const inFlight = useRef(false)
  useEffect(() => {
    if (!busy) inFlight.current = false
  }, [busy])

  if (!plan || plan.status !== 'AWAITING_APPROVAL' || !plan.approval) return null

  const candidate = plan.candidates.find((c) => c.revision === plan.approval.revision)
  if (!candidate) return null

  const decide = (fn) => {
    if (inFlight.current || busy) return
    inFlight.current = true
    fn(plan.approval.approval_id)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="approval-title">
      <div className="card max-h-[90vh] w-full max-w-md overflow-y-auto">
        <div className="border-b border-ink-600 px-5 py-3">
          <h3 id="approval-title" className="text-sm font-bold uppercase tracking-wider text-status-amber">
            Human Approval Required
          </h3>
        </div>
        <div className="space-y-3 px-5 py-4 text-sm">
          <Row label="Agent" value={plan.agent_id} />
          <Row label="Plan" value={`${plan.plan_id} · revision ${candidate.revision}`} />
          <Row label="Warehouse version" value={`v${plan.warehouse_version}`} />

          <div>
            <div className="label mb-1">Proposed actions</div>
            <div className="font-mono text-slate-100">{describeActions(candidate.plan.actions)}</div>
          </div>

          <div className="grid grid-cols-3 gap-2 rounded-lg bg-ink-700 p-2 text-center">
            <Badge label="Authorization" value="PASSED" tone="text-status-green" />
            <Badge label="Simulation" value="PASSED" tone="text-status-green" />
            <Badge
              label="Risk"
              value={plan.risk?.risk || 'ELEVATED'}
              tone="text-status-amber"
            />
          </div>

          <p className="text-xs text-slate-500">
            Total movement: {plan.risk?.total_packages} packages — exceeds the low-risk threshold,
            so an administrator decision is required before execution.
          </p>
        </div>
        <div className="flex gap-3 border-t border-ink-600 px-5 py-3">
          <button className="btn-ghost flex-1" onClick={() => decide(onDeny)} disabled={busy}>
            Deny
          </button>
          <button className="btn-primary flex-1" onClick={() => decide(onApprove)} disabled={busy}>
            {busy ? 'Submitting…' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between">
      <span className="label">{label}</span>
      <span className="font-mono text-slate-200">{value}</span>
    </div>
  )
}

function Badge({ label, value, tone }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-xs font-bold ${tone}`}>{value}</div>
    </div>
  )
}
