---
name: safety-kb
description: Build and query the flight-safety knowledge base. Use whenever the user uploads, attaches or mentions a manual, SOP, procedure, checklist, regulation or policy document (PDF, DOCX, MD, TXT) for Audit, SMS, FDM, Safety or any department, says "add/ingest/save this manual", "update to revision N", "load our manuals", or when any safety agent needs to look up what a manual says. Converts documents to sectioned markdown with revision and page tracking, and searches them with citations.
---

# Safety knowledge base

All department agents read from one shared knowledge base (KB) of markdown made from the user's own manuals.
This skill creates it (ingest) and reads it (search). Everything else in this plugin depends on it.

## Where things live

- KB folder: `./safety-kb/` in the user's working folder, or `$SAFETY_KB_DIR` if set. Never inside the plugin folder (plugin updates would wipe it) and never in git (the repo `.gitignore` excludes it; manuals are confidential).
- Script: `scripts/kb.py` next to this file. When installed as a Claude Code plugin it is `${CLAUDE_PLUGIN_ROOT}/skills/safety-kb/scripts/kb.py`. Run it with `python3`. Standard library only; PDFs need `pypdf` or poppler's `pdftotext` (`pip install pypdf` / `brew install poppler`).
- Layout, one folder per department: `safety-kb/<dept>/<doc-id>/NN-section.md`, plus `_doc.md` (table of contents), `<dept>/INDEX.md`, `INDEX.md`, `_superseded/` (older revisions) and `_outputs/` (reports the agents write). Details: `references/kb-layout.md`.
- Use dept `shared` for material every team needs (regulations, ICAO/IOSA references, company risk matrix, glossary).

## Ingesting a manual

When the user gives you a document ("this is our SMS manual", "yeh audit checklist save kar do"):

1. **Find the file.** Use the path they gave, or the uploaded file (in claude.ai, look under `/mnt/user-data/uploads`). Several files: ingest them one by one.
2. **Get the metadata right. This matters more than anything else here**, because every later answer cites it.
   - Department: `audit`, `sms`, `fdm`, `shared`, or a custom one. If unclear, ask once; run `kb.py status` to show the existing ones.
   - Revision/amendment and effective date: read the first pages, the list of effective pages or the revision record, and propose what you found ("looks like Revision 05, effective 01 Mar 2026, right?"). If you cannot find it, ask. If the user says to skip it, ingest with the default `unspecified` and tell them it will be flagged in every citation.
   - Title: the document's real title, not the filename.
3. **Run it:**
   ```
   python3 <skill>/scripts/kb.py ingest "<file>" --dept sms --title "Safety Management Manual" --rev "Rev 05" --effective 2026-03-01
   ```
   Add `--layout` for PDFs with many tables. Same revision again is refused unless `--force`; a new `--rev` automatically moves the old revision to `_superseded/`.
4. **Check the result; do not trust it blindly.** Read the new `_doc.md` contents list. Open one or two chunk files and compare against the source: headings split sensibly, tables readable, page numbers plausible. If the script warns about few headings or a scanned PDF, say so and offer a fix (OCR with `ocrmypdf`, `--layout`, or splitting the document).
5. **Report briefly:** document, department, revision, how many sections and pages, warnings. Never paste manual text back into chat just to show it worked.
6. **Revision update?** Offer to summarise what changed between the old and new revision (search both with `--include-superseded` and compare), and remind the user that agents now answer from the new revision only.

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

## Saving work products

Write reports, briefs and drafts to `safety-kb/_outputs/<dept>/<YYYY-MM-DD>-<slug>.md` so the next agent (or the user next week) can find them. Put the question, the answer, the citations used and the revisions consulted in the file.

## claude.ai without a persistent disk

Files created in a chat may not survive the session. After an ingest, zip the `safety-kb/` folder for the user and tell them to upload it to the Project's knowledge, or to keep it and re-upload next time.
