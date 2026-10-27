export const initials = (name = '') => {
  const words = String(name).replace(/[^\p{L}\p{N} ]/gu, ' ').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return '?'
  return (words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[words.length - 1][0]).toUpperCase()
}

// kind: chief | head | hired | owner | system
export default function Avatar({ name, kind = 'hired', size = '' }) {
  return <span className={`avatar ${kind} ${size}`} aria-hidden="true">{kind === 'system' ? 'FS' : initials(name)}</span>
}
