# Flight Safety Command dashboard

    npm install
    npm run dev        # Vite on :5173 against the real backend (or run ../scripts/dev.sh for both)
    npm run dev:mock   # mock API on :8000 (same contract) + Vite
    npm run build && npm test

Vite proxies `/api` to `localhost:8000`. Contract: `../backend/API.md` (v0.4.0).

## How it talks to the API
- `src/api.js` `getState()` fetches `/overview`, `/org?include_retired=true`, `/departments?include_retired=true`, `/work-requests` (+ each `/work-requests/{id}` for briefs and the completion report), `/tasks`, `/messages`, and adapts them to the view shape (`dept` -> `dept_id`, `acceptance` -> `acceptance_criteria`, task note `{note, ts}` -> `{text, at}`, message `{body, ts, sender_name}` -> `{text, at, sender}`, `progress.percent` -> number).
- Writes: `POST /work-requests`, `POST /instructions {target, text}`, `POST /departments` (multipart; a 409 `needs_decision` is shown as an Update existing / Add as new choice, which calls `/departments/{id}/replace` or resends with `decision=new`), `POST /departments/{id}/retire`.
- `useLive` listens to the named SSE events from `/api/events` (`task.updated`, `message.created`, ...), refetches state (debounced 150 ms) and falls back to 2 s polling if SSE drops.
- Hiring is done by Vertical Head agents; it appears in the Org Chart and Chat Feed via `agent.hired` events.
- The mock server (`src/mock/`) implements the same endpoints and event names with fixture data.

## Design tokens

All colours, spacing, radii, shadows and type sizes are CSS custom properties in `:root` at the top of `src/styles.css`. Components use `var(--token)` only; no hex or rgb values in JSX or in rules below `:root`. One dark navy/slate theme with a gold brand accent.

**Surfaces** (darkest to lightest)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#070b14` | page |
| `--bg-2` | `#0b1220` | sidebar, inset wells |
| `--surface` | `#111a2c` | cards |
| `--surface-2` | `#18243b` | inputs, hover, nested panels |
| `--surface-3` | `#223250` | chips, avatars, raised bits |
| `--line` / `--line-2` | `#25344f` / `#6a7fa8` | decorative divider / control border and edges |

**Text:** `--text #eef2f9`, `--text-2 #c3cde0`, `--muted #92a1bc`.

**Brand (gold):** `--accent #f5c242`, `--accent-2 #ffd878`, `--accent-deep #d9a01a`, `--accent-ink #1a1406` (text on gold), `--accent-soft`, `--accent-line`. Gold is for the brand, primary actions, active nav and key highlights only.

**Status** (each has `--x`, `--x-soft` background and `--x-line` border; always paired with a text label)

| Token | Value | Meaning |
|---|---|---|
| `--ok` | `#4fd1a1` | done, live, healthy |
| `--info` | `#6cb6ff` | review, information |
| `--warn` | `#f5a54a` | caution, File Checker |
| `--bad` | `#ff7b72` | blocked, error |
| `--progress` | `#a99bff` | in progress / working (not gold) |

**Scales:** spacing `--sp-1..--sp-10` (4 to 40 px), radius `--radius-xs..--radius-lg` and `--radius-pill`, elevation `--shadow-1..--shadow-3`, type `--fs-2xs..--fs-3xl`, motion `--t-fast` and `--t` (at most 200 ms, off under `prefers-reduced-motion`).

**Neutral overlays:** `--overlay`, `--overlay-line` and `--scrim` are the only white/black transparencies and are allowed on purpose.

**Contrast (WCAG 2.1)**, computed from the token values above. Soft backgrounds are the status colour at 12% over `--surface`. Body text target is 7:1, other text 4.5:1, borders and focus rings 3:1.

| Pair | Ratio | Needs | Pass |
|---|---|---|---|
| `--text` on `--bg` | 17.53:1 | 7:1 | yes |
| `--text` on `--bg-2` | 16.68:1 | 7:1 | yes |
| `--text` on `--surface` | 15.48:1 | 7:1 | yes |
| `--text` on `--surface-2` | 13.81:1 | 7:1 | yes |
| `--text` on `--surface-3` | 11.40:1 | 7:1 | yes |
| `--text-2` on `--bg` | 12.30:1 | 4.5:1 | yes |
| `--text-2` on `--bg-2` | 11.71:1 | 4.5:1 | yes |
| `--text-2` on `--surface` | 10.87:1 | 4.5:1 | yes |
| `--text-2` on `--surface-2` | 9.69:1 | 4.5:1 | yes |
| `--text-2` on `--surface-3` | 8.01:1 | 4.5:1 | yes |
| `--muted` on `--bg` | 7.54:1 | 4.5:1 | yes |
| `--muted` on `--bg-2` | 7.17:1 | 4.5:1 | yes |
| `--muted` on `--surface` | 6.66:1 | 4.5:1 | yes |
| `--muted` on `--surface-2` | 5.94:1 | 4.5:1 | yes |
| `--muted` on `--surface-3` | 4.91:1 | 4.5:1 | yes |
| `--accent` text on `--surface` | 10.50:1 | 4.5:1 | yes |
| `--accent` text on `--accent-soft` (pill/banner on card) | 8.24:1 | 4.5:1 | yes |
| `--accent` text on `--surface-3` | 7.73:1 | 4.5:1 | yes |
| `--ok` text on `--surface` | 9.08:1 | 4.5:1 | yes |
| `--ok` text on `--ok-soft` (pill/banner on card) | 7.20:1 | 4.5:1 | yes |
| `--ok` text on `--surface-3` | 6.69:1 | 4.5:1 | yes |
| `--info` text on `--surface` | 8.09:1 | 4.5:1 | yes |
| `--info` text on `--info-soft` (pill/banner on card) | 6.47:1 | 4.5:1 | yes |
| `--info` text on `--surface-3` | 5.96:1 | 4.5:1 | yes |
| `--warn` text on `--surface` | 8.58:1 | 4.5:1 | yes |
| `--warn` text on `--warn-soft` (pill/banner on card) | 6.93:1 | 4.5:1 | yes |
| `--warn` text on `--surface-3` | 6.32:1 | 4.5:1 | yes |
| `--bad` text on `--surface` | 6.89:1 | 4.5:1 | yes |
| `--bad` text on `--bad-soft` (pill/banner on card) | 5.77:1 | 4.5:1 | yes |
| `--bad` text on `--surface-3` | 5.08:1 | 4.5:1 | yes |
| `--progress` text on `--surface` | 7.30:1 | 4.5:1 | yes |
| `--progress` text on `--progress-soft` (pill/banner on card) | 5.98:1 | 4.5:1 | yes |
| `--progress` text on `--surface-3` | 5.38:1 | 4.5:1 | yes |
| `--accent-ink` on `--accent` (primary button) | 11.06:1 | 4.5:1 | yes |
| `--accent-ink` on `--accent-deep` | 7.84:1 | 4.5:1 | yes |
| `--line-2` border on `--surface` | 4.32:1 | 3:1 | yes |
| `--line-2` border on `--surface-2` (inputs) | 3.85:1 | 3:1 | yes |
| `--line-2` border on `--surface-3` (chips) | 3.18:1 | 3:1 | yes |
| `--line-2` border on `--bg` | 4.89:1 | 3:1 | yes |
| focus ring `--accent` on `--bg` | 11.88:1 | 3:1 | yes |
| focus ring `--accent` on `--surface-2` | 9.36:1 | 3:1 | yes |
