// Which Claude each kind of agent uses (backend/API.md: /api/models).
export const ROLE_ORDER = ['chief', 'checker', 'head', 'hired']
export const ROLE_LABELS = {
  chief: 'Chief of Flight Safety',
  checker: 'File Checker',
  head: 'Vertical Heads',
  hired: 'Hired specialists',
}

// "claude-sonnet-5-5" -> "Sonnet 5.5", "opus" -> "Opus", nothing -> "not reported yet".
export function prettyModel(id) {
  if (!id) return 'not reported yet'
  const m = /(opus|sonnet|haiku|fable)(?:-(\d+(?:-\d+)*))?/i.exec(String(id).replace(/-\d{8}\b/, ''))
  if (!m) return String(id)
  const name = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase()
  return m[2] ? `${name} ${m[2].replace(/-/g, '.')}` : name
}

// What an agent of this kind will really run on: its own setting, or the session's model.
export function effectiveModel(models, role) {
  const r = models?.roles?.[role]
  if (!r) return null
  return r.setting === 'inherit' ? models.session_model : r.setting
}
