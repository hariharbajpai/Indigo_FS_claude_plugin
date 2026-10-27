export default function BriefPanel({ brief }) {
  if (!brief) return <p className="muted small">No brief yet. The Chief has not planned this request.</p>
  return (
    <div className="brief">
      <strong>Brief v{brief.version}</strong>
      <p style={{ margin: '.25rem 0' }}>{brief.summary}</p>
      {brief.goals?.length > 0 && (
        <ul style={{ margin: 0 }}>{brief.goals.map((g, i) => <li key={i}>{g}</li>)}</ul>
      )}
    </div>
  )
}
