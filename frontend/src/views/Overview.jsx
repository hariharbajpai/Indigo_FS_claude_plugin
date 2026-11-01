import { useStore } from '../useLive.js'
import WorkRequestCard from '../components/WorkRequestCard.jsx'
import ActivityPanel from '../components/ActivityPanel.jsx'
import ModelsCard from '../components/ModelsCard.jsx'
import { effectiveModel, prettyModel } from '../models.js'

function Kpi({ label, value, of, hint, accent }) {
  return (
    <div className={`kpi ${accent ? 'accent' : ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}{of !== undefined && <small> / {of}</small>}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

export default function Overview() {
  const { data } = useStore()
  const list = [...data.work_requests].reverse()
  const active = data.departments.filter((d) => d.status !== 'retired')
  const agents = data.agents.filter((a) => a.status !== 'retired')
  const open = data.work_requests.filter((w) => w.status !== 'Done').length
  const done = data.tasks.filter((t) => t.status === 'done').length
  const blocked = data.tasks.filter((t) => t.status === 'blocked').length
  const checked = data.tasks.filter((t) => t.source_pack).length
  const models = data.models
  return (
    <>
      <section className="kpis" aria-label="Key figures">
        <Kpi label="Departments" value={active.length} hint={`${agents.filter((a) => a.kind === 'head').length} Vertical Heads`} />
        <Kpi label="Agents" value={agents.length} hint={`${agents.filter((a) => a.kind === 'hired').length} hired specialists`} />
        <Kpi label="Open requests" value={open} of={data.work_requests.length} accent={open > 0} hint="work in progress" />
        <Kpi label="Tasks done" value={done} of={data.tasks.length} hint={blocked ? `${blocked} blocked` : 'none blocked'} />
        <Kpi label="Sources checked" value={checked} of={data.tasks.length} hint="by the File Checker" />
        <Kpi label="Files" value={data.files.length} hint="PPT, Word, Excel" />
        {models && <Kpi label="Claude (your session)" value={prettyModel(models.session_model)} hint={`Chief ${prettyModel(effectiveModel(models, 'chief'))} · Heads ${prettyModel(effectiveModel(models, 'head'))}`} />}
      </section>
      <div className="split">
        <section aria-label="Work requests">
          <div className="section-title"><h2>Work requests</h2><span className="muted small">{data.work_requests.length} total</span></div>
          {list.length === 0
            ? <div className="empty"><strong>No work yet</strong>In Claude Code run <code>/flight-safety-agents:work &lt;request&gt;</code>, or send one from the Owner Console.</div>
            : list.map((w) => <WorkRequestCard key={w.id} wr={w} briefs={data.briefs} tasks={data.tasks} files={data.files} />)}
        </section>
        <aside><ModelsCard models={models} /><ActivityPanel activity={data.activity} agents={data.agents} /></aside>
      </div>
    </>
  )
}
