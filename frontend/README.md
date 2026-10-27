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
