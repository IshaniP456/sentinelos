// Single source of truth for all backend communication (contract §5.3).
// React components MUST call these functions and never issue raw fetch()
// calls of their own.
//
// Set VITE_MOCK=false and VITE_API_BASE_URL=<api gateway /v1 url> to talk to
// the real backend. Until then, an in-browser engine implements the same
// contract so the dashboard is fully interactive.

import { mockApi } from '../mock/engine.js'

const MOCK = (import.meta.env.VITE_MOCK ?? 'true') !== 'false'
const BASE = import.meta.env.VITE_API_BASE_URL || '/v1'

// Normalize any failure into an Error carrying the standard error object
// (contract §3.6) on `.payload.error` when the backend provided one.
async function request(method, path, body) {
  let res
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'include', // admin session cookie for mutating routes
    })
  } catch (networkErr) {
    const err = new Error('Network error — could not reach SentinelOS API.')
    err.payload = { error: { code: 'NETWORK_ERROR', message: err.message, retryable: true } }
    throw err
  }

  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  if (!res.ok) {
    const err = new Error(data?.error?.message || `Request failed (${res.status})`)
    err.status = res.status
    err.payload = data || {
      error: { code: 'INTERNAL_ERROR', message: `HTTP ${res.status}`, retryable: res.status >= 500 },
    }
    throw err
  }
  return data
}

// --- public surface — consumed by React components --------------------------

export function submitPlan(instruction) {
  if (MOCK) return mockApi.submitPlan(instruction)
  return request('POST', '/plans', { instruction })
}

// Image prompt-injection input (Tishneet's image contract). Exactly one body
// variant: image (never mixed with text). Scripted preset adds demo_mode.
// Browser never holds model credentials.
export function submitImage({ image_b64, mime_type, demo_mode, instruction } = {}) {
  if (MOCK) return mockApi.submitImage({ image_b64, mime_type, demo_mode })
  // The deployed Lambda has no image handler, so a scripted preset can't run
  // image extraction live. Instead we submit the (scripted) extracted text as a
  // real text plan: the extraction is scripted, but the LIMIT_EXCEEDED rejection
  // is produced live by the real policy engine. Labeled as such in the panel.
  if (demo_mode && instruction) return request('POST', '/plans', { instruction })
  const body = { image_b64, mime_type }
  if (demo_mode) body.demo_mode = demo_mode
  return request('POST', '/plans', body)
}

export function getPlanStatus(planId) {
  if (MOCK) return mockApi.getPlanStatus(planId)
  return request('GET', `/plans/${encodeURIComponent(planId)}`)
}

export function getWarehouse() {
  if (MOCK) return mockApi.getWarehouse()
  return request('GET', '/warehouse')
}

export function getAgent() {
  if (MOCK) return mockApi.getAgent()
  return request('GET', '/agents/current')
}

export function getAuditLog(planId) {
  if (MOCK) return mockApi.getAuditLog(planId)
  const qs = planId ? `?plan_id=${encodeURIComponent(planId)}` : ''
  return request('GET', `/audit${qs}`)
}

// Clear the activity log (mock/demo convenience; no-op display clear on real).
export function clearAudit() {
  if (MOCK) return mockApi.clearAudit()
  return Promise.resolve({ events: [] })
}

export function approvePlan(approvalId) {
  if (MOCK) return mockApi.decideApproval(approvalId, 'APPROVED')
  return request('POST', `/approvals/${encodeURIComponent(approvalId)}`, { decision: 'APPROVED' })
}

export function denyPlan(approvalId) {
  if (MOCK) return mockApi.decideApproval(approvalId, 'DENIED')
  return request('POST', `/approvals/${encodeURIComponent(approvalId)}`, { decision: 'DENIED' })
}

export function revokeAgent() {
  if (MOCK) return mockApi.revokeAgent()
  return request('POST', '/agents/current/revoke', {})
}

export function resetDemo() {
  if (MOCK) return mockApi.resetDemo()
  return request('POST', '/demo/reset', {})
}

// --- zone management (mock-only; real backend has fixed demo zones) ----------
export function addZone(name, capacity, inventory = 0) {
  if (MOCK) return mockApi.addZone(name, capacity, inventory)
  return Promise.reject(makeUnsupported('add zone'))
}

export function editZone(name, patch) {
  if (MOCK) return mockApi.editZone(name, patch)
  return Promise.reject(makeUnsupported('edit zone'))
}

export function removeZone(name) {
  if (MOCK) return mockApi.removeZone(name)
  return Promise.reject(makeUnsupported('remove zone'))
}

function makeUnsupported(what) {
  const e = new Error(`Zone management (${what}) is a demo-mode feature; the real warehouse uses fixed zones.`)
  e.payload = { error: { code: 'INVALID_REQUEST', message: e.message, retryable: false } }
  return e
}

export const IS_MOCK = MOCK
