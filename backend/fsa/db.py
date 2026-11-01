"""SQLite connection and schema. One shared connection per process, guarded by a lock."""
import os
import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, head_id TEXT, source TEXT,
  status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agents(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('chief','checker','head','hired')),
  dept TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')),
  reason TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS work_requests(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Received'
    CHECK(status IN ('Received','Briefed','In progress','Done')),
  turns INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS briefs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, work_request_id TEXT NOT NULL, version INTEGER NOT NULL,
  summary TEXT NOT NULL, goals TEXT NOT NULL, departments TEXT NOT NULL,
  needs_department INTEGER NOT NULL DEFAULT 0, question TEXT, change_note TEXT,
  deliverables TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, UNIQUE(work_request_id, version));
CREATE TABLE IF NOT EXISTS tasks(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  acceptance TEXT NOT NULL DEFAULT '', dept TEXT NOT NULL, agent_id TEXT,
  status TEXT NOT NULL DEFAULT 'todo'
    CHECK(status IN ('todo','in_progress','review','blocked','done')),
  work_request_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS task_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, author TEXT,
  status TEXT NOT NULL, note TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL,
  dept TEXT, task_id TEXT, work_request_id TEXT, kind TEXT NOT NULL DEFAULT 'chat',
  body TEXT NOT NULL, ts TEXT NOT NULL, ref TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, ts TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activations(
  id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','done','cancelled')),
  work_request_id TEXT, first_message INTEGER, last_message INTEGER, watermark INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL, ended_at TEXT, report TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT, work_request_id TEXT, task_id TEXT, format TEXT NOT NULL,
  title TEXT NOT NULL, path TEXT NOT NULL UNIQUE, size INTEGER, created_by TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_packs(
  task_id TEXT PRIMARY KEY, work_request_id TEXT, agent_id TEXT, summary TEXT NOT NULL DEFAULT '',
  coverage TEXT NOT NULL DEFAULT 'full', issues TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reads(
  activation TEXT NOT NULL, file TEXT NOT NULL, line INTEGER NOT NULL, ts TEXT NOT NULL,
  PRIMARY KEY(activation, file, line));
CREATE INDEX IF NOT EXISTS ix_pack_wr ON source_packs(work_request_id);
CREATE INDEX IF NOT EXISTS ix_msg_task ON messages(task_id);
CREATE INDEX IF NOT EXISTS ix_msg_recipient ON messages(recipient);
CREATE INDEX IF NOT EXISTS ix_task_wr ON tasks(work_request_id);
CREATE INDEX IF NOT EXISTS ix_act_status ON activations(status);
"""


def default_path():
    from .paths import db_path
    return db_path()


class Database:
    """The MCP server and the dashboard server are separate processes on the same file: WAL mode,
    BEGIN IMMEDIATE for writes and a busy timeout keep them from stepping on each other."""

    def __init__(self, path=None):
        self.path = path or default_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self._depth = 0

    def _migrate(self):
        """Columns added after a table first shipped (databases made by older versions)."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(briefs)")}
        if "deliverables" not in cols:
            self.conn.execute("ALTER TABLE briefs ADD COLUMN deliverables TEXT NOT NULL DEFAULT '[]'")
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(activations)")}
        if "model" not in cols:
            self.conn.execute("ALTER TABLE activations ADD COLUMN model TEXT")
        self._allow_checker_kind()

    def _allow_checker_kind(self):
        """agents.kind used to allow only chief/head/hired; rebuild the table once so the File Checker fits.
        Both server processes may get here at the same time, so the check is repeated inside the write lock."""
        def old():
            sql = self.conn.execute("SELECT sql FROM sqlite_master WHERE name='agents'").fetchone()
            return bool(sql) and "'checker'" not in sql[0]
        if not old():
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if old():
                self.conn.execute("""CREATE TABLE agents_new(
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                  kind TEXT NOT NULL CHECK(kind IN ('chief','checker','head','hired')),
                  dept TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')),
                  reason TEXT, created_at TEXT NOT NULL)""")
                self.conn.execute("INSERT INTO agents_new(id,name,role,kind,dept,status,reason,created_at) "
                                  "SELECT id,name,role,kind,dept,status,reason,created_at FROM agents ORDER BY rowid")
                self.conn.execute("DROP TABLE agents")
                self.conn.execute("ALTER TABLE agents_new RENAME TO agents")
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    @contextmanager
    def tx(self):
        """Single-writer transaction; nested calls join the outer one."""
        with self.lock:
            if self._depth:
                self._depth += 1
                try:
                    yield self.conn
                finally:
                    self._depth -= 1
                return
            self.conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            finally:
                self._depth = 0

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def close(self):
        with self.lock:
            self.conn.close()
