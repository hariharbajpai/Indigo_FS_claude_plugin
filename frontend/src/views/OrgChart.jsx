import { useCallback, useMemo, useState } from 'react'
import { useStore } from '../useLive.js'
import OrgGraph from '../components/OrgGraph.jsx'
import OrgDetail from '../components/OrgDetail.jsx'
import LinksCard from '../components/LinksCard.jsx'
import { layoutOrg } from '../orgLayout.js'

export default function OrgChart() {
  const { data } = useStore()
  const [selected, setSelected] = useState(null)
  const working = useMemo(() => new Set(data.activity.running.map((a) => a.agent_id)), [data.activity.running])
  const chief = useMemo(() => ({ ...(data.chief || {}), id: 'chief', name: data.chief?.name || 'Dhruv Rebbapragada', role: data.chief?.role || 'Chief of Flight Safety' }), [data.chief])
  const depts = useMemo(() => [...data.departments].sort((a, b) => (a.status === 'retired') - (b.status === 'retired')), [data.departments])
  const graph = { chief, checker: data.checker, departments: depts, agents: data.agents }
  const node = selected ? layoutOrg(graph).nodes.find((n) => n.id === selected) : null
  const close = useCallback(() => {
    const id = selected
    setSelected(null)
    if (id) requestAnimationFrame(() => document.querySelector(`[data-node="${CSS.escape(id)}"]`)?.focus())
  }, [selected])
  const nodeBusy = (n) => (n.kind === 'dept'
    ? data.agents.some((a) => a.dept_id === n.dept.id && working.has(a.id))
    : working.has(n.id))

  return (
    <>
      <div className={`org-stage ${node ? 'has-detail' : ''}`}>
        <OrgGraph {...graph} working={working} selected={node ? selected : null} onSelect={setSelected} />
        {node && <OrgDetail node={node} data={{ ...data, chief }} working={nodeBusy(node)} onSelect={setSelected} onClose={close} />}
      </div>
      {depts.length === 0 && (
        <div className="empty">
          <strong>No departments yet</strong>
          In Claude Code run <code>/flight-safety-agents:add-dept</code>, or add one from the Owner Console.
        </div>
      )}
      <div className="org-legend">
        <span><span className="avatar chief sm">C</span> Chief</span>
        <span><span className="avatar checker sm">F</span> File Checker</span>
        <span><span className="legend-hub" /> Department</span>
        <span><span className="avatar head sm">H</span> Vertical Head</span>
        <span><span className="avatar sm">S</span> Specialist</span>
        <span><span className="dot working" /> Working now</span>
        <span>Click anyone to see what they do, their tasks and manuals, and to rename them.</span>
      </div>
      <LinksCard links={data.links} departments={data.departments} />
    </>
  )
}
