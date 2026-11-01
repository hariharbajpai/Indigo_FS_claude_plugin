// Keyword links the team has learned: a word -> the department it belongs to (backend: kb.py links).
export default function LinksCard({ links, departments = [] }) {
  const name = (id) => departments.find((d) => d.id === id)?.name || id
  const rows = (links || []).filter((l) => l.weight >= 1).slice(0, 14) // one passing mention is not a link yet
  return (
    <div className="card" aria-label="Learned links between departments">
      <div className="card-title"><h3>Interconnections, learned by keywords</h3></div>
      <p className="small muted">
        When a task mentions one of these words, only that department's matching notes and manual sections are read, not everything.
        The map teaches itself from the Chief's tasks, the questions departments ask each other and the manuals.
      </p>
      {rows.length === 0
        ? <p className="muted small">Nothing learned yet. Links appear as the Chief assigns tasks and departments ask each other.</p>
        : (
          <ul className="links-list">
            {rows.map((l) => (
              <li key={`${l.term}|${l.dept}`}>
                <span className="chip">{l.term}</span>
                <span className="muted">→</span>
                <strong>{name(l.dept)}</strong>
                <span className="tiny-text muted">seen {l.seen}×</span>
              </li>
            ))}
          </ul>
        )}
    </div>
  )
}
