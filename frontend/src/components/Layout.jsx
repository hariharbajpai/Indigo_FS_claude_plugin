import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useStore } from '../useLive.js'
import { BrandMark, Icon } from './Icons.jsx'
import Avatar from './Avatar.jsx'

export const PAGES = [
  { to: '/', icon: 'overview', label: 'Overview', eyebrow: 'Command centre', title: 'Overview', sub: 'Work requests, briefs, files and who is working right now.' },
  { to: '/board', icon: 'board', label: 'Task Board', eyebrow: 'Operations', title: 'Task board', sub: 'Every task across the departments, by status.' },
  { to: '/org', icon: 'org', label: 'Organisation', eyebrow: 'People', title: 'Organisation', sub: 'The Chief of Flight Safety, the Vertical Heads and the specialists they hired.' },
  { to: '/chat', icon: 'chat', label: 'Communications', eyebrow: 'Messages', title: 'Communications', sub: 'Every message between you and the team.' },
  { to: '/console', icon: 'console', label: 'Owner Console', eyebrow: 'Owner', title: 'Owner console', sub: 'Give work, steer the team and manage departments.' },
]

const MODE = { sse: 'Live', polling: 'Polling', connecting: 'Connecting' }

export default function Layout() {
  const { data, error, loading, mode } = useStore()
  const { pathname } = useLocation()
  const page = PAGES.find((p) => (p.to === '/' ? pathname === '/' : pathname.startsWith(p.to))) || PAGES[0]
  const running = data?.activity.running.length || 0
  const waiting = data?.activity.waiting || []
  const openTasks = data ? data.tasks.filter((t) => t.status !== 'done').length : 0
  const chief = data?.chief

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><BrandMark /></div>
          <div>
            <div className="brand-name">Flight Safety Command</div>
            <div className="brand-sub">Safety organisation</div>
          </div>
        </div>
        <div className="nav-label">Navigation</div>
        <nav className="nav" aria-label="Main">
          {PAGES.map((p) => (
            <NavLink key={p.to} to={p.to} end={p.to === '/'}>
              <Icon name={p.icon} />
              <span className="label">{p.label}</span>
              {p.to === '/board' && openTasks > 0 && <span className="badge" title="Open tasks">{openTasks}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="status-card" aria-label="Status">
            <div className="status-row"><span className={`dot ${mode === 'sse' ? 'live' : mode}`} />{MODE[mode] || mode} updates</div>
            <div className="status-row">
              <span className={`dot ${running ? 'working' : ''}`} />
              {running ? `${running} agent${running > 1 ? 's' : ''} working` : 'No agent running'}
            </div>
          </div>
          {chief && (
            <div className="chief-chip">
              <Avatar name={chief.name} kind="chief" size="sm" />
              <div className="who"><strong>{chief.name}</strong><span className="muted tiny-text">{chief.role}</span></div>
            </div>
          )}
        </div>
      </aside>

      <div className="main">
        <header className="page-head">
          <div>
            <div className="eyebrow">{page.eyebrow}</div>
            <h1>{page.title}</h1>
            <p className="sub">{page.sub}</p>
          </div>
          {running > 0 && <div className="head-actions"><span className="pill working"><span className="dot working" />{running} working</span></div>}
        </header>
        <main className="content">
          {error && !data && <div className="banner error" role="alert">Cannot reach the dashboard server: {error.message}</div>}
          {error && data && <div className="banner warn" role="status">Connection problem, showing the last data. {error.message}</div>}
          {data && running === 0 && waiting.length > 0 && (
            <div className="banner info" role="status">
              <strong>{waiting.map((a) => a.agent_name).join(', ')}</strong> {waiting.length === 1 ? 'has' : 'have'} new
              work waiting. In Claude Code, run <code>/flight-safety-agents:run</code> so the team picks it up.
            </div>
          )}
          {loading ? <p className="muted">Loading...</p> : data && <Outlet />}
        </main>
      </div>
    </div>
  )
}
