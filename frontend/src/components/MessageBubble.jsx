import { memo } from 'react'
import Avatar from './Avatar.jsx'

const KIND_LABEL = {
  request: 'work', brief: 'brief', assign: 'task', status: 'status', blocked: 'blocked', hire: 'hire', instruction: 'instruction',
  question: 'question', review: 'review', report: 'report', refusal: 'refused', board: 'board', note: 'note', chat: '',
}

function MessageBubble({ m, kindOf }) {
  const owner = m.sender_kind === 'owner' || m.sender === 'Owner'
  const system = m.sender_id === 'system'
  const kind = owner ? 'owner' : system ? 'system' : kindOf(m.sender_id)
  const label = KIND_LABEL[m.kind] ?? m.kind
  return (
    <div className={`msg ${owner ? 'owner' : ''}`}>
      <Avatar name={owner ? 'Owner' : m.sender} kind={kind} size="sm" />
      <div className="body">
        <div className="head">
          <strong>{owner ? 'Owner' : m.sender}</strong>
          <span className="to">→ {m.recipient === 'Owner' ? 'Owner' : m.recipient}</span>
          {label && <span className={`pill ${m.kind === 'blocked' ? 'blocked' : m.kind === 'report' ? 'done' : ''}`}>{label}</span>}
          {m.task_id && <span className="chip id">{m.task_id}</span>}
          <time dateTime={m.at}>{new Date(m.at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}</time>
        </div>
        <div className="text">{m.text}</div>
      </div>
    </div>
  )
}
export default memo(MessageBubble)
