export default function AgentNode({ agent, working, children }) {
  const retired = agent.status === 'retired'
  return (
    <li>
      <div className={`agent-node ${retired ? 'retired' : ''} ${working ? 'is-working' : ''}`}>
        <strong>{agent.name}</strong> <span className="muted small">{agent.role}</span>
        {retired && <span className="pill"> retired</span>}
        {working && <span className="pill working"> working</span>}
        {agent.hire_reason && <div className="small muted">Hired: {agent.hire_reason}</div>}
      </div>
      {children}
    </li>
  )
}
