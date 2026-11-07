import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './services/api.js'
import { TERMINAL_STATUSES } from './mock/data.js'
import Header from './components/Header.jsx'
import WarehouseOverview from './components/WarehouseOverview.jsx'
import AgentConsole from './components/AgentConsole.jsx'
import PlanComparison from './components/PlanComparison.jsx'
import WorkflowStatus from './components/WorkflowStatus.jsx'
import ApprovalModal from './components/ApprovalModal.jsx'
import AuditLog from './components/AuditLog.jsx'
import AgentControls from './components/AgentControls.jsx'

const POLL_MS = 2000

// Persist the active plan id so a page refresh can recover an in-flight or
// pending-approval plan (PRD FR11 "active plan can be retrieved" / NFR03).
const PLAN_KEY = 'sentinel.active_plan_id'
const savePlanId = (id) => { try { localStorage.setItem(PLAN_KEY, id) } catch { /* ignore */ } }
const loadPlanId = () => { try { return localStorage.getItem(PLAN_KEY) } catch { return null } }
const clearPlanId = () => { try { localStorage.removeItem(PLAN_KEY) } catch { /* ignore */ } }

// Turn the standard error object (contract §3.6) into a readable message.
function errMessage(e) {
  return e?.payload?.error?.message || e?.message || 'Something went wrong.'
}

export default function App() {
  const [warehouse, setWarehouse] = useState(null)
  const [agent, setAgent] = useState(null)
  const [plan, setPlan] = useState(null)
  const [events, setEvents] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const planIdRef = useRef(null)

  const refreshStatic = useCallback(async () => {
    try {
      const [w, a, log] = await Promise.all([api.getWarehouse(), api.getAgent(), api.getAuditLog()])
      setWarehouse(w)
      setAgent(a)
      setEvents(log.events)
    } catch (e) {
      setError(errMessage(e))
    }
  }, [])

  // Initial load — fetch static state, then rehydrate any persisted plan so a
  // refresh recovers an active/pending plan (PRD FR11 / NFR03).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      await refreshStatic()
      const storedId = loadPlanId()
      if (!storedId) return
      try {
        const status = await api.getPlanStatus(storedId)
        if (!cancelled) {
          planIdRef.current = storedId
          setPlan(status)
        }
      } catch {
        // Stale id (e.g. after a reset or backend restart) — drop it quietly.
        clearPlanId()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshStatic])

  // Poll the active plan every 2s while it is non-terminal (PRD FR11 / §5.5).
  useEffect(() => {
    if (!plan || TERMINAL_STATUSES.includes(plan.status)) return
    const id = setInterval(async () => {
      try {
        const next = await api.getPlanStatus(planIdRef.current)
        setPlan(next)
        // Keep audit + warehouse fresh as the workflow emits events / commits.
        const log = await api.getAuditLog()
        setEvents(log.events)
        if (next.status === 'COMPLETED') {
          const w = await api.getWarehouse()
          setWarehouse(w)
        }
      } catch (e) {
        setError(errMessage(e))
      }
    }, POLL_MS)
    return () => clearInterval(id)
  }, [plan])

  const handleSubmit = async (instruction) => {
    setError(null)
    setSubmitting(true)
    try {
      const { plan_id } = await api.submitPlan(instruction)
      planIdRef.current = plan_id
      savePlanId(plan_id)
      const status = await api.getPlanStatus(plan_id)
      setPlan(status)
      const log = await api.getAuditLog()
      setEvents(log.events)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  const decide = async (fn, approvalId) => {
    setBusy(true)
    try {
      await fn(approvalId)
      // Immediately re-poll so the modal closes and execution begins.
      const next = await api.getPlanStatus(planIdRef.current)
      setPlan(next)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const handleRevoke = async () => {
    setBusy(true)
    setError(null)
    try {
      const a = await api.revokeAgent()
      setAgent(a)
      const log = await api.getAuditLog()
      setEvents(log.events)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const handleReset = async () => {
    // Guard: don't reset while a workflow is active (PRD FR13).
    if (plan && !TERMINAL_STATUSES.includes(plan.status)) {
      setError('Cannot reset while a plan is active. Wait for it to finish or be denied.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.resetDemo()
      planIdRef.current = null
      clearPlanId()
      setPlan(null)
      await refreshStatic()
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
    }
  }

  // Overlay the active candidate's projected state onto the warehouse cards
  // while a plan is mid-flight (and not yet committed).
  const activeCandidate =
    plan && !['COMPLETED'].includes(plan.status)
      ? plan.candidates?.find((c) => c.revision === (plan.approval?.revision ?? plan.candidates.length))
      : null
  const projectedState =
    activeCandidate?.simulation?.passed ? activeCandidate.simulation.projected_state : null

  const agentRevoked = agent?.status && agent.status !== 'ACTIVE'

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <Header agent={agent} warehouse={warehouse} onReset={handleReset} busy={busy} />

      {error && (
        <div className="mt-4 flex items-start justify-between rounded-lg border border-status-red/40 bg-status-red/10 p-3 text-sm text-status-red">
          <span>{error}</span>
          <button className="ml-4 text-xs underline" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}

      <main className="mt-6 space-y-6">
        <WarehouseOverview warehouse={warehouse} projectedState={projectedState} />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <AgentConsole
              onSubmit={handleSubmit}
              plan={plan}
              submitting={submitting}
              error={null}
              revoked={agentRevoked}
            />
          </div>
          <WorkflowStatus plan={plan} />
        </div>

        <PlanComparison plan={plan} />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <AgentControls agent={agent} onRevoke={handleRevoke} busy={busy} />
          <AuditLog events={events} />
        </div>
      </main>

      <ApprovalModal
        plan={plan}
        onApprove={(id) => decide(api.approvePlan, id)}
        onDeny={(id) => decide(api.denyPlan, id)}
        busy={busy}
      />

      <footer className="mt-10 border-t border-ink-600 pt-4 text-center text-xs text-slate-600">
        SentinelOS · AWS × A10 Hackathon · AI proposes, the backend decides.
      </footer>
    </div>
  )
}
