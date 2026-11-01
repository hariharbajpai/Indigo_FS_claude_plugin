import { useState } from 'react'
import { api } from '../api.js'
import { useStore } from '../useLive.js'
import { Icon } from './Icons.jsx'
import { ROLE_LABELS, ROLE_ORDER, prettyModel } from '../models.js'

// Which Claude is in use, and the option to upgrade (or lighten) it: a preset, or a model per kind of agent.
export default function ModelsCard({ models }) {
  const { refresh } = useStore()
  const [state, setState] = useState({ busy: false, error: '' })
  if (!models) return null
  const apply = async (payload) => {
    setState({ busy: true, error: '' })
    try {
      await api.setModels(payload)
      await refresh()
      setState({ busy: false, error: '' })
    } catch (err) { setState({ busy: false, error: err.message }) }
  }
  const label = (id) => (id === 'inherit' ? 'Same as my session' : prettyModel(id))
  return (
    <div className="card" aria-label="Claude models">
      <div className="card-title"><Icon name="bolt" /><h3>Which Claude</h3></div>
      <p className="small">
        Your Claude Code session: <strong>{prettyModel(models.session_model)}</strong>
        {!models.session_model && <span className="muted"> (shown after the team has run once)</span>}
      </p>
      <table className="models-table">
        <tbody>
          {ROLE_ORDER.map((role) => {
            const r = models.roles[role]
            return (
              <tr key={role}>
                <th scope="row">{ROLE_LABELS[role]}</th>
                <td>
                  <select aria-label={`Model for ${ROLE_LABELS[role]}`} value={r.setting} disabled={state.busy}
                    onChange={(e) => apply({ roles: { [role]: e.target.value } })}>
                    {models.options.map((o) => <option key={o.id} value={o.id}>{label(o.id)}</option>)}
                  </select>
                  {r.setting === 'inherit' && <div className="tiny-text muted">now: {prettyModel(models.session_model)}</div>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="sub-title">Upgrade in one click</div>
      <div className="preset-row">
        {models.presets.map((p) => (
          <button key={p.id} type="button" className={`tiny ${models.preset === p.id ? '' : 'ghost'}`}
            title={p.note} disabled={state.busy} onClick={() => apply({ preset: p.id })}>{p.label}</button>
        ))}
      </div>
      <p className="small muted">{models.hint}</p>
      {state.error && <div className="field-error" role="alert">{state.error}</div>}
    </div>
  )
}
