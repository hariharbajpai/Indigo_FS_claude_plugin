"""Dashboard server: the built UI (backend/fsa/web) plus the JSON API in backend/API.md and live events.

Standard library only, so the plugin needs no installs. Local only: binds 127.0.0.1, checks the Host
header, and every /api call except /api/health needs the dashboard token (X-FSA-Token header or
?token=), which /flight-safety-agents:start puts in the link it gives the Owner.
"""
import json
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import VERSION, paths
from .kb_bridge import KbBridge
from .loop import Office
from .services import add_department, replace_documents, retire_department
from .store import Store, StoreError
from .workflow import Workflow

MAX_BODY = 200 * 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
RUN_HINT = "Sent. In Claude Code, run /flight-safety-agents:run so the team picks it up."


OFFICE_TYPES = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class FileOut:
    """A route result that is a file download, not JSON."""

    def __init__(self, path, name, ctype):
        self.path, self.name, self.ctype = path, name, ctype


class HttpError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


def parse_multipart(content_type, body):
    """multipart/form-data -> ({field: value}, [(file name, bytes)] for the `files` field)."""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise HttpError(400, "Expected multipart/form-data")
    fields, files = {}, []
    for part in body.split(b"--" + m.group(1).encode())[1:]:
        if part.startswith(b"--"):
            break
        if part.startswith(b"\r\n"):
            part = part[2:]
        head, _, data = part.partition(b"\r\n\r\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        head = head.decode("utf-8", "replace")
        name = re.search(r'\bname="([^"]*)"', head)
        fname = re.search(r'\bfilename="([^"]*)"', head)
        if not name:
            continue
        if fname is not None:
            if name.group(1) == "files" and fname.group(1):
                files.append((fname.group(1), data))
        else:
            fields[name.group(1)] = data.decode("utf-8", "replace")
    return fields, files


class Request:
    def __init__(self, handler, path, query, params):
        self.h, self.path, self.query, self.params = handler, path, query, params
        self._body = None

    def q(self, key, default=None, cast=str):
        v = self.query.get(key)
        if v is None or v == "":
            return default
        try:
            return cast(v)
        except ValueError:
            raise HttpError(422, f"Bad value for {key}")

    def flag(self, key):
        return str(self.query.get(key, "")).lower() in ("1", "true", "yes")

    def body(self):
        if self._body is None:
            n = int(self.h.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise HttpError(413, "Upload too large")
            self._body = self.h.rfile.read(n) if n else b""
        return self._body

    def json(self, *required):
        try:
            data = json.loads(self.body() or b"{}")
        except ValueError:
            raise HttpError(422, "Body must be JSON")
        if not isinstance(data, dict):
            raise HttpError(422, "Body must be a JSON object")
        for r in required:
            if r not in data or data[r] is None:
                raise HttpError(422, f"Field '{r}' is required")
        return data

    def form(self):
        return parse_multipart(self.h.headers.get("Content-Type"), self.body())


class App:
    def __init__(self, db_path=None, kb_root=None, kb_script=None, token=None, web_dir=None, planner=None,
                 agent_mode=True, message_cap=30):
        self.kb = KbBridge(kb_root, kb_script)
        self.store = Store(db_path or os.environ.get("FSA_DB") or paths.db_path(self.kb.root))
        self.wf = Workflow(self.store, planner, message_cap=message_cap, scope_provider=self.kb.keywords,
                           agent_mode=agent_mode)
        self.office = Office(self.store, self.wf, self.kb)
        self.token = token
        self.web_dir = web_dir or paths.WEB_DIR
        self._synced = 0.0
        self.board_sync_seconds = 10  # mirroring the kb.py board runs a subprocess, so not on every call
        R = self.route
        self.routes = [
            R("GET", "/api/health", self.health, auth=False),
            R("GET", "/api/overview", self.overview),
            R("GET", "/api/activity", lambda r: self.office.activity()),
            R("GET", "/api/org", lambda r: self.store.org_chart(r.flag("include_retired"))),
            R("GET", "/api/work-requests", lambda r: self.store.list_work_requests()),
            R("GET", "/api/work-requests/(?P<wid>[^/]+)", lambda r: self.wf.request_detail(r.params["wid"])),
            R("POST", "/api/work-requests", self.post_work),
            R("POST", "/api/instructions", self.post_instruction),
            R("GET", "/api/tasks", lambda r: self.store.list_tasks(r.q("status"), r.q("dept"), r.q("work_request_id"))),
            R("GET", "/api/tasks/(?P<tid>[^/]+)", lambda r: self.store.get_task(r.params["tid"])),
            R("POST", "/api/tasks/(?P<tid>[^/]+)/status", self.task_status),
            R("POST", "/api/tasks/(?P<tid>[^/]+)/assign",
              lambda r: self.store.assign_task(r.params["tid"], r.json("agent_id")["agent_id"])),
            R("POST", "/api/departments/(?P<did>[^/]+)/hire", self.hire),
            R("GET", "/api/messages", self.messages),
            R("GET", "/api/departments", lambda r: self.store.list_departments(r.flag("include_retired"))),
            R("POST", "/api/departments", self.add_department),
            R("POST", "/api/departments/(?P<did>[^/]+)/replace", self.replace_department),
            R("POST", "/api/departments/(?P<did>[^/]+)/retire",
              lambda r: retire_department(self.store, self.kb, r.params["did"])),
            R("POST", "/api/agents/(?P<aid>[^/]+)/retire", lambda r: self.store.retire_agent(r.params["aid"])),
            R("POST", "/api/agents/(?P<aid>[^/]+)/rename",
              lambda r: self.store.rename_agent(r.params["aid"], r.json("name")["name"])),
            R("POST", "/api/departments/(?P<did>[^/]+)/rename",
              lambda r: self.store.rename_department(r.params["did"], r.json("name")["name"])),
            R("GET", "/api/files", lambda r: self.store.list_files(r.q("work_request_id"))),
            R("GET", "/api/files/(?P<fid>[0-9]+)/download", self.download),
            R("GET", "/api/events", None, stream=True),
        ]

    @staticmethod
    def route(method, pattern, fn, auth=True, stream=False):
        return {"method": method, "re": re.compile(pattern + "$"), "fn": fn, "auth": auth, "stream": stream}

    def close(self):
        self.store.close()

    # ---- handlers ----
    def health(self, r):
        return {"ok": True, "version": VERSION}

    def sync_board(self):
        if self.board_sync_seconds and time.time() - self._synced < self.board_sync_seconds:
            return
        self._synced = time.time()
        try:
            self.wf.sync_board(self.kb.board_entries())
        except Exception:
            pass

    def overview(self, r):
        self.sync_board()
        out = self.store.overview()
        out["activity"] = self.office.activity()
        out["kb_root"] = self.kb.root
        return out

    def messages(self, r):
        self.sync_board()
        limit = r.q("limit", 500, int)
        if limit > 5000:
            raise HttpError(422, "limit must be at most 5000")
        return self.store.list_messages(r.q("dept"), r.q("agent"), r.q("task"), r.q("work_request_id"),
                                        r.q("since_id", 0, int), limit)

    def post_work(self, r):
        wr = self.wf.submit_work_request(r.json("text")["text"])
        if not self.wf.agent_mode and r.flag("wait"):
            self.wf.chief_plan(wr["id"])
            d = self.wf.request_detail(wr["id"])
            return 201, {"request": d["request"], "brief": d["brief"], "tasks": d["tasks"]}
        if not self.wf.agent_mode:
            self.wf.chief_plan(wr["id"])
        return 201, dict(wr, hint=RUN_HINT if self.wf.agent_mode else None)

    def post_instruction(self, r):
        b = r.json("target", "text")
        out = self.wf.send_instruction(b["target"], b["text"], b.get("work_request_id"))
        out["hint"] = RUN_HINT if self.wf.agent_mode else None
        return 201, out

    def task_status(self, r):
        b = r.json("status", "note")
        return self.wf.update_task(r.params["tid"], b["status"], b["note"], b.get("author"))

    def hire(self, r):
        b = r.json("name", "role", "reason")
        return 201, self.wf.hire(r.params["did"], b["name"], b["role"], b["reason"], b.get("task_id"))

    def add_department(self, r):
        fields, files = r.form()
        return add_department(self.store, self.kb, files, fields.get("name", ""), fields.get("head_name", ""),
                              fields.get("decision", ""), fields.get("target", ""))

    def replace_department(self, r):
        _, files = r.form()
        return replace_documents(self.store, self.kb, r.params["did"], files)

    def download(self, r):
        """Only files the team built (recorded in the files table) can be downloaded."""
        f = self.store.get_file(r.params["fid"])
        if not os.path.isfile(f["path"]):
            raise HttpError(404, f"The file is no longer on disk: {f['path']}")
        return FileOut(f["path"], f["name"], OFFICE_TYPES.get(f["format"], "application/octet-stream"))

    # ---- dispatch ----
    def match(self, method, path):
        allowed = False
        for rt in self.routes:
            m = rt["re"].match(path)
            if m:
                if rt["method"] == method:
                    return rt, {k: unquote(v) for k, v in m.groupdict().items()}
                allowed = True
        raise HttpError(405 if allowed else 404, "Method not allowed" if allowed else "Not found")


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"FlightSafetyCommand/{VERSION}"

        def log_message(self, fmt, *args):  # quiet; errors still go to stderr via send_error paths
            pass

        def _send(self, status, payload, headers=None):
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            host = (self.headers.get("Host") or "").strip()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            return name in LOCAL_HOSTS

        def _handle(self, method):
            parts = urlsplit(self.path)
            path = parts.path
            query = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
            try:
                if not self._host_ok():
                    raise HttpError(403, "Only local access is allowed")
                if not path.startswith("/api/"):
                    if method != "GET":
                        raise HttpError(405, "Method not allowed")
                    return self._static(path)
                rt, params = app.match(method, path)
                if rt["auth"] and app.token:
                    given = self.headers.get("X-FSA-Token") or query.get("token")
                    if given != app.token:
                        raise HttpError(401, "Missing or wrong dashboard token. Open the link that "
                                             "/flight-safety-agents:start gave you.")
                req = Request(self, path, query, params)
                if rt["stream"]:
                    return self._events(req)
                out = rt["fn"](req)
                if isinstance(out, FileOut):
                    return self._file(out)
                status, payload = out if isinstance(out, tuple) else (200, out)
                self._send(status, payload)
            except HttpError as e:
                self._send(e.status, {"detail": e.detail})
            except StoreError as e:
                self._send(e.status, {"detail": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # never kill the server thread silently
                import traceback
                traceback.print_exc()
                try:
                    self._send(500, {"detail": f"Server error: {e}"})
                except Exception:
                    pass

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _file(self, f):
            with open(f.path, "rb") as fh:
                data = fh.read()
            safe = re.sub(r'[^A-Za-z0-9._-]+', "_", f.name)
            self.send_response(200)
            self.send_header("Content-Type", f.ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _static(self, path):
            root = os.path.realpath(app.web_dir)
            rel = unquote(path).lstrip("/") or "index.html"
            full = os.path.realpath(os.path.join(root, rel))
            if not full.startswith(root + os.sep) or not os.path.isfile(full):
                full = os.path.join(root, "index.html")  # single-page app: the UI routes itself
            if not os.path.isfile(full):
                raise HttpError(503, "The dashboard UI is not built (backend/fsa/web is missing)")
            with open(full, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(data)))
            immutable = "/assets/" in full.replace(os.sep, "/")
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _events(self, req):
            store = app.store
            last = req.q("since_id", None, int)
            if last is None:
                hdr = self.headers.get("Last-Event-ID")
                last = int(hdr) if hdr and hdr.isdigit() else store.last_event_id()
            max_seconds = req.q("max_seconds", None, float)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            cursor, idle, waited = last, 0.0, 0.0
            while True:
                for ev in store.list_events(cursor):
                    cursor = ev["id"]
                    frame = f"id: {ev['id']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
                    self.wfile.write(frame.encode())
                    idle = 0.0
                self.wfile.flush()
                if max_seconds is not None and waited >= max_seconds:
                    return
                time.sleep(0.5)
                idle += 0.5
                waited += 0.5
                if idle >= 15:
                    self.wfile.write(b": keepalive\n\n")
                    idle = 0.0

    return Handler


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(app, host="127.0.0.1", port=4810):
    httpd = DashboardServer((host, port), make_handler(app))
    return httpd
