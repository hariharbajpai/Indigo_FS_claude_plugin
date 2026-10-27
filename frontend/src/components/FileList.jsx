import { fileUrl } from '../api.js'

const LABEL = { pptx: 'PPT', docx: 'Word', xlsx: 'Excel' }

// Files the team built for a work request (PPT, Word, Excel): where they are on disk, plus a download link.
export default function FileList({ files }) {
  if (!files.length) return null
  return (
    <div className="files" aria-label="Files">
      <strong className="small">Files</strong>
      <ul>
        {files.map((f) => (
          <li key={f.id}>
            <span className={`pill fmt ${f.format}`}>{LABEL[f.format] || f.format}</span>{' '}
            <strong>{f.title}</strong>{' '}
            <a href={fileUrl(f.id)} download={f.name}>Download</a>
            <div className="small muted path" title={f.path}><code>{f.path}</code></div>
          </li>
        ))}
      </ul>
    </div>
  )
}
