import { Icon } from './Icons.jsx'
import { useState } from 'react'
import { api } from '../api.js'

const isPdf = (f) => f.type === 'application/pdf' || /\.pdf$/i.test(f.name)

export function validate({ files, name, headName }) {
  const e = {}
  if (!files.length) e.files = 'Add at least one PDF file.'
  else if (!files.every(isPdf)) e.files = 'Only PDF files are allowed.'
  if (!name.trim()) e.name = 'Department name is required.'
  if (!headName.trim()) e.headName = 'Vertical Head name is required.'
  return e
}

const KIND = { duplicate: 'is a duplicate of', new_version: 'looks like a new version of', new: 'is new' }

export default function AddDepartmentForm({ departments }) {
  const [files, setFiles] = useState([])
  const [name, setName] = useState('')
  const [headName, setHeadName] = useState('')
  const [errors, setErrors] = useState({})
  const [state, setState] = useState({ busy: false, error: '', ok: '', matches: null })

  const send = async (decision, target) => {
    setState({ busy: true, error: '', ok: '', matches: null })
    try {
      const r = await api.addDepartment({ files, name: name.trim(), headName: headName.trim(), decision, target })
      if (r?.status === 'needs_decision') return setState({ busy: false, error: '', ok: '', matches: r.matches || [] })
      setState({ busy: false, error: '', ok: `Department "${name.trim()}" created with Vertical Head ${headName.trim()}.`, matches: null })
      setFiles([]); setName(''); setHeadName('')
    } catch (err) { setState({ busy: false, error: err.message, ok: '', matches: null }) }
  }
  const submit = (e) => {
    e.preventDefault()
    const v = validate({ files, name, headName })
    setErrors(v)
    if (Object.keys(v).length === 0) send(undefined)
  }
  const deptName = (id) => departments.find((d) => d.id === id)?.name || id || 'an existing department'
  const act = async (fn, okMsg) => {
    setState({ busy: true, error: '', ok: '', matches: null })
    try { await fn(); setState({ busy: false, error: '', ok: okMsg, matches: null }) }
    catch (err) { setState({ busy: false, error: err.message, ok: '', matches: null }) }
  }

  return (
    <div className="card">
      <form onSubmit={submit} aria-label="Add department" noValidate>
        <div className="card-title"><Icon name="building" /><h3>Add department</h3></div>
        <p className="small muted">Its PDF manuals become the department's knowledge base; the Vertical Head runs it.</p>
        <label htmlFor="dept-files">PDF files</label>
        <input id="dept-files" type="file" accept="application/pdf,.pdf" multiple onChange={(e) => setFiles([...e.target.files])} />
        {errors.files && <p className="field-error" role="alert">{errors.files}</p>}
        <label htmlFor="dept-name">Department name</label>
        <input id="dept-name" value={name} onChange={(e) => setName(e.target.value)} />
        {errors.name && <p className="field-error" role="alert">{errors.name}</p>}
        <label htmlFor="dept-head">Vertical Head name</label>
        <input id="dept-head" value={headName} onChange={(e) => setHeadName(e.target.value)} />
        {errors.headName && <p className="field-error" role="alert">{errors.headName}</p>}
        {state.error && <p className="field-error" role="alert">{state.error}</p>}
        {state.ok && <p className="banner ok" role="status">{state.ok}</p>}
        <button disabled={state.busy}>{state.busy ? 'Working...' : 'Add department'}</button>
      </form>
      {state.matches && (
        <div className="banner warn" role="status">
          <strong>Existing department found.</strong>
          {state.matches.map((m, i) => (
            <p key={i}>This upload {KIND[m.result] || 'matches'} <strong>{deptName(m.existing_dept)}</strong>{m.file ? ` (${m.file})` : ''}.</p>
          ))}
          <p>Update the existing department or add as a new one?</p>
          <button type="button" disabled={!state.matches.some((m) => m.existing_dept)} onClick={() => {
            const id = state.matches.find((m) => m.existing_dept)?.existing_dept
            if (id) act(() => api.replaceDepartment(id, files), 'Department updated with the new files.')
          }}>Update existing</button>{' '}
          <button type="button" className="ghost" onClick={() => send('new')}>Add as new</button>
        </div>
      )}
      <div className="sub-title" style={{ marginTop: 22 }}>Manage departments</div>
      {departments.length === 0 ? <p className="muted">No departments yet.</p> : (
        <ul className="dept-list">
          {departments.map((d) => (
            <li key={d.id}>
              <span className="name">{d.name}</span>
              {d.status === 'retired' ? <span className="pill">retired</span> : (
                <span className="row-actions">
                  <label className="file-button">
                    Update PDFs
                    <input type="file" accept=".pdf" multiple className="visually-hidden" aria-label={`Replace PDFs for ${d.name}`}
                      onChange={(e) => e.target.files.length && act(() => api.replaceDepartment(d.id, [...e.target.files]), `${d.name} updated with the new PDFs.`)} />
                  </label>
                  <button type="button" className="danger tiny" onClick={() => window.confirm(`Retire ${d.name}? Its head and hired agents retire too.`) && act(() => api.retireDepartment(d.id), `${d.name} retired.`)}>Retire</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
