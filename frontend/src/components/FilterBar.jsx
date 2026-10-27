export default function FilterBar({ filters, setFilters, departments, agents, tasks }) {
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value })
  const any = filters.dept || filters.agent || filters.task
  return (
    <div className="card toolbar" role="search" aria-label="Filter messages">
      <div className="field"><label htmlFor="f-dept">Department</label>
        <select id="f-dept" value={filters.dept} onChange={set('dept')}>
          <option value="">All departments</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
      <div className="field"><label htmlFor="f-agent">Agent</label>
        <select id="f-agent" value={filters.agent} onChange={set('agent')}>
          <option value="">Everyone</option>{agents.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}</select></div>
      <div className="field"><label htmlFor="f-task">Task</label>
        <select id="f-task" value={filters.task} onChange={set('task')}>
          <option value="">All tasks</option>{tasks.map((t) => <option key={t.id} value={t.id}>{t.id}: {t.title}</option>)}</select></div>
      <button type="button" className="ghost" disabled={!any} onClick={() => setFilters({ dept: '', agent: '', task: '' })}>Clear</button>
    </div>
  )
}
