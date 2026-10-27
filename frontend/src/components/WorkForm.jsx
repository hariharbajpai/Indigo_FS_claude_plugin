import { Icon } from './Icons.jsx'
import { useState } from 'react'
import { api } from '../api.js'

export default function WorkForm() {
  const [text, setText] = useState('')
  const [state, setState] = useState({ busy: false, error: '', ok: '' })
  const submit = async (e) => {
    e.preventDefault()
    if (!text.trim()) return setState({ busy: false, error: 'Describe the work first.', ok: '' })
    setState({ busy: true, error: '', ok: '' })
    try {
      const wr = await api.submitWork(text.trim())
      setText('')
      setState({ busy: false, error: '', ok: wr?.hint || 'Sent to the Chief. Status: Received.' })
    } catch (err) { setState({ busy: false, error: err.message, ok: '' }) }
  }
  return (
    <form className="card" onSubmit={submit} aria-label="New work request">
      <div className="card-title"><Icon name="send" /><h3>New work request</h3></div>
      <p className="small muted">The Chief writes the brief and assigns it to departments. Ask for a PPT, Word or Excel file in plain words.</p>
      <label htmlFor="work-text">Work (English or Hinglish)</label>
      <textarea id="work-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Pichle quarter ke hydraulic incidents review karo" />
      {state.error && <p className="field-error" role="alert">{state.error}</p>}
      {state.ok && <p className="banner ok" role="status">{state.ok}</p>}
      <button disabled={state.busy}>{state.busy ? 'Sending...' : 'Send to Chief'}</button>
    </form>
  )
}
