export default function FilterBar({ filters, setFilters, departments, agents, tasks }) {
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value })
  return (
    <div className="filters" role="search" aria-label="Filter messages">
      <label>Department <select value={filters.dept} onChange={set('dept')}>
        <option value="">All</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
      <label>Agent <select value={filters.agent} onChange={set('agent')}>
        <option value="">All</option>{agents.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}</select></label>
      <label>Task <select value={filters.task} onChange={set('task')}>
        <option value="">All</option>{tasks.map((t) => <option key={t.id} value={t.id}>{t.id}: {t.title}</option>)}</select></label>
      <button type="button" className="ghost" onClick={() => setFilters({ dept: '', agent: '', task: '' })}>Clear</button>
    </div>
  )
}
