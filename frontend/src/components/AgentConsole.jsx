import { useState } from 'react'
import { statusTone, TONE } from '../lib/format.js'

const PRESETS = [
  { label: 'Demo 1 · low-risk', text: 'Move three packages from Zone A to Zone C.' },
  {
    label: 'Demo 2 · replan + approval',
    text: 'Move five packages out of Zone A, preferably into Zone B. Use another zone if necessary.',
  },
  { label: 'Run preflight test (A→B×5)', text: 'Run preflight test: move five packages from Zone A to Zone B.' },
]

// The AI instruction console. The browser submits ONLY the instruction string
// (contract §2.4) — the backend assigns plan_id, agent, revisions, etc.
export default function AgentConsole({ onSubmit, plan, submitting, error, disabled }) {
  const [text, setText] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    const instruction = text.trim()
    if (!instruction || submitting || disabled) return
    onSubmit(instruction)
  }

  const tone = plan ? TONE[statusTone(plan.status)] : null

  return (
    <section className="card card-pad">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label">AI Instruction Console</h2>
        {plan && (
          <span className={`flex items-center gap-2 text-xs font-semibold ${tone.text}`}>
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
            {plan.status.replace(/_/g, ' ')} · {plan.plan_id}
          </span>
        )}
      </div>

      <form onSubmit={handleSubmit}>
        <textarea
          className="h-24 w-full resize-none rounded-lg border border-ink-500 bg-ink-900 p-3 text-sm text-slate-100 placeholder-slate-600 focus:border-status-blue focus:outline-none focus:ring-1 focus:ring-status-blue"
          placeholder="e.g. Move three packages from Zone A to Zone C."
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={disabled}
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="submit" className="btn-primary" disabled={submitting || disabled || !text.trim()}>
            {submitting ? 'Submitting…' : 'Submit Instruction'}
          </button>
          {disabled && (
            <span className="text-xs text-status-red">
              Agent revoked — new instructions are denied by authorization.
            </span>
          )}
        </div>
      </form>

      <div className="mt-4">
        <div className="label mb-2">Presets</div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="rounded-md border border-ink-500 bg-ink-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-ink-600 disabled:opacity-40"
              onClick={() => setText(p.text)}
              disabled={disabled}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-status-red/40 bg-status-red/10 p-3 text-sm text-status-red">
          {error}
        </div>
      )}
    </section>
  )
}
