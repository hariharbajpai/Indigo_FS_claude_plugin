"""Run the dashboard server in the background, one per knowledge base.

State lives in <kb>/_team/dashboard.json (pid, port, token, url) and output in <kb>/_team/dashboard.log.
start() reuses a healthy server of the same version, and replaces an old or dead one.
"""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

from . import VERSION, paths

DEFAULT_PORT = 4810


def _state_file(root):
    return os.path.join(paths.team_dir(root), "dashboard.json")


def _read(root):
    try:
        with open(_state_file(root)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _health(port, timeout=1.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _free_port(start):
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port between {start} and {start + 49}")


def status(root=None):
    root = os.path.abspath(root or paths.kb_root())
    st = _read(root)
    if st and _alive(st.get("pid")):
        h = _health(st.get("port"))
        if h and h.get("ok"):
            return dict(st, running=True, server_version=h.get("version"))
    return {"running": False, "kb_root": root}


def start(root=None, port=None, open_browser=False):
    root = os.path.abspath(root or paths.kb_root())
    st = status(root)
    if st["running"] and st.get("server_version") == VERSION:
        out = dict(st, started=False)
    else:
        if st["running"] or (_read(root) or {}).get("pid"):
            stop(root)
        os.makedirs(paths.team_dir(root), exist_ok=True)
        port = _free_port(port or DEFAULT_PORT)
        token = secrets.token_hex(16)
        env = dict(os.environ, FSA_KB_ROOT=root, FSA_DB=paths.db_path(root), FSA_DASHBOARD_TOKEN=token)
        log_path = os.path.join(paths.team_dir(root), "dashboard.log")
        with open(log_path, "ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", "backend.fsa", "serve", "--port", str(port)],
                                    cwd=paths.PLUGIN_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=log, start_new_session=True)
        for _ in range(60):
            if proc.poll() is not None:
                break
            if _health(port, 0.5):
                break
            time.sleep(0.25)
        if proc.poll() is not None or not _health(port):
            try:
                with open(log_path, errors="replace") as f:
                    tail = "".join(f.readlines()[-8:])
            except OSError:
                tail = ""
            if proc.poll() is None:
                proc.terminate()
            raise RuntimeError(f"The dashboard server did not start. Log ({log_path}):\n{tail}")
        out = {"pid": proc.pid, "port": port, "token": token, "url": f"http://127.0.0.1:{port}/?token={token}",
               "version": VERSION, "kb_root": root,
               "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        with open(_state_file(root), "w") as f:
            json.dump(out, f, indent=2)
        out = dict(out, running=True, started=True)
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(out["url"])
        except Exception:
            pass
    return out


def stop(root=None):
    root = os.path.abspath(root or paths.kb_root())
    st = _read(root)
    stopped = False
    if st and _alive(st.get("pid")):
        try:
            os.kill(int(st["pid"]), signal.SIGTERM)
            for _ in range(40):
                if not _alive(st["pid"]):
                    break
                time.sleep(0.1)
            stopped = True
        except OSError:
            pass
    try:
        os.remove(_state_file(root))
    except OSError:
        pass
    return {"stopped": stopped, "kb_root": root}


def url(root=None):
    st = status(root)
    return st.get("url") if st["running"] else None
