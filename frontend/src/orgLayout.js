// Where each node of the organisation graph sits: the Chief on top, then the File Checker,
// the departments, their Vertical Heads and the specialists they hired. Pure, so it is easy to test.
export const SLOT = 118 // width given to one node and its name
export const ROW = 132 // distance between rows
export const LABEL = 36 // room for a two-line name under a node
export const PAD = 40
export const RADIUS = { chief: 30, checker: 24, dept: 26, head: 23, hired: 19 }
const GAP = 0.4 // space between departments, in slots

export function layoutOrg({ chief, checker, departments, agents }) {
  const nodes = []
  const edges = []
  const top = PAD + RADIUS.chief
  const yOf = (row) => top + row * ROW
  const depts = departments.map((d) => {
    const head = agents.find((a) => a.id === d.head_id) || null
    const staff = agents.filter((a) => a.dept_id === d.id && a.id !== d.head_id && a.kind !== 'chief' && a.kind !== 'checker')
    return { d, head, staff, slots: Math.max(1, staff.length) }
  })
  const slots = depts.reduce((n, x) => n + x.slots, 0) + Math.max(0, depts.length - 1) * GAP
  const width = Math.max(slots, 2) * SLOT + PAD * 2
  const cx = width / 2

  nodes.push({ id: 'chief', kind: 'chief', x: cx, y: yOf(0), agent: chief })
  let parent = 'chief'
  let row = 1
  if (checker) {
    nodes.push({ id: checker.id || 'checker', kind: 'checker', x: cx, y: yOf(row), agent: checker })
    edges.push({ from: 'chief', to: checker.id || 'checker' })
    parent = checker.id || 'checker'
    row += 1
  }
  let lastRow = row - 1
  let left = PAD + (width - PAD * 2 - slots * SLOT) / 2
  for (const x of depts) {
    const mid = left + (x.slots * SLOT) / 2
    const deptNode = `dept:${x.d.id}`
    nodes.push({ id: deptNode, kind: 'dept', x: mid, y: yOf(row), dept: x.d })
    edges.push({ from: parent, to: deptNode })
    lastRow = Math.max(lastRow, row)
    let lead = deptNode
    if (x.head) {
      nodes.push({ id: x.head.id, kind: 'head', x: mid, y: yOf(row + 1), agent: x.head, deptId: x.d.id })
      edges.push({ from: deptNode, to: x.head.id })
      lead = x.head.id
      lastRow = Math.max(lastRow, row + 1)
    }
    x.staff.forEach((a, i) => {
      nodes.push({ id: a.id, kind: 'hired', x: left + SLOT * (i + 0.5), y: yOf(row + 2), agent: a, deptId: x.d.id })
      edges.push({ from: lead, to: a.id })
      lastRow = Math.max(lastRow, row + 2)
    })
    left += (x.slots + GAP) * SLOT
  }
  const height = yOf(lastRow) + RADIUS.chief + LABEL + PAD
  return { nodes, edges, width, height }
}

// Ids of the nodes from the Chief down to `id`, so the path to the selected node can be lit up.
export function pathTo(edges, id) {
  const up = new Map(edges.map((e) => [e.to, e.from]))
  const out = new Set()
  for (let at = id; at && !out.has(at); at = up.get(at)) out.add(at)
  return out
}

// An edge leaves under the parent's name and arrives on top of the child's circle.
export function edgePath(a, b) {
  const y1 = a.y + RADIUS[a.kind] + LABEL
  const y2 = b.y - RADIUS[b.kind] - 4
  const mid = (y1 + y2) / 2
  return `M${a.x} ${y1} C${a.x} ${mid} ${b.x} ${mid} ${b.x} ${y2}`
}
