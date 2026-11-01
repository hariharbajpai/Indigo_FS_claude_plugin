import { useEffect, useRef, useState } from 'react'
import { api, fileUrl } from '../api.js'
import { useStore } from '../useLive.js'
import Avatar from './Avatar.jsx'
import RenameButton from './RenameButton.jsx'
import { Icon } from './Icons.jsx'
import { NAME as STATUS } from '../views/TaskBoard.jsx'
import { clip, isCut, shortRole } from '../roles.js'

const KIND = { chief: 'Chief', checker: 'File Checker', head: 'Vertical Head', hired: 'Specialist' }
const CAP = 5 // people per department, Vertical Head included
const date = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '')

function Section({ label, children }) {
  return (
    <section className="od-sec">
      <h3 className="od-label">{label}</h3>
      {children}
    </section>
  )
}

// A person or department as a link to their own card.
function Chip({ id, name, kind, onSelect }) {
  return (
    <button type="button" className="od-chip" onClick={() => onSelect(id)}>
      {kind === 'dept' ? <span className="od-chip-icon"><Icon name="building" /></span> : <Avatar name={name} kind={kind} size="sm" />}
      <span>{name}</span>
    </button>
  )
}

function TaskList({ tasks, empty }) {
  if (!tasks.length) return <p className="muted small">{empty}</p>
  return (
    <ul className="od-list">
      {tasks.map((t) => (
        <li key={t.id}>
          <span className={`pill ${t.status}`}>{t.badge || STATUS[t.status] || t.status}</span>
          <span><span className="muted">{t.id}</span> {t.title}</span>
        </li>
      ))}
    </ul>
  )
}

// The department's manuals, fetched when a card that needs them opens.
function Manuals({ deptId }) {
  const [state, setState] = useState({ docs: null, error: '' })
  useEffect(() => {
    let alive = true
    setState({ docs: null, error: '' })
    api.departmentDocuments(deptId)
      .then((r) => alive && setState({ docs: r.documents || [], error: '' }))
      .catch((e) => alive && setState({ docs: null, error: e.message }))
    return () => { alive = false }
  }, [deptId])
  if (state.error) return <p className="muted small">Could not load the manuals: {state.error}</p>
  if (!state.docs) return <p className="muted small">Loading...</p>
  if (!state.docs.length) return <p className="muted small">No manuals loaded.</p>
  return (
    <ul className="od-list">
      {state.docs.map((d) => (
        <li key={d.id}>
          <span className="od-doc-icon"><Icon name="file" /></span>
          <span>
            <strong>{d.title}</strong>
            <span className="muted tiny-text od-doc-meta">
              {[d.revision && d.revision !== 'unspecified' ? d.revision : 'revision not recorded',
                d.effective && `effective ${d.effective}`, d.pages && `${d.pages} pages`].filter(Boolean).join(' · ')}
            </span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function FilesBuilt({ files }) {
  if (!files.length) return <p className="muted small">None yet.</p>
  return (
    <ul className="od-list">
      {files.map((f) => (
        <li key={f.id}>
          <span className="od-doc-icon"><Icon name="file" /></span>
          <span><a href={fileUrl(f.id)} download={f.name}>{f.title || f.name}</a> <span className="muted tiny-text">{String(f.format).toUpperCase()}</span></span>
        </li>
      ))}
    </ul>
  )
}

// The full role and hire note, closed by default: the card itself shows only their short forms.
function FullText({ role, roleShort, reason, reasonShort }) {
  const longRole = Boolean(role) && isCut(role, roleShort)
  const longReason = Boolean(reason) && isCut(reason, reasonShort)
  if (!longRole && !longReason) return null
  return (
    <details className="od-more">
      <summary>{longRole && longReason ? 'Full role and hire note' : longRole ? 'Full role' : 'Full hire note'}</summary>
      {longRole && <p className="od-text">{role}</p>}
      {longReason && <><h3 className="od-label">Hired for</h3><p className="od-text">{reason}</p></>}
    </details>
  )
}

function about(kind, dept, head) {
  if (kind === 'chief') return 'Reads every work request, writes the brief, picks the departments and merges their answers into one report for you.'
  if (kind === 'checker') return 'Reads the manuals once for every task and hands the department a source pack: document, revision, section and page. Every task passes here first.'
  if (kind === 'head') return `Leads ${dept?.name || 'the department'}. Plans its tasks, hires specialists when a task needs one (up to ${CAP} people) and reviews their work.`
  return `Specialist in ${dept?.name || 'the department'}${head ? `, hired by ${head.name}` : ''}.`
}

function PersonCard({ node, data, working, onSelect }) {
  const { refresh } = useStore()
  const a = node.agent
  const kind = node.kind
  const dept = node.deptId ? data.departments.find((d) => d.id === node.deptId) : null
  const head = dept ? data.agents.find((x) => x.id === dept.head_id) : null
  const retired = a.status === 'retired'
  const mine = data.tasks.filter((t) => t.agent_id === a.id)
  const open = mine.filter((t) => t.status !== 'done')
  const files = data.files.filter((f) => f.created_by === a.id)
  const team = kind === 'head' ? data.agents.filter((x) => x.dept_id === dept?.id && x.id !== a.id) : []
  const roleShort = shortRole(a.role, 90)
  const reason = kind === 'hired' ? a.hire_reason : ''
  const reasonShort = clip(reason, 160)

  return (
    <>
      <div className="od-hero">
        <Avatar name={a.name} kind={kind} size="lg" />
        <div>
          <h2 id="od-title">{a.name}</h2>
          <div className="muted small">{roleShort || KIND[kind]}</div>
        </div>
      </div>
      <div className="od-pills">
        <span className="pill">{KIND[kind]}</span>
        {retired ? <span className="pill">Retired</span>
          : working ? <span className="pill working"><span className="dot working" />Working now</span>
            : <span className="pill">Idle</span>}
      </div>
      <p className="od-about">{about(kind, dept, head)}</p>

      {reasonShort && <Section label="Hired for"><p className="od-text">{reasonShort}</p></Section>}

      {kind !== 'chief' && (
        <Section label="Reports to">
          <div className="od-chips">
            {kind === 'hired' && head
              ? <Chip id={head.id} name={head.name} kind="head" onSelect={onSelect} />
              : <Chip id="chief" name={data.chief?.name || 'Chief'} kind="chief" onSelect={onSelect} />}
            {dept && <Chip id={`dept:${dept.id}`} name={dept.name} kind="dept" onSelect={onSelect} />}
          </div>
        </Section>
      )}

      {kind === 'chief' && (
        <Section label="Departments">
          {data.departments.filter((d) => d.status !== 'retired').length
            ? <div className="od-chips">{data.departments.filter((d) => d.status !== 'retired').map((d) => <Chip key={d.id} id={`dept:${d.id}`} name={d.name} kind="dept" onSelect={onSelect} />)}</div>
            : <p className="muted small">No departments yet.</p>}
        </Section>
      )}

      {kind === 'head' && (
        <Section label={`Team · ${1 + team.filter((x) => x.status !== 'retired').length}/${CAP}`}>
          {team.length
            ? <div className="od-chips">{team.map((x) => <Chip key={x.id} id={x.id} name={x.name} kind="hired" onSelect={onSelect} />)}</div>
            : <p className="muted small">No specialists hired yet.</p>}
        </Section>
      )}

      {kind === 'chief' && (
        <Section label="Work requests in hand">
          <TaskList tasks={data.work_requests.filter((w) => w.status !== 'Done').map((w) => ({ id: w.id, title: w.text, status: w.status }))}
            empty="Nothing waiting." />
        </Section>
      )}

      {kind === 'checker' && (
        <Section label="Source packs">
          <TaskList tasks={data.tasks.filter((t) => t.status !== 'done').slice(-6).map((t) => ({
            ...t, status: t.source_pack ? 'done' : 'todo', badge: t.source_pack ? `Pack ${t.source_pack.coverage}` : 'Waiting' }))}
            empty="No open tasks to check." />
        </Section>
      )}

      {(kind === 'head' || kind === 'hired') && (
        <Section label={`Working on${mine.length > open.length ? ` · ${mine.length - open.length} done` : ''}`}>
          <TaskList tasks={open} empty="No open tasks." />
        </Section>
      )}

      {(kind === 'head' || kind === 'hired') && dept && <Section label="Works from"><Manuals deptId={dept.id} /></Section>}

      {kind !== 'checker' && <Section label="Files built"><FilesBuilt files={files} /></Section>}

      <FullText role={a.role} roleShort={roleShort} reason={reason} reasonShort={reasonShort} />

      {a.created_at && <p className="muted tiny-text od-foot">Joined {date(a.created_at)}</p>}
      {!retired && a.id && (
        <div className="od-actions">
          <RenameButton current={a.name} label={`${KIND[kind]} ${a.name}`}
            onSave={async (name) => { await api.renameAgent(a.id, name); await refresh() }} />
        </div>
      )}
    </>
  )
}

function DeptCard({ node, data, working, onSelect }) {
  const { refresh } = useStore()
  const d = node.dept
  const retired = d.status === 'retired'
  const head = data.agents.find((a) => a.id === d.head_id)
  const staff = data.agents.filter((a) => a.dept_id === d.id && a.id !== d.head_id)
  const people = (head && head.status !== 'retired' ? 1 : 0) + staff.filter((a) => a.status !== 'retired').length
  const tasks = data.tasks.filter((t) => t.dept_id === d.id)
  const open = tasks.filter((t) => t.status !== 'done')
  return (
    <>
      <div className="od-hero">
        <span className="od-hub"><Icon name="building" /></span>
        <div>
          <h2 id="od-title">{d.name}</h2>
          <div className="muted small">Department</div>
        </div>
      </div>
      <div className="od-pills">
        {retired ? <span className="pill">Retired</span> : <span className="pill">{people}/{CAP} people</span>}
        {working && <span className="pill working"><span className="dot working" />Working now</span>}
      </div>
      <p className="od-about">The Vertical Head plans the department's work and hires specialists when a task needs one.</p>
      <Section label="Vertical Head">
        {head ? <div className="od-chips"><Chip id={head.id} name={head.name} kind="head" onSelect={onSelect} /></div> : <p className="muted small">None.</p>}
      </Section>
      <Section label="Specialists">
        {staff.length
          ? <div className="od-chips">{staff.map((a) => <Chip key={a.id} id={a.id} name={a.name} kind="hired" onSelect={onSelect} />)}</div>
          : <p className="muted small">None hired yet.</p>}
      </Section>
      <Section label="Manuals"><Manuals deptId={d.id} /></Section>
      <Section label={`Open tasks${tasks.length > open.length ? ` · ${tasks.length - open.length} done` : ''}`}>
        <TaskList tasks={open} empty="No open tasks." />
      </Section>
      {!retired && (
        <div className="od-actions">
          <RenameButton current={d.name} label={`department ${d.name}`}
            onSave={async (name) => { await api.renameDepartment(d.id, name); await refresh() }} />
        </div>
      )}
    </>
  )
}

// The card that opens beside the graph when a node is clicked. Esc or × closes it.
export default function OrgDetail({ node, data, working, onSelect, onClose }) {
  const closeRef = useRef(null)
  useEffect(() => { closeRef.current?.focus() }, [node.id])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const where = node.kind === 'dept' ? 'Department' : node.deptId
    ? data.departments.find((d) => d.id === node.deptId)?.name || node.deptId : 'Leadership'
  return (
    <aside className="org-detail" role="dialog" aria-modal="false" aria-labelledby="od-title">
      <div className="od-top">
        <span className="od-crumb">Organisation · {where}</span>
        <button ref={closeRef} type="button" className="ghost tiny od-close" onClick={onClose} aria-label="Close">×</button>
      </div>
      {node.kind === 'dept'
        ? <DeptCard node={node} data={data} working={working} onSelect={onSelect} />
        : <PersonCard node={node} data={data} working={working} onSelect={onSelect} />}
    </aside>
  )
}
