# Knowledge base layout

```
safety-kb/
├── INDEX.md                      departments and document counts (rebuilt on every ingest)
├── shared/                       regulations, risk matrix, glossary: read by every agent
│   ├── INDEX.md
│   └── icao-annex-19/
├── sms/
│   ├── INDEX.md                  table of current documents + superseded revisions
│   ├── sms-manual/
│   │   ├── _doc.md               metadata + table of contents (read this first)
│   │   ├── 01-chapter-1-introduction.md
│   │   └── 03-chapter-3-hazard-identification.md
│   └── _superseded/
│       └── sms-manual__rev-04__2026-10-26/     older revision, kept for history, not searched
├── audit/
├── fdm/
└── _outputs/<dept>/              reports and briefs written by agents
```

Folders starting with `_` are not departments. `_outputs` and `_superseded` are skipped by search unless asked.

## Chunk file front matter

```yaml
---
doc: "Safety Management Manual"
doc_id: "safety-management-manual"
dept: "sms"
revision: "Rev 05"
effective: "2026-03-01"
section: "3.2 Risk assessment"
pages: "14-18"
page_start: 14
source_file: "SMS_Manual_R05.pdf"
---
<!-- page 14 -->
## 3.2 Risk assessment
...
```

`<!-- page N -->` markers sit inside the text so a citation can name the page. `_doc.md` also stores the SHA-256 of the source file, so you can show which exact file a KB entry came from.

## Chunking rules

- Split at chapter level first. Any chapter over about 24,000 characters is split at the next heading level, and so on, then by size.
- A PDF with no detectable headings is cut into 8-page windows.
- Repeating page headers and footers are removed from PDFs before splitting.
