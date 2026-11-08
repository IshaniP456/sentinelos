// Small presentation helpers shared across components.

export function utilization(zone) {
  if (!zone || !zone.capacity) return 0
  return Math.round((zone.inventory / zone.capacity) * 100)
}

// Map a utilization % to the contract's status language (§4.1).
export function zoneStatus(zone) {
  const pct = utilization(zone)
  if (zone.inventory > zone.capacity) return { label: 'OVER CAPACITY', tone: 'red' }
  if (pct >= 90) return { label: 'AT CAPACITY', tone: 'red' }
  if (pct >= 75) return { label: 'NEAR CAPACITY', tone: 'amber' }
  return { label: 'HEALTHY', tone: 'green' }
}

// Tailwind classes per status tone.
export const TONE = {
  green: { text: 'text-status-green', bar: 'bg-status-green', ring: 'ring-status-green/40', dot: 'bg-status-green' },
  amber: { text: 'text-status-amber', bar: 'bg-status-amber', ring: 'ring-status-amber/40', dot: 'bg-status-amber' },
  red: { text: 'text-status-red', bar: 'bg-status-red', ring: 'ring-status-red/40', dot: 'bg-status-red' },
  blue: { text: 'text-status-blue', bar: 'bg-status-blue', ring: 'ring-status-blue/40', dot: 'bg-status-blue' },
  gray: { text: 'text-status-gray', bar: 'bg-status-gray', ring: 'ring-status-gray/30', dot: 'bg-status-gray' },
}

// PlanStatus.status -> tone for badges.
export function statusTone(status) {
  switch (status) {
    case 'COMPLETED':
      return 'green'
    case 'AWAITING_APPROVAL':
      return 'amber'
    case 'REJECTED':
    case 'FAILED':
    case 'EXPIRED':
      return 'red'
    case 'PLANNING':
    case 'VALIDATING':
    case 'AUTHORIZING':
    case 'SIMULATING':
    case 'REPLANNING':
    case 'REAUTHORIZING':
    case 'REVALIDATING':
    case 'EXECUTING':
      return 'blue'
    default:
      return 'gray'
  }
}

export function describeActions(actions) {
  if (!actions || !actions.length) return '—'
  return actions.map((a) => `${a.from} → ${a.to}: ${a.count}`).join(', ')
}

export function formatTime(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}
