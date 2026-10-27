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


class KbBridge:
    def __init__(self, root=None, kb_script=None):
        self.root = os.path.abspath(root or paths.kb_root())
        self.kb_script = os.path.abspath(kb_script or paths.kb_script())

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

    def keywords(self, dept):
        """Planner scope hints: the department's document ids."""
        return " ".join(x.replace("-", " ") for x in self.list_docs(dept))

    # ---- match ----
    def _match_raw(self, paths):
        r = self.run("match", "--json", *paths)
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
        keep = ("score", "dept", "doc", "doc_id", "revision", "effective", "section", "page", "file", "snippet")
        return [{k: x.get(k) for k in keep} for x in rows]

    def inside(self, path):
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(self.root, path))
        root = os.path.realpath(self.root)
        if not full.startswith(root + os.sep):
            raise Invalid("That file is not in the knowledge base")
        return full

    def read_file(self, path, limit=40000):
        full = self.inside(path)
        if not os.path.isfile(full):
            raise Invalid(f"No such file in the knowledge base: {path}")
        with open(full, encoding="utf-8", errors="replace") as f:
            text = f.read()
        return {"file": full, "text": text[:limit], "truncated": len(text) > limit}

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
