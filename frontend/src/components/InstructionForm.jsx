import { Icon } from './Icons.jsx'
import { useState } from 'react'
import { api } from '../api.js'

export default function InstructionForm({ departments }) {
  const [target, setTarget] = useState('chief')
  const [text, setText] = useState('')
  const [state, setState] = useState({ busy: false, error: '', ok: '' })
  const submit = async (e) => {
    e.preventDefault()
    if (!text.trim()) return setState({ busy: false, error: 'Write an instruction first.', ok: '' })
    setState({ busy: true, error: '', ok: '' })
    try {
      const r = await api.sendInstruction(target, text.trim())
      setText('')
      setState({ busy: false, error: '', ok: r?.hint || 'Instruction delivered. See it in the Chat Feed.' })
    } catch (err) { setState({ busy: false, error: err.message, ok: '' }) }
  }
  return (
    <form className="card" onSubmit={submit} aria-label="Send instruction">
      <div className="card-title"><Icon name="steer" /><h3>Steer the team</h3></div>
      <p className="small muted">An instruction mid-way: the Chief re-plans, conflicting tasks are blocked.</p>
      <label htmlFor="ins-target">To</label>
      <select id="ins-target" value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="chief">Chief</option>
        {departments.filter((d) => d.status !== 'retired').map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      <label htmlFor="ins-text">Instruction</label>
      <textarea id="ins-text" value={text} onChange={(e) => setText(e.target.value)} />
      {state.error && <p className="field-error" role="alert">{state.error}</p>}
      {state.ok && <p className="banner ok" role="status">{state.ok}</p>}
      <button disabled={state.busy}>{state.busy ? 'Sending...' : 'Send instruction'}</button>
    </form>
  )
}
