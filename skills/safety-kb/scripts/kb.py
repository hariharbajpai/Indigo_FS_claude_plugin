#!/usr/bin/env python3
"""safety-kb: turn manuals into a sectioned markdown knowledge base, and search it.

  kb.py match  FILE...             is each file new, a duplicate, or a new version of a document already there?
  kb.py ingest FILE --dept DEPT [--title T] [--doc-id ID] [--rev R] [--effective YYYY-MM-DD]
                    [--force] [--layout] [--max-chars N]
  kb.py ingest FILE --replace DOC_ID --rev R      update an existing document (old revision archived)
  kb.py retire DOC_ID [--dept D] [--reason ...]   withdraw a document from search (kept, never deleted)
  kb.py search QUERY [--dept D ...] [--doc ID] [--top N] [--include-superseded] [--json]
  kb.py index                      rebuild INDEX.md files
  kb.py status                     show what the KB holds

  kb.py board post|inbox|answer|close|show|pending   messages between departments (_team/board.jsonl)
  kb.py mem   add|show|search|forget                 per-department memory (_memory/<dept>.jsonl)

KB location: --kb, else $SAFETY_KB_DIR, else ./safety-kb
Layout:      <kb>/<dept>/<doc-id>/{_doc.md, NN-section.md}   (older revisions: <kb>/<dept>/_superseded/)

Stdlib only. PDF text comes from pypdf, PyMuPDF or the pdftotext CLI (first one found).
DOCX is read directly from its XML. Markdown and plain text are accepted as they are.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

try:
    import fcntl  # type: ignore  (POSIX only; locking is best effort elsewhere)
except ImportError:
    fcntl = None

TODAY = dt.date.today().isoformat()
DEFAULT_MAX_CHARS = 24000
PAGE_WINDOW = 8  # pages per chunk when a PDF has no detectable headings

PAGE_RE = re.compile(r"^<!-- page (\d+) -->$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


# --------------------------------------------------------------------------- helpers

def kb_root(arg: str | None) -> Path:
    return Path(arg or os.environ.get("SAFETY_KB_DIR") or "safety-kb").expanduser().resolve()


def slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:maxlen].strip("-") or "untitled"


def fm_dump(d: dict) -> str:
    rows = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in d.items()] + ["---", ""]
    return "\n".join(rows)


def fm_load(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        k, _, v = line.partition(":")
        v = v.strip()
        try:
            meta[k.strip()] = json.loads(v)
        except ValueError:
            meta[k.strip()] = v
    return meta, text[end + 5:]


def die(msg: str) -> None:
    sys.exit(f"error: {msg}")


# --------------------------------------------------------------------------- headings

_WORD_HEAD = re.compile(r"^(?i:chapter|part|appendix|annex|section)\s+([0-9]+|[IVXLC]+|[A-Z])\b")
_NUM_HEAD = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(\S.*)$")


def detect_heading(line: str) -> int:
    """Return a heading level (1-4) if the line looks like a manual heading, else 0."""
    s = line.strip()
    if not s or len(s) > 100 or re.search(r"\.{3,}\s*\d+$", s):  # blank, long, or table-of-contents line
        return 0
    if _WORD_HEAD.match(s) and len(s) <= 80:
        return 1
    m = _NUM_HEAD.match(s)
    if not m:
        return 0
    num, title = m.groups()
    if re.search(r"\s\d{1,4}$", title) or title[-1] in ".,;:" or len(title.split()) > 14:
        return 0
    if not re.match(r"[A-Za-z]{3,}", title) or not title[0].isupper():
        return 0
    if "." not in num and not title.isupper():  # bare "3 Something" only counts when it is ALL CAPS
        return 0
    return min(num.count(".") + 1, 4)


# --------------------------------------------------------------------------- extraction

def pdf_pages(path: Path, layout: bool) -> list[str]:
    try:
        import pypdf  # type: ignore
        return [(p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages]
    except ImportError:
        pass
    try:
        import fitz  # type: ignore
        with fitz.open(str(path)) as d:
            return [p.get_text() for p in d]
    except ImportError:
        pass
    exe = shutil.which("pdftotext")
    if exe:
        cmd = [exe] + (["-layout"] if layout else []) + [str(path), "-"]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        pages = out.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        return pages
    die("no PDF backend found. Run: pip install pypdf   (or install poppler: brew install poppler)")
    return []


def strip_running_lines(pages: list[str]) -> list[str]:
    """Drop page headers/footers: short lines that repeat (digits ignored) on at least half the pages."""
    n = len(pages)
    if n < 4:
        return pages

    def norm(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    counts: Counter = Counter()
    for p in pages:
        counts.update({norm(l) for l in p.splitlines() if 5 < len(l.strip()) < 110})
    common = {k for k, v in counts.items() if v >= max(3, n * 0.5)}
    bare_number = re.compile(r"\s*(page\s*)?\d+(\s*(of|/)\s*\d+)?\s*", re.I)
    return ["\n".join(l for l in p.splitlines() if norm(l) not in common and not bare_number.fullmatch(l)) for p in pages]


def pdf_to_md(path: Path, layout: bool) -> str:
    try:
        raw_pages = pdf_pages(path, layout)
    except Exception as e:  # corrupt, encrypted or truncated file; SystemExit from die() passes through
        die(f"could not read {path.name} as a PDF ({type(e).__name__}). Is it corrupt or password-protected?")
    pages = [re.sub(r"([a-z])-\n([a-z])", r"\1\2", p) for p in raw_pages]
    if sum(len(p.strip()) for p in pages) < 200:
        die("this PDF has almost no extractable text, so it is probably scanned. OCR it first "
            "(e.g. `ocrmypdf in.pdf out.pdf`) and ingest the result.")
    out: list[str] = []
    for i, text in enumerate(strip_running_lines(pages), 1):
        out.append(f"<!-- page {i} -->")
        for line in text.splitlines():
            lvl = detect_heading(line)
            out.append(f"{'#' * lvl} {line.strip()}" if lvl else line.rstrip())
        out.append("")
    return "\n".join(out)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_md(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("word/document.xml"))
        styles: dict[str, str] = {}
        if "word/styles.xml" in z.namelist():
            for st in ET.fromstring(z.read("word/styles.xml")).iter(_W + "style"):
                nm = st.find(_W + "name")
                styles[st.get(_W + "styleId", "")] = (nm.get(_W + "val", "") if nm is not None else "").lower()

    def ptext(p) -> str:
        parts = []
        for el in p.iter():
            if el.tag == _W + "t":
                parts.append(el.text or "")
            elif el.tag == _W + "tab":
                parts.append("\t")
            elif el.tag == _W + "br":
                parts.append("\n")
        return "".join(parts).strip()

    def para(p) -> str | None:
        txt = ptext(p)
        if not txt:
            return None
        ppr = p.find(_W + "pPr")
        sid, numbered = "", False
        if ppr is not None:
            ps = ppr.find(_W + "pStyle")
            sid = ps.get(_W + "val", "") if ps is not None else ""
            numbered = ppr.find(_W + "numPr") is not None
        name = styles.get(sid, sid).lower()
        m = re.match(r"heading\s*(\d)", name)
        if name == "title":
            return f"# {txt}"
        if m:
            return f"{'#' * min(int(m.group(1)), 6)} {txt}"
        return ("- " if numbered else "") + txt

    def table(t) -> str:
        rows = [[" ".join(x for x in (ptext(p) for p in tc.iter(_W + "p")) if x).replace("|", "/")
                 for tc in tr.findall(_W + "tc")] for tr in t.findall(_W + "tr")]
        rows = [r for r in rows if r]
        if not rows:
            return ""
        w = max(len(r) for r in rows)
        rows = [r + [""] * (w - len(r)) for r in rows]
        md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * w]
        md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(md)

    body = doc.find(_W + "body")
    blocks: list[str] = []
    for ch in (body if body is not None else []):
        piece = para(ch) if ch.tag == _W + "p" else table(ch) if ch.tag == _W + "tbl" else None
        if piece:
            blocks.append(piece)
    md = "\n\n".join(blocks)
    return md if HEAD_RE.search(md) or "\n#" in md else add_heuristic_headings(md)


def add_heuristic_headings(md: str) -> str:
    out = []
    for line in md.splitlines():
        lvl = 0 if line.startswith(("|", "-", "#")) else detect_heading(line)
        out.append(f"{'#' * lvl} {line.strip()}" if lvl else line)
    return "\n".join(out)


def to_markdown(path: Path, layout: bool) -> tuple[str, bool]:
    """Return (markdown, has_page_markers)."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_to_md(path, layout), True
    if ext == ".docx":
        return docx_to_md(path), False
    if ext in (".md", ".markdown", ".txt"):
        text = path.read_text(encoding="utf-8", errors="replace")
        return (text if any(HEAD_RE.match(l) for l in text.splitlines()) else add_heuristic_headings(text)), False
    if ext == ".doc":
        die("legacy .doc is not supported. Open it in Word and Save As .docx, then ingest again.")
    die(f"unsupported file type {ext!r}. Use PDF, DOCX, MD or TXT.")
    return "", False


# --------------------------------------------------------------------------- sectioning

def add_page_window_headings(md: str) -> str:
    """PDF with no detectable headings: cut it into fixed page windows so chunks stay small."""
    out = []
    for line in md.splitlines():
        m = PAGE_RE.match(line)
        if m:
            p = int(m.group(1))
            if (p - 1) % PAGE_WINDOW == 0:
                out.append(f"# Pages {p}-{p + PAGE_WINDOW - 1}")
        out.append(line)
    return "\n".join(out)


def parse_sections(md: str) -> list[dict]:
    secs: list[dict] = []
    page = None
    cur = {"level": 0, "title": "Front matter", "lines": [], "p0": None, "subs": []}
    for line in md.splitlines():
        m = PAGE_RE.match(line)
        if m:
            page = int(m.group(1))
            if cur["p0"] is None:
                cur["p0"] = page
        h = HEAD_RE.match(line)
        if h:
            tail = len(cur["lines"])
            while tail and not cur["lines"][tail - 1].strip():
                tail -= 1
            if tail and PAGE_RE.match(cur["lines"][tail - 1]):  # marker belongs to the page this heading opens
                del cur["lines"][tail - 1:]
            secs.append(cur)
            lvl, title = len(h.group(1)), h.group(2)
            cur = {"level": lvl, "title": title, "lines": [f"<!-- page {page} -->"] if page else [],
                   "p0": page, "subs": [(lvl, title, page)]}
        cur["lines"].append(line)
    secs.append(cur)
    return [s for s in secs if any(l.strip() and not PAGE_RE.match(l) for l in s["lines"])]


def _size(c: dict) -> int:
    return sum(len(l) + 1 for s in c["secs"] for l in s["lines"])


def _group(secs: list[dict], level: int) -> list[dict]:
    chunks: list[dict] = []
    for s in secs:
        if not chunks or s["level"] <= level:
            chunks.append({"title": s["title"], "secs": [s]})
        else:
            chunks[-1]["secs"].append(s)
    return chunks


def split_tree(secs: list[dict], max_chars: int, level: int = 1) -> list[dict]:
    out: list[dict] = []
    for c in _group(secs, level):
        if _size(c) > max_chars and level < 6 and len(c["secs"]) > 1:
            out += split_tree(c["secs"], max_chars, level + 1)
        else:
            out.append(c)
    return out


def finalize_chunks(chunks: list[dict], max_chars: int) -> list[dict]:
    """Flatten each chunk to lines/pages/subheadings and size-split any that are still too big."""
    final: list[dict] = []
    for c in chunks:
        lines = [l for s in c["secs"] for l in s["lines"]]
        subs = [x for s in c["secs"] for x in s["subs"]]
        first_page = next((s["p0"] for s in c["secs"] if s["p0"] is not None), None)
        parts: list[tuple[list[str], int | None]] = []
        buf: list[str] = []
        size, page, buf_page = 0, first_page, first_page
        for line in lines:
            m = PAGE_RE.match(line)
            if m:
                page = int(m.group(1))
            if size > max_chars and not line.strip():
                parts.append((buf, buf_page))
                buf, size, buf_page = ([f"<!-- page {page} -->"] if page else []), 0, page
            buf.append(line)
            size += len(line) + 1
        parts.append((buf, buf_page))
        for i, (plines, p0) in enumerate(parts, 1):
            pages = [int(m.group(1)) for l in plines if (m := PAGE_RE.match(l))]
            lo = p0 if p0 is not None else (min(pages) if pages else None)
            hi = max(pages + ([lo] if lo else [])) if (pages or lo) else None
            final.append({
                "title": c["title"] if len(parts) == 1 else f"{c['title']} (part {i})",
                "lines": plines, "p0": lo, "p1": hi,
                "subs": subs if i == 1 else [],
            })
    return final


# --------------------------------------------------------------------------- writing

def pages_label(lo, hi) -> str:
    if lo is None:
        return ""
    return str(lo) if hi in (None, lo) else f"{lo}-{hi}"


def ingest(a: argparse.Namespace) -> None:
    src = Path(a.file).expanduser().resolve()
    if not src.is_file():
        die(f"file not found: {src}")
    kb = kb_root(a.kb)
    if a.replace:
        dept, current = find_doc(kb, a.replace, a.dept)
        doc_id = a.replace
        title = a.title or current.get("doc") or doc_id
    else:
        if not a.dept:
            die("--dept is required for a new document (or use --replace DOC_ID to update an existing one).")
        dept = slugify(a.dept, 30)
        title = a.title or re.sub(r"[_\-]+", " ", src.stem).strip()
        doc_id = slugify(a.doc_id or title)
    rev = a.rev or "unspecified"

    md, has_pages = to_markdown(src, a.layout)
    if has_pages and not any(HEAD_RE.match(l) for l in md.splitlines()):
        md = add_page_window_headings(md)
        print("note: no headings detected, so the PDF was split into page windows.")
    secs = parse_sections(md)
    if not secs:
        die("nothing extracted from the file.")
    n_headings = sum(1 for s in secs if s["level"] > 0)
    chunks = finalize_chunks(split_tree(secs, a.max_chars), a.max_chars)

    d = kb / dept / doc_id
    prev_rev = ""
    if d.exists():
        old = fm_load((d / "_doc.md").read_text(encoding="utf-8"))[0] if (d / "_doc.md").exists() else {}
        prev_rev = str(old.get("revision", ""))
        if old.get("revision") == rev and not a.force:
            die(f"{dept}/{doc_id} revision '{rev}' is already ingested. Give the new revision with --rev, "
                f"or pass --force if this is a corrected re-issue of the same revision.")
        arch = kb / dept / "_superseded" / f"{doc_id}__{slugify(str(old.get('revision', 'unknown')))}__{TODAY}"
        n = 2
        while arch.exists():
            arch = arch.with_name(f"{arch.name}-{n}")
            n += 1
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(arch))
        if (arch / "_doc.md").exists():
            m, body = fm_load((arch / "_doc.md").read_text(encoding="utf-8"))
            m.update(status="superseded", superseded_on=TODAY)
            (arch / "_doc.md").write_text(fm_dump(m) + body, encoding="utf-8")
        print(f"archived previous revision '{old.get('revision', 'unknown')}' to {arch.relative_to(kb)}")
        stale = mark_memory_stale(kb, doc_id, str(old.get("revision", "")))
        if stale:
            print(f"  {stale} memory note(s) were based on the old revision and are now flagged 'verify before use'.")
    d.mkdir(parents=True)

    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    toc: list[str] = []
    total_chars = 0
    for i, c in enumerate(chunks, 1):
        fname = f"{i:02d}-{slugify(c['title'], 50)}.md"
        meta = {"doc": title, "doc_id": doc_id, "dept": dept, "revision": rev, "effective": a.effective or "",
                "section": c["title"], "pages": pages_label(c["p0"], c["p1"]), "page_start": c["p0"],
                "source_file": src.name}
        text = "\n".join(c["lines"]).strip() + "\n"
        total_chars += len(text)
        (d / fname).write_text(fm_dump(meta) + text, encoding="utf-8")
        pg = pages_label(c["p0"], c["p1"])
        toc.append(f"- [{fname}]({fname}) — {c['title']}" + (f" (p.{pg})" if pg else ""))
        for lvl, st, sp in c["subs"][1:41]:
            if lvl <= 3:
                toc.append(f"{'  ' * (lvl - 1)}- {st}" + (f" (p.{sp})" if sp else ""))

    last_page = max((c["p1"] for c in chunks if c["p1"]), default=None)
    docmeta = {"doc": title, "doc_id": doc_id, "dept": dept, "revision": rev, "effective": a.effective or "",
               "status": "current", "source_file": src.name, "source_sha256": sha, "ingested": TODAY,
               "total_pages": last_page, "chunks": len(chunks)}
    if prev_rev:
        docmeta["replaces_revision"] = prev_rev
    (d / "_doc.md").write_text(
        fm_dump(docmeta) + f"# {title}\n\nRevision: {rev} · Effective: {a.effective or 'not recorded'} · "
        f"Department: {dept}\n\n## Contents\n\n" + "\n".join(toc) + "\n", encoding="utf-8")

    rebuild_index(kb)
    print(f"ingested  {title}  →  {d.relative_to(kb.parent) if kb.parent in d.parents else d}")
    print(f"  chunks: {len(chunks)} · headings detected: {n_headings} · characters: {total_chars:,}"
          + (f" · pages: {last_page}" if last_page else ""))
    if rev == "unspecified":
        print("  WARNING: revision not recorded. Re-run with --rev so answers can cite the right revision.")
    if not a.effective:
        print("  note: effective date not recorded (--effective YYYY-MM-DD).")
    if n_headings < 3:
        print("  WARNING: very few headings detected; check the chunk files and adjust if needed.")


# --------------------------------------------------------------------------- index

def _doc_rows(folder: Path) -> list[dict]:
    rows = []
    for f in sorted(folder.glob("*/_doc.md")):
        meta = fm_load(f.read_text(encoding="utf-8"))[0]
        meta["_folder"] = f.parent.name
        rows.append(meta)
    return rows


def rebuild_index(kb: Path) -> None:
    depts = sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
    root = ["# Safety knowledge base index", "",
            f"Rebuilt {TODAY}. Search with `kb.py search \"<query>\"`. Cite document, revision, section and page.", "",
            "| Department | Current documents | Index |", "|---|---|---|"]
    for dp in depts:
        cur = _doc_rows(dp)
        sup = _doc_rows(dp / "_superseded") if (dp / "_superseded").is_dir() else []
        lines = [f"# {dp.name.upper()} — documents", "",
                 "| Document | Doc ID | Revision | Effective | Pages | Chunks | Folder |", "|---|---|---|---|---|---|---|"]
        for m in cur:
            lines.append(f"| {m.get('doc','')} | {m.get('doc_id','')} | {m.get('revision','')} | {m.get('effective','') or '—'} "
                         f"| {m.get('total_pages') or '—'} | {m.get('chunks','')} | `{m['_folder']}/` |")
        if not cur:
            lines.append("| _(none yet)_ | | | | | | |")
        if sup:
            lines += ["", "## Superseded revisions (not searched by default)", "",
                      "| Document | Revision | Status | Since | Folder |", "|---|---|---|---|---|"]
            for m in sup:
                lines.append(f"| {m.get('doc','')} | {m.get('revision','')} | {m.get('status','superseded')} "
                             f"| {m.get('superseded_on','')} | `_superseded/{m['_folder']}/` |")
        (dp / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        root.append(f"| {dp.name} | {len(cur)} | [{dp.name}/INDEX.md]({dp.name}/INDEX.md) |")
    if not depts:
        root.append("| _(empty)_ | 0 | |")
    (kb / "INDEX.md").write_text("\n".join(root) + "\n", encoding="utf-8")


def status(a: argparse.Namespace) -> None:
    kb = kb_root(a.kb)
    if not kb.is_dir() or not any(p.is_dir() for p in kb.iterdir()):
        print(f"Knowledge base at {kb} is empty. Ingest a manual first (kb.py ingest FILE --dept DEPT --rev REV).")
        return
    rebuild_index(kb)
    print(f"KB: {kb}\n")
    for dp in sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        rows = _doc_rows(dp)
        print(f"[{dp.name}] {len(rows)} document(s)")
        for m in rows:
            print(f"   - {m.get('doc')} · rev {m.get('revision')} · eff {m.get('effective') or 'n/a'} · "
                  f"{m.get('total_pages') or '?'} pp · id={m.get('doc_id')} · from {m.get('source_file')}")


# --------------------------------------------------------------------------- search

STOP = set("the a an of to in and or for is are be by on at as with from that this it its if shall must may will not no do does".split())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(s: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1]


def iter_blocks(kb: Path, depts: list[str] | None, doc: str | None, include_sup: bool):
    for md in sorted(kb.rglob("*.md")):
        parts = md.relative_to(kb).parts
        if md.name in ("_doc.md", "INDEX.md") or len(parts) < 3 or parts[0].startswith(("_", ".")):
            continue
        sup = parts[1] == "_superseded"
        if parts[1].startswith("_") and not sup:
            continue
        if sup and not include_sup:
            continue
        if depts and parts[0] not in depts:
            continue
        text = md.read_text(encoding="utf-8")
        meta, body = fm_load(text)
        if doc and doc not in meta.get("doc_id", ""):
            continue
        offset = text[: len(text) - len(body)].count("\n")
        page, heading = meta.get("page_start"), meta.get("section", "")
        cur: list[str] = []
        start_line, start_page, start_head, chars = 0, page, heading, 0

        def emit():
            if cur and "".join(cur).strip():
                yield {"path": md, "line": start_line, "page": start_page, "section": start_head,
                       "meta": meta, "text": "\n".join(cur).strip(), "superseded": sup}

        for i, line in enumerate(body.splitlines(), start=offset + 1):
            m = PAGE_RE.match(line)
            if m:
                page = int(m.group(1))
                continue
            h = HEAD_RE.match(line)
            if h:
                yield from emit()
                cur, chars = [], 0
                heading = h.group(2)
            if not cur:
                start_line, start_page, start_head = i, page, heading
            cur.append(line)
            chars += len(line) + 1
            if (not line.strip() and chars >= 400) or chars >= 1200:
                yield from emit()
                cur, chars = [], 0
        yield from emit()


def search(a: argparse.Namespace) -> None:
    kb = kb_root(a.kb)
    q = tokens(a.query)
    if not q:
        die("query has no searchable words.")
    qset = set(q)
    blocks = list(iter_blocks(kb, a.dept, a.doc, a.include_superseded))
    if not blocks:
        die(f"nothing to search in {kb} (check --dept / --doc, or ingest a manual first).")
    for b in blocks:
        b["tf"] = Counter(tokens(b["text"]) + tokens(b["section"]) * 2)
        b["dl"] = sum(b["tf"].values()) or 1
    n = len(blocks)
    avgdl = sum(b["dl"] for b in blocks) / n
    df: Counter = Counter()
    for b in blocks:
        df.update(b["tf"].keys())
    k1, bb = 1.5, 0.75
    phrase = a.query.lower().strip()
    scored = []
    for b in blocks:
        hit = [t for t in qset if t in b["tf"]]
        if not hit:
            continue
        s = 0.0
        for t in hit:
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            tf = b["tf"][t]
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - bb + bb * b["dl"] / avgdl))
        s *= 0.5 + 0.5 * len(hit) / len(qset)
        if len(q) > 1 and phrase in b["text"].lower():
            s *= 1.5
        scored.append((s, b))
    scored.sort(key=lambda x: -x[0])
    results = []
    for s, b in scored[: a.top]:
        flat = re.sub(r"\s+", " ", b["text"])
        pos = min((flat.lower().find(w) for w in re.findall(r"[a-z0-9]+", a.query.lower()) if flat.lower().find(w) >= 0), default=0)
        snippet = flat[max(0, pos - 100): max(0, pos - 100) + 420]
        m = b["meta"]
        results.append({"score": round(s, 2), "dept": m.get("dept"), "doc": m.get("doc"), "doc_id": m.get("doc_id"),
                        "revision": m.get("revision"), "effective": m.get("effective"), "section": b["section"],
                        "page": b["page"], "file": str(b["path"]), "line": b["line"],
                        "superseded": b["superseded"], "snippet": snippet})
    if a.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    if not results:
        print("No matches. Try different words, drop --dept, or say plainly that the KB does not cover this.")
        return
    for i, r in enumerate(results, 1):
        page = f"p.{r['page']}" if r["page"] else "p.n/a"
        flag = "  [SUPERSEDED REVISION]" if r["superseded"] else ""
        print(f"[{i}] {r['dept'].upper()} · {r['doc']} · rev {r['revision']} · §{r['section']} · {page}  (score {r['score']}){flag}")
        print(f"    {r['file']}:{r['line']}")
        print(f"    …{r['snippet']}…\n")


# --------------------------------------------------------------------------- matching, replacing, retiring

def find_doc(kb: Path, doc_id: str, dept: str | None = None) -> tuple[str, dict]:
    """Locate a current document by id. Returns (dept, _doc.md metadata) or exits with a helpful message."""
    hits = []
    for dp in sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))) if kb.is_dir() else []:
        if dept and dp.name != slugify(dept, 30):
            continue
        f = dp / doc_id / "_doc.md"
        if f.exists():
            hits.append((dp.name, fm_load(f.read_text(encoding="utf-8"))[0]))
    if not hits:
        known = [m.get("doc_id") for dp in (kb.iterdir() if kb.is_dir() else []) if dp.is_dir() and not dp.name.startswith(("_", "."))
                 for m in _doc_rows(dp)]
        die(f"no current document with id '{doc_id}'" + (f" in {dept}" if dept else "") +
            (f". Known ids: {', '.join(known)}." if known else ". The knowledge base is empty.") +
            " To add it as a new document, drop --replace and give --dept.")
    if len(hits) > 1:
        die(f"id '{doc_id}' exists in several departments ({', '.join(h[0] for h in hits)}); add --dept.")
    return hits[0]


_REV_NOISE = re.compile(r"\b(?:rev(?:ision)?|amdt|amendment|issue|ver(?:sion)?|v|r)\s*0*\d+(?:\s\d+)*[a-z]?\b")
_DATE_NOISE = re.compile(r"\b(?:19|20)\d{2}(?:\s\d{2}\s\d{2})?\b|\b(?:19|20)\d{6}\b")
_WORD_NOISE = {"final", "draft", "copy", "new", "newer", "updated", "update", "latest", "pdf", "docx", "md", "txt",
               "rev", "revision", "amdt", "amendment", "issue", "version", "the", "of"}


def name_key(name: str) -> frozenset[str]:
    """Reduce a file name or title to its identity words: revision numbers, dates and 'final/copy' are dropped."""
    s = re.sub(r"[\W_]+", " ", re.sub(r"\(\d+\)", " ", name.lower()))  # "(1)" is what browsers append to repeat downloads
    s = _DATE_NOISE.sub(" ", _REV_NOISE.sub(" ", s))
    return frozenset(t for t in s.split() if t not in _WORD_NOISE)


def name_sim(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return 1.0 if a == b else len(a & b) / len(a | b)


def match_cmd(a: argparse.Namespace) -> None:
    """Before ingesting: is each file new, a duplicate, or probably a new version of something already there?"""
    kb = kb_root(a.kb)
    docs = []
    for dp in (sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))) if kb.is_dir() else []):
        docs += [(dp.name, m, False) for m in _doc_rows(dp)]
        if (dp / "_superseded").is_dir():
            docs += [(dp.name, m, True) for m in _doc_rows(dp / "_superseded")]
    report = []
    for f in a.files:
        p = Path(f).expanduser()
        if not p.is_file():
            report.append({"file": f, "action": "error", "note": "file not found"})
            continue
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        key = name_key(p.stem)
        dup = next(((d, m, old) for d, m, old in docs if m.get("source_sha256") == sha), None)
        if dup:
            d, m, old = dup
            report.append({"file": f, "action": "ask_old_revision" if old else "skip_duplicate", "dept": d, "doc_id": m.get("doc_id"),
                           "doc": m.get("doc"), "revision": m.get("revision"),
                           "note": ("identical to an OLDER, superseded revision; ingesting it would roll the document back"
                                    if old else "byte-for-byte identical to the current document; nothing to do")})
            continue
        cands = []
        for d, m, old in docs:
            if old:
                continue
            keys = {name_key(Path(m.get("source_file", "")).stem), name_key(m.get("doc", "")), name_key(str(m.get("doc_id", "")).replace("-", " "))}
            best = max(name_sim(key, k) for k in keys)
            if best >= 0.75:
                cands.append((best, d, m))
        cands.sort(key=lambda x: -x[0])
        if cands:
            report.append({"file": f, "action": "ask_update_or_new",
                           "candidates": [{"similarity": round(s, 2), "dept": d, "doc_id": m.get("doc_id"), "doc": m.get("doc"),
                                           "revision": m.get("revision"), "source_file": m.get("source_file")} for s, d, m in cands[:3]]})
        else:
            report.append({"file": f, "action": "new", "note": "no existing document looks like this one"})
    if a.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    for i, r in enumerate(report, 1):
        print(f"[{i}] {Path(r['file']).name}")
        if r["action"] == "new":
            print("    NEW: nothing in the KB looks like it. Add as a new document.")
        elif r["action"] == "skip_duplicate":
            print(f"    DUPLICATE of {r['dept']}/{r['doc_id']} (rev {r['revision']}): {r['note']}")
        elif r["action"] == "ask_old_revision":
            print(f"    OLD REVISION: {r['note']} ({r['dept']}/{r['doc_id']}, rev {r['revision']}). Ask the user.")
        elif r["action"] == "ask_update_or_new":
            print("    ASK THE USER: update an existing document, or add as a new one?")
            for c in r["candidates"]:
                print(f"      · {c['dept']}/{c['doc_id']}  \"{c['doc']}\"  current rev {c['revision']}  (from {c['source_file']}, similarity {c['similarity']})")
            print(f"      update: ingest \"{r['file']}\" --replace <doc_id> --rev \"<new revision>\"")
            print(f"      new:    ingest \"{r['file']}\" --dept <dept> --doc-id <new-id> --title \"<title>\" --rev \"<revision>\"")
        else:
            print(f"    ERROR: {r['note']}")


def retire_cmd(a: argparse.Namespace) -> None:
    """Withdraw a document from search without deleting it (aviation records are kept)."""
    kb = kb_root(a.kb)
    dept, meta = find_doc(kb, a.doc_id, a.dept)
    d = kb / dept / a.doc_id
    arch = kb / dept / "_superseded" / f"{a.doc_id}__{slugify(str(meta.get('revision', 'unknown')))}__{TODAY}-withdrawn"
    n = 2
    while arch.exists():
        arch = arch.with_name(f"{arch.name}-{n}")
        n += 1
    arch.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(arch))
    m, body = fm_load((arch / "_doc.md").read_text(encoding="utf-8"))
    m.update(status="withdrawn", superseded_on=TODAY, withdrawn_reason=a.reason or "")
    (arch / "_doc.md").write_text(fm_dump(m) + body, encoding="utf-8")
    stale = mark_memory_stale(kb, a.doc_id, str(meta.get("revision", "")))
    rebuild_index(kb)
    print(f"withdrew {dept}/{a.doc_id} (rev {meta.get('revision')}); kept in {arch.relative_to(kb)}, no longer searched")
    if stale:
        print(f"  {stale} memory note(s) relied on it and are now flagged 'verify before use'.")


# --------------------------------------------------------------------------- shared state helpers

def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now().strftime('%y%m%d%H%M%S')}-{secrets.token_hex(2)}"


@contextlib.contextmanager
def locked(path: Path):
    """Serialise read-modify-write on a state file so parallel agents don't clobber each other."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "w") as lk:
        if fcntl:
            fcntl.flock(lk, fcntl.LOCK_EX)
        yield


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def append_jsonl(path: Path, rec: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- team board

MAX_REQUESTS_PER_THREAD = 8


def board_path(kb: Path) -> Path:
    return kb / "_team" / "board.jsonl"


def _line(r: dict) -> str:
    return (f"[{r['id']}] thread {r['thread']} · {r['from']} → {r['to']} · {r['kind']} · {r['status']} · {r['subject']}\n"
            f"    {r['text']}")


def board_post(a: argparse.Namespace) -> None:
    path = board_path(kb_root(a.kb))
    frm, to = slugify(a.sender, 30), slugify(a.to, 30)
    if a.kind == "request" and to == "all":
        die("a request must name one department (or 'user'). Use --kind note for broadcasts.")
    if frm == to:
        die("a department cannot post to itself.")
    with locked(path):
        rows = read_jsonl(path)
        rid = new_id("b")
        thread = a.thread or rid
        if a.kind == "request":
            reqs = [r for r in rows if r["thread"] == thread and r["kind"] == "request"]
            if len(reqs) >= MAX_REQUESTS_PER_THREAD:
                die(f"thread {thread} already has {len(reqs)} requests. It looks like a loop; escalate to the user instead.")
            if any(r["kind"] == "request" and r["status"] == "open" and r["from"] == frm and r["to"] == to
                   and r["subject"].lower() == a.subject.lower() for r in rows):
                die("an identical open request already exists on the board. Wait for the answer instead of asking again.")
        rec = {"id": rid, "ts": now(), "thread": thread, "from": frm, "to": to, "kind": a.kind,
               "subject": a.subject, "text": " ".join(a.text.split()), "status": "open"}
        append_jsonl(path, rec)
    print(f"posted {rid} (thread {thread}) {frm} → {to}")


def board_inbox(a: argparse.Namespace) -> None:
    path = board_path(kb_root(a.kb))
    me = slugify(a.dept, 30)
    with locked(path):
        rows = read_jsonl(path)
        todo = [r for r in rows if r["kind"] in ("request", "note") and r["status"] == "open" and r["to"] in (me, "all") and r["from"] != me]
        answers = [r for r in rows if r["kind"] == "answer" and r["status"] == "unread" and r["to"] == me]
        if answers and not a.peek:
            for r in rows:
                if r in answers:
                    r["status"] = "read"
            write_jsonl(path, rows)
    if a.json:
        print(json.dumps({"requests": todo, "answers": answers}, indent=2, ensure_ascii=False))
        return
    if not todo and not answers:
        print(f"inbox for {me}: empty")
        return
    if todo:
        print(f"== Open for {me} (answer with: board answer ID --from {me} --text ...)")
        print("\n".join(_line(r) for r in todo))
    if answers:
        print(f"== Answers to {me}'s requests")
        print("\n".join(_line(r) for r in answers))


def board_answer(a: argparse.Namespace) -> None:
    path = board_path(kb_root(a.kb))
    me = slugify(a.sender, 30)
    with locked(path):
        rows = read_jsonl(path)
        req = next((r for r in rows if r["id"] == a.id and r["kind"] == "request"), None)
        if not req:
            die(f"no request with id {a.id}.")
        if req["to"] != me:
            die(f"request {a.id} is addressed to {req['to']}, not {me}.")
        if req["status"] != "open":
            die(f"request {a.id} is already {req['status']}.")
        req["status"] = "answered"
        rows.append({"id": new_id("b"), "ts": now(), "thread": req["thread"], "from": me, "to": req["from"], "kind": "answer",
                     "reply_to": req["id"], "subject": f"Re: {req['subject']}", "text": " ".join(a.text.split()), "status": "unread"})
        write_jsonl(path, rows)
    print(f"answered {a.id}")


def board_close(a: argparse.Namespace) -> None:
    path = board_path(kb_root(a.kb))
    with locked(path):
        rows = read_jsonl(path)
        hit = 0
        for r in rows:
            if r["id"] in a.ids and r["status"] not in ("closed",):
                r["status"], r["closed_reason"] = "closed", a.reason or ""
                hit += 1
        write_jsonl(path, rows)
    print(f"closed {hit} item(s)")


def board_show(a: argparse.Namespace) -> None:
    rows = read_jsonl(board_path(kb_root(a.kb)))
    if a.thread:
        rows = [r for r in rows if r["thread"] == a.thread]
    if a.open:
        rows = [r for r in rows if r["status"] in ("open", "unread")]
    rows = rows[-a.limit:]
    print("\n".join(_line(r) for r in rows) if rows else "board: nothing to show")


def board_pending(a: argparse.Namespace) -> None:
    """What the coordinator must act on: open requests (addressee runs next) and unread answers (requester runs next)."""
    rows = read_jsonl(board_path(kb_root(a.kb)))
    reqs: dict[str, list[str]] = {}
    ans: dict[str, list[str]] = {}
    for r in rows:
        if r["kind"] == "request" and r["status"] == "open":
            reqs.setdefault(r["to"], []).append(r["id"])
        elif r["kind"] == "answer" and r["status"] == "unread":
            ans.setdefault(r["to"], []).append(r["id"])
    if a.json:
        print(json.dumps({"requests": reqs, "answers": ans}, indent=2))
        return
    if not reqs and not ans:
        print("pending: none")
        return
    for dept, ids in sorted(reqs.items()):
        print(f"{'for the USER' if dept == 'user' else dept}: {len(ids)} open request(s): {', '.join(ids)}")
    for dept, ids in sorted(ans.items()):
        print(f"{dept}: {len(ids)} unread answer(s) to its requests: {', '.join(ids)}")


# --------------------------------------------------------------------------- department memory

MEM_KINDS = ("term", "source-map", "preference", "decision", "correction", "lesson")
MAX_MEM_CHARS = 400


def mem_path(kb: Path, dept: str) -> Path:
    return kb / "_memory" / f"{slugify(dept, 30)}.jsonl"


def has_pii(text: str) -> bool:
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        return True
    return any(sum(c.isdigit() for c in m.group()) >= 10 for m in re.finditer(r"\+?\d[\d \-()]{8,}\d", text))


def mem_add(a: argparse.Namespace) -> None:
    kb = kb_root(a.kb)
    text = " ".join(a.text.split())
    if a.kind not in MEM_KINDS:
        die(f"--kind must be one of: {', '.join(MEM_KINDS)}")
    if len(text) > MAX_MEM_CHARS:
        die(f"memory notes are short pointers (max {MAX_MEM_CHARS} chars). The manual itself is already in the KB; note where to look, not what it says.")
    if has_pii(text) or has_pii(a.src):
        die("this looks like it contains an email address or phone number. Memory must not hold personal data.")
    path = mem_path(kb, a.dept)
    with locked(path):
        rows = read_jsonl(path)
        for r in rows:
            if r["status"] in ("active", "stale") and " ".join(r["text"].lower().split()) == text.lower():
                r["confirmed"] = r.get("confirmed", 1) + 1
                r["last_confirmed"] = now()
                if r["status"] == "stale" and a.doc and a.rev:  # re-verified against the current revision
                    r.update(status="active", doc=a.doc, rev=a.rev, src=a.src)
                write_jsonl(path, rows)
                print(f"already known; confirmed x{r['confirmed']} ({r['id']})")
                return
        rec = {"id": new_id("m"), "ts": now(), "dept": slugify(a.dept, 30), "kind": a.kind, "text": text, "src": a.src,
               "doc": a.doc or "", "rev": a.rev or "", "status": "active", "confirmed": 1}
        append_jsonl(path, rec)
    print(f"remembered {rec['id']} [{rec['dept']}/{a.kind}]")


def _mem_files(kb: Path, depts: list[str] | None) -> list[Path]:
    d = kb / "_memory"
    if depts:
        return [mem_path(kb, x) for x in depts]
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def mem_show(a: argparse.Namespace) -> None:
    kb = kb_root(a.kb)
    shown_any = False
    out_json = []
    for f in _mem_files(kb, a.dept):
        rows = [r for r in read_jsonl(f) if r["status"] in ("active", "stale") and (not a.kind or r["kind"] == a.kind)]
        if not rows:
            continue
        shown_any = True
        active = sorted((r for r in rows if r["status"] == "active"), key=lambda r: (-r.get("confirmed", 1), r["ts"]), reverse=False)[: a.limit]
        stale = [r for r in rows if r["status"] == "stale"]
        if a.json:
            out_json += active + stale
            continue
        print(f"## Memory: {f.stem} ({len(active)} active)")
        for r in active:
            print(f"- ({r['kind']}) {r['text']}  — src: {r['src']} · confirmed {r.get('confirmed', 1)}x · {r['ts'][:10]} · {r['id']}")
        if stale:
            print(f"### {f.stem}: VERIFY BEFORE USE (the source revision has been superseded)")
            for r in stale:
                print(f"- ({r['kind']}) {r['text']}  — src: {r['src']} · {r['id']}")
        print()
    if a.json:
        print(json.dumps(out_json, indent=2, ensure_ascii=False))
    elif not shown_any:
        print("memory: empty")


def mem_search(a: argparse.Namespace) -> None:
    q = set(tokens(a.query))
    hits = []
    for f in _mem_files(kb_root(a.kb), a.dept):
        for r in read_jsonl(f):
            if r["status"] in ("active", "stale"):
                score = len(q & set(tokens(r["text"] + " " + r["src"])))
                if score:
                    hits.append((score, r))
    for _, r in sorted(hits, key=lambda x: -x[0])[: a.top]:
        flag = " [VERIFY: source superseded]" if r["status"] == "stale" else ""
        print(f"- [{r['dept']}/{r['kind']}] {r['text']}  — src: {r['src']} · {r['id']}{flag}")
    if not hits:
        print("memory: no match")


def mem_forget(a: argparse.Namespace) -> None:
    kb = kb_root(a.kb)
    for f in _mem_files(kb, None):
        with locked(f):
            rows = read_jsonl(f)
            hit = [r for r in rows if r["id"] == a.id]
            if hit:
                hit[0].update(status="forgotten", forgotten_on=TODAY, forgotten_reason=a.reason or "")
                write_jsonl(f, rows)
                print(f"forgot {a.id} ({f.stem})")
                return
    die(f"no memory with id {a.id}.")


def mark_memory_stale(kb: Path, doc_id: str, old_rev: str) -> int:
    """A manual was re-issued: flag notes that relied on the old revision so nobody trusts them blindly."""
    n = 0
    mem_dir = kb / "_memory"
    for f in (sorted(mem_dir.glob("*.jsonl")) if mem_dir.is_dir() else []):
        with locked(f):
            rows = read_jsonl(f)
            changed = False
            for r in rows:
                if r["status"] == "active" and r.get("doc") == doc_id and r.get("rev") == old_rev:
                    r.update(status="stale", stale_since=TODAY)
                    n, changed = n + 1, True
            if changed:
                write_jsonl(f, rows)
    return n


# --------------------------------------------------------------------------- cli

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--kb", help="knowledge base folder (default: $SAFETY_KB_DIR or ./safety-kb)")

    p = sub.add_parser("ingest", parents=[common], help="convert a manual into the knowledge base")
    p.add_argument("file")
    p.add_argument("--dept", help="department folder, e.g. sms, audit, fdm, shared (not needed with --replace)")
    p.add_argument("--replace", metavar="DOC_ID", help="update this existing document with the file (old revision is archived)")
    p.add_argument("--title")
    p.add_argument("--doc-id")
    p.add_argument("--rev", help="revision / amendment, e.g. 'Rev 5' or 'Amdt 3'")
    p.add_argument("--effective", help="effective date YYYY-MM-DD")
    p.add_argument("--force", action="store_true", help="replace even if this revision is already ingested")
    p.add_argument("--layout", action="store_true", help="pdftotext -layout (keeps table columns)")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p.set_defaults(fn=ingest)

    p = sub.add_parser("match", parents=[common], help="check files against the KB: new, duplicate, or a new version of something there?")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=match_cmd)

    p = sub.add_parser("retire", parents=[common], help="withdraw a document from search (kept on disk, never deleted)")
    p.add_argument("doc_id")
    p.add_argument("--dept")
    p.add_argument("--reason")
    p.set_defaults(fn=retire_cmd)

    p = sub.add_parser("search", parents=[common], help="keyword search with citations")
    p.add_argument("query")
    p.add_argument("--dept", action="append", help="limit to a department (repeatable)")
    p.add_argument("--doc", help="limit to a doc id (substring)")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--include-superseded", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=search)

    p = sub.add_parser("index", parents=[common], help="rebuild INDEX.md files")
    p.set_defaults(fn=lambda a: (rebuild_index(kb_root(a.kb)), print("index rebuilt")))

    p = sub.add_parser("status", parents=[common], help="list what the KB holds")
    p.set_defaults(fn=status)

    board = sub.add_parser("board", help="messages between departments").add_subparsers(dest="bcmd", required=True)
    p = board.add_parser("post", parents=[common], help="ask another department (request) or inform it (note)")
    p.add_argument("--from", dest="sender", required=True, help="your department")
    p.add_argument("--to", required=True, help="department, 'user' (needs a human), or 'all' (notes only)")
    p.add_argument("--kind", choices=["request", "note"], default="request")
    p.add_argument("--subject", required=True)
    p.add_argument("--text", required=True, help="the question or note; include what you already know and why you ask")
    p.add_argument("--thread", help="reuse a thread id when following up")
    p.set_defaults(fn=board_post)
    p = board.add_parser("inbox", parents=[common], help="open requests for a department, plus answers to its own requests")
    p.add_argument("--dept", required=True)
    p.add_argument("--peek", action="store_true", help="do not mark answers as read")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=board_inbox)
    p = board.add_parser("answer", parents=[common], help="answer a request addressed to you")
    p.add_argument("id")
    p.add_argument("--from", dest="sender", required=True)
    p.add_argument("--text", required=True)
    p.set_defaults(fn=board_answer)
    p = board.add_parser("close", parents=[common], help="close items that are handled or no longer needed")
    p.add_argument("ids", nargs="+")
    p.add_argument("--reason")
    p.set_defaults(fn=board_close)
    p = board.add_parser("show", parents=[common], help="show the board, or one thread")
    p.add_argument("--thread")
    p.add_argument("--open", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=board_show)
    p = board.add_parser("pending", parents=[common], help="which departments have open requests (for the coordinator)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=board_pending)

    mem = sub.add_parser("mem", help="per-department memory").add_subparsers(dest="mcmd", required=True)
    p = mem.add_parser("add", parents=[common], help="remember a durable, sourced fact or lesson")
    p.add_argument("--dept", required=True, help="department name, or 'team' for shared notes")
    p.add_argument("--kind", required=True, help=" | ".join(MEM_KINDS))
    p.add_argument("--text", required=True, help=f"short pointer, max {MAX_MEM_CHARS} chars")
    p.add_argument("--src", required=True, help="citation like '[SMS Manual Rev 5 §2.1, p.9]' or 'user, 2026-10-26'")
    p.add_argument("--doc", help="doc id the note relies on (enables staleness checks)")
    p.add_argument("--rev", help="revision of that document")
    p.set_defaults(fn=mem_add)
    p = mem.add_parser("show", parents=[common], help="read memory (default: every department)")
    p.add_argument("--dept", action="append")
    p.add_argument("--kind")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=mem_show)
    p = mem.add_parser("search", parents=[common], help="search memory")
    p.add_argument("query")
    p.add_argument("--dept", action="append")
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(fn=mem_search)
    p = mem.add_parser("forget", parents=[common], help="retire a wrong or outdated note")
    p.add_argument("id")
    p.add_argument("--reason")
    p.set_defaults(fn=mem_forget)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
