import { memo } from 'react'

function MessageBubble({ m }) {
  const owner = m.sender_kind === 'owner' || m.sender === 'Owner'
  return (
    <div className={`bubble ${owner ? 'owner' : ''}`}>
      <div className="small">
        <strong>{owner ? 'Owner' : m.sender}</strong> to {m.recipient === 'Owner' ? 'Owner' : m.recipient}
        {m.task_id && <> · <span className="pill">task {m.task_id}</span></>}
        <span className="muted"> · {new Date(m.at).toLocaleTimeString()}</span>
      </div>
      <div>{m.text}</div>
    </div>
  )
}
export default memo(MessageBubble)
