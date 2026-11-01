// Short forms of the long role and hire texts, so the organisation shows a name and one short line, not a page.

const tidy = (text) => String(text || '').replace(/\s+/g, ' ').trim()

// Cut `text` to at most `max` characters, at a word, with "…" when something was cut.
export function clip(text, max) {
  const s = tidy(text)
  if (s.length <= max) return s
  const cut = s.slice(0, max - 1)
  const space = cut.lastIndexOf(' ')
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.(]+$/, '')}…`
}

// The title part of a role: its first sentence, without manual references.
// "Chief of Flight Safety (FSM Issue 5 Rev 0 §2.3.1, pp41-42). RACI from ..." -> "Chief of Flight Safety"
export function shortRole(role, max = 60) {
  const s = tidy(role)
  let depth = 0
  let end = s.length
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i]
    if (c === '(' || c === '[') depth += 1
    else if ((c === ')' || c === ']') && depth) depth -= 1
    else if (depth) continue
    else if ('.:;'.includes(c) && (i + 1 === s.length || s[i + 1] === ' ')) { end = i; break }
    else if (c === '—' || c === '–' || (c === '-' && s[i - 1] === ' ' && s[i + 1] === ' ')) { end = i; break }
  }
  const first = s.slice(0, end)
    .replace(/\s*[([][^()[\]]*[\d§][^()[\]]*[)\]]/g, '') // "(FSM Issue 5 Rev 0 §2.3.1)", "[p. 41]"
    .replace(/\s*\([A-Z]{1,2}\)/g, '') // RACI letters such as "(C)"
    .replace(/[\s,]+$/, '')
    .trim()
  return clip(first || s, max)
}

// True when shortRole or clip left something out, so the full text is worth offering.
export const isCut = (full, short) => tidy(full) !== short
