import { useEffect, useMemo, useRef, useState } from 'react'
import { useStore } from '../useLive.js'
import FilterBar from '../components/FilterBar.jsx'
import MessageBubble from '../components/MessageBubble.jsx'

const PAGE = 200

export function filterMessages(messages, agents, tasks, f) {
  return messages.filter((m) => {
    if (f.task && m.task_id !== f.task) return false
    if (f.agent && m.sender !== f.agent && m.recipient !== f.agent) return false
    if (f.dept) {
      const task = tasks.find((t) => t.id === m.task_id)
      const names = agents.filter((a) => a.dept_id === f.dept).map((a) => a.name)
      const inDept = m.dept_id === f.dept || task?.dept_id === f.dept || names.includes(m.sender) || names.includes(m.recipient)
      if (!inDept) return false
    }
    return true
  })
}

export default function ChatFeed() {
  const { data } = useStore()
  const [filters, setFilters] = useState({ dept: '', agent: '', task: '' })
  const [limit, setLimit] = useState(PAGE)
  const listRef = useRef(null)
  const stick = useRef(true)

  const all = useMemo(() => filterMessages(data.messages, data.agents, data.tasks, filters), [data, filters])
  const shown = all.slice(-limit)

  useEffect(() => {
    const el = listRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [shown.length, filters])

  const onScroll = (e) => {
    const el = e.currentTarget
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

  const kindOf = (id) => data.agents.find((a) => a.id === id)?.kind || 'hired'
  return (
    <>
      <FilterBar filters={filters} setFilters={setFilters} departments={data.departments} agents={data.agents} tasks={data.tasks} />
      <div className="card" style={{ padding: 0 }}>
        <div className="chat-list" ref={listRef} onScroll={onScroll} role="log" aria-live="polite" tabIndex={0}>
          {all.length > shown.length && (
            <div style={{ padding: '10px 18px' }}>
              <button type="button" className="ghost tiny" onClick={() => setLimit(limit + PAGE)}>Show {Math.min(PAGE, all.length - shown.length)} earlier messages</button>
            </div>
          )}
          {shown.length === 0 && <p className="muted" style={{ padding: '18px' }}>{data.messages.length ? 'No messages match these filters.' : 'No messages yet.'}</p>}
          {shown.map((m) => <MessageBubble key={m.id} m={m} kindOf={kindOf} />)}
        </div>
      </div>
      <p className="muted small">{all.length} message{all.length === 1 ? '' : 's'}</p>
    </>
  )
}
