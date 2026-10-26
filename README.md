# flight-safety-agents

A team of flight-safety department agents (**Audit, SMS, FDM**, plus any department you add) that share one knowledge base built from **your own manuals**. Upload a manual and it becomes searchable, revision-tracked markdown. Ask a question and the right departments answer from it, with citations, in the same chat.

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
| `safety-team` skill | The coordinator. Routes a request, runs departments in parallel (or in turn where subagents don't exist), does one round of hand-offs, then merges. |
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

Revision update? Ingest the new file with the new `--rev`. The old revision moves to `_superseded/` and agents answer from the new one.

## Multi-agent in one chat

You steer it with plain words:

| You say | Happens |
|---|---|
| "SMS and FDM both..." / `@audit` | exactly those departments |
| "full team" | every department that has documents loaded |
| a topic only | the coordinator picks by scope and says which, in one line |
| "SMS drafts, Audit reviews" | draft → review pattern |
| "compare what SMS and Audit manuals say" | cross-check pattern |

Each department answers in the same shape: **Position / Evidence (cited) / Gaps / Needs from other departments / Confidence**. The coordinator relays hand-offs for one round, then shows a combined view: agreements, conflicts (both sources cited, no silent winner), gaps and actions with owners.

## Add your own department

> "Add a department for Flight Ops Safety. They review route and airport hazards, brief crews on safety notices and own the safety notice register."

`safety-add-department` interviews you briefly and writes `.claude/skills/<code>-dept/` and `.claude/agents/<code>-agent.md` in your project, plus `safety-kb/<code>/`. The coordinator then treats it like the built-in ones.

## Command line (optional)

The same tool the skills use:

```bash
python3 skills/safety-kb/scripts/kb.py ingest manual.pdf --dept sms --title "SMS Manual" --rev "Rev 05" --effective 2026-03-01
python3 skills/safety-kb/scripts/kb.py search "risk assessment matrix" --dept sms --dept shared
python3 skills/safety-kb/scripts/kb.py status
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
- The department skills are frameworks. They do not contain your regulations or procedures, only how to work with them. Quality depends on the documents you ingest.

## Repository layout

```
.claude-plugin/        plugin.json, marketplace.json
skills/
  safety-kb/           ingest + search (scripts/kb.py), conventions
  safety-team/         coordinator
  sms-dept/  audit-dept/  fdm-dept/
  safety-add-department/   + assets/ templates
agents/                sms-agent, audit-agent, fdm-agent
scripts/package-skills.sh
tests/                 python3 -m unittest discover -s tests -v
```

## Development

```bash
python3 -m unittest discover -s tests -v     # builds fictional PDF/DOCX/MD fixtures, no third-party libraries
```

Contributions welcome: more departments (Investigation, Cabin, Ground, Maintenance safety), better table handling for PDFs, a semantic search backend. Do not commit real manuals or flight data.

## License

MIT
