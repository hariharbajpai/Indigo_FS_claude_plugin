import BriefPanel from './BriefPanel.jsx'
import FileList from './FileList.jsx'

export default function WorkRequestCard({ wr, briefs, tasks, files = [] }) {
  const mine = briefs.filter((b) => b.work_request_id === wr.id)
  const latest = mine.reduce((a, b) => (!a || b.version > a.version ? b : a), null)
  const pct = Math.max(0, Math.min(100, Math.round(wr.progress ?? 0)))
  const own = tasks.filter((t) => t.work_request_id === wr.id)
  const statusClass = wr.status === 'In progress' ? 'in_progress' : wr.status
  return (
    <article className="card wr" aria-label={`Work request ${wr.id}`}>
      <div className="wr-head">
        <div>
          <span className="chip id">{wr.id}</span>
          <h3>{wr.text}</h3>
        </div>
        <span className={`pill ${statusClass}`}>{wr.status}</span>
      </div>
      <div className="wr-body">
        <div className="progress-row">
          <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></div>
          <span className="small muted">{own.filter((t) => t.status === 'done').length}/{own.length} tasks · {pct}%</span>
        </div>
        <BriefPanel brief={latest} />
        <FileList files={files.filter((f) => f.work_request_id === wr.id)} />
        {wr.report && <div className="banner ok report"><strong>Completion report</strong>{'\n'}{wr.report}</div>}
      </div>
    </article>
  )
}
