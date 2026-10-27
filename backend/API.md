# Flight Safety Command API (v0.4.0)

Base URL `http://localhost:8000`. JSON everywhere except `POST /api/departments` (multipart) and `GET /api/events` (SSE).
CORS allows `http://localhost:5173` and `http://127.0.0.1:5173`. One local Owner, no auth.
Timestamps are ISO-8601 UTC strings (`2026-10-27T04:17:16Z`). IDs are strings: `WR-1` work request, `TK-1` task, `ag-1` agent (Chief is `chief`), `dept-slug` for departments (e.g. `engine-maintenance`), messages and events use integers.

Errors: `{"detail": "clear message"}` with 400 (bad input), 404 (unknown id), 409 (refused: Chief retire, hire cap, duplicate, bad state), 422 (validation).

## Shapes

```jsonc
Agent      { "id":"ag-3","name":"Asha Verma","role":"Vertical Head","kind":"chief|head|hired","dept":"engine-maintenance"|null,"status":"active|retired","created_at":"..." }
Department { "id":"engine-maintenance","name":"Engine Maintenance","head_id":"ag-2","head_name":"Asha Verma","status":"active|retired","created_at":"..." }
WorkRequest{ "id":"WR-1","text":"...","status":"Received|Briefed|In progress|Done","created_at":"...","updated_at":"...",
             "brief_version":2|null,
             "progress":{"total":4,"done":1,"percent":25} }
Brief      { "work_request_id":"WR-1","version":2,"summary":"...","goals":["..."],
             "departments":["engine-maintenance"],"needs_department":false,"question":null|"Which department should handle this? ...",
             "change_note":null|"Owner instruction: ...","created_at":"..." }
Task       { "id":"TK-1","title":"...","description":"...","acceptance":"...","dept":"engine-maintenance",
             "agent_id":"ag-5"|null,"agent_name":"..."|null,"status":"todo|in_progress|review|blocked|done",
             "work_request_id":"WR-1","created_at":"...","updated_at":"...",
             "notes":[{"id":1,"task_id":"TK-1","author":"ag-2","status":"in_progress","note":"...","ts":"..."}],  // only in detail/list responses (always included)
             "message_count":3 }
Message    { "id":10,"sender":"owner|chief|ag-2","sender_name":"Owner","recipient":"chief|ag-2|owner","recipient_name":"...",
             "dept":"engine-maintenance"|null,"task_id":"TK-1"|null,"work_request_id":"WR-1"|null,
             "kind":"request|brief|assign|status|hire|instruction|board|report|refusal|chat","body":"...","ts":"..." }
Event      { "id":55,"type":"work_request.created|brief.created|task.created|task.updated|message.created|agent.hired|agent.hire_refused|department.created|department.retired|work_request.updated|report.posted","ts":"...","data":{...} }
```

## Endpoints

### GET /api/overview
```json
{ "chief": Agent,
  "counts": {"departments":2,"agents":6,"work_requests":3,"tasks":{"todo":1,"in_progress":2,"review":0,"blocked":0,"done":4},"messages":42},
  "work_requests": [WorkRequest],
  "last_event_id": 55 }
```

### GET /api/org
Org chart, Chief at the top.
```json
{ "chief": Agent,
  "departments": [ { "department": Department, "head": Agent, "agents": [Agent /* active hired agents */], "active_count": 3, "hire_cap": 5 } ] }
```
Add `?include_retired=true` to include retired departments.

### GET /api/work-requests  ->  `[WorkRequest]` (newest first)
### GET /api/work-requests/{id}
```json
{ "request": WorkRequest, "briefs": [Brief /* all versions, oldest first */], "brief": Brief /* latest */|null,
  "tasks": [Task], "report": Message|null }
```
### POST /api/work-requests
Body `{ "text": "Inspect hydraulic leaks on fleet B, English or Hinglish" }` -> 201 `WorkRequest` (status Received). The Chief processes it (brief + tasks) asynchronously within seconds; watch SSE. Add `?wait=true` to plan synchronously and return `{request, brief, tasks}` instead (used by curl demos and tests).
Empty text -> 422.

### POST /api/instructions
Body `{ "target": "chief" | "<dept id>", "text": "...", "work_request_id": "WR-1" /* optional, defaults to latest open request */ }` -> 201 `{ "message": Message, "brief": Brief|null, "blocked_tasks": ["TK-2"] }`.
Delivered as message from `owner`. The Chief re-plans: new brief version, conflicting in-flight tasks become `blocked` with a note. Unknown dept -> 404; empty text -> 422.

### GET /api/tasks?status=&dept=&work_request_id=  ->  `[Task]`
### GET /api/tasks/{id}  ->  `Task`
### POST /api/tasks/{id}/status
Body `{ "status": "in_progress|review|blocked|done", "note": "required, non-empty", "author": "ag-2" /* optional, defaults to the dept head */ }` -> `Task`. Missing note -> 422.
### POST /api/tasks/{id}/assign
Body `{ "agent_id": "ag-5" }` -> `Task`. Agent must be active and belong to the task's department.
### POST /api/departments/{id}/hire
Body `{ "name":"Ravi", "role":"Hydraulics analyst", "reason":"Task TK-1 needs...", "task_id":"TK-1" /* optional: also assigns */ }` -> 201 `Agent`. At 5 active agents (head + hired) in the department -> 409 and a `refusal` message + `agent.hire_refused` event are logged.

### GET /api/messages?dept=&agent=&task=&work_request_id=&since_id=&limit=
Oldest first, default limit 500. `dept` matches messages tied to the department or sent/received by its agents; `agent` matches sender or recipient; `task` matches task id. -> `[Message]`.

### GET /api/departments?include_retired=  ->  `[Department]`
### POST /api/departments   (multipart/form-data)
Fields: `files` (one or more PDFs, repeated field), `name` (string), `head_name` (string), optional `decision` (`""|"new"|"replace"` used after a match decision, with `target` = existing dept id).
- Missing PDF -> 400 `"Upload at least one PDF"`. Missing/blank `head_name` -> 400 `"Vertical Head name is required"`. Missing `name` -> 400.
- The PDFs are checked with the real `skills/safety-kb/scripts/kb.py match` first (duplicate = same SHA-256, new_version = similar document name; each result may carry `doc_id`); new departments are ingested with `kb.py ingest` (KB root `FSA_KB_ROOT`). A PDF with no extractable text (scanned) -> 400. Response 200/201:
```json
{ "status": "created", "department": Department, "head": Agent, "matches": [] }
```
or, nothing is written and the Owner must decide:
```json
{ "status": "needs_decision", "matches": [ { "file":"a.pdf","result":"duplicate|new_version|new","existing_dept":"engine-maintenance"|null,"detail":"..." } ] }
```
(HTTP 409 for `needs_decision`.) To proceed, resend with `decision=replace&target=<dept id>` (updates the matching document via `kb.py ingest --replace`, old revision archived; keeps head) or `decision=new` (force create).
### POST /api/departments/{id}/replace  (multipart: `files`) -> `{ "status":"replaced","department":Department }`
### POST /api/departments/{id}/retire  -> `{ "department": Department, "retired_agents": ["ag-2","ag-5"] }`. Retires head and hired agents. Open tasks of the dept become `blocked` with a note.
Chief cannot be retired: `POST /api/agents/chief/retire` -> 409.

### GET /api/events  (Server-Sent Events)
`Content-Type: text/event-stream`. Each frame:
```
id: 55
event: message.created
data: {"id":55,"type":"message.created","ts":"...","data":{...}}

```
Send `Last-Event-ID` (or `?since_id=55`) to replay missed events. A `: keepalive` comment is sent every 15s. The server also polls the DB every 0.5s so every change is pushed within 3s. UI pattern: on any event refetch the affected resource (`task.*` -> /api/tasks, `message.created` -> /api/messages, `brief.created`/`work_request.*` -> /api/work-requests, `agent.*`/`department.*` -> /api/org).

### GET /api/health  ->  `{ "ok": true, "version": "0.4.0" }`
