import { useEffect, useState } from 'react'
import { useStore } from '../useLive.js'
import TaskCard from '../components/TaskCard.jsx'

const COLS = ['todo', 'in_progress', 'review', 'blocked', 'done']
const NAME = { todo: 'To do', in_progress: 'In progress', review: 'Review', blocked: 'Blocked', done: 'Done' }

export default function TaskBoard() {
  const { data } = useStore()
  const [openId, setOpenId] = useState(null)
  const dept = (id) => data.departments.find((d) => d.id === id)?.name
  const agentOf = (id) => data.agents.find((a) => a.id === id)
  const open = data.tasks.find((t) => t.id === openId)

  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && setOpenId(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (data.tasks.length === 0) {
    return <div className="empty"><strong>No tasks yet</strong>Tasks appear once the Chief briefs a work request.</div>
  }
  return (
    <>
      <div className="kanban">
        {COLS.map((c) => {
          const items = data.tasks.filter((t) => t.status === c)
          return (
            <div className="column" key={c} aria-label={NAME[c]}>
              <div className="column-head"><span className={`status-dot ${c}`} />{NAME[c]}<span className="count">{items.length}</span></div>
              {items.map((t) => (
                <TaskCard key={t.id} task={t} deptName={dept(t.dept_id)} agent={agentOf(t.agent_id)} onOpen={(x) => setOpenId(x.id)} />
              ))}
            </div>
          )
        })}
      </div>
      {open && (
        <div className="modal-back" onClick={() => setOpenId(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label={`Task ${open.id}`} onClick={(e) => e.stopPropagation()}>
            <span className="chip id">{open.id}</span> <span className={`pill ${open.status}`}>{NAME[open.status] || open.status}</span>
            <h3>{open.title}</h3>
            <p className="small muted">{dept(open.dept_id) || 'Unassigned'} · {agentOf(open.agent_id)?.name || 'no owner'} · {open.work_request_id}</p>
            {open.description && <p>{open.description}</p>}
            {open.acceptance_criteria && <div className="brief"><div className="small"><strong>Acceptance criteria</strong></div><p>{open.acceptance_criteria}</p></div>}
            <div className="sub-title">Activity</div>
            {(open.notes || []).length === 0 ? <p className="muted">No activity yet.</p> : (
              <ul className="timeline">
                {open.notes.map((n, i) => (
                  <li key={i}>
                    <div className="small"><strong>{n.author}</strong> {n.status && <span className={`pill ${n.status}`}>{NAME[n.status] || n.status}</span>}
                      <span className="muted"> · {new Date(n.at).toLocaleString()}</span></div>
                    <div>{n.text}</div>
                  </li>
                ))}
              </ul>
            )}
            <button type="button" className="ghost" autoFocus onClick={() => setOpenId(null)}>Close</button>
          </div>
        </div>
      )}
    </>
  )
}

