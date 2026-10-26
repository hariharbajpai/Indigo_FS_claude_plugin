# Conventions shared by every department agent

## Citation format

`[<Document> <Revision> §<section>, p.<page>]`

- `[SMS Manual Rev 05 §3.2, p.14]`
- No page (DOCX/MD source): `[Audit Handbook Rev 3 §4.1]`
- Revision unknown: `[Audit Handbook (revision unspecified) §4.1]` and say it needs confirming.
- A superseded revision must be marked: `[SMS Manual Rev 04 (SUPERSEDED) §3.2, p.12]`.
- A fact from the user's data file (CSV, report, spreadsheet): `[fdm_export_2026-09.csv, rows 2-4410]`.
- A claim with no source is either labelled as general knowledge or left out.

## Response contract (what a department agent hands back)

Keep it in this shape so a coordinator, or a colleague agent in the same chat, can merge several answers.

```
## <DEPT> — <one-line topic>
**Position:** the answer or recommendation in 2-5 sentences.
**Evidence:** bullets, each with a citation.
**Gaps:** what the KB does not cover, what needs a human decision or a document that is missing.
**Needs from other departments:** "[FDM] last 12 months of exceedance rate for event X" (or "none").
**Confidence:** high / medium / low, and why.
**Memory:** notes added or forgotten this run (or "none").
```

## Handoffs between departments

- A department asks another by posting on the board (`kb.py board post`, see the safety-kb skill) with the exact question, and lists the request id under "Needs from other departments". It does not guess the other department's content, and it labels its own position provisional until the answer arrives.
- The coordinator runs the departments in rounds: addressees answer open requests, then requesters are re-run to finish with the answers. Up to 3 rounds unless the user sets another limit. Anything still open after that goes to the user as an open item.
- A department answers cross-department questions from its own folder first, and from other folders only as read-only reference.
- Only the owning department's folder is written to: `safety-kb/_outputs/<dept>/`. The board is the only channel between departments.

## Memory

- Memory (`kb.py mem`) stores short, sourced pointers about how this operator works. It never replaces the manuals and never overrides them.
- A department writes only to its own memory; `team` memory is for the coordinator and for conventions the user has confirmed.
- No personal data, no raw FDM figures, no copied manual text. Say in the answer what was remembered.

## Guardrails that apply to everyone

- Decision support only. Approvals, sign-offs, risk acceptance and regulatory submissions stay with the accountable human; say so on any output that looks like one.
- Use the operator's approved risk matrix and classification scheme from the KB. If none is ingested, say which default you assumed (for example ICAO-style severity A–E and likelihood 1–5) and mark the tolerability result "to be confirmed against the company matrix".
- Just culture: do not name or help identify individual crew members, reporters or employees from FDM data or safety reports unless the user's own programme documents allow it. De-identify by default.
- Quote sparingly. Summarise requirements and cite them; copy exact wording only when the exact words matter.
- Reply in the user's language (English, Hindi, Hinglish). Keep document titles, citations, event names and technical terms in English.
