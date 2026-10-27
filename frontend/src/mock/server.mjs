// Mock API on :8000 following backend/API.md (v0.4.0). Run: npm run mock
import http from 'node:http'
import { makeState } from './fixtures.js'

const S = makeState()
const clients = new Set()
let n = 100, eventId = 100
const iso = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z')
const emit = (type, data = {}) => {
  const frame = `id: ${++eventId}\nevent: ${type}\ndata: ${JSON.stringify({ id: eventId, type, ts: iso(), data })}\n\n`
  clients.forEach((r) => r.write(frame))
}
const slug = (s) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
const agent = (id) => (id === 'chief' ? S.chief : S.agents.find((a) => a.id === id))
const nameOf = (id) => (id === 'owner' ? 'Owner' : agent(id)?.name || id)

function addMsg(sender, recipient, body, kind, extra = {}) {
  const m = { id: ++n, sender, sender_name: nameOf(sender), recipient, recipient_name: nameOf(recipient), dept: null, task_id: null, work_request_id: null, kind, body, ts: iso(), ...extra }
  S.messages.push(m); emit('message.created', { id: m.id }); return m
}
const progress = (wr) => {
  const mine = S.tasks.filter((t) => t.work_request_id === wr.id)
  const done = mine.filter((t) => t.status === 'done').length
  return { total: mine.length, done, percent: mine.length ? Math.round((done / mine.length) * 100) : 0 }
}
const wrOut = (w) => ({ ...w, progress: progress(w) })
const briefsOf = (id) => S.briefs.filter((b) => b.work_request_id === id)
function setStatus(t, status, author, note) {
  t.status = status; t.updated_at = iso()
  t.notes.push({ id: ++n, task_id: t.id, author, status, note, ts: iso() })
  const wr = S.work_requests.find((w) => w.id === t.work_request_id)
  const p = progress(wr)
  wr.status = p.done === p.total ? 'Done' : 'In progress'
  addMsg(author, 'chief', `Task ${t.id} -> ${status}: ${note}`, 'status', { task_id: t.id, dept: t.dept, work_request_id: wr.id })
  emit('task.updated', { id: t.id })
  if (wr.status === 'Done') {
    addMsg('chief', 'owner', `${wr.id} complete. All tasks done.`, 'report', { work_request_id: wr.id }); emit('report.posted', { work_request_id: wr.id })
  }
}

// Simulate agents working: advance a random open task every 6s.
setInterval(() => {
  const order = ['todo', 'in_progress', 'review', 'done']
  const open = S.tasks.filter((t) => t.status !== 'done' && t.status !== 'blocked')
  if (!open.length) return
  const t = open[Math.floor(Math.random() * open.length)]
  setStatus(t, order[order.indexOf(t.status) + 1], t.agent_id || 'chief', 'simulated progress')
}, 6000)

const body = (req) => new Promise((ok) => { const c = []; req.on('data', (d) => c.push(d)); req.on('end', () => ok(Buffer.concat(c))) })
const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type' }
const send = (res, code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json', ...CORS }); res.end(JSON.stringify(obj)) }
const orgRow = (d) => {
  const hired = S.agents.filter((a) => a.dept === d.id && a.kind === 'hired' && a.status === 'active')
  return { department: d, head: agent(d.head_id), agents: hired, active_count: hired.length + (d.status === 'active' ? 1 : 0), hire_cap: 5 }
}
const field = (s, k) => new RegExp(`name="${k}"\\r\\n\\r\\n([^\\r]*)`).exec(s)?.[1]

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x')
  const p = url.pathname, q = url.searchParams, get = req.method === 'GET'
  if (req.method === 'OPTIONS') { res.writeHead(204, { ...CORS, 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' }); return res.end() }
  if (p === '/api/events') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive', ...CORS })
    res.write(': keepalive\n\n'); clients.add(res); req.on('close', () => clients.delete(res)); return
  }
  if (get && p === '/api/health') return send(res, 200, { ok: true, version: '0.4.0' })
  if (get && p === '/api/overview') {
    const tasks = { todo: 0, in_progress: 0, review: 0, blocked: 0, done: 0 }
    S.tasks.forEach((t) => tasks[t.status]++)
    return send(res, 200, { chief: S.chief, counts: { departments: S.departments.filter((d) => d.status === 'active').length, agents: S.agents.filter((a) => a.status === 'active').length + 1, work_requests: S.work_requests.length, tasks, messages: S.messages.length }, work_requests: S.work_requests.map(wrOut).reverse(), last_event_id: eventId })
  }
  if (get && p === '/api/org') {
    const all = q.get('include_retired') === 'true'
    return send(res, 200, { chief: S.chief, departments: S.departments.filter((d) => all || d.status === 'active').map(orgRow) })
  }
  if (get && p === '/api/departments') return send(res, 200, S.departments.filter((d) => q.get('include_retired') === 'true' || d.status === 'active'))
  if (get && p === '/api/work-requests') return send(res, 200, S.work_requests.map(wrOut).reverse())
  let m = /^\/api\/work-requests\/([^/]+)$/.exec(p)
  if (get && m) {
    const w = S.work_requests.find((x) => x.id === m[1])
    if (!w) return send(res, 404, { detail: 'Unknown work request' })
    const bs = briefsOf(w.id)
    return send(res, 200, { request: wrOut(w), briefs: bs, brief: bs.at(-1) || null, tasks: S.tasks.filter((t) => t.work_request_id === w.id), report: S.messages.filter((x) => x.kind === 'report' && x.work_request_id === w.id).at(-1) || null })
  }
  if (get && p === '/api/tasks') return send(res, 200, S.tasks.filter((t) => (!q.get('status') || t.status === q.get('status')) && (!q.get('dept') || t.dept === q.get('dept'))))
  if (get && p === '/api/messages') return send(res, 200, S.messages.filter((x) => !q.get('task') || x.task_id === q.get('task')).slice(-Number(q.get('limit') || 500)))
  if (req.method !== 'POST') return send(res, 404, { detail: 'not found' })

  const raw = await body(req)
  const ctype = req.headers['content-type'] || ''
  const json = () => { try { return JSON.parse(raw.toString() || '{}') } catch { return {} } }
  if (p === '/api/work-requests') {
    const { text } = json()
    if (!text || !text.trim()) return send(res, 422, { detail: 'text must not be empty' })
    const w = { id: `WR-${S.work_requests.length + 1}`, text, status: 'Received', created_at: iso(), updated_at: iso(), brief_version: null }
    S.work_requests.push(w); emit('work_request.created', { id: w.id })
    addMsg('owner', 'chief', text, 'request', { work_request_id: w.id })
    setTimeout(() => {
      w.status = 'Briefed'; w.brief_version = 1; w.updated_at = iso()
      S.briefs.push({ work_request_id: w.id, version: 1, summary: `Plan for: ${text}`, goals: ['Understand scope'], departments: ['flight-operations'], needs_department: false, question: null, change_note: null, created_at: iso() })
      emit('brief.created', { work_request_id: w.id })
      const sam = agent('ag-2')
      S.tasks.push({ id: `TK-${S.tasks.length + 1}`, title: `Handle: ${text.slice(0, 40)}`, description: text, acceptance: 'Owner accepts result', dept: 'flight-operations', agent_id: sam.id, agent_name: sam.name, status: 'todo', work_request_id: w.id, created_at: iso(), updated_at: iso(), notes: [], message_count: 0 })
      emit('task.created', { work_request_id: w.id }); emit('work_request.updated', { id: w.id })
    }, 2000)
    return send(res, 201, wrOut(w))
  }
  if (p === '/api/instructions') {
    const { target, text } = json()
    if (!text || !text.trim()) return send(res, 422, { detail: 'text must not be empty' })
    if (target !== 'chief' && !S.departments.find((d) => d.id === target)) return send(res, 404, { detail: 'Unknown department' })
    const to = target === 'chief' ? 'chief' : S.departments.find((d) => d.id === target).head_id
    const msg = addMsg('owner', to, text, 'instruction', { dept: target === 'chief' ? null : target })
    return send(res, 201, { message: msg, brief: null, blocked_tasks: [] })
  }
  if (p === '/api/departments') {
    const s = raw.toString('latin1')
    const name = field(s, 'name'), head = field(s, 'head_name'), decision = field(s, 'decision')
    if (!ctype.startsWith('multipart') || !/filename=/.test(s)) return send(res, 400, { detail: 'Upload at least one PDF' })
    if (!head || !head.trim()) return send(res, 400, { detail: 'Vertical Head name is required' })
    if (!name || !name.trim()) return send(res, 400, { detail: 'Department name is required' })
    const existing = S.departments.find((d) => d.id === slug(name) && d.status === 'active')
    if (existing && !decision) return send(res, 409, { status: 'needs_decision', matches: [{ file: /filename="([^"]*)"/.exec(s)?.[1] || 'file.pdf', result: /v2/i.test(s) ? 'new_version' : 'duplicate', existing_dept: existing.id, detail: 'Similar to existing department' }] })
    const hid = `ag-${S.agents.length + 1}`
    const head_ag = { id: hid, name: head, role: 'Vertical Head', kind: 'head', dept: slug(name), status: 'active', created_at: iso() }
    const d = { id: slug(name), name, head_id: hid, head_name: head, status: 'active', created_at: iso() }
    S.agents.push(head_ag); S.departments.push(d); emit('department.created', { id: d.id })
    return send(res, 201, { status: 'created', department: d, head: head_ag, matches: [] })
  }
  m = /^\/api\/departments\/([^/]+)\/(replace|retire)$/.exec(p)
  if (m) {
    const d = S.departments.find((x) => x.id === m[1])
    if (!d) return send(res, 404, { detail: 'Unknown department' })
    if (m[2] === 'replace') return send(res, 200, { status: 'replaced', department: d })
    d.status = 'retired'
    const retired = S.agents.filter((a) => a.dept === d.id && a.status === 'active')
    retired.forEach((a) => { a.status = 'retired' })
    S.tasks.filter((t) => t.dept === d.id && t.status !== 'done').forEach((t) => setStatus(t, 'blocked', d.head_id, 'Department retired'))
    emit('department.retired', { id: d.id })
    return send(res, 200, { department: d, retired_agents: retired.map((a) => a.id) })
  }
  send(res, 404, { detail: 'not found' })
}).listen(8000, () => console.log('mock API on http://localhost:8000'))
