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

Restart or reload, then type `/` and look for the `safety-kb`, `safety-team`, `sms-dept`, `audit-dept`, `fdm-dept` and `safety-add-department` skills, and the Flight Safety Command commands (`start`, `add-dept`, `work`, `tell`, `run`, `status`, `stop`, `update`). Plugin skills are namespaced, so they may show as `flight-safety-agents:safety-team`. The agents are listed under `/agents`.

### Update

Plugins from a GitHub marketplace don't update on their own. When a new version is out, type this in Claude Code:

```
/flight-safety-agents:update
```

It refreshes the marketplace and updates the plugin. Run `/reload-plugins` or start a new session to use the new version; the dashboard switches over the next time `/flight-safety-agents:start` runs.

On v0.10.0 or older, which don't have that command yet, paste this into the Claude Code prompt box once (or run the two commands in a terminal):

```
Run `claude plugin marketplace update flight-safety-agents` and then `claude plugin update flight-safety-agents@flight-safety-agents`
```

To get new versions automatically instead, run `/plugin` in a terminal session, open **Marketplaces**, select `flight-safety-agents` and choose **Enable auto-update**.

**Publishing a new version:** raise `version` in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `backend/fsa/__init__.py` and `frontend/package.json` (a test checks they match), then push to `main`. Claude Code only offers an update when this number changes.

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
python3 skills/safety-kb/scripts/kb.py match a.pdf b.docx c.pdf          # new, duplicate, or a new version of something stored? Also reads title, revision and date from each cover
python3 skills/safety-kb/scripts/kb.py ingest new_issue.pdf --replace sms-manual --rev "Rev 6"
python3 skills/safety-kb/scripts/kb.py retire hazard-register-sop --reason "superseded by company SOP"
python3 skills/safety-kb/scripts/kb.py search "risk assessment matrix" --dept sms --dept shared
python3 skills/safety-kb/scripts/kb.py reindex                           # rebuild the saved search index (a cache in safety-kb/_index/; searches take milliseconds)
python3 skills/safety-kb/scripts/kb.py status
python3 skills/safety-kb/scripts/kb.py board show --open      # what departments are asking each other
python3 skills/safety-kb/scripts/kb.py mem show               # what each department has learned
python3 skills/safety-kb/scripts/kb.py links find --dept sms --learn --text "unstable approach rate at Delhi"   # only what the words trigger, in other departments too
python3 skills/safety-kb/scripts/kb.py links show             # the word -> department links learned so far
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

## Flight Safety Command (v0.11.0): a Chief, a File Checker, Vertical Heads and a live dashboard, inside Claude Code

Flight Safety Command runs a small flight-safety organisation as **subagents in your Claude Code session** (desktop app, IDE or terminal), on your own login. No API key, no terminal, nothing to install beyond the plugin.

```
Owner (you) ──work / instructions──▶ Dhruv Rebbapragada, Chief of Flight Safety
                                         │ brief (versioned) + tasks, one department each
                                         ▼
                                    File Checker (Documentation Controller): reads the manuals once per task,
                                         │ hands each department a source pack (exact document, revision, section, page)
                       ┌─────────────────┼─────────────────┐
                 Vertical Head      Vertical Head     Vertical Head      (one per department: its PDFs + Head name)
                       │ does the task, or hires specialists (max 5 active agents per department)
                   specialists ──▶ results saved as markdown, task marked done ──▶ Chief reports to the Owner
```

### Commands

| Command | What it does |
|---|---|
| `/flight-safety-agents:start` | Starts the live dashboard and gives you its link (the link carries an access token). |
| `/flight-safety-agents:add-dept Engine Maintenance \| Asha Verma \| ~/Docs/engine_manual.pdf` | Adds a department from its PDFs plus the Vertical Head's name. Duplicates and new versions are detected and you decide: update the existing department or add a new one. |
| `/flight-safety-agents:work <request>` | Gives the Chief work (English or Hinglish), including "make a PPT / Word report / Excel sheet". The team runs until it is done or needs you. |
| `/flight-safety-agents:tell [@dept-id] <instruction>` | Steers mid-way (to the Chief, or one department) or answers the Chief's question. The Chief re-plans: new brief version, conflicting tasks blocked, new tasks added. |
| `/flight-safety-agents:run` | Runs waiting work, for example after you sent work or an instruction from the dashboard. |
| `/flight-safety-agents:rename Dhruv Rebbapragada -> Arjun Mehta` | Renames anyone: the Chief, a Vertical Head, a hired specialist, or a department (by current name, a unique part of it, an id like `ag-2`, or `chief`). Also from the dashboard's Org Chart (Rename buttons). |
| `/flight-safety-agents:model [recommended \| best \| economy \| inherit \| opus \| sonnet \| haiku \| chief=opus head=sonnet]` | Shows which Claude (Opus, Sonnet, Haiku) the session and each kind of agent use, and upgrades or lightens it. Also in the dashboard's Overview. |
| `/flight-safety-agents:status`, `/flight-safety-agents:stop` | Status in chat (it lists the Claude models in use); stop the dashboard server. |
| `/flight-safety-agents:update` | Updates the plugin to the latest version from GitHub. Run `/reload-plugins` or start a new session afterwards. |

### How a request flows
1. You send work. The **Chief** (`agents/chief-of-flight-safety.md`) first decides if it is small or big. A **small** request (a question or lookup one department's manuals answer, no file, no assessment) he answers himself from the manuals, with sources, in one agent run: no brief, no File Checker, no department run. A **big** request gets a **brief**: he searches what each department's manuals cover and writes summary, goals and tasks, each owned by one department. If no department fits, he asks which one to add and creates no tasks.
2. The **File Checker** (`agents/file-checker.md`) takes every new task **before its department starts**. It searches the manuals (the task's department, `shared`, and any other department the task's words point at), picks the 3 to 5 sections that answer the task (at most 6) and checks them: current revision, sections that disagree, parts the manuals do not cover. The system itself reads each section **once** and stores it in the task's **source pack** with its exact document, revision, section and page (a copy is saved under `_outputs/<WR>/<task>-source-pack.md`). Only then does the department start. If the File Checker delivers nothing it is asked again, and after two tries the departments start without a pack (flagged), so work never stalls.
3. Each **Vertical Head** (`agents/vertical-head.md`) gets its tasks together with the source pack in its prompt. It starts from the pack, searches only for what the pack lacks, or **hires** a specialist (`agents/dept-specialist.md`) for a task. Every hire, and every refusal at the cap, is logged.
4. Agents work only from the uploaded manuals, cite document, section and page, save results with `save_output` (`safety-kb/_outputs/<WR>/<task>.md`) and move tasks through `todo → in_progress → done` (or `blocked`), always with a note.
5. When the last task is done the Chief reads the notes and outputs (the File Checker's documentation issues are in his review message), builds any file you asked for, and sends you a **completion report** that lists every file with its full path.

### Read once, not again and again
- **Source packs** hold the sections a task needs, already read. The prompt of a Head or specialist contains them, so there is nothing to look up first.
- `read_section` **does not send a part twice**: a part already in the agent's source pack, or already read in the same run, comes back as "already have it" (pass `again=true` to force it). A part another agent read is served from memory, and the KB files are cached in memory while unchanged (`safety-kb/_index/search.db` makes searches take milliseconds).

### Interconnection by keywords, with a little self-learning
Departments connect by **words, not by reading everything**. When a task mentions a term another department owns (for example "unstable approach" → FDM), the Head's prompt gets a *Linked by keywords* section with only the matching memory notes, open board items and manual sections of that department (`related_departments` does the same on demand). The map (`safety-kb/_team/links.json`, `kb.py links show`) teaches itself: the Chief's tasks teach it which department owns which words, a question to another department teaches it that department's words, and a word nobody has taught yet is looked up once in the saved search index. One passing mention is only a weak hint; a manual that uses the word, or a second mention, makes it a link. Words that point at every department ("safety", "procedure") are ignored. Wrong link: `kb.py links forget <term>`. The dashboard's Organisation page lists what was learned.

### Which Claude is in use, and upgrading it
By default every agent uses the model of your Claude Code session. The work loop reports that model (`next_work` gets `session_model`), so the dashboard's Overview ("Claude (your session)") and `/flight-safety-agents:status` show it, and each recent run shows the model it was asked to use. To upgrade, use `/flight-safety-agents:model` or the **Which Claude** card on the Overview: presets **Recommended** (Chief and File Checker on Opus, departments on Sonnet), **Best quality** (everyone on Opus), **Economy** and **Same as my session**, or a model per kind of agent (Chief, File Checker, Vertical Heads, specialists). Opus, Sonnet and Haiku always mean the newest version your Claude plan offers; the setting applies from the next run and is passed to each Agent call. Your session's own model is changed with `/model` in Claude Code. If a run fails with a model error, set that role back to "Same as my session".

The main session is only the office manager: it asks the plugin's MCP server what is ready (`next_work`), starts those agents in parallel (up to 4 at a time) and reports back when each finishes. An agent wakes only for messages it must act on (new task, instruction, question, blocked task, review). A work request pauses after 60 agent runs since your last message and asks you to continue, so a loop can never run away.

### PowerPoint, Word and Excel files
Ask for a file in plain words ("Safety Review Board ke liye PPT bana do", "findings ka Excel do", "audit report Word mein"):

1. The Chief lists it in the brief as a **deliverable** (`pptx`, `docx` or `xlsx` plus a title) and asks the departments for content that drops straight in: slide points, sections or table rows, each with its manual source.
2. The departments write that content from their manuals. A Head or specialist can also build a file for its own task.
3. The Chief builds the final file with `build_file`: a 16:9 deck (title slide, one idea per slide, bullet points, tables, source notes, a Sources slide), a Word report (title, headings, paragraphs, bullets, tables, Sources) or an Excel workbook (one sheet per table, header row frozen, Sources sheet).
4. The report is refused until every requested file exists (or the Chief says why it cannot be made). Files land in `safety-kb/_outputs/<WR>/`; the report, `/flight-safety-agents:status` and the dashboard show the full path, and the dashboard has a Download link.

Files are written with the Python standard library (Office Open XML), so nothing extra is installed. They open in PowerPoint, Word, Excel, Keynote, Pages, Numbers, Google and LibreOffice.

### Renaming
The Chief starts as **Dhruv Rebbapragada**, and every name is the Owner's to change: the Chief, any Vertical Head, any hired specialist, and department display names. Use `/flight-safety-agents:rename <who> -> <new name>` or the Rename buttons in the Org Chart. Only the name changes: ids, tasks, history and the department's knowledge-base folder stay. The renamed agent gets a note, the Chat Feed logs it, and every prompt, report and dashboard view uses the new name from then on. Two active agents (or departments) cannot share a name.

### Dashboard
A dark, gold-accented control room with a left sidebar (it becomes a top bar on phones) that also shows the live connection, how many agents are working and the Chief. Pages: Overview (key figures including the Claude in use and sources checked, **a card to see and upgrade which Claude each agent uses**, work requests, briefs, progress, **files built with Download links**, **who is working now**, recent agent runs), Task Board (kanban with each task's note history and a chip showing whether the File Checker covered its sources), Organisation (an org chart: the Chief at the top, the File Checker below, a branch per department with its Vertical Head and hired specialists, plus the keyword links the team has learned, hire reasons, team size against the cap of 5, Rename on every card, agents at work highlighted), Communications (every message between you and the agents with avatars, message type and task, filterable by department, agent and task) and Owner Console (new work, instructions, add/update/retire departments). Updates are live. Work or instructions sent from the dashboard are picked up when you run `/flight-safety-agents:run` in Claude Code; the dashboard reminds you.

The dashboard server binds to 127.0.0.1 only, accepts only local Host headers and needs the token from the `/start` link for every API call.

### Where things live
**Big knowledge bases stay cheap and fast.** Search uses a saved SQLite index (`safety-kb/_index/search.db`, kept up to date by ingest, retire and edits), so a search over thousands of pages takes milliseconds instead of rescanning every file. Agents read only what they need: `search_manuals` returns the `line` of each hit and `read_section` with that line returns about 4,000 characters from there (and `next_line` to carry on), instead of a whole section file.

Everything is in the project's `./safety-kb/` (git-ignored; set `SAFETY_KB_DIR` or `FSA_KB_ROOT` to move it): department manuals as markdown (`<department>/`), agent outputs and PPT/Word/Excel files (`_outputs/<WR>/`), and the team database and dashboard state (`_team/fsa.db`, `_team/dashboard.json`, `_team/dashboard.log`). The same knowledge base serves the Audit, SMS and FDM skills above.

### Requirements
`python3` 3.9+ on your PATH (standard library only) and, for PDFs, `pdftotext` (`brew install poppler`) or `pip install pypdf`, as for `kb.py`. Node is needed only to rebuild the dashboard (`cd frontend && npm run build` writes `backend/fsa/web`, which ships with the plugin).

### Tests
```bash
python3 -m unittest discover tests                       # kb.py (v0.3), standard library only
python3 -m pytest tests/backend                          # store, workflow, work loop, MCP over stdio, dashboard, Office files, plugin wiring
cd frontend && npm install && npm test && npm run build  # dashboard
```

### Development
`scripts/dev.sh` runs the dashboard server on :4810 without a token plus the Vite dev server on :5173 with live reload. `python3 -m backend.fsa start|stop|status [--kb PATH]` manages the background dashboard; `python3 -m backend.fsa mcp` runs the MCP server on stdio. API reference: `backend/API.md`.

### Known limits
- Agents run only while a command (`/work`, `/tell`, `/run`) is running the loop in Claude Code; the dashboard shows and queues, it does not run agents by itself.
- `/api/messages` returns at most 500 messages per call by default; the Chat Feed shows the latest window.
- No browser-level end-to-end tests (the dashboard has unit tests; the backend is tested over real HTTP and stdio).
- The File Checker adds one agent run per brief (and one per re-plan that adds tasks) before the departments start. It picks sections from search results, so it is only as good as the manuals' wording; its `issues` are hints to confirm, not a legal check of the documents.
- Keyword links are hints too: they are learned from usage and can be wrong or stale (`kb.py links forget`). Models are chosen per kind of agent, not per task; "which Claude is in use" depends on the work loop reporting the session's model (`session_model`), which the `/work`, `/tell` and `/run` commands do.

## Repository layout

```
.claude-plugin/        plugin.json, marketplace.json
skills/
  safety-kb/           ingest + search (scripts/kb.py), conventions
  safety-team/         coordinator
  sms-dept/  audit-dept/  fdm-dept/
  safety-add-department/   + assets/ templates
  start/ add-dept/ work/ tell/ run/ status/ stop/ rename/ model/ update/   Flight Safety Command commands
agents/                sms-agent, audit-agent, fdm-agent; chief-of-flight-safety, file-checker, vertical-head, dept-specialist
.mcp.json              the Flight Safety Command MCP server (python3 backend/mcp_main.py)
backend/               Flight Safety Command (standard library): store, workflow, work loop, MCP server,
                       dashboard server, bundled UI in backend/fsa/web, API.md
frontend/              dashboard source (React + Vite)
scripts/package-skills.sh, scripts/dev.sh
tests/                 python3 -m unittest discover -s tests -v   (backend tests in tests/backend, run with pytest)
```

## Development

```bash
python3 -m unittest discover -s tests -v     # builds fictional PDF/DOCX/MD fixtures, no third-party libraries
python3 -m pytest tests/backend              # Flight Safety Command (pip install pytest; python-pptx, python-docx,
                                             # openpyxl and LibreOffice add extra file checks when present)
```

Contributions welcome: more departments (Investigation, Cabin, Ground, Maintenance safety), better table handling for PDFs, a semantic search backend. Do not commit real manuals or flight data.

## License

MIT
