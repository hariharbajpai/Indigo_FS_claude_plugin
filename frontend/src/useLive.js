import { createContext, createElement, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api } from './api.js'

const POLL_MS = 2000

// SSE (/api/events) sends NAMED events (API.md); any of them triggers a (debounced) refetch.
// If SSE is unavailable, poll every 2s.
export const EVENT_TYPES = ['work_request.created', 'work_request.updated', 'brief.created', 'task.created', 'task.updated',
  'message.created', 'agent.hired', 'agent.hire_refused', 'department.created', 'department.retired', 'report.posted']
export function useLive(fetcher = api.getState) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('connecting') // sse | polling | connecting
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher

  const refresh = useCallback(async () => {
    try {
      setData(await fetchRef.current())
      setError(null)
    } catch (e) {
      setError(e)
    }
  }, [])

  useEffect(() => {
    let alive = true
    let timer = null
    let es = null
    const startPolling = () => {
      if (timer || !alive) return
      setMode('polling')
      timer = setInterval(refresh, POLL_MS)
    }
    const stopPolling = () => { clearInterval(timer); timer = null }
    refresh()
    if (typeof EventSource === 'undefined') {
      startPolling()
    } else {
      es = new EventSource('/api/events')
      es.onopen = () => { stopPolling(); setMode('sse'); refresh() }
      let debounce = null
      const onEvent = () => { clearTimeout(debounce); debounce = setTimeout(refresh, 150) }
      EVENT_TYPES.forEach((t) => es.addEventListener(t, onEvent))
      es.onmessage = onEvent
      es.onerror = () => startPolling() // browser keeps retrying; polling covers the gap
    }
    return () => { alive = false; stopPolling(); es && es.close() }
  }, [refresh])

  return { data, error, mode, loading: data === null && !error, refresh }
}

const LiveContext = createContext(null)

export function LiveProvider({ children }) {
  const live = useLive()
  return createElement(LiveContext.Provider, { value: live }, children)
}

export function useStore() {
  const v = useContext(LiveContext)
  if (!v) throw new Error('useStore must be used inside LiveProvider')
  return v
}
