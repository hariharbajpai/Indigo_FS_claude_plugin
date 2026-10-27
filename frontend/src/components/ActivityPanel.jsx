const ago = (ts) => {
  if (!ts) return ''
  const s = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
}

// Who is working now (subagents running in Claude Code), who has work waiting, and the last runs.
export default function ActivityPanel({ activity }) {
  const { running, waiting, recent } = activity
  return (
    <div className="card" aria-label="Agent activity">
      <h3>Agent activity</h3>
      {running.length === 0 && waiting.length === 0 && recent.length === 0 && (
        <p className="muted small">No agent has run yet.</p>
      )}
      {running.length > 0 && (
        <p className="small"><strong>Working now:</strong>{' '}
          {running.map((a) => <span key={a.activation_id} className="pill working">{a.agent_name} · {ago(a.started_at)}</span>)}
        </p>
      )}
      {waiting.length > 0 && (
        <p className="small"><strong>Waiting to run:</strong>{' '}
          {waiting.map((a) => <span key={a.agent_id} className="pill">{a.agent_name}</span>)}
        </p>
      )}
      {recent.length > 0 && (
        <ul className="runs">
          {recent.map((r) => (
            <li key={r.id} className="small">
              <strong>{r.agent_name}</strong> <span className="muted">{r.status} · {ago(r.ended_at)}</span>
              {r.report && <div>{r.report}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
