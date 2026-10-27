import Avatar from './Avatar.jsx'
import { Icon } from './Icons.jsx'

const ago = (ts) => {
  if (!ts) return ''
  const s = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
}

// Who is working now (subagents running in Claude Code), who has work waiting, and the last runs.
export default function ActivityPanel({ activity, agents = [] }) {
  const { running, waiting, recent } = activity
  const kind = (id) => agents.find((a) => a.id === id)?.kind || (id === 'chief' ? 'chief' : 'hired')
  return (
    <div className="card" aria-label="Agent activity">
      <div className="card-title"><Icon name="bolt" /><h3>Agent activity</h3></div>
      {running.length === 0 && waiting.length === 0 && recent.length === 0 && (
        <p className="muted small">No agent has run yet. Agents work while a /flight-safety-agents command runs in Claude Code.</p>
      )}
      {running.length > 0 && (
        <>
          <div className="sub-title">Working now</div>
          <ul className="activity-list">
            {running.map((a) => (
              <li key={a.activation_id}>
                <Avatar name={a.agent_name} kind={kind(a.agent_id)} size="sm" />
                <div className="who"><strong>{a.agent_name}</strong><div className="small muted">started {ago(a.started_at)}</div></div>
                <span className="dot working" title="working" />
              </li>
            ))}
          </ul>
        </>
      )}
      {waiting.length > 0 && (
        <>
          <div className="sub-title">Waiting to run</div>
          <ul className="activity-list">
            {waiting.map((a) => (
              <li key={a.agent_id}>
                <Avatar name={a.agent_name} kind={kind(a.agent_id)} size="sm" />
                <div className="who"><strong>{a.agent_name}</strong><div className="small muted">{a.messages} new message{a.messages === 1 ? '' : 's'}</div></div>
              </li>
            ))}
          </ul>
        </>
      )}
      {recent.length > 0 && (
        <>
          <div className="sub-title">Recent runs</div>
          <ul className="activity-list">
            {recent.map((r) => (
              <li key={r.id}>
                <Avatar name={r.agent_name} kind={kind(r.agent_id)} size="sm" />
                <div className="who">
                  <strong>{r.agent_name}</strong> <span className="small muted">· {r.status} · {ago(r.ended_at)}</span>
                  {r.report && <div className="report-text">{r.report}</div>}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
