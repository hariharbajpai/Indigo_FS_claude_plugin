import { useStore } from '../useLive.js'
import AgentNode from '../components/AgentNode.jsx'

export default function OrgChart() {
  const { data } = useStore()
  const chief = data.chief
  return (
    <section className="tree">
      <h2>Org Chart</h2>
      <ul style={{ borderLeft: 0, paddingLeft: 0 }}>
        <AgentNode agent={{ name: chief?.name || 'Dhruv Rebbapragada', role: chief?.role || 'Chief of Flight Safety' }}>
          {data.departments.length === 0
            ? <p className="muted">No departments yet. Add one from the Owner Console.</p>
            : (
              <ul>
                {data.departments.map((d) => {
                  const head = data.agents.find((a) => a.id === d.head_id)
                  const hired = data.agents.filter((a) => a.dept_id === d.id && a.id !== d.head_id)
                  const retired = d.status === 'retired'
                  return (
                    <li key={d.id}>
                      <div className={`small ${retired ? 'muted' : ''}`}><strong>{d.name}</strong>{retired && ' (retired)'}</div>
                      <ul>
                        {head && <AgentNode agent={head}>
                          {hired.length > 0 && <ul>{hired.map((h) => <AgentNode key={h.id} agent={h} />)}</ul>}
                        </AgentNode>}
                      </ul>
                    </li>
                  )
                })}
              </ul>
            )}
        </AgentNode>
      </ul>
      {data.stats && <p className="muted small">Departments: {data.stats.departments ?? 0} · Agents: {data.stats.agents ?? 0} · Messages: {data.stats.messages ?? 0}</p>}
    </section>
  )
}
