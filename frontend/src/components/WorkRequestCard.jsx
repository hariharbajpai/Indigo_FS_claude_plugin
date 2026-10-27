import BriefPanel from './BriefPanel.jsx'
import FileList from './FileList.jsx'

export default function WorkRequestCard({ wr, briefs, tasks, files = [] }) {
  const mine = briefs.filter((b) => b.work_request_id === wr.id)
  const latest = mine.reduce((a, b) => (!a || b.version > a.version ? b : a), null)
  const pct = Math.max(0, Math.min(100, Math.round(wr.progress ?? 0)))
  const count = tasks.filter((t) => t.work_request_id === wr.id)
  return (
    <article className="card" aria-label={`Work request ${wr.id}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '.5rem', flexWrap: 'wrap' }}>
        <h3>{wr.text}</h3>
        <span className={`pill ${wr.status === 'Done' ? 'done' : ''}`}>{wr.status}</span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="muted small">{pct}% complete, {count.filter((t) => t.status === 'done').length}/{count.length} tasks done</p>
      <BriefPanel brief={latest} />
      <FileList files={files.filter((f) => f.work_request_id === wr.id)} />
      {wr.report && <div className="banner ok report"><strong>Completion report:</strong> {wr.report}</div>}
    </article>
  )
}
