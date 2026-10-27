// Line icons (24px grid, stroke = currentColor) and the brand mark.
const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }

const PATHS = {
  overview: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.6" /><rect x="13.5" y="3.5" width="7" height="4.5" rx="1.6" /><rect x="13.5" y="11" width="7" height="9.5" rx="1.6" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.6" /></>,
  board: <><rect x="3.5" y="4" width="5" height="16" rx="1.4" /><rect x="9.5" y="4" width="5" height="11" rx="1.4" /><rect x="15.5" y="4" width="5" height="13.5" rx="1.4" /></>,
  org: <><rect x="9" y="3" width="6" height="4.5" rx="1.2" /><rect x="3" y="16.5" width="6" height="4.5" rx="1.2" /><rect x="15" y="16.5" width="6" height="4.5" rx="1.2" /><path d="M12 7.5v4.5M6 16.5V12h12v4.5" /></>,
  chat: <><path d="M20.5 12.2c0 4-3.8 7.3-8.5 7.3-1.2 0-2.3-.2-3.3-.6L4 20l1.2-3.6C4.1 15.2 3.5 13.8 3.5 12.2 3.5 8.2 7.3 5 12 5s8.5 3.2 8.5 7.2Z" /><path d="M8.5 11h7M8.5 14h4.5" /></>,
  console: <><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /><path d="M4 12h6M14 12h6" /><circle cx="12" cy="12" r="2" /></>,
  bolt: <path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z" />,
  file: <><path d="M14 3.5H7.5A2 2 0 0 0 5.5 5.5v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8L14 3.5Z" /><path d="M14 3.5V8h4.5" /></>,
  send: <path d="m4 12 16-8-6 16-2.6-6.4L4 12Z" />,
  building: <><path d="M4 20.5h16M6 20.5V5.5a1.5 1.5 0 0 1 1.5-1.5h9A1.5 1.5 0 0 1 18 5.5v15" /><path d="M9.5 8h1.5M13 8h1.5M9.5 11.5h1.5M13 11.5h1.5M10.5 20.5v-4h3v4" /></>,
  steer: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="2.2" /><path d="M12 3.5v6.3M4 13.5l6-1M20 13.5l-6-1" /></>,
}

export function Icon({ name, ...rest }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true" {...S} {...rest}>{PATHS[name]}</svg>
}

// A shield with a rising wing: flight safety.
export function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2.8 4.5 5.6v5.8c0 4.6 3.1 8.2 7.5 9.8 4.4-1.6 7.5-5.2 7.5-9.8V5.6L12 2.8Z" />
      <path d="M7.6 13.6 12 9.4l4.4 4.2M12 9.4v6.4" />
    </svg>
  )
}
