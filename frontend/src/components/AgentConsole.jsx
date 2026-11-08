import { useState } from 'react'
import { statusTone, TONE } from '../lib/format.js'

// Example requests. Each fills the box so people can see what the agent does.
const PRESETS = [
  { title: 'Simple move', hint: 'Move 3 from A → C. Low-risk, so it runs on its own.', text: 'Move three packages from Zone A to Zone C.' },
  { title: 'Big move', hint: 'Move 5 out of A. Large, so it pauses for your approval.', text: 'Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary.' },
  { title: 'Over capacity', hint: 'Force 5 into B (only fits 2). Blocked — the AI retries a safe split.', text: 'Run preflight test: move five packages from Zone A to Zone B.' },
]

// The browser submits ONLY the instruction string (contract §2.4); the backend
// assigns plan_id/agent/revisions. When revoked we keep submit enabled so the
// backend is what denies it (Demo 3) — `revoked` is informational only.
export default function AgentConsole({ onSubmit, plan, submitting, error, revoked }) {
  const [text, setText] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    const instruction = text.trim()
    if (!instruction || submitting) return
    onSubmit(instruction)
  }

  const tone = plan ? TONE[statusTone(plan.status)] : null

  return (
    <section className="card card-pad">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label">Tell the agent what to do</h2>
        {plan && (
          <span className={`flex items-center gap-2 text-xs font-semibold ${tone.text}`}>
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
            {plan.status.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {/* Examples first — the easiest way in */}
      <div className="mb-3">
        <div className="mb-1.5 text-xs text-slate-500">Tap an example, then Submit:</div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {PRESETS.map((p) => (
            <button
              key={p.title}
              type="button"
              onClick={() => setText(p.text)}
              className="rounded-xl border border-ink-500 bg-ink-700/60 px-3 py-2 text-left transition-colors hover:border-brand/50 hover:bg-ink-600"
            >
              <div className="text-sm font-semibold text-white">{p.title}</div>
              <div className="text-[11px] text-slate-400">{p.hint}</div>
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <textarea
          className="h-20 w-full resize-none rounded-xl border border-ink-500 bg-ink-900 p-3 text-sm text-slate-100 placeholder-slate-600 focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          placeholder="…or type your own, e.g. Move 2 packages from A to B."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="submit" className="btn-primary" disabled={submitting || !text.trim()}>
            {submitting ? 'Submitting…' : 'Submit'}
          </button>
          {revoked && <span className="text-xs text-status-amber">Agent revoked — the backend will deny this.</span>}
        </div>
      </form>

      {error && (
        <div className="mt-3 rounded-xl border border-status-red/40 bg-status-red/10 p-3 text-sm text-status-red">
          {error}
        </div>
      )}
    </section>
  )
}
