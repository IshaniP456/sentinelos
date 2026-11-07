import { IS_MOCK } from '../services/api.js'

export default function Header({ agent, warehouse, onReset, busy }) {
  return (
    <header className="flex flex-col gap-3 border-b border-ink-600 pb-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-status-blue/20 text-status-blue">
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-4z" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white">
            SentinelOS <span className="text-slate-400">· Warehouse Agent Console</span>
          </h1>
          <p className="text-xs text-slate-500">
            AI proposes; the backend decides. Every action is authorized and simulated.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {IS_MOCK && (
          <span className="rounded-md border border-status-amber/40 bg-status-amber/10 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-status-amber">
            Mock Mode
          </span>
        )}
        <div className="text-right text-xs">
          <div className="text-slate-500">Warehouse</div>
          <div className="font-mono text-slate-300">
            {warehouse ? `v${warehouse.version}` : '—'}
          </div>
        </div>
        <button className="btn-ghost" onClick={onReset} disabled={busy}>
          Reset Demo
        </button>
      </div>
    </header>
  )
}
