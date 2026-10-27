import { useEffect, useState } from 'react'
import { useStore } from '../useLive.js'
import TaskCard from '../components/TaskCard.jsx'

const COLS = ['todo', 'in_progress', 'review', 'blocked', 'done']

export default function TaskBoard() {
  const { data } = useStore()
  const [openId, setOpenId] = useState(null)
  const dept = (id) => data.departments.find((d) => d.id === id)?.name
  const agent = (id) => data.agents.find((a) => a.id === id)?.name
  const open = data.tasks.find((t) => t.id === openId)

  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && setOpenId(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (data.tasks.length === 0) return <section><h2>Task Board</h2><p className="muted">No tasks yet. Tasks appear once the Chief briefs a work request.</p></section>
  return (
    <section>
      <h2>Task Board</h2>
      <div className="kanban">
        {COLS.map((c) => {
          const items = data.tasks.filter((t) => t.status === c)
          return (
            <div className="column" key={c} aria-label={c}>
              <h3>{c.replace('_', ' ')} ({items.length})</h3>
              {items.map((t) => <TaskCard key={t.id} task={t} deptName={dept(t.dept_id)} agentName={agent(t.agent_id)} onOpen={(x) => setOpenId(x.id)} />)}
            </div>
          )
        })}
      </div>
      {open && (
        <div className="modal-back" onClick={() => setOpenId(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label={`Task ${open.id}`} onClick={(e) => e.stopPropagation()}>
            <h3>{open.id}: {open.title}</h3>
            <p className="small muted">{dept(open.dept_id) || 'Unassigned'} · {agent(open.agent_id) || 'no owner'} · <span className={`pill ${open.status}`}>{open.status}</span></p>
            {open.description && <p>{open.description}</p>}
            {open.acceptance_criteria && <p><strong>Acceptance:</strong> {open.acceptance_criteria}</p>}
            <h3>Activity</h3>
            {(open.notes || []).length === 0 ? <p className="muted">No activity yet.</p> : (
              <ul className="timeline">
                {open.notes.map((n, i) => (
                  <li key={i}><strong>{n.author}</strong> {n.status && <span className={`pill ${n.status}`}>{n.status}</span>}
                    <div>{n.text}</div><div className="small muted">{new Date(n.at).toLocaleString()}</div></li>
                ))}
              </ul>
            )}
            <button type="button" className="ghost" autoFocus onClick={() => setOpenId(null)}>Close</button>
          </div>
        </div>
      )}
    </section>
  )
}
