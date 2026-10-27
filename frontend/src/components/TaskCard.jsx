import Avatar from './Avatar.jsx'

export default function TaskCard({ task, deptName, agent, onOpen }) {
  return (
    <button type="button" className="task-card" onClick={() => onOpen(task)}>
      <div className="t-top"><span className="chip id">{task.id}</span><span className="chip dept" title={deptName}>{deptName || 'Unassigned'}</span></div>
      <div className="t-title">{task.title}</div>
      {task.acceptance_criteria && <div className="t-accept">{task.acceptance_criteria}</div>}
      <div className="t-meta">
        {agent && <Avatar name={agent.name} kind={agent.kind} size="sm" />}
        <span className="t-owner">{agent?.name || 'No owner'}</span>
      </div>
    </button>
  )
}
