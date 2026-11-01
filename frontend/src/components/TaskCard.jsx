import Avatar from './Avatar.jsx'

export default function TaskCard({ task, deptName, agent, onOpen }) {
  return (
    <button type="button" className="task-card" onClick={() => onOpen(task)}>
      <div className="t-top"><span className="chip id">{task.id}</span>
        {task.source_pack && <span className={`chip pack ${task.source_pack.coverage}`} title="Sources checked by the File Checker">sources: {task.source_pack.coverage}{task.source_pack.issues ? ` · ${task.source_pack.issues} issue${task.source_pack.issues === 1 ? '' : 's'}` : ''}</span>}<span className="chip dept" title={deptName}>{deptName || 'Unassigned'}</span></div>
      <div className="t-title">{task.title}</div>
      {task.acceptance_criteria && <div className="t-accept">{task.acceptance_criteria}</div>}
      <div className="t-meta">
        {agent && <Avatar name={agent.name} kind={agent.kind} size="sm" />}
        <span className="t-owner">{agent?.name || 'No owner'}</span>
      </div>
    </button>
  )
}
