import { useStore } from '../useLive.js'
import AgentNode from '../components/AgentNode.jsx'
import RenameButton from '../components/RenameButton.jsx'
import { api } from '../api.js'

export default function OrgChart() {
  const { data, refresh } = useStore()
  const chief = data.chief
  const working = new Set(data.activity.running.map((a) => a.agent_id))
  return (
    <section className="tree">
      <h2>Org Chart</h2>
      <ul style={{ borderLeft: 0, paddingLeft: 0 }}>
        <AgentNode agent={{ ...(chief || {}), name: chief?.name || 'Dhruv Rebbapragada', role: chief?.role || 'Chief of Flight Safety' }}
          working={working.has('chief')}>
          {data.departments.length === 0
            ? <p className="muted">No departments yet. In Claude Code run /flight-safety-agents:add-dept, or add one from the Owner Console.</p>
            : (
              <ul>
                {data.departments.map((d) => {
                  const head = data.agents.find((a) => a.id === d.head_id)
                  const hired = data.agents.filter((a) => a.dept_id === d.id && a.id !== d.head_id)
                  const retired = d.status === 'retired'
                  return (
                    <li key={d.id}>
                      <div className={`small ${retired ? 'muted' : ''}`}><strong>{d.name}</strong>{retired && ' (retired)'}
                        {!retired && <> {' '}<RenameButton current={d.name} label={`department ${d.name}`}
                          onSave={async (name) => { await api.renameDepartment(d.id, name); await refresh() }} /></>}
                      </div>
                      <ul>
                        {head && <AgentNode agent={head} working={working.has(head.id)}>
                          {hired.length > 0 && <ul>{hired.map((h) => <AgentNode key={h.id} agent={h} working={working.has(h.id)} />)}</ul>}
                        </AgentNode>}
                      </ul>
                    </li>
                  )
                })}
              </ul>
            )}
        </AgentNode>
      </ul>
      <p className="muted small">Rename anyone with the Rename buttons, or in Claude Code: /flight-safety-agents:rename &lt;who&gt; -&gt; &lt;new name&gt;</p>
      {data.stats && <p className="muted small">Departments: {data.stats.departments ?? 0} · Agents: {data.stats.agents ?? 0} · Messages: {data.stats.messages ?? 0}</p>}
    </section>
  )
}
