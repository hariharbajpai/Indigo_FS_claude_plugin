import { api } from '../api.js'
import { useStore } from '../useLive.js'
import Avatar from './Avatar.jsx'
import RenameButton from './RenameButton.jsx'

// One person in the organisation chart: avatar, name, role, state, and a Rename action.
export default function OrgCard({ agent, kind, working, reason }) {
  const { refresh } = useStore()
  const retired = agent.status === 'retired'
  return (
    <div className={`org-card ${kind} ${working ? 'working' : ''} ${retired ? 'retired' : ''}`}>
      <Avatar name={agent.name} kind={kind} size={kind === 'chief' ? 'lg' : ''} />
      <div className="who">
        <strong>{agent.name}</strong>
        <div className="role">{agent.role}</div>
        {reason && <div className="reason">Hired for: {reason}</div>}
        {(working || retired) && (
          <div className="state">
            {working && <span className="pill working"><span className="dot working" />working</span>}
            {retired && <span className="pill">retired</span>}
          </div>
        )}
      </div>
      {!retired && agent.id && (
        <div className="actions">
          <RenameButton current={agent.name} label={agent.role}
            onSave={async (name) => { await api.renameAgent(agent.id, name); await refresh() }} />
        </div>
      )}
    </div>
  )
}
