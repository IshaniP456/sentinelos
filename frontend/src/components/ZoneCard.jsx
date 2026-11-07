import { utilization, zoneStatus, TONE } from '../lib/format.js'

// Renders one warehouse zone. When `projected` is supplied the card shows the
// counterfactual value alongside the actual, making the actual-vs-projected
// distinction (contract §3.3) visible.
export default function ZoneCard({ name, zone, projected }) {
  const pct = utilization(zone)
  const status = zoneStatus(zone)
  const tone = TONE[status.tone]
  const hasProjection = projected && projected.inventory !== zone.inventory
  const projPct = hasProjection ? utilization(projected) : pct
  const projTone = hasProjection ? TONE[zoneStatus(projected).tone] : tone

  return (
    <div className={`card card-pad ring-1 ${tone.ring}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold tracking-widest text-white">ZONE {name}</h3>
        <span className={`text-xs font-semibold ${tone.text}`}>{status.label}</span>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-mono text-3xl font-bold text-white">{zone.inventory}</span>
        <span className="text-sm text-slate-500">/ {zone.capacity} packages</span>
      </div>

      <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-ink-600">
        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div className="mt-1 text-right text-xs font-mono text-slate-400">{pct}%</div>

      {hasProjection && (
        <div className="mt-3 rounded-lg border border-dashed border-ink-500 bg-ink-700/50 p-2">
          <div className="flex items-center justify-between text-xs">
            <span className="label">Projected</span>
            <span className={`font-mono font-semibold ${projTone.text}`}>
              {projected.inventory} / {projected.capacity} · {projPct}%
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
