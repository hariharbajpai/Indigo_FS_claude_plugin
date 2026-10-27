"""Where things live.

KB root (department manuals, the team database, dashboard state), first match wins:
  $FSA_KB_ROOT, $SAFETY_KB_DIR, $CLAUDE_PROJECT_DIR/safety-kb, ./safety-kb
The database is <kb>/_team/fsa.db unless $FSA_DB is set. Never inside the plugin folder.
"""
import os

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KB_SCRIPT = os.path.join(PLUGIN_ROOT, "skills", "safety-kb", "scripts", "kb.py")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def kb_root():
    for var in ("FSA_KB_ROOT", "SAFETY_KB_DIR"):
        if os.environ.get(var):
            return os.path.abspath(os.environ[var])
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return os.path.join(os.path.abspath(os.environ["CLAUDE_PROJECT_DIR"]), "safety-kb")
    return os.path.join(os.getcwd(), "safety-kb")


def team_dir(root=None):
    return os.path.join(root or kb_root(), "_team")


def db_path(root=None):
    if os.environ.get("FSA_DB") and root is None:
        return os.path.abspath(os.environ["FSA_DB"])
    return os.path.join(team_dir(root), "fsa.db")


def kb_script():
    return os.path.abspath(os.environ.get("FSA_KB_SCRIPT") or KB_SCRIPT)
