import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useStore } from '../useLive.js'

const LINKS = [
  ['/', 'Overview'],
  ['/board', 'Task Board'],
  ['/org', 'Org Chart'],
  ['/chat', 'Chat Feed'],
  ['/console', 'Owner Console'],
]

export default function Layout() {
  const { data, error, loading, mode } = useStore()
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <div className="app">
      <header className="topbar">
        <h1>Flight Safety Command</h1>
        <nav aria-label="Main">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'}>{label}</NavLink>
          ))}
        </nav>
        <div className="topbar-right">
          {data && data.activity.running.length > 0 && (
            <span className="pill working" title="Agents running in Claude Code">{data.activity.running.length} working</span>
          )}
          <span className={`pill ${mode}`} title="Live connection">{mode === 'sse' ? 'live' : mode}</span>
          <button type="button" className="ghost" onClick={() => setDark(!dark)} aria-pressed={dark}>
            {dark ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>
      <main>
        {error && !data && <div className="banner error" role="alert">Cannot reach the API: {error.message}</div>}
        {error && data && <div className="banner warn" role="status">Connection problem, showing last data. {error.message}</div>}
        {data && data.activity.running.length === 0 && data.activity.waiting.length > 0 && (
          <div className="banner info" role="status">
            {data.activity.waiting.map((a) => a.agent_name).join(', ')} {data.activity.waiting.length === 1 ? 'has' : 'have'} new
            work waiting. In Claude Code, run <code>/flight-safety-agents:run</code> so the team picks it up.
          </div>
        )}
        {loading ? <p className="muted">Loading...</p> : data && <Outlet />}
      </main>
    </div>
  )
}
