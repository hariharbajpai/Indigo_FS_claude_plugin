export default function TaskCard({ task, deptName, agentName, onOpen }) {
  return (
    <button type="button" className="card task-card" onClick={() => onOpen(task)}>
      <strong>{task.id}: {task.title}</strong>
      <div className="small muted">{deptName || 'Unassigned'} · {agentName || 'no owner'}</div>
      {task.acceptance_criteria && <div className="small">Accept: {task.acceptance_criteria}</div>}
    </button>
  )
}
