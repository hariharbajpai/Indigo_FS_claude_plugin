import { fileUrl } from '../api.js'

const LABEL = { pptx: 'PPT', docx: 'DOC', xlsx: 'XLS' }

// Files the team built for a work request: where they are on disk, plus a download link.
export default function FileList({ files }) {
  if (!files.length) return null
  return (
    <div className="files" aria-label="Files">
      {files.map((f) => (
        <div className="file" key={f.id}>
          <span className={`file-icon ${f.format}`}>{LABEL[f.format] || f.format}</span>
          <div className="meta">
            <strong>{f.title}</strong>
            <code className="path muted" title={f.path}>{f.path}</code>
          </div>
          <a className="dl" href={fileUrl(f.id)} download={f.name}>Download</a>
        </div>
      ))}
    </div>
  )
}
