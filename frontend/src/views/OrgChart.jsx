import { useEffect, useRef } from 'react'
import { useStore } from '../useLive.js'
import OrgCard from '../components/OrgCard.jsx'
import RenameButton from '../components/RenameButton.jsx'
import { api } from '../api.js'

export default function OrgChart() {
  const { data, refresh } = useStore()
  const working = new Set(data.activity.running.map((a) => a.agent_id))
  const chief = { ...(data.chief || {}), name: data.chief?.name || 'Dhruv Rebbapragada', role: data.chief?.role || 'Chief of Flight Safety' }
  const depts = [...data.departments].sort((a, b) => (a.status === 'retired') - (b.status === 'retired'))
  const wrap = useRef(null)
  useEffect(() => { // a wide chart starts centred on the Chief
    const el = wrap.current
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2
  }, [depts.length])
  return (
    <>
      <div className="org-wrap card" aria-label="Organisation chart" ref={wrap}>
        <div className="org">
          <OrgCard agent={chief} kind="chief" working={working.has('chief')} />
          {depts.length === 0 ? (
            <div className="empty" style={{ marginTop: 28 }}>
              <strong>No departments yet</strong>
              In Claude Code run <code>/flight-safety-agents:add-dept</code>, or add one from the Owner Console.
            </div>
          ) : (
            <ul className="org-tree">
              {depts.map((d) => {
                const head = data.agents.find((a) => a.id === d.head_id)
                const staff = data.agents.filter((a) => a.dept_id === d.id && a.id !== d.head_id)
                const retired = d.status === 'retired'
                const active = (head && head.status !== 'retired' ? 1 : 0) + staff.filter((a) => a.status !== 'retired').length
                return (
                  <li key={d.id}>
                    <div className={`dept ${retired ? 'retired' : ''}`}>
                      <div className="dept-label">
                        {d.name}{retired ? ' · retired' : <span className="cap">{active}/5</span>}
                        {!retired && <RenameButton current={d.name} label={`department ${d.name}`}
                          onSave={async (name) => { await api.renameDepartment(d.id, name); await refresh() }} />}
                      </div>
                      {head && <OrgCard agent={head} kind="head" working={working.has(head.id)} />}
                      {staff.length > 0 && (
                        <ul className="staff">
                          {staff.map((a) => (
                            <li key={a.id}><OrgCard agent={a} kind="hired" working={working.has(a.id)} reason={a.hire_reason} /></li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
      <div className="org-legend">
        <span><span className="avatar chief sm">C</span> Chief</span>
        <span><span className="avatar head sm">H</span> Vertical Head</span>
        <span><span className="avatar sm">S</span> Specialist</span>
        <span><span className="dot working" /> Working now</span>
        <span>Hover a card to rename it, or run <code>/flight-safety-agents:rename &lt;who&gt; -&gt; &lt;new name&gt;</code></span>
      </div>
    </>
  )
}
