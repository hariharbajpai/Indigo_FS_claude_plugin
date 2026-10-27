// API client for backend/API.md (v0.4.0). getState() composes several endpoints into the shape the views use.
async function request(path, opts = {}) {
  const res = await fetch('/api' + path, opts)
  let body = null
  try { body = await res.json() } catch { /* empty body */ }
  if (!res.ok) {
    const detail = body && (body.detail || body.error || body.message)
    const msg = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `Request failed (${res.status})`
    const err = new Error(msg)
    err.status = res.status
    err.body = body
    throw err
  }
  return body
}

const json = (method, data) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

const EMPTY = {
  chief: null, departments: [], agents: [], work_requests: [],
  briefs: [], tasks: [], messages: [], stats: null,
}

// Fill missing collections so views never crash on a partial payload.
export function normalizeState(s) {
  const out = { ...EMPTY, ...(s || {}) }
  for (const k of ['departments', 'agents', 'work_requests', 'briefs', 'tasks', 'messages']) {
    if (!Array.isArray(out[k])) out[k] = []
  }
  return out
}

// ---- adapters: API.md shapes -> view shapes ----
export const adaptAgent = (a) => ({ ...a, dept_id: a.dept ?? null })
export const adaptTask = (t) => ({
  ...t,
  dept_id: t.dept,
  acceptance_criteria: t.acceptance,
  notes: (t.notes || []).map((n) => ({ at: n.ts, author: n.author, status: n.status, text: n.note })),
})
export const adaptMessage = (m) => ({
  ...m,
  sender_id: m.sender,
  sender: m.sender_name || m.sender,
  recipient: m.recipient_name || m.recipient,
  sender_kind: m.sender === 'owner' ? 'owner' : 'agent',
  dept_id: m.dept ?? null,
  text: m.body,
  at: m.ts,
})
export const adaptRequest = (w, report) => ({ ...w, progress: w.progress?.percent ?? 0, report: report ? report.body : null })

// Build the view state from the REST endpoints.
export function buildState({ overview, org, departments, requests, details, tasks, messages }) {
  const agents = new Map()
  const add = (a) => a && agents.set(a.id, adaptAgent(a))
  add(org.chief)
  for (const row of org.departments) { add(row.head); (row.agents || []).forEach(add) }
  const agentName = (id) => agents.get(id)?.name || id
  const taskList = tasks.map(adaptTask).map((t) => ({
    ...t, notes: t.notes.map((n) => ({ ...n, author: agentName(n.author) })),
  }))
  const reports = Object.fromEntries(details.map((d) => [d.request.id, d.report]))
  return normalizeState({
    chief: org.chief,
    departments,
    agents: [...agents.values()],
    work_requests: requests.map((w) => adaptRequest(w, reports[w.id])),
    briefs: details.flatMap((d) => d.briefs || []),
    tasks: taskList,
    messages: messages.map(adaptMessage),
    stats: { agents: overview.counts.agents, messages: overview.counts.messages, departments: overview.counts.departments },
  })
}

async function loadState() {
  const [overview, org, departments, requests, tasks, messages] = await Promise.all([
    request('/overview'), request('/org?include_retired=true'), request('/departments?include_retired=true'),
    request('/work-requests'), request('/tasks'), request('/messages'),
  ])
  const details = await Promise.all(requests.map((w) => request(`/work-requests/${encodeURIComponent(w.id)}`)))
  return buildState({ overview, org, departments, requests: requests.slice().reverse(), details, tasks, messages })
}

export const api = {
  getState: async () => loadState(),
  submitWork: (text) => request('/work-requests', json('POST', { text })),
  sendInstruction: (target, text) => request('/instructions', json('POST', { target, text })),
  // decision: undefined (ask first) | 'replace' (with target dept id) | 'new'
  // Returns {status:'created'|'needs_decision', ...}. A 409 needs_decision is a normal answer, not an error.
  addDepartment: async ({ files, name, headName, decision, target }) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    fd.append('name', name)
    fd.append('head_name', headName)
    if (decision) fd.append('decision', decision)
    if (target) fd.append('target', target)
    try {
      return await request('/departments', { method: 'POST', body: fd })
    } catch (err) {
      if (err.status === 409 && err.body?.status === 'needs_decision') return err.body
      throw err
    }
  },
  replaceDepartment: (id, files) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    return request(`/departments/${encodeURIComponent(id)}/replace`, { method: 'POST', body: fd })
  },
  retireDepartment: (id) => request(`/departments/${encodeURIComponent(id)}/retire`, { method: 'POST' }),
}
