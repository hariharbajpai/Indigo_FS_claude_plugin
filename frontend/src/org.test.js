import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { render, screen, fireEvent, cleanup, within, waitFor } from '@testing-library/react'
import { layoutOrg, pathTo, SLOT } from './orgLayout.js'
import { LiveContext } from './useLive.js'
import { api } from './api.js'
import OrgChart from './views/OrgChart.jsx'
import { clip, shortRole } from './roles.js'

globalThis.CSS ??= { escape: (s) => String(s) } // jsdom has no CSS.escape; closing a card uses it

const CHIEF_ROLE = 'Chief of Flight Safety (FSM Issue 5 Rev 0 §2.3.1, pp41-42). RACI from FSM Issue 5 Rev 0 §2.3.1: '
  + 'A (accountable): effective implementation and application of the SMS in all IndiGo departments.'
const FACT_CHECKER = 'Independent fact-checker (C), Safety. Checks every Safety department output against the Safety library.'

describe('short role', () => {
  it('keeps the title and drops manual references and the rest', () => {
    expect(shortRole(CHIEF_ROLE)).toBe('Chief of Flight Safety')
    expect(shortRole(FACT_CHECKER)).toBe('Independent fact-checker, Safety')
    expect(shortRole('Associate Director (Emergency Response & Cabin Safety), ag-4 — leads ERM drills'))
      .toBe('Associate Director (Emergency Response & Cabin Safety), ag-4')
    expect(shortRole('Vertical Head')).toBe('Vertical Head')
    expect(shortRole('')).toBe('')
  })

  it('cuts a long title at a word, with an ellipsis', () => {
    const s = shortRole('Senior specialist for hydraulic, pneumatic and landing gear repeat defect trend analysis across the fleet', 48)
    expect(s.length).toBeLessThanOrEqual(48)
    expect(s.endsWith('…')).toBe(true)
    expect(s).not.toMatch(/\s…$/)
    expect(clip('short', 10)).toBe('short')
  })
})

const REASON = 'TK-1 needs someone to read the hydraulic incident logs against the AMM Rev 12 and list every repeat defect.'
const chief = { id: 'chief', name: 'Dhruv Rebbapragada', role: 'Chief of Flight Safety', kind: 'chief', status: 'active' }
const checker = { id: 'checker', name: 'File Checker', role: 'Documentation Controller', kind: 'checker', status: 'active' }
const head = (id, name, dept) => ({ id, name, role: 'Vertical Head', kind: 'head', dept_id: dept, status: 'active' })
const hired = (id, name, dept, reason = 'Needed for a task') => ({ id, name, role: 'Analyst', kind: 'hired', dept_id: dept, hire_reason: reason, status: 'active' })
const dept = (id, name, headId) => ({ id, name, head_id: headId, status: 'active' })

const agents = [chief, checker, head('ag-1', 'Meera Rao', 'mx'), head('ag-2', 'Samir Khan', 'ops'),
  hired('ag-3', 'Hydraulics Analyst', 'mx', REASON), hired('ag-4', 'Engine Analyst', 'mx'), hired('ag-5', 'Crew Trainer', 'ops')]
const departments = [dept('mx', 'Maintenance', 'ag-1'), dept('ops', 'Flight Operations', 'ag-2')]

describe('organisation graph layout', () => {
  const { nodes, edges, width } = layoutOrg({ chief, checker, departments, agents })
  const at = (id) => nodes.find((n) => n.id === id)

  it('puts the Chief on top, then the File Checker, departments, heads and specialists', () => {
    expect(at('chief').x).toBe(width / 2)
    const rows = ['chief', 'checker', 'dept:mx', 'ag-1', 'ag-3'].map((id) => at(id).y)
    expect([...rows].sort((a, b) => a - b)).toEqual(rows)
    expect(at('ag-3').y).toBe(at('ag-5').y)
    expect(at('ag-1').x).toBe(at('dept:mx').x) // the head sits under its department
  })

  it('never lets two nodes of a row overlap', () => {
    const byRow = Object.groupBy(nodes, (n) => n.y)
    for (const row of Object.values(byRow)) {
      const xs = row.map((n) => n.x).sort((a, b) => a - b)
      xs.slice(1).forEach((x, i) => expect(x - xs[i]).toBeGreaterThanOrEqual(SLOT))
    }
  })

  it('links everyone up to the Chief', () => {
    expect(edges).toHaveLength(nodes.length - 1)
    expect([...pathTo(edges, 'ag-3')]).toEqual(['ag-3', 'ag-1', 'dept:mx', 'checker', 'chief'])
  })

  it('works without a File Checker or departments', () => {
    const g = layoutOrg({ chief, checker: null, departments: [], agents: [chief] })
    expect(g.nodes.map((n) => n.id)).toEqual(['chief'])
    expect(g.edges).toEqual([])
  })
})

describe('organisation page', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks() })
  const data = {
    chief, checker, departments, agents, tasks: [{ id: 'TK-1', title: 'Collect hydraulic incident logs', status: 'in_progress', agent_id: 'ag-3', dept_id: 'mx' }],
    files: [], work_requests: [], links: [], activity: { running: [{ agent_id: 'ag-3' }], waiting: [], recent: [] },
  }
  const show = () => render(createElement(LiveContext.Provider, { value: { data, refresh: async () => {} } }, createElement(OrgChart)))

  it('shows only names on the graph, and the details after a click', async () => {
    vi.spyOn(api, 'departmentDocuments').mockResolvedValue({ documents: [{ id: 'amm', title: 'Aircraft Maintenance Manual', revision: 'Rev 12' }] })
    show()
    const graph = screen.getByRole('group', { name: 'Organisation chart' })
    expect(within(graph).getByText('Hydraulics Analyst')).toBeTruthy()
    expect(screen.queryByText(REASON)).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Hydraulics Analyst, Specialist/ }))
    const card = screen.getByRole('dialog')
    expect(within(card).getByRole('heading', { name: 'Hydraulics Analyst' })).toBeTruthy()
    expect(within(card).getByText(REASON)).toBeTruthy()
    expect(within(card).getByText(/Collect hydraulic incident logs/)).toBeTruthy()
    expect(within(card).getByText('Working now')).toBeTruthy()
    expect(await within(card).findByText('Aircraft Maintenance Manual')).toBeTruthy()

    fireEvent.click(within(card).getByRole('button', { name: /Meera Rao/ })) // Reports to
    expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Meera Rao' })).toBeTruthy()

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('shows a short line under each name and keeps the long role out of sight', () => {
    vi.spyOn(api, 'departmentDocuments').mockResolvedValue({ documents: [] })
    const long = { ...agents[4], role: `${FACT_CHECKER} ${'Checks every Safety department output. '.repeat(8)}` }
    render(createElement(LiveContext.Provider, { value: { data: { ...data, agents: agents.map((a) => (a.id === long.id ? long : a)) }, refresh: async () => {} } },
      createElement(OrgChart)))
    const graph = screen.getByRole('group', { name: 'Organisation chart' })
    expect(within(graph).getByText('Independent fact-checker, Safety')).toBeTruthy()
    expect(within(graph).getAllByText('Vertical Head', { selector: '.gnode-desc' })).toHaveLength(2)
    expect(within(graph).getByText('3 people')).toBeTruthy()
    expect(within(graph).queryByText(/Checks every/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Hydraulics Analyst, Specialist/ }))
    const card = screen.getByRole('dialog')
    expect(within(card).getByText('Independent fact-checker, Safety')).toBeTruthy()
    const more = card.querySelector('details.od-more')
    expect(more.open).toBe(false)
    expect(within(more).getByText('Full role')).toBeTruthy()
  })

  it('opens a department card with its people and manuals', async () => {
    vi.spyOn(api, 'departmentDocuments').mockResolvedValue({ documents: [{ id: 'fom', title: 'Flight Operations Manual', revision: 'Rev 4', pages: 210 }] })
    show()
    fireEvent.click(screen.getByRole('button', { name: /Flight Operations, Department/ }))
    const card = screen.getByRole('dialog')
    expect(within(card).getByText('2/5 people')).toBeTruthy()
    expect(within(card).getByRole('button', { name: /Crew Trainer/ })).toBeTruthy()
    expect(await within(card).findByText('Rev 4 · 210 pages')).toBeTruthy()
  })
})
