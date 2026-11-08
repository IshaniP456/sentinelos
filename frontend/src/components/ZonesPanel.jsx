import { useState } from 'react'
import { utilization, zoneStatus, TONE } from '../lib/format.js'
import ProgressRing from './ProgressRing.jsx'

function ZoneCard({ name, zone, projected, onEdit, onRemove, busy }) {
  const [editing, setEditing] = useState(false)
  const [inv, setInv] = useState(zone.inventory)
  const [cap, setCap] = useState(zone.capacity)
  const status = zoneStatus(zone)
  const tone = TONE[status.tone]
  const projPct = projected ? utilization(projected) : undefined

  const save = (overrides) => {
    const patch = { inventory: Number(inv), capacity: Number(cap), ...overrides }
    onEdit(name, patch)
    setEditing(false)
  }

  return (
    <div className={`card card-pad flex flex-col items-center text-center ring-1 ${tone.ring}`}>
      <div className="flex w-full items-center justify-between">
        <h3 className="font-display text-sm font-bold tracking-widest text-white">ZONE {name}</h3>
        <span className={`chip border-ink-500 ${tone.text}`}>{status.label}</span>
      </div>

      <div className="my-4">
        <ProgressRing
          value={utilization(zone)}
          projected={projPct}
          tone={status.tone}
          label={`${zone.inventory}/${zone.capacity}`}
          sublabel="packages"
        />
      </div>

      {projected && projected.inventory !== zone.inventory && (
        <div className="mb-2 text-xs text-slate-400">
          projected <span className={`font-mono font-semibold ${TONE[zoneStatus(projected).tone].text}`}>
            {projected.inventory}/{projected.capacity}
          </span>
        </div>
      )}

      {!editing ? (
        <div className="mt-auto flex gap-2">
          <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => { setInv(zone.inventory); setCap(zone.capacity); setEditing(true) }} disabled={busy}>
            Edit
          </button>
          <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => save({ inventory: zone.capacity })} disabled={busy} title="Auto-fill to capacity">
            Auto-fill
          </button>
        </div>
      ) : (
        <div className="mt-auto w-full space-y-2">
          <div className="flex items-center gap-2">
            <label className="w-16 text-left text-[11px] text-slate-500">Inv</label>
            <input type="number" value={inv} min={0} onChange={(e) => setInv(e.target.value)}
              className="w-full rounded-lg border border-ink-500 bg-ink-900 px-2 py-1 text-sm text-white" />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 text-left text-[11px] text-slate-500">Cap</label>
            <input type="number" value={cap} min={1} onChange={(e) => setCap(e.target.value)}
              className="w-full rounded-lg border border-ink-500 bg-ink-900 px-2 py-1 text-sm text-white" />
          </div>
          <div className="flex gap-2">
            <button className="btn-primary flex-1 px-2 py-1.5 text-xs" onClick={() => save()} disabled={busy}>Save</button>
            <button className="btn-ghost px-2 py-1.5 text-xs" onClick={() => setEditing(false)}>Cancel</button>
            {onRemove && <button className="btn-ghost px-2 py-1.5 text-xs text-status-red" onClick={() => onRemove(name)} disabled={busy}>Del</button>}
          </div>
        </div>
      )}
    </div>
  )
}

function AddZoneCard({ onAdd, busy }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [cap, setCap] = useState(20)
  const [inv, setInv] = useState(0)

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="card card-pad flex min-h-[260px] flex-col items-center justify-center gap-2 border-dashed text-slate-500 transition-colors hover:border-brand/50 hover:text-brand"
      >
        <span className="text-3xl leading-none">＋</span>
        <span className="text-sm font-semibold">Add a zone</span>
      </button>
    )
  }
  return (
    <div className="card card-pad flex min-h-[260px] flex-col justify-center gap-2">
      <div className="label mb-1">New zone</div>
      <input placeholder="Name (e.g. D)" value={name} onChange={(e) => setName(e.target.value)}
        className="rounded-lg border border-ink-500 bg-ink-900 px-2.5 py-1.5 text-sm text-white placeholder-slate-600" />
      <div className="flex gap-2">
        <input type="number" placeholder="Capacity" value={cap} min={1} onChange={(e) => setCap(e.target.value)}
          className="w-full rounded-lg border border-ink-500 bg-ink-900 px-2.5 py-1.5 text-sm text-white" />
        <input type="number" placeholder="Start inv" value={inv} min={0} onChange={(e) => setInv(e.target.value)}
          className="w-full rounded-lg border border-ink-500 bg-ink-900 px-2.5 py-1.5 text-sm text-white" />
      </div>
      <div className="mt-1 flex gap-2">
        <button className="btn-primary flex-1 px-2 py-1.5 text-xs"
          onClick={() => { onAdd(name, cap, inv); setOpen(false); setName(''); setCap(20); setInv(0) }}
          disabled={busy || !name.trim()}>Create</button>
        <button className="btn-ghost px-2 py-1.5 text-xs" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  )
}

export default function ZonesPanel({ warehouse, projectedState, onAddZone, onEditZone, onRemoveZone, busy }) {
  if (!warehouse) return <div className="card card-pad text-sm text-slate-500">Loading zones…</div>
  const zones = Object.entries(warehouse.zones)
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label">Warehouse Zones</h2>
        <span className="text-xs text-slate-500">{warehouse.warehouse_id} · actual state · v{warehouse.version}</span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {zones.map(([name, zone]) => (
          <ZoneCard key={name} name={name} zone={zone} projected={projectedState?.[name]}
            onEdit={onEditZone} onRemove={zones.length > 1 ? onRemoveZone : null} busy={busy} />
        ))}
        <AddZoneCard onAdd={onAddZone} busy={busy} />
      </div>
      {warehouse.restricted_zones?.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          Restricted: {warehouse.restricted_zones.join(', ')} — transfers to these are denied.
        </p>
      )}
    </section>
  )
}
