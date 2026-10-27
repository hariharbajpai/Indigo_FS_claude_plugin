import { describe, it, expect } from 'vitest'
import { validate } from './components/AddDepartmentForm.jsx'
import { filterMessages } from './views/ChatFeed.jsx'

describe('validate', () => {
  it('requires PDF and head name', () => {
    const e = validate({ files: [], name: 'X', headName: '' })
    expect(e.files).toMatch(/PDF/)
    expect(e.headName).toMatch(/Head/)
    expect(e.name).toBeUndefined()
  })
  it('passes with valid input', () => {
    const f = { name: 'a.pdf', type: 'application/pdf' }
    expect(validate({ files: [f], name: 'X', headName: 'Y' })).toEqual({})
  })
})
describe('filterMessages', () => {
  it('filters by task', () => {
    const ms = [{ id: 1, task_id: 't1' }, { id: 2, task_id: 't2' }]
    expect(filterMessages(ms, [], [], { dept: '', agent: '', task: 't2' })).toHaveLength(1)
  })
})

import { adaptMessage, adaptTask, adaptRequest, buildState } from './api.js'
describe('API.md adapters', () => {
  it('maps messages', () => {
    const m = adaptMessage({ id: 1, sender: 'owner', sender_name: 'Owner', recipient: 'chief', recipient_name: 'Dhruv', dept: 'x', body: 'hi', ts: 't' })
    expect(m).toMatchObject({ sender: 'Owner', recipient: 'Dhruv', text: 'hi', at: 't', dept_id: 'x', sender_kind: 'owner' })
  })
  it('maps tasks and requests', () => {
    const t = adaptTask({ id: 'TK-1', dept: 'd', acceptance: 'ok', notes: [{ author: 'ag-1', status: 'done', note: 'n', ts: 't' }] })
    expect(t).toMatchObject({ dept_id: 'd', acceptance_criteria: 'ok' })
    expect(t.notes[0]).toEqual({ at: 't', author: 'ag-1', status: 'done', text: 'n' })
    expect(adaptRequest({ id: 'WR-1', progress: { percent: 25 } }, { body: 'rep' })).toMatchObject({ progress: 25, report: 'rep' })
  })
  it('builds state', () => {
    const chief = { id: 'chief', name: 'C' }, head = { id: 'ag-1', name: 'H', dept: 'd' }
    const s = buildState({ overview: { counts: { agents: 2, messages: 0, departments: 1 } }, org: { chief, departments: [{ head, agents: [] }] },
      departments: [{ id: 'd' }], requests: [{ id: 'WR-1', progress: { percent: 0 } }], details: [{ request: { id: 'WR-1' }, briefs: [{ version: 1 }], report: null }],
      tasks: [{ id: 'TK-1', dept: 'd', notes: [{ author: 'ag-1', note: 'x', ts: 't' }] }], messages: [] })
    expect(s.agents.map((a) => a.dept_id)).toEqual([undefined, 'd'].map((x) => x ?? null))
    expect(s.tasks[0].notes[0].author).toBe('H')
    expect(s.briefs).toHaveLength(1)
  })
})
