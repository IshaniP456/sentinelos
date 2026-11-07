// Seed state and canonical shapes from the Team Integration Contract (§2).
// Everything here is snake_case to match the real HTTP contract so components
// never need to change when the mock engine is swapped for the live API.

export const SEED_WAREHOUSE = {
  warehouse_id: 'demo-warehouse',
  version: 1,
  zones: {
    A: { inventory: 20, capacity: 30 },
    B: { inventory: 8, capacity: 10 },
    C: { inventory: 5, capacity: 20 },
  },
  restricted_zones: ['HAZMAT'],
}

export const SEED_AGENT = {
  agent_id: 'inventory-agent-01',
  status: 'ACTIVE',
  role: 'INVENTORY_MANAGER',
  max_transfer: 10,
}

// Non-terminal vs terminal status sets (contract §5.1).
export const TERMINAL_STATUSES = ['COMPLETED', 'REJECTED', 'FAILED', 'EXPIRED']

// Ordered pipeline used by the WorkflowStatus component to render the
// multi-check story. Not every status appears in every run.
export const WORKFLOW_STEPS = [
  { key: 'PLANNING', label: 'AI Planning' },
  { key: 'AUTHORIZING', label: 'Authorization' },
  { key: 'SIMULATING', label: 'Preflight Simulation' },
  { key: 'REPLANNING', label: 'AI Replanning' },
  { key: 'AWAITING_APPROVAL', label: 'Human Approval' },
  { key: 'EXECUTING', label: 'Execution' },
]
