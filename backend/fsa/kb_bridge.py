"""Bridge to the real safety-kb tool (skills/safety-kb/scripts/kb.py).

Everything goes through the kb.py command line, run with the current python3:
  match   PDF vs the KB: new / duplicate / new version (kb.py's own SHA-256 and file-name logic)
  ingest  PDF -> sectioned markdown under <kb>/<dept>/<doc-id>/; --replace archives the old revision
  retire  withdraw a document from search (kept on disk)
  board   messages between departments, mirrored into the message feed

KB root and kb.py path: see paths.py (default ./safety-kb in the project, git-ignored; kb.py from this plugin).
Results keep the API vocabulary: new | duplicate | new_version.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

from . import paths
from .store import Invalid

DEFAULT_READ_CHARS = 16000   # a whole file read: a few thousand tokens at most
DEFAULT_WINDOW_CHARS = 4000  # a read around a line from search_manuals: about a thousand tokens
MAX_READ_CHARS = 40000
PACK_CHARS = 2400            # what the File Checker stores per section of a source pack
CACHE_FILES = 64             # chunk files kept in memory, so a file is read from disk once while it is unchanged
_PAGE_LINE = re.compile(r"^<!-- page (\d+) -->$")
_HEAD_LINE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def _front_matter(lines):
    """(metadata of a chunk file's front matter, number of front-matter lines)."""
    if not lines or lines[0] != "---":
        return {}, 0
    for i in range(1, min(len(lines), 40)):
        if lines[i] == "---":
            meta = {}
            for text in lines[1:i]:
                k, _, v = text.partition(":")
                try:
                    meta[k.strip()] = json.loads(v.strip())
                except ValueError:
                    meta[k.strip()] = v.strip()
            return meta, i + 1
    return {}, 0


def _context(lines, meta, body_from, start):
    """Document, revision, section and page of `start` in a chunk file (front matter is not part of the text)."""
    page, section = meta.get("page_start"), meta.get("section")
    for text in lines[body_from:start]:
        m = _PAGE_LINE.match(text)
        if m:
            page = int(m.group(1))
        h = _HEAD_LINE.match(text)
        if h:
            section = h.group(1)
    ctx = {"doc": meta.get("doc"), "revision": meta.get("revision"), "section": section, "page": page}
    return {k: v for k, v in ctx.items() if v not in (None, "")}


class KbBridge:
    def __init__(self, root=None, kb_script=None):
        self.root = os.path.abspath(root or paths.kb_root())
        self.kb_script = os.path.abspath(kb_script or paths.kb_script())
        self._cache = {}  # full path -> (mtime_ns, size, lines)

    def _lines(self, full):
        """The lines of a KB file, read from disk only when it is new or has changed."""
        st = os.stat(full)
        hit = self._cache.get(full)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        with open(full, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        if len(self._cache) >= CACHE_FILES:
            self._cache.pop(next(iter(self._cache)))
        self._cache[full] = (st.st_mtime_ns, st.st_size, lines)
        return lines

    # ---- running kb.py ----
    def run(self, *args, check=True):
        try:
            r = subprocess.run([sys.executable, "-I", self.kb_script, *args, "--kb", self.root],
                               capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as e:
            raise Invalid(f"Knowledge base tool could not run: {e}")
        if check and r.returncode:
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise Invalid("Knowledge base: " + (msg[-1] if msg else "command failed"))
        return r

    @staticmethod
    def kb_dept(dept_id):
        """kb.py shortens department folder names to 30 characters."""
        return re.sub(r"[^a-z0-9]+", "-", dept_id.lower()).strip("-")[:30].strip("-")

    @staticmethod
    def safe_name(name):
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name or "")).strip("._")
        return base or "document.pdf"

    @staticmethod
    def validate(files):
        """files: [(filename, bytes)]. Raises Invalid with a clear message."""
        if not files:
            raise Invalid("Upload at least one PDF")
        for name, data in files:
            if not (name or "").lower().endswith(".pdf") or not data.startswith(b"%PDF"):
                raise Invalid(f"'{name}' is not a PDF file")

    @staticmethod
    def _stage(tmp, files):
        paths = []
        for i, (name, data) in enumerate(files):
            folder = os.path.join(tmp, str(i))
            os.makedirs(folder)
            path = os.path.join(folder, KbBridge.safe_name(name))
            with open(path, "wb") as f:
                f.write(data)
            paths.append(path)
        return paths

    # ---- documents on disk ----
    def list_docs(self, dept):
        """Current doc ids of a department (folders holding _doc.md)."""
        d = os.path.join(self.root, self.kb_dept(dept))
        if not os.path.isdir(d):
            return []
        return sorted(n for n in os.listdir(d) if not n.startswith(("_", "."))
                      and os.path.isfile(os.path.join(d, n, "_doc.md")))

    def documents(self, dept):
        """The department's current manuals for the dashboard: title, revision, effective date and pages
        from each _doc.md front matter."""
        base = os.path.join(self.root, self.kb_dept(dept))
        out = []
        for doc_id in self.list_docs(dept):
            try:
                with open(os.path.join(base, doc_id, "_doc.md"), encoding="utf-8") as f:
                    meta, _ = _front_matter([next(f, "").rstrip("\n") for _ in range(40)])
            except OSError:
                meta = {}
            out.append({"id": doc_id, "title": meta.get("doc") or doc_id, "revision": meta.get("revision") or None,
                        "effective": meta.get("effective") or None, "pages": meta.get("total_pages") or None,
                        "source_file": meta.get("source_file") or None})
        return out

    def keywords(self, dept):
        """Planner scope hints: the department's document ids."""
        return " ".join(x.replace("-", " ") for x in self.list_docs(dept))

    # ---- match ----
    def _match_raw(self, paths):
        r = self.run("match", "--json", "--no-detect", *paths)
        try:
            return json.loads(r.stdout)
        except ValueError:
            raise Invalid("Knowledge base returned an unreadable match report")

    def match(self, files, active_depts=None):
        """Per file: {file, result, existing_dept, doc_id, detail}. Only active departments count."""
        active = {self.kb_dept(d): d for d in (active_depts or [])}
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            report = self._match_raw(self._stage(tmp, files))
        for (name, _), rep in zip(files, report):
            res = {"file": name, "result": "new", "existing_dept": None, "doc_id": None,
                   "detail": "No similar document found"}
            act = rep.get("action")
            if act in ("skip_duplicate", "ask_old_revision"):
                dept = rep.get("dept")
                if active_depts is None or dept in active:
                    res.update(result="duplicate", existing_dept=active.get(dept, dept), doc_id=rep.get("doc_id"),
                               detail=rep.get("note") or "Identical document already stored")
            elif act == "ask_update_or_new":
                c = next((c for c in rep["candidates"] if active_depts is None or c["dept"] in active), None)
                if c:
                    res.update(result="new_version", existing_dept=active.get(c["dept"], c["dept"]),
                               doc_id=c["doc_id"],
                               detail=f"Looks like a new version of {c['doc_id']} (rev {c['revision']}) in {c['dept']}")
            elif act == "error":
                raise Invalid(f"'{name}': {rep.get('note', 'unreadable')}")
            out.append(res)
        return out

    # ---- ingest / replace / retire ----
    @staticmethod
    def _title(path):
        return re.sub(r"[_\-]+", " ", os.path.splitext(os.path.basename(path))[0]).strip()

    def ingest(self, dept, files):
        """Ingest each PDF as a new document of `dept`. Returns the doc ids created."""
        ids = []
        with tempfile.TemporaryDirectory() as tmp:
            for path in self._stage(tmp, files):
                before = set(self.list_docs(dept))
                self.run("ingest", path, "--dept", self.kb_dept(dept), "--title", self._title(path))
                ids += sorted(set(self.list_docs(dept)) - before)
        return ids

    def replace(self, dept, files):
        """Update `dept` with new files: a file that is a new version of one of its documents replaces it
        (old revision archived by kb.py); an identical file is skipped; anything else is added."""
        rev = "Upload " + dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        kd, done = self.kb_dept(dept), []
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._stage(tmp, files)
            for path, rep in zip(paths, self._match_raw(paths)):
                act = rep.get("action")
                if act == "error":
                    raise Invalid(f"'{os.path.basename(path)}': {rep.get('note', 'unreadable')}")
                if act == "skip_duplicate" and rep.get("dept") == kd:
                    continue
                cand = next((c for c in rep.get("candidates", []) if c["dept"] == kd), None)
                if cand:
                    self.run("ingest", path, "--replace", cand["doc_id"], "--dept", kd, "--rev", rev, "--force")
                    done.append(cand["doc_id"])
                else:
                    done += self.ingest(dept, [(os.path.basename(path), open(path, "rb").read())])
        return done

    def retire(self, dept):
        """Withdraw every current document of the department (kb.py keeps them on disk, never deleted)."""
        for doc_id in self.list_docs(dept):
            self.run("retire", doc_id, "--dept", self.kb_dept(dept), "--reason", "department retired")

    # ---- search / read / outputs (agent tools) ----
    def search(self, query, depts=None, top=8):
        """kb.py search --json. [] when the KB is empty or nothing matches."""
        if not (query or "").strip():
            raise Invalid("Give some words to search for")
        if not os.path.isdir(self.root):
            return []
        args = ["search", query, "--json", "--top", str(int(top))]
        for d in depts or []:
            args += ["--dept", self.kb_dept(d)]
        r = self.run(*args, check=False)
        if r.returncode:
            return []
        try:
            rows = json.loads(r.stdout or "[]")
        except ValueError:
            return []
        keep = ("score", "dept", "doc", "doc_id", "revision", "effective", "section", "page", "file", "line", "snippet")
        base, out = os.path.realpath(self.root), []
        for x in rows:
            row = {k: x.get(k) for k in keep}
            rel = os.path.relpath(row["file"], base) if row.get("file") else ""
            if rel and not rel.startswith(".."):
                row["file"] = rel  # shorter than the absolute path; read_section accepts it
            out.append(row)
        return out

    def inside(self, path):
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(self.root, path))
        root = os.path.realpath(self.root)
        if not full.startswith(root + os.sep):
            raise Invalid("That file is not in the knowledge base")
        return full

    def read_file(self, path, line=None, chars=None):
        """Read part of a KB file. With `line` (from search_manuals): about DEFAULT_WINDOW_CHARS characters from that
        line on. Without: the first DEFAULT_READ_CHARS characters. Cuts fall on line boundaries; `next_line` says where
        to carry on (pass it as `line`). Never more than MAX_READ_CHARS."""
        full = self.inside(path)
        if not os.path.isfile(full):
            raise Invalid(f"No such file in the knowledge base: {path}")
        lines = self._lines(full)
        total = len(lines)
        try:
            line = int(line) if line else None
            chars = int(chars) if chars else None
        except (TypeError, ValueError):
            raise Invalid("line and chars must be whole numbers")
        budget = max(500, min(chars, MAX_READ_CHARS)) if chars else (DEFAULT_WINDOW_CHARS if line else DEFAULT_READ_CHARS)
        meta, body_from = _front_matter(lines)
        start = 1
        used = 0
        if line:
            start = min(max(line, 1), max(total, 1))
        out, end, cut = [], start - 1, False
        for i in range(start, total + 1):
            text = lines[i - 1]
            if len(text) > MAX_READ_CHARS:
                text, cut = text[:MAX_READ_CHARS], True
            if out and used + len(text) + 1 > budget:
                break
            out.append(text)
            used += len(text) + 1
            end = i
        res = {"file": full, "text": "\n".join(out), "truncated": end < total or cut,
               "from_line": start, "to_line": end, "total_lines": total}
        if end < total:
            res["next_line"] = end + 1
        if start > 1:  # the front matter is not in the text, so say which document, section and page this is
            res["context"] = _context(lines, meta, body_from, start)
        return res

    def pack_source(self, file, line=None, chars=PACK_CHARS):
        """One section of a source pack, read by the system itself so the citation is exact: the document, revision,
        section and page come from the file, not from whoever picked it. Raises Invalid if the file is not in the
        knowledge base."""
        r = self.read_file(file, line, chars)
        full = r["file"]
        lines = self._lines(full)
        meta, body_from = _front_matter(lines)
        ctx = _context(lines, meta, body_from, r["from_line"])
        rel = os.path.relpath(full, os.path.realpath(self.root)).replace(os.sep, "/")
        issues = []
        if "/_superseded/" in "/" + rel:
            issues.append(f"{ctx.get('doc') or rel} rev {ctx.get('revision') or '?'} is a superseded or withdrawn revision")
        return dict(ctx, file=rel, line=r["from_line"], to_line=r["to_line"], dept=meta.get("dept"),
                    extract=r["text"], truncated=r["truncated"], issues=issues)

    def save_output(self, folder, name, content):
        if not (content or "").strip():
            raise Invalid("The output is empty")
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", folder).strip("-.") or "general"
        fname = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:80] or "output"
        d = os.path.join(self.root, "_outputs", base)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, fname if fname.endswith(".md") else fname + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")
        return path

    # ---- keyword links between departments (kb.py links) ----
    def links_find(self, text, dept=None, learn=False, top=3):
        """Which other departments do the words in `text` point at, and what do they know about it?
        {"terms": [...], "related": [{dept, score, via, memory, board, manuals}]}; empty when nothing is tied."""
        empty = {"terms": [], "related": []}
        if not (text or "").strip() or not os.path.isdir(self.root):
            return empty
        args = ["links", "find", "--text", text[:4000], "--json", "--top", str(int(top))]
        if dept:
            args += ["--dept", self.kb_dept(dept)]
        if learn:
            args.append("--learn")
        try:
            r = self.run(*args, check=False)
            return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else empty
        except (Invalid, ValueError):
            return empty

    def links_learn(self, text, dept, src="task"):
        """Teach the map that the words in `text` belong to `dept`. Never raises: learning is a bonus."""
        if not (text or "").strip() or not dept or not os.path.isdir(self.root):
            return
        try:
            self.run("links", "learn", "--text", text[:4000], "--dept", self.kb_dept(dept), "--src", src, check=False)
        except Invalid:
            pass

    def links_show(self, limit=60):
        if not os.path.isdir(self.root):
            return {"links": [], "ignored": []}
        try:
            r = self.run("links", "show", "--json", "--limit", str(int(limit)), check=False)
            return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {"links": [], "ignored": []}
        except (Invalid, ValueError):
            return {"links": [], "ignored": []}

    # ---- board mirror ----
    def board_entries(self):
        """Read `kb.py board show` and return [{id, from, to, text, ts}]."""
        if not os.path.isfile(self.kb_script) or not os.path.isdir(self.root):
            return []
        try:
            r = self.run("board", "show", "--limit", "1000", check=False)
        except Invalid:
            return []
        return parse_board(r.stdout) if r.returncode == 0 else []


_HEAD = re.compile(r"^\[(?P<id>[^\]]+)\] thread (?P<thread>\S+) · (?P<f>.+?) → (?P<t>.+?) · (?P<kind>\w+) · "
                   r"(?P<status>\w+) · (?P<subject>.*)$")


def parse_board(text):
    """Parse kb.py board lines: `[id] thread T · from → to · kind · status · subject` + indented text line."""
    entries, cur = [], None
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            cur = {"id": m["id"], "from": m["f"], "to": m["t"], "ts": "", "subject": m["subject"], "text": ""}
            entries.append(cur)
        elif cur is not None and line.startswith("    ") and not cur["text"]:
            cur["text"] = line.strip()
    for e in entries:
        e["text"] = f"{e.pop('subject')}: {e['text']}" if e["text"] else e.pop("subject")
    return entries
