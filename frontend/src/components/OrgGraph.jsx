import { useEffect, useMemo, useRef } from 'react'
import { layoutOrg, pathTo, edgePath, RADIUS, SLOT } from '../orgLayout.js'
import { initials } from './Avatar.jsx'
import { Icon } from './Icons.jsx'

const KIND = { chief: 'Chief', checker: 'File Checker', dept: 'Department', head: 'Vertical Head', hired: 'Specialist' }

export const nodeName = (n) => (n.kind === 'dept' ? n.dept.name : n.agent?.name || '')
const isRetired = (n) => (n.kind === 'dept' ? n.dept.status : n.agent?.status) === 'retired'

// The organisation as a graph: every node shows only a name. Clicking one calls onSelect(node id).
export default function OrgGraph({ chief, checker, departments, agents, working, selected, onSelect }) {
  const { nodes, edges, width, height } = useMemo(
    () => layoutOrg({ chief, checker, departments, agents }),
    [chief, checker, departments, agents],
  )
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const lit = useMemo(() => (selected ? pathTo(edges, selected) : new Set()), [edges, selected])
  const busy = (n) => (n.kind === 'dept'
    ? agents.some((a) => a.dept_id === n.dept.id && working.has(a.id))
    : working.has(n.id))

  const wrap = useRef(null)
  useEffect(() => { // a wide graph starts centred on the Chief
    const el = wrap.current
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2
  }, [width])
  useEffect(() => { // bring the selected node into view, e.g. after a click on a name in the card
    const el = wrap.current
    const n = selected && byId.get(selected)
    if (!el || !n || el.scrollWidth <= el.clientWidth) return
    const x = n.x + el.firstElementChild.getBoundingClientRect().left - el.getBoundingClientRect().left + el.scrollLeft
    if (x - SLOT / 2 < el.scrollLeft || x + SLOT / 2 > el.scrollLeft + el.clientWidth) {
      el.scrollTo({ left: x - el.clientWidth / 2, behavior: 'smooth' })
    }
  }, [selected, byId])

  return (
    <div className="org-wrap card" ref={wrap}>
      <div className="org-graph" role="group" aria-label="Organisation chart" style={{ width, height }}>
        <svg className="org-edges" width={width} height={height} aria-hidden="true">
          {edges.map((e) => {
            const a = byId.get(e.from), b = byId.get(e.to)
            const cls = ['edge', b.kind === 'hired' ? 'dashed' : '', busy(b) ? 'live' : '',
              lit.has(e.to) && lit.has(e.from) ? 'on' : '', isRetired(b) ? 'retired' : ''].filter(Boolean).join(' ')
            return <path key={`${e.from}>${e.to}`} className={cls} d={edgePath(a, b)} />
          })}
        </svg>
        {nodes.map((n) => {
          const r = RADIUS[n.kind]
          const name = nodeName(n)
          const on = selected === n.id
          const cls = ['gnode', n.kind, busy(n) ? 'working' : '', isRetired(n) ? 'retired' : '', on ? 'selected' : '',
            lit.has(n.id) && !on ? 'trail' : ''].filter(Boolean).join(' ')
          return (
            <button key={n.id} type="button" data-node={n.id} className={cls} aria-pressed={on}
              aria-label={`${name}, ${KIND[n.kind]}${isRetired(n) ? ', retired' : ''}${busy(n) ? ', working now' : ''}`}
              title={name} onClick={() => onSelect(on ? null : n.id)}
              style={{ left: n.x - SLOT / 2, top: n.y - r, width: SLOT, '--r': `${r}px` }}>
              <span className="gnode-dot">
                {n.kind === 'dept' ? <Icon name="building" /> : n.kind === 'checker' ? <Icon name="file" /> : initials(name)}
              </span>
              <span className="gnode-name">{name}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
