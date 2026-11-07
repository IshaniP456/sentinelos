import ZoneCard from './ZoneCard.jsx'

// Shows the three zone cards. If `projectedState` is provided (from the
// active plan's selected candidate simulation) each card overlays the
// projected inventory so operators see what *would* happen vs what *is*.
export default function WarehouseOverview({ warehouse, projectedState }) {
  if (!warehouse) {
    return (
      <div className="card card-pad text-sm text-slate-500">Loading warehouse…</div>
    )
  }

  const zones = Object.entries(warehouse.zones)

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label">Warehouse Overview</h2>
        <span className="text-xs text-slate-500">
          {warehouse.warehouse_id} · actual state (DynamoDB)
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {zones.map(([name, zone]) => (
          <ZoneCard key={name} name={name} zone={zone} projected={projectedState?.[name]} />
        ))}
      </div>
      {warehouse.restricted_zones?.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          Restricted: {warehouse.restricted_zones.join(', ')} — transfers to these zones are denied.
        </p>
      )}
    </section>
  )
}
