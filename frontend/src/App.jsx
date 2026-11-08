import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './services/api.js'
import { IS_MOCK } from './services/api.js'
import { TERMINAL_STATUSES } from './mock/data.js'
import TabNav from './components/TabNav.jsx'
import AboutView from './components/AboutView.jsx'
import ZonesPanel from './components/ZonesPanel.jsx'
import AgentConsole from './components/AgentConsole.jsx'
import PlanComparison from './components/PlanComparison.jsx'
import WorkflowStatus from './components/WorkflowStatus.jsx'
import ApprovalModal from './components/ApprovalModal.jsx'
import AuditLog from './components/AuditLog.jsx'
import AgentControls from './components/AgentControls.jsx'
import ImageAttackPanel from './components/ImageAttackPanel.jsx'

const POLL_MS = 2000

const PLAN_KEY = 'sentinel.active_plan_id'
const savePlanId = (id) => { try { localStorage.setItem(PLAN_KEY, id) } catch { /* ignore */ } }
const loadPlanId = () => { try { return localStorage.getItem(PLAN_KEY) } catch { return null } }
const clearPlanId = () => { try { localStorage.removeItem(PLAN_KEY) } catch { /* ignore */ } }

function errMessage(e) {
  return e?.payload?.error?.message || e?.message || 'Something went wrong.'
}

const TABS = [
  { id: 'about', label: 'Overview' },
  { id: 'operations', label: 'Operations' },
]

export default function App() {
  const [tab, setTab] = useState('about')
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
        clearPlanId()
      }
    })()
    return () => { cancelled = true }
  }, [refreshStatic])

  useEffect(() => {
    if (!plan || TERMINAL_STATUSES.includes(plan.status)) return
    const id = setInterval(async () => {
      try {
        const next = await api.getPlanStatus(planIdRef.current)
        // Preserve the scripted-attack image framing across polls (the live
        // text plan the preset submits carries no input_metadata of its own).
        setPlan((prev) => ({ ...next, input_metadata: next.input_metadata || prev?.input_metadata }))
        const log = await api.getAuditLog()
        setEvents(log.events)
        if (next.status === 'COMPLETED') setWarehouse(await api.getWarehouse())
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
      setPlan(await api.getPlanStatus(plan_id))
      setEvents((await api.getAuditLog()).events)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  // In real (non-mock) mode the scripted attack submits its extracted text as a
  // live plan, so the response has no image metadata — stamp it here so the
  // panel renders the injection narrative over the live rejection.
  const stampImage = (p) =>
    !p || IS_MOCK || p.input_metadata
      ? p
      : { ...p, input_metadata: { type: 'image', mode: 'scripted', intent_source: 'UNTRUSTED_IMAGE_EXTRACTION' } }

  const handleSubmitImage = async (meta) => {
    setError(null)
    setSubmitting(true)
    try {
      const { plan_id } = await api.submitImage(meta)
      planIdRef.current = plan_id
      savePlanId(plan_id)
      setPlan(stampImage(await api.getPlanStatus(plan_id)))
      setEvents((await api.getAuditLog()).events)
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
      // Refresh plan AND the activity log immediately — a denial makes the plan
      // terminal, which stops polling, so the log must be pulled here or it
      // would freeze on the old "pending" entry.
      setPlan(await api.getPlanStatus(planIdRef.current))
      setEvents((await api.getAuditLog()).events)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const handleRevoke = async () => {
    setBusy(true); setError(null)
    try {
      setAgent(await api.revokeAgent())
      setEvents((await api.getAuditLog()).events)
    } catch (e) { setError(errMessage(e)) } finally { setBusy(false) }
  }

  const handleReset = async () => {
    if (plan && !TERMINAL_STATUSES.includes(plan.status)) {
      setError('Cannot reset while a plan is active. Wait for it to finish or be denied.')
      return
    }
    setBusy(true); setError(null)
    try {
      await api.resetDemo()
      planIdRef.current = null
      clearPlanId()
      setPlan(null)
      await refreshStatic()
    } catch (e) { setError(errMessage(e)) } finally { setBusy(false) }
  }

  // Zone management (mock-mode demo feature).
  const zoneOp = async (fn) => {
    setBusy(true); setError(null)
    try {
      setWarehouse(await fn())
      setEvents((await api.getAuditLog()).events)
    } catch (e) { setError(errMessage(e)) } finally { setBusy(false) }
  }
  const handleAddZone = (name, cap, inv) => zoneOp(() => api.addZone(name, cap, inv))
  const handleEditZone = (name, patch) => zoneOp(() => api.editZone(name, patch))
  const handleRemoveZone = (name) => zoneOp(() => api.removeZone(name))

  const handleClearLog = async () => {
    try {
      await api.clearAudit()
      setEvents([])
    } catch (e) { setError(errMessage(e)) }
  }

  const activeCandidate =
    plan && !['COMPLETED'].includes(plan.status)
      ? plan.candidates?.find((c) => c.revision === (plan.approval?.revision ?? plan.candidates.length))
      : null
  const projectedState = activeCandidate?.simulation?.passed ? activeCandidate.simulation.projected_state : null
  const agentRevoked = agent?.status && agent.status !== 'ACTIVE'

  return (
    <div className="min-h-full">
      {/* Top bar */}
      <header className="sticky top-0 z-40 border-b border-ink-500/60 bg-ink-900/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand/15 text-brand shadow-glow">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-4z" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="font-display text-lg font-bold tracking-tight text-white">
              Sentinel<span className="text-brand">OS</span>
            </div>
          </div>

          <div className="order-last w-full sm:order-none sm:ml-4 sm:w-auto">
            <TabNav tabs={TABS} active={tab} onChange={setTab} />
          </div>

          <div className="ml-auto flex items-center gap-2">
            {IS_MOCK && <span className="chip border-status-amber/40 bg-status-amber/10 text-status-amber">Demo</span>}
            <span className="font-mono text-xs text-slate-500">{warehouse ? `v${warehouse.version}` : '—'}</span>
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={handleReset} disabled={busy}>Reset</button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        {error && (
          <div className="mb-5 flex items-start justify-between rounded-xl border border-status-red/40 bg-status-red/10 p-3 text-sm text-status-red">
            <span>{error}</span>
            <button className="ml-4 text-xs underline" onClick={() => setError(null)}>dismiss</button>
          </div>
        )}

        {tab === 'about' ? (
          <AboutView onStart={() => setTab('operations')} />
        ) : (
          <main className="space-y-6">
            <ZonesPanel
              warehouse={warehouse}
              projectedState={projectedState}
              onAddZone={handleAddZone}
              onEditZone={handleEditZone}
              onRemoveZone={handleRemoveZone}
              busy={busy}
              editable={IS_MOCK}
            />

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <AgentConsole onSubmit={handleSubmit} plan={plan} submitting={submitting} error={null} revoked={agentRevoked} />
              </div>
              <WorkflowStatus plan={plan} />
            </div>

            <ImageAttackPanel onSubmitImage={handleSubmitImage} plan={plan} submitting={submitting} isMock={IS_MOCK} />

            <PlanComparison plan={plan} />

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <AgentControls agent={agent} onRevoke={handleRevoke} busy={busy} />
              <AuditLog events={events} onClear={handleClearLog} />
            </div>
          </main>
        )}
      </div>

      <ApprovalModal
        plan={plan}
        onApprove={(id) => decide(api.approvePlan, id)}
        onDeny={(id) => decide(api.denyPlan, id)}
        busy={busy}
      />

      <footer className="mx-auto max-w-6xl px-4 py-8 text-center text-xs text-slate-600 sm:px-6">
        SentinelOS · AWS × A10 Hackathon · AI proposes, the backend decides.
      </footer>
    </div>
  )
}
