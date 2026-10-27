"""Test helpers: a tiny HTTP client for the stdlib dashboard server, and real test PDFs."""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))  # tests/fixtures.py builds real PDFs
import fixtures  # noqa: E402

HAS_PDFTOTEXT = bool(shutil.which("pdftotext"))
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n"  # looks like a PDF, but has no text
_BASE = {}


def pdf(tag=""):
    """A real, text-extractable PDF; the tag makes the bytes (and SHA-256) differ."""
    if "pdf" not in _BASE:
        d = tempfile.mkdtemp()
        try:
            _BASE["pdf"] = fixtures.make_pdf(__import__("pathlib").Path(d) / "base.pdf").read_bytes()
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return _BASE["pdf"] + b"\n% " + tag.encode()


class Resp:
    def __init__(self, status, headers, body):
        self.status_code, self.headers, self.content = status, headers, body

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)


def multipart(data=None, files=None):
    b = uuid.uuid4().hex
    parts = []
    for k, v in (data or {}).items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for field, (fname, content, ctype) in files or []:
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


class Client:
    def __init__(self, base, token=None):
        self.base, self.token = base, token

    def request(self, method, path, json_body=None, data=None, files=None, headers=None, token=True):
        h = dict(headers or {})
        if token and self.token:
            h.setdefault("X-FSA-Token", self.token)
        body = None
        if json_body is not None:
            body, h["Content-Type"] = json.dumps(json_body).encode(), "application/json"
        elif data is not None or files is not None:
            body, h["Content-Type"] = multipart(data, files)
        elif method == "POST":
            body = b""
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return Resp(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.headers, e.read())

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, json=None, **kw):
        return self.request("POST", path, json_body=json, **kw)


def start_server(test, **app_kwargs):
    """Start App on a free port for one test; cleaned up automatically."""
    from backend.fsa.server import App, serve
    tmp = tempfile.TemporaryDirectory()
    app_kwargs.setdefault("token", "test-token")
    app = App(os.path.join(tmp.name, "fsa.db"), kb_root=os.path.join(tmp.name, "kb"), **app_kwargs)
    app.board_sync_seconds = 0
    httpd = serve(app, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()

    def stop():
        httpd.shutdown()
        httpd.server_close()
        app.close()
        tmp.cleanup()
    test.addCleanup(stop)
    return app, Client(f"http://127.0.0.1:{httpd.server_address[1]}", app_kwargs["token"]), tmp.name
