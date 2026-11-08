import { IS_MOCK } from '../services/api.js'

export default function Header({ agent, warehouse, onReset, busy }) {
  return (
    <header className="flex flex-col gap-3 border-b border-ink-600 pb-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-status-blue/20 text-status-blue sm:h-10 sm:w-10">
          <svg viewBox="0 0 24 24" className="h-5 w-5 sm:h-6 sm:w-6" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-4z" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="min-w-0">
          <h1 className="text-base font-bold tracking-tight text-white sm:text-lg">
            SentinelOS <span className="text-slate-400">· Warehouse Agent Console</span>
          </h1>
          <p className="hidden text-xs text-slate-500 sm:block">
            AI proposes; the backend decides. Every action is authorized and simulated.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
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
