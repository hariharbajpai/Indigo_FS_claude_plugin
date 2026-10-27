import { useState } from 'react'

// Inline rename: a small "Rename" button that turns into an input with Save / Cancel (Enter saves, Esc cancels).
export default function RenameButton({ current, label, onSave }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(current)
  const [state, setState] = useState({ busy: false, error: '' })

  const open = () => { setValue(current); setState({ busy: false, error: '' }); setEditing(true) }
  const save = async () => {
    const name = value.trim()
    if (!name) return setState({ busy: false, error: 'Enter a name.' })
    if (name === current) return setEditing(false)
    setState({ busy: true, error: '' })
    try {
      await onSave(name)
      setEditing(false)
      setState({ busy: false, error: '' })
    } catch (err) { setState({ busy: false, error: err.message }) }
  }

  if (!editing) {
    return <button type="button" className="ghost tiny" onClick={open} aria-label={`Rename ${label || current}`}>Rename</button>
  }
  return (
    <span className="rename">
      <input
        aria-label={`New name for ${label || current}`}
        value={value}
        maxLength={80}
        autoFocus
        onFocus={(e) => e.target.select()}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
      />
      <button type="button" className="tiny" disabled={state.busy} onClick={save}>{state.busy ? 'Saving...' : 'Save'}</button>
      <button type="button" className="ghost tiny" onClick={() => setEditing(false)}>Cancel</button>
      {state.error && <span className="field-error" role="alert">{state.error}</span>}
    </span>
  )
}
