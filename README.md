# flight-safety-agents

A team of flight-safety department agents (**Audit, SMS, FDM**, plus any department you add) that share one knowledge base built from **your own manuals**. Upload a manual and it becomes searchable, revision-tracked markdown. Ask a question and the right departments answer from it, with citations, in the same chat. Departments ask each other for input through a shared board and keep their own sourced memory, so they get better at your operation over time.

> **Decision support only.** The agents draft, analyse and cross-check. Approvals, risk acceptance, finding closure and regulatory submissions stay with the accountable people.

## How it works

```
                        you, in one chat
                              │
                      ┌───────▼────────┐
                      │  safety-team   │  coordinator: picks departments,
                      │ (main chat)    │  merges answers, flags conflicts
                      └─┬─────┬──────┬─┘
            ┌───────────┘     │      └────────────┐
      ┌─────▼─────┐    ┌──────▼─────┐    ┌────────▼───┐   + your own
      │ sms-agent │    │ audit-agent│    │ fdm-agent  │   (safety-add-department)
      │ sms-dept  │    │ audit-dept │    │ fdm-dept   │
      └─────┬─────┘    └──────┬─────┘    └────────┬───┘
            └───────────┬─────┴───────────────────┘
                  ┌─────▼──────┐
                  │ safety-kb  │  ingest manuals → sectioned markdown
                  │ (skill +   │  search with citations
                  │  kb.py)    │  revision control
                  └─────┬──────┘
                        ▼
             ./safety-kb/  (your folder, never in git)
             shared/  sms/  audit/  fdm/  _outputs/
```

| Piece | What it is |
|---|---|
| `safety-kb` skill | Turns PDF/DOCX/MD/TXT manuals into markdown split by chapter and section, with page markers, revision and effective date. Keyword search that returns document, revision, section and page. Old revisions are kept aside and not searched. |
| `sms-dept`, `audit-dept`, `fdm-dept` skills | What each department does: workflows, output templates, what to look up, what to cross-reference. |
| `sms-agent`, `audit-agent`, `fdm-agent` | The same departments as subagents, so several can work in parallel in Claude Code. |
| `safety-team` skill | The coordinator. Routes a request, runs departments in parallel (or in turn where subagents don't exist), runs follow-up rounds while the board has open requests, then merges. |
| `safety-add-department` skill | Creates a new department (skill + agent + KB folder) from a short interview. |

## Install

### Claude Code (recommended)

```
/plugin marketplace add hariharbajpai/Indigo_FS_claude_plugin
/plugin install flight-safety-agents@flight-safety-agents
```

The same from a normal terminal: `claude plugin marketplace add hariharbajpai/Indigo_FS_claude_plugin` then `claude plugin install flight-safety-agents@flight-safety-agents`. Both forms also accept a local folder path in place of `<user>/<repo>`, which is handy for testing before you push.

Restart or reload, then type `/` and look for the `safety-kb`, `safety-team`, `sms-dept`, `audit-dept`, `fdm-dept` and `safety-add-department` skills. Plugin skills are namespaced, so they may show as `flight-safety-agents:safety-team`. The agents are listed under `/agents`.

Check a clone of the repo before publishing: `claude plugin validate .`

For PDFs, install one of: `pip install pypdf` or `brew install poppler` (provides `pdftotext`). DOCX, MD and TXT need nothing extra.

### claude.ai (Skills upload)

```bash
./scripts/package-skills.sh        # writes dist/*.zip
```

In claude.ai go to **Settings → Capabilities → Skills**, upload `safety-kb.zip` first, then the department skills you want, and `safety-team.zip` for team work. claude.ai has no subagents, so the coordinator runs each department in turn in the same reply. Files created in a chat may not persist, so keep the generated `safety-kb/` folder in a Project's knowledge.

## Quick start

1. **Work in a folder you control** (your project folder). The KB is created there as `./safety-kb/`.
2. **Load manuals.** Drop files into the chat or point to them:
   > "Ingest `~/Docs/SMS_Manual_R05.pdf` into sms. Revision 05, effective 1 March 2026."
   > "Yeh audit handbook audit department me save kar do."

   Claude reads the revision from the document, confirms it with you, converts the file, and checks the result.
3. **Ask.**
   > "SMS: assess the hazard of crews continuing unstable approaches at one airport. Use our risk matrix."
   > "FDM aur SMS dono dekho: unstable approach rate badh gaya hai (CSV attached). Audit challenge kare."
   > "Do our SMS manual and audit handbook agree on report acknowledgement timelines?"
   > "@audit write a finding and CAP for this: ..."

### Many files, updates and replacements

A department can hold as many documents as you like: one manual, ten SOPs, checklists, forms. Each file becomes one document (a folder of markdown). Upload several at once and say which department they belong to.

Every upload is checked against what is already stored before anything is written:

| Result | What happens |
|---|---|
| **New** | added as a new document; Claude confirms the revision it read from the cover |
| **Duplicate** (identical file) | skipped, and you are told |
| **Looks like a new version of a stored document** | **Claude asks you: update the existing document, or add it as a separate new one?** |
| **Identical to an older, superseded revision** | Claude warns that this would roll the document back and asks |

Then you steer with plain words:

> "Yeh teen files sms me daal do." → one plan table, one set of questions, then ingest all.
> "SMS Manual ko is file se replace karo." → the document is updated in place (same id); the old revision is archived and not searched.
> "Yeh file sahi nahi thi, corrected wali se replace karo (same revision)." → forced re-issue of the same revision.
> "Hazard Register SOP hata do." → withdrawn from search but kept on disk; nothing is hard-deleted.

When a document is replaced or withdrawn, department memory notes that relied on the old version are flagged *verify before use*.

## Multi-agent in one chat

You steer it with plain words:

| You say | Happens |
|---|---|
| "SMS and FDM both..." / `@audit` | exactly those departments |
| "full team" | every department that has documents loaded |
| a topic only | the coordinator picks by scope and says which, in one line |
| "SMS drafts, Audit reviews" | draft → review pattern |
| "compare what SMS and Audit manuals say" | cross-check pattern |

Each department answers in the same shape: **Position / Evidence (cited) / Gaps / Needs from other departments / Confidence / Memory**. The coordinator relays requests between departments in rounds (details below), then shows a combined view: agreements, conflicts (both sources cited, no silent winner), gaps and actions with owners.

## Departments coordinating with each other

Subagents cannot message each other live, so coordination goes through a **board** in the knowledge base (`safety-kb/_team/board.jsonl`) and the coordinator runs the departments in rounds:

```
Round 1   SMS, FDM, Audit work in parallel.
          SMS posts to the board:  "FDM: unstable-approach rate by airport, last 12 months?"
          SMS gives a provisional position.
Round 2   FDM reads its inbox, answers with citations.
Round 3   SMS reads the answer and finishes its position.   → combined view
```

- Each request names one department and carries the exact question. Identical open requests are refused, a thread is capped at 8 requests, and the coordinator stops after 3 follow-up rounds (you can ask for more). Anything unresolved, or addressed to you, is listed as an *open item*.
- See what happened: `python3 skills/safety-kb/scripts/kb.py board show`, and the combined view ends with a one-line coordination trace.

## Memory

Each department keeps a small memory in `safety-kb/_memory/<dept>.jsonl`: terms your organisation uses, where the authoritative answer to a recurring question lives, your preferences and corrections, decisions (by role and date), recurring pitfalls. Every note has a source.

- **Guardrails:** notes are short pointers (max 400 characters), not copies of manuals. Emails and phone numbers are rejected; the agents are told never to store names of crew or employees, or raw FDM figures. Memory is a hint, never a source: the manual wins, and the agent confirms in the manual before relying on a note.
- **Stays correct:** when you ingest a new revision of a manual, notes that relied on the old one are flagged *VERIFY BEFORE USE* until an agent re-checks them or forgets them.
- **You stay in control:** agents say what they remembered at the end of each answer. Review with `kb.py mem show`, remove with `kb.py mem forget <id>`.
- Memory is local to your `safety-kb/` folder and, like the manuals, is not committed to git.

## Add your own department

> "Add a department for Flight Ops Safety. They review route and airport hazards, brief crews on safety notices and own the safety notice register."

`safety-add-department` interviews you briefly and writes `.claude/skills/<code>-dept/` and `.claude/agents/<code>-agent.md` in your project, plus `safety-kb/<code>/`. The coordinator then treats it like the built-in ones.

## Command line (optional)

The same tool the skills use:

```bash
python3 skills/safety-kb/scripts/kb.py ingest manual.pdf --dept sms --title "SMS Manual" --rev "Rev 05" --effective 2026-03-01
python3 skills/safety-kb/scripts/kb.py match a.pdf b.docx c.pdf          # new, duplicate, or a new version of something stored?
python3 skills/safety-kb/scripts/kb.py ingest new_issue.pdf --replace sms-manual --rev "Rev 6"
python3 skills/safety-kb/scripts/kb.py retire hazard-register-sop --reason "superseded by company SOP"
python3 skills/safety-kb/scripts/kb.py search "risk assessment matrix" --dept sms --dept shared
python3 skills/safety-kb/scripts/kb.py status
python3 skills/safety-kb/scripts/kb.py board show --open      # what departments are asking each other
python3 skills/safety-kb/scripts/kb.py mem show               # what each department has learned
```

KB location: `--kb DIR`, else `$SAFETY_KB_DIR`, else `./safety-kb`.

## Confidentiality

Manuals, FDM data and reports are confidential. `.gitignore` excludes `safety-kb/`, PDFs, Word, Excel and CSV files so they are not pushed by accident. Before you ingest company documents into any AI tool, check your organisation's data policy with IT/Compliance. FDM outputs are de-identified by default.

## Known limits

- **Scanned PDFs** have no text layer. The tool stops and asks you to OCR first (`ocrmypdf in.pdf out.pdf`).
- **Page numbers** are PDF page indexes, which can differ from the printed page labels.
- **Heading detection** for PDFs is heuristic (Chapter/Part/numbered headings). The ingest report shows how many headings were found; if few, check the chunk files or use `--layout`.
- **Search is keyword-based** (BM25), not semantic. It works well on manuals because they use consistent terms; agents try several phrasings. For very large libraries, front it with a proper vector index or a document connector.
- Legacy `.doc` is not read; save as `.docx`.
- **Coordination is asynchronous.** A department sees another's answer in the next round, not mid-run. Claude Code's experimental agent-teams mode could allow live messaging; this plugin does not depend on it.
- **Memory is only as good as what gets recorded.** Agents are told to record sparingly and with sources; review it now and then.
- The department skills are frameworks. They do not contain your regulations or procedures, only how to work with them. Quality depends on the documents you ingest.

## Flight Safety Command (v0.4.0): Chief, Vertical Heads, hiring and live dashboard

On top of the plugin there is a small web app: a FastAPI backend (`backend/`), a React dashboard (`frontend/`) and a Chief agent (`agents/chief-agent.md`).

### Chief
**Dhruv Rebbapragada, Chief of Flight Safety**, is seeded on first start and cannot be retired. The Owner gives work to the Chief (Received -> Briefed -> In progress -> Done). The Chief writes a versioned brief and tasks, each owned by one department. If no department fits, the brief asks which department to add. Owner instructions (to the Chief or a department) re-plan the brief; conflicting in-flight tasks become `blocked`.

### Vertical Heads and departments
Add a department with one or more PDFs, a department name and a **Vertical Head name** (both required). PDFs go through the real `skills/safety-kb/scripts/kb.py`: `match` first (a duplicate or new version returns `needs_decision`, nothing is written), then `ingest` (or `ingest --replace` to update). Retiring a department withdraws its documents with `kb.py retire`; they stay on disk. The Head moves tasks (`in_progress`, `review`, `blocked`, `done`, note required).

### Hiring
A Vertical Head can hire agents for a task: cap 5 active agents per department, every hire (and refusal) is logged.

### Dashboard
Org chart, task board, work requests, and a chat feed with every message (Owner, Chief, Heads, hired agents, and the inter-department board mirrored from `kb.py board`). Updates arrive live over SSE (`/api/events`). The Owner can send further instructions at any time. API reference: `backend/API.md` (interactive docs at `/docs`).

### Run
```bash
scripts/dev.sh        # creates .venv, npm install, starts backend :8000 and frontend :5173; Ctrl-C stops both
```
Needs `python3` (3.10+) and `node`/`npm` (18+); PDF text needs `pdftotext`, pypdf or PyMuPDF (as for `kb.py`). Backend only: `.venv/bin/python -m backend.fsa --port 8000`.

Environment: `FSA_DB` (SQLite file, default `./safety-kb/_team/fsa.db`), `FSA_KB_ROOT` (knowledge-base root, default `./safety-kb`, git-ignored), `FSA_KB_SCRIPT` (alternative kb.py), `ANTHROPIC_API_KEY` and `FSA_MODEL` for a Claude planner. Without a key a deterministic keyword planner is used.

### Tests
```bash
python3 -m unittest discover tests                                    # kb.py tests, standard library only
.venv/bin/python -m pytest tests/backend                              # backend (pip install -r backend/requirements.txt first)
cd frontend && npm install && npm test && npm run build               # frontend
```

### Known gaps
- `/api/messages` returns at most 500 messages by default; the frontend has no paging.
- The Vite proxy is hardcoded to `http://localhost:8000` (`frontend/vite.config.js`).
- No browser-level end-to-end tests (frontend has unit tests only).

## Repository layout

```
.claude-plugin/        plugin.json, marketplace.json
skills/
  safety-kb/           ingest + search (scripts/kb.py), conventions
  safety-team/         coordinator
  sms-dept/  audit-dept/  fdm-dept/
  safety-add-department/   + assets/ templates
agents/                sms-agent, audit-agent, fdm-agent, chief-agent
backend/               FastAPI app (Chief, departments, hiring, SSE) + API.md
frontend/              React dashboard (Vite)
scripts/package-skills.sh, scripts/dev.sh
tests/                 python3 -m unittest discover -s tests -v   (backend tests in tests/backend, run with pytest)
```

## Development

```bash
python3 -m unittest discover -s tests -v     # builds fictional PDF/DOCX/MD fixtures, no third-party libraries
python3 -m pytest tests/backend              # web app backend (needs backend/requirements.txt)
```

Contributions welcome: more departments (Investigation, Cabin, Ground, Maintenance safety), better table handling for PDFs, a semantic search backend. Do not commit real manuals or flight data.

## License

MIT
