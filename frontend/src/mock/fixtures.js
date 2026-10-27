// Fixture state for the mock server, in the shapes of backend/API.md (v0.4.0).
const now = Date.now()
const ago = (m) => new Date(now - m * 60000).toISOString().replace(/\.\d+Z$/, 'Z')

export function makeState() {
  const chief = { id: 'chief', name: 'Dhruv Rebbapragada', role: 'Chief of Flight Safety', kind: 'chief', dept: null, status: 'active', created_at: ago(90) }
  const ag = (id, name, role, kind, dept, status = 'active') => ({ id, name, role, kind, dept, status, created_at: ago(80) })
  const dept = (id, name, head, status = 'active') => ({ id, name, head_id: head.id, head_name: head.name, status, created_at: ago(80) })
  const meera = ag('ag-1', 'Meera Rao', 'Vertical Head', 'head', 'maintenance')
  const sam = ag('ag-2', 'Samir Khan', 'Vertical Head', 'head', 'flight-operations')
  const old = ag('ag-3', 'Old Head', 'Vertical Head', 'head', 'legacy-fuel', 'retired')
  const hyd = ag('ag-4', 'Hydraulics Analyst', 'Hydraulics analyst', 'hired', 'maintenance')
  const note = (id, task_id, author, status, text, m) => ({ id, task_id, author, status, note: text, ts: ago(m) })
  const task = (id, title, d, agent, status, notes) => ({
    id, title, description: title, acceptance: 'Delivered and reviewed', dept: d,
    agent_id: agent?.id ?? null, agent_name: agent?.name ?? null, status, work_request_id: 'WR-1',
    created_at: ago(28), updated_at: ago(5), notes, message_count: 1,
  })
  return {
    chief,
    agents: [meera, sam, old, hyd],
    departments: [dept('maintenance', 'Maintenance', meera), dept('flight-operations', 'Flight Operations', sam), dept('legacy-fuel', 'Legacy Fuel', old, 'retired')],
    work_requests: [{ id: 'WR-1', text: 'Review hydraulic incidents of last quarter', status: 'In progress', created_at: ago(30), updated_at: ago(5), brief_version: 1 }],
    briefs: [{ work_request_id: 'WR-1', version: 1, summary: 'Audit hydraulic incidents and propose fixes.', goals: ['Find root causes', 'Check crew procedures'], departments: ['maintenance'], needs_department: false, question: null, change_note: null, created_at: ago(28) }],
    tasks: [
      task('TK-1', 'Collect hydraulic incident logs', 'maintenance', hyd, 'in_progress', [note(1, 'TK-1', 'chief', 'todo', 'Assigned to Maintenance', 25), note(2, 'TK-1', 'ag-4', 'in_progress', 'Started collecting logs', 10)]),
      task('TK-2', 'Review crew procedures', 'flight-operations', sam, 'todo', [note(3, 'TK-2', 'chief', 'todo', 'Assigned to Flight Operations', 25)]),
      task('TK-3', 'Summarise findings', 'maintenance', meera, 'done', [note(4, 'TK-3', 'ag-1', 'done', 'Done', 5)]),
    ],
    messages: [
      { id: 1, sender: 'owner', sender_name: 'Owner', recipient: 'chief', recipient_name: chief.name, dept: null, task_id: null, work_request_id: 'WR-1', kind: 'request', body: 'Review hydraulic incidents of last quarter', ts: ago(30) },
      { id: 2, sender: 'chief', sender_name: chief.name, recipient: 'ag-1', recipient_name: meera.name, dept: 'maintenance', task_id: 'TK-1', work_request_id: 'WR-1', kind: 'assign', body: 'Please start on the incident logs.', ts: ago(25) },
      { id: 3, sender: 'ag-1', sender_name: meera.name, recipient: 'ag-4', recipient_name: hyd.name, dept: 'maintenance', task_id: 'TK-1', work_request_id: 'WR-1', kind: 'hire', body: 'Hired you for this; see TK-1.', ts: ago(20) },
    ],
  }
}
