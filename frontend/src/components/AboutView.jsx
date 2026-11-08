// Intro / "what is SentinelOS" tab — short and scannable.

const STEPS = [
  { k: 'Propose', d: 'AI drafts a plan', tone: 'text-brand' },
  { k: 'Authorize', d: 'Check each action', tone: 'text-status-blue' },
  { k: 'Simulate', d: 'Test the full plan', tone: 'text-status-green' },
  { k: 'Approve', d: 'Human okays risky moves', tone: 'text-status-amber' },
  { k: 'Execute', d: 'Apply once, audited', tone: 'text-status-green' },
]

const PILLARS = [
  { t: 'AI proposes, backend decides', d: 'The AI only suggests. The backend authorizes and commits.' },
  { t: 'Checks the whole plan', d: 'Simulated against live state before anything changes.' },
  { t: 'Fully traceable', d: 'Every decision and outcome is recorded.' },
]

export default function AboutView({ onStart }) {
  return (
    <div className="space-y-6">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-3xl border border-ink-500/70 bg-ink-800/60 p-8 sm:p-12">
        <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-brand/20 blur-3xl animate-glowpulse" />
        <div className="relative max-w-xl">
          <span className="chip border-brand/40 bg-brand/10 text-brand">Safe AI Operations</span>
          <h1 className="mt-4 font-display text-4xl font-bold leading-tight text-white sm:text-5xl">
            An <span className="text-brand">execution firewall</span> for AI agents.
          </h1>
          <p className="mt-4 text-base text-slate-300">
            Let an AI run operations — without letting it do anything unsafe.
          </p>
          <button className="btn-primary mt-6" onClick={onStart}>
            Open the console →
          </button>
        </div>
      </section>

      {/* The insight */}
      <section className="card card-pad sm:p-6">
        <div className="label mb-2 text-brand">Why it matters</div>
        <p className="text-lg leading-relaxed text-slate-200">
          An allowed action can still break things — moving 5 packages into a zone with room for 2 overflows it.
          <span className="text-brand"> We catch that by simulating the plan first.</span>
        </p>
      </section>

      {/* How it works */}
      <section>
        <div className="label mb-3">How it works</div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {STEPS.map((s, i) => (
            <div key={s.k} className="card card-pad">
              <div className={`font-mono text-xs font-bold ${s.tone}`}>0{i + 1}</div>
              <div className="mt-1 text-sm font-semibold text-white">{s.k}</div>
              <div className="text-xs text-slate-400">{s.d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Pillars */}
      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {PILLARS.map((p) => (
          <div key={p.t} className="card card-pad">
            <h3 className="text-sm font-bold text-white">{p.t}</h3>
            <p className="mt-1 text-sm text-slate-400">{p.d}</p>
          </div>
        ))}
      </section>
    </div>
  )
}
