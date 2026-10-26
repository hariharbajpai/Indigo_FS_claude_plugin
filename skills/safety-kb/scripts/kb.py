#!/usr/bin/env python3
"""safety-kb: turn manuals into a sectioned markdown knowledge base, and search it.

  kb.py ingest FILE --dept DEPT [--title T] [--doc-id ID] [--rev R] [--effective YYYY-MM-DD]
                    [--force] [--layout] [--max-chars N]
  kb.py search QUERY [--dept D ...] [--doc ID] [--top N] [--include-superseded] [--json]
  kb.py index                      rebuild INDEX.md files
  kb.py status                     show what the KB holds

KB location: --kb, else $SAFETY_KB_DIR, else ./safety-kb
Layout:      <kb>/<dept>/<doc-id>/{_doc.md, NN-section.md}   (older revisions: <kb>/<dept>/_superseded/)

Stdlib only. PDF text comes from pypdf, PyMuPDF or the pdftotext CLI (first one found).
DOCX is read directly from its XML. Markdown and plain text are accepted as they are.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

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
    if d.exists():
        old = fm_load((d / "_doc.md").read_text(encoding="utf-8"))[0] if (d / "_doc.md").exists() else {}
        if old.get("revision") == rev and not a.force:
            die(f"{dept}/{doc_id} revision '{rev}' is already ingested. Pass --force to replace it, "
                f"or give the new revision with --rev.")
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
                      "| Document | Revision | Superseded on | Folder |", "|---|---|---|---|"]
            for m in sup:
                lines.append(f"| {m.get('doc','')} | {m.get('revision','')} | {m.get('superseded_on','')} | `_superseded/{m['_folder']}/` |")
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
                  f"{m.get('total_pages') or '?'} pp · id={m.get('doc_id')}")


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


# --------------------------------------------------------------------------- cli

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--kb", help="knowledge base folder (default: $SAFETY_KB_DIR or ./safety-kb)")

    p = sub.add_parser("ingest", parents=[common], help="convert a manual into the knowledge base")
    p.add_argument("file")
    p.add_argument("--dept", required=True, help="department folder, e.g. sms, audit, fdm, shared")
    p.add_argument("--title")
    p.add_argument("--doc-id")
    p.add_argument("--rev", help="revision / amendment, e.g. 'Rev 5' or 'Amdt 3'")
    p.add_argument("--effective", help="effective date YYYY-MM-DD")
    p.add_argument("--force", action="store_true", help="replace even if this revision is already ingested")
    p.add_argument("--layout", action="store_true", help="pdftotext -layout (keeps table columns)")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p.set_defaults(fn=ingest)

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

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
