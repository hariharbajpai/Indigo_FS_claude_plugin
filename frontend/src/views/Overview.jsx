import { useStore } from '../useLive.js'
import WorkRequestCard from '../components/WorkRequestCard.jsx'
import ActivityPanel from '../components/ActivityPanel.jsx'

export default function Overview() {
  const { data } = useStore()
  const list = [...data.work_requests].reverse()
  return (
    <section>
      <h2>Overview</h2>
      {data.stats && (
        <p className="muted small">Departments: {data.stats.departments ?? 0} · Agents: {data.stats.agents ?? 0} · Messages: {data.stats.messages ?? 0}</p>
      )}
      <ActivityPanel activity={data.activity} />
      {list.length === 0
        ? <p className="muted">No work requests yet. In Claude Code run /flight-safety-agents:work, or send one from the Owner Console.</p>
        : list.map((w) => <WorkRequestCard key={w.id} wr={w} briefs={data.briefs} tasks={data.tasks} files={data.files} />)}
    </section>
  )
}
