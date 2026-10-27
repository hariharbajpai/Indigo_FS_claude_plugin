import { api } from '../api.js'
import { useStore } from '../useLive.js'
import RenameButton from './RenameButton.jsx'

export default function AgentNode({ agent, working, children }) {
  const { refresh } = useStore()
  const retired = agent.status === 'retired'
  return (
    <li>
      <div className={`agent-node ${retired ? 'retired' : ''} ${working ? 'is-working' : ''}`}>
        <strong>{agent.name}</strong> <span className="muted small">{agent.role}</span>
        {retired && <span className="pill"> retired</span>}
        {working && <span className="pill working"> working</span>}
        {!retired && agent.id && (
          <> {' '}<RenameButton current={agent.name} label={agent.role}
            onSave={async (name) => { await api.renameAgent(agent.id, name); await refresh() }} /></>
        )}
        {agent.hire_reason && <div className="small muted">Hired: {agent.hire_reason}</div>}
      </div>
      {children}
    </li>
  )
}
