const FMT = { pptx: 'PPT', docx: 'Word', xlsx: 'Excel' }

export default function BriefPanel({ brief }) {
  if (!brief) return <p className="muted small">No brief yet: the Chief has not planned this request.</p>
  return (
    <div className="brief">
      <div className="small"><strong>Brief v{brief.version}</strong>{brief.change_note && <span className="muted"> · {brief.change_note}</span>}</div>
      <p>{brief.summary}</p>
      {brief.goals?.length > 0 && <ul>{brief.goals.map((g, i) => <li key={i}>{g}</li>)}</ul>}
      {brief.deliverables?.length > 0 && (
        <p className="small muted">Deliverables: {brief.deliverables.map((d) => `${FMT[d.format] || d.format} "${d.title}"`).join(' · ')}</p>
      )}
    </div>
  )
}
