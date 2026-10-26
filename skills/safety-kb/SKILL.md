---
name: safety-kb
description: Build, update and query the flight-safety knowledge base. Use whenever the user uploads, attaches or mentions one or several manuals, SOPs, procedures, checklists, regulations or policy documents (PDF, DOCX, MD, TXT) for Audit, SMS, FDM, Safety or any department; says "add/ingest/save these files", "replace this file with this one", "update to revision N", "remove/withdraw this document", "load our manuals"; or when any safety agent needs to look up what a manual says. Converts each file to sectioned markdown with revision and page tracking, checks every upload against what is already stored (new, duplicate, or a new version) and asks before updating, and searches with citations.
---

# Safety knowledge base

All department agents read from one shared knowledge base (KB) of markdown made from the user's own manuals.
This skill creates it (ingest) and reads it (search). Everything else in this plugin depends on it.

## Where things live

- KB folder: `./safety-kb/` in the user's working folder, or `$SAFETY_KB_DIR` if set. Never inside the plugin folder (plugin updates would wipe it) and never in git (the repo `.gitignore` excludes it; manuals are confidential).
- Script: `scripts/kb.py` next to this file. When installed as a Claude Code plugin it is `${CLAUDE_PLUGIN_ROOT}/skills/safety-kb/scripts/kb.py`. Run it with `python3`. Standard library only; PDFs need `pypdf` or poppler's `pdftotext` (`pip install pypdf` / `brew install poppler`).
- Layout, one folder per department: `safety-kb/<dept>/<doc-id>/NN-section.md`, plus `_doc.md` (table of contents), `<dept>/INDEX.md`, `INDEX.md`, `_superseded/` (older revisions) and `_outputs/` (reports the agents write). Details: `references/kb-layout.md`.
- Use dept `shared` for material every team needs (regulations, ICAO/IOSA references, company risk matrix, glossary).

## Adding, updating and replacing documents

A department can hold any number of documents (manual, SOPs, checklists, forms, regulations). **Each file becomes one document folder** (`safety-kb/<dept>/<doc-id>/`) of markdown. A new upload either creates a new document or updates an existing one; never guess which.

### 1. Look at what you were given

Collect every file the user supplied (a path, several paths, or uploaded files; in claude.ai look under `/mnt/user-data/uploads`). For each, read the title page / first pages and note title, revision or amendment, effective date. See what is already stored: `kb.py status` (shows each document's id, revision and source file).

### 2. Check every file against the KB (always, even for one file)

```
python3 <skill>/scripts/kb.py match "<file1>" "<file2>" "<file3>"
```

It compares each file by content hash and by name (revision numbers, dates, "FINAL", "(1)" are ignored) and reports one of:

| Result | Meaning | What you do |
|---|---|---|
| **NEW** | nothing in the KB looks like it | add it as a new document; tell the user, no question needed (unless metadata is missing) |
| **DUPLICATE** | identical bytes to the current document | skip it; tell the user it is already there (offer `--force` only if they insist) |
| **ASK THE USER** | looks like a version of an existing document | **ask: update the existing document, or add as a new, separate one?** |
| **OLD REVISION** | identical to an already superseded revision | warn that ingesting would roll back; ask what they want |

Names can mislead, so also use what you read in step 1: if the title or document number clearly says it is the same document (or clearly a different one), say so when you ask or when you override a weak match. If `match` says NEW but the content is plainly a new issue of a stored document (renamed file), treat it as an update candidate and ask.

### 3. One plan, one set of questions

Show a short table for all files, then ask everything in one message, only about what is open:

```
| File | Plan |
|---|---|
| SMS_Manual_R06.pdf | ASK: update "SMS Manual" (now Rev 5) → Rev 6, or add as a new document? |
| Hazard_Register_SOP.docx | NEW in sms. Revision? (I read "Issue 2, 14 Feb 2026" on the cover; correct?) |
| SMS_Manual_R05.pdf | DUPLICATE of the current SMS Manual; skipping |
```

Also settle, per file, anything you could not read from the document: department (`audit`, `sms`, `fdm`, `shared`, a custom one), revision, effective date. Do not ask what you can read yourself; do not ask twice.

### 4. Ingest

New document:
```
python3 <skill>/scripts/kb.py ingest "<file>" --dept sms --title "Hazard Register SOP" --rev "Issue 2" --effective 2026-02-14
```
Update an existing document (the user said "update", or answered "update"; the file name does not matter, the document id decides):
```
python3 <skill>/scripts/kb.py ingest "<file>" --replace sms-manual --rev "Rev 6" --effective 2026-11-01
```
- The old revision is moved to `_superseded/` (kept for history, not searched). Memory notes that relied on it are flagged *verify before use*. The file is converted **before** anything is archived, so a failed conversion leaves the current document untouched.
- Same revision, corrected file ("replace this file with the fixed one"): add `--force`.
- Several files: run them one after another; report once at the end.
- `--layout` for PDFs with many tables. A DOCX or MD is read directly; a scanned PDF needs OCR first.

### 5. When the user gives an instruction instead of a file list

- **"Replace X with this file"**: find X with `kb.py status` (match the title, id or source file name they used). One clear match: `ingest --replace <id>`. Several or none: ask which. Revision unknown: read it from the file, else ask.
- **"Remove / withdraw X"**: confirm the document and the reason, then `kb.py retire <id> --reason "..."`. It leaves the search and is kept on disk; nothing is ever hard-deleted, because aviation records need history. Memory notes based on it are flagged.
- **An amendment or temporary revision that changes only some pages**: add it as its own document in the same department (for example "SMS Manual Amendment 3") and add a `source-map` memory note saying it modifies the base document, unless the user supplies a full re-issue.
- **Move a document to another department**: retire it, then ingest it again in the new department.

### 6. Check the result; do not trust conversion blindly

Read each new `_doc.md` contents list. Open one or two chunk files and compare against the source: headings split sensibly, tables readable, page numbers plausible. If the script warns about few headings or a scanned PDF, say so and offer a fix (OCR with `ocrmypdf`, `--layout`, splitting the document).

### 7. Report briefly

Per file: what happened (new / updated Rev 5 → Rev 6 / skipped duplicate / withdrawn), department, how many sections and pages, warnings. For updates, also say how many memory notes were flagged and offer a summary of what changed (search old and new with `--include-superseded` and compare). Never paste manual text back into chat just to show it worked.

Page numbers are PDF page indexes, which can differ from the printed page labels in a manual. Say so if the user asks for exact page references.

## Searching (every agent, every time)

```
python3 <skill>/scripts/kb.py search "unstable approach criteria" --dept fdm --dept shared --top 8
```

- Search your own department and `shared` first. Search other departments only to cross-reference.
- Try two or three phrasings (abbreviation and long form: "SPI" / "safety performance indicator").
- Snippets are only pointers. Open the chunk file at the reported line and read the surrounding text before you quote or rely on a requirement.
- **Cite every claim that comes from a manual** as `[<Document> <Revision> §<section>, p.<page>]`. Conventions and the shared answer format: `references/conventions.md`.
- Superseded revisions are hidden by default. Use `--include-superseded` only when the user asks about history or a past event.
- **Nothing found means say so:** "not found in the KB". You may add general industry knowledge, but label it "general knowledge, not from your manuals" and never present it as company policy.
- If two documents disagree, report both with citations. Do not pick a winner silently.

## Team board: how departments talk to each other

Departments run as separate agents and cannot message each other live. They coordinate through a shared board (`safety-kb/_team/board.jsonl`); the coordinator (`safety-team`) runs the departments in rounds and routes by what is on the board.

```
kb.py board inbox  --dept sms                       # open requests for you + answers to your own requests
kb.py board post   --from sms --to fdm --subject "Unstable approach rate, last 12 months" --text "<exact question, what you already know, why you need it>"
kb.py board answer <id> --from fdm --text "<answer with citations>"
kb.py board close  <id> --reason "no longer needed"
kb.py board show --open        # everything still open
```

- **Start of every run:** `board inbox --dept <you>`. Answer each open request with a cited answer (`board answer`). If you cannot, answer saying exactly what is missing; never leave it open silently. Read the answers to your own requests and use them.
- **Asking another department:** check `board show --open` first so you don't duplicate. Put the exact question, what you already know and why you need it. At most 3 requests per run. Use `--to user` when only a human can decide or supply something.
- **You will not see the answer in this run.** The other department answers in the next round. Say so: give a provisional position, list the request id under *Needs from other departments*, and the coordinator will bring you back once it is answered.
- A thread is capped at 8 requests and identical open requests are refused. If the script refuses a post as a loop, stop and put it to the user.
- Requests carry no personal data, and nothing here replaces writing to your own `_outputs/` folder. Never write into another department's folders.

## Memory: what each department learns over time

Each department has a small memory (`safety-kb/_memory/<dept>.jsonl`; `team` for shared notes). It holds how *this operator* works: terms, where answers live, preferences, decisions, corrections. It is **not** a second copy of the manuals.

```
kb.py mem show --dept sms --dept team                     # at the start of a run
kb.py mem add  --dept sms --kind source-map --text "Report acknowledgement deadline: SMS Manual §3.1" \
               --src "[SMS Manual Rev 5 §3.1, p.12]" --doc sms-manual --rev "Rev 5"
kb.py mem search "acknowledgement"      kb.py mem forget <id> --reason "..."
```

**Reading it:** memory is a hint. Before you rely on a note that matters, confirm it in the manual with `search`. If memory and the manual disagree, the manual wins: `mem forget` the note and record a `correction`. Notes under *VERIFY BEFORE USE* rely on a manual revision that has since been replaced; re-check them, then either re-add (same text, with the current `--doc/--rev`, which reactivates it) or forget them.

**Writing it.** Record only these, 1–3 notes per run, each short and sourced:
1. The user corrected you or stated a term, preference or convention (`correction`, `preference`, `term`; src `user, <date>`).
2. You found where an authoritative answer lives after several searches (`source-map`, with `--doc/--rev`).
3. A human decision was made in this chat (`decision`; record the role and the date, not a name).
4. A recurring pitfall in the procedure or data (`lesson`, with its source).

**Never record:** personal data (names of crew, employees or reporters; the script also rejects emails and phone numbers), raw FDM figures, copied manual text, guesses, or anything that only matters for this one question.

**Tell the user** in the answer what you remembered or forgot (`Memory: +1 source-map "..."`). They can inspect everything with `mem show` and remove anything with `mem forget`.

## Saving work products

Write reports, briefs and drafts to `safety-kb/_outputs/<dept>/<YYYY-MM-DD>-<slug>.md` so the next agent (or the user next week) can find them. Put the question, the answer, the citations used and the revisions consulted in the file.

## claude.ai without a persistent disk

Files created in a chat may not survive the session. After an ingest, zip the `safety-kb/` folder for the user and tell them to upload it to the Project's knowledge, or to keep it and re-upload next time.
