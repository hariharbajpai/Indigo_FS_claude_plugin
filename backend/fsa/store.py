"""Domain store: agents, departments, work requests, briefs, tasks, messages, events."""
import json
import re
from datetime import datetime, timezone

from . import CHIEF_ID, CHIEF_NAME, CHIEF_ROLE, HIRE_CAP, SYSTEM_ID
from .db import Database

TASK_STATUSES = ("todo", "in_progress", "review", "blocked", "done")


class StoreError(Exception):
    status = 400


class NotFound(StoreError):
    status = 404


class Conflict(StoreError):
    status = 409


class Invalid(StoreError):
    status = 400


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "dept"


class Store:
    def __init__(self, path=None):
        self.db = Database(path)
        self.seed_chief()

    def close(self):
        self.db.close()

    # ---------- events / messages ----------
    def add_event(self, type_, data=None):
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO events(type,ts,data) VALUES(?,?,?)",
                            (type_, now(), json.dumps(data or {})))
            return cur.lastrowid

    def list_events(self, since_id=0, limit=500):
        rows = self.db.q("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (since_id, limit))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    def last_event_id(self):
        return self.db.one("SELECT MAX(id) m FROM events")["m"] or 0

    def add_message(self, sender, recipient, body, kind="chat", task_id=None, dept=None,
                    work_request_id=None, ref=None):
        if not body or not str(body).strip():
            raise Invalid("Message body is required")
        with self.db.tx() as c:
            if ref and self.db.one("SELECT id FROM messages WHERE ref=?", (ref,)):
                return None
            if task_id and not work_request_id:
                t = self.db.one("SELECT work_request_id w FROM tasks WHERE seq=?",
                                (self._seq(task_id, "TK"),))
                work_request_id = t["w"] if t else None
            cur = c.execute(
                "INSERT INTO messages(sender,recipient,dept,task_id,work_request_id,kind,body,ts,ref)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (sender, recipient, dept, task_id, work_request_id, kind, body, now(), ref))
            mid = cur.lastrowid
            self.add_event("message.created", {"id": mid, "task_id": task_id, "dept": dept, "kind": kind})
        return self.get_message(mid)

    def _name(self, ident):
        if ident == "owner":
            return "Owner"
        if ident == SYSTEM_ID:
            return "Flight Safety Command"
        a = self.db.one("SELECT name FROM agents WHERE id=?", (ident,))
        return a["name"] if a else ident

    def _msg(self, r):
        r["sender_name"] = self._name(r["sender"])
        r["recipient_name"] = self._name(r["recipient"])
        r.pop("ref", None)
        return r

    def get_message(self, mid):
        r = self.db.one("SELECT * FROM messages WHERE id=?", (mid,))
        return self._msg(r) if r else None

    def list_messages(self, dept=None, agent=None, task=None, work_request_id=None,
                      since_id=0, limit=500, kind=None):
        sql, args = "SELECT * FROM messages WHERE id>?", [since_id]
        if dept:
            sql += (" AND (dept=? OR sender IN (SELECT id FROM agents WHERE dept=?)"
                    " OR recipient IN (SELECT id FROM agents WHERE dept=?))")
            args += [dept, dept, dept]
        if agent:
            sql += " AND (sender=? OR recipient=?)"
            args += [agent, agent]
        if task:
            sql += " AND task_id=?"
            args.append(task)
        if work_request_id:
            sql += " AND work_request_id=?"
            args.append(work_request_id)
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY id LIMIT ?"
        args.append(limit)
        return [self._msg(r) for r in self.db.q(sql, args)]

    def count_task_messages(self, task_id):
        return self.db.one("SELECT COUNT(*) n FROM messages WHERE task_id=?", (task_id,))["n"]

    # ---------- agents ----------
    def seed_chief(self):
        with self.db.tx() as c:
            if self.db.one("SELECT id FROM agents WHERE id=?", (CHIEF_ID,)):
                return
            c.execute("INSERT INTO agents(id,name,role,kind,dept,status,created_at) VALUES(?,?,?,?,?,?,?)",
                      (CHIEF_ID, CHIEF_NAME, CHIEF_ROLE, "chief", None, "active", now()))
            self.add_event("agent.created", {"id": CHIEF_ID})

    def get_agent(self, aid):
        a = self.db.one("SELECT * FROM agents WHERE id=?", (aid,))
        if not a:
            raise NotFound(f"Unknown agent {aid}")
        return a

    def list_agents(self, dept=None, active_only=True):
        sql, args = "SELECT * FROM agents WHERE 1=1", []
        if dept:
            sql += " AND dept=?"
            args.append(dept)
        if active_only:
            sql += " AND status='active'"
        return self.db.q(sql + " ORDER BY rowid", args)

    def _new_agent_id(self):
        n = self.db.one("SELECT COUNT(*) n FROM agents")["n"]
        while self.db.one("SELECT 1 FROM agents WHERE id=?", (f"ag-{n}",)):
            n += 1
        return f"ag-{n}"

    # ---------- names (the Owner can rename anyone) ----------
    @staticmethod
    def clean_name(name, what="name"):
        n = " ".join(str(name or "").split())
        if not n:
            raise Invalid(f"A new {what} is required")
        if len(n) > 80:
            raise Invalid(f"Keep the {what} under 80 characters")
        if n.lower() in ("owner", "system", "flight safety command"):
            raise Invalid(f"'{n}' is reserved; pick another {what}")
        return n

    def rename_agent(self, aid, new_name):
        """Display name only: ids, tasks and history stay. Retired agents keep their name."""
        a = self.get_agent(aid)
        n = self.clean_name(new_name)
        if a["status"] != "active":
            raise Conflict(f"{a['name']} is retired; retired agents keep their name")
        if n == a["name"]:
            return a
        if self.db.one("SELECT id FROM agents WHERE status='active' AND lower(name)=lower(?) AND id!=?", (n, aid)):
            raise Conflict(f"Another agent is already called {n}")
        with self.db.tx() as c:
            c.execute("UPDATE agents SET name=? WHERE id=?", (n, aid))
            self.add_event("agent.renamed", {"id": aid, "old": a["name"], "new": n})
            self.add_message(SYSTEM_ID, aid, f"The Owner renamed {a['name']} to {n}. Use the new name from now on.",
                             kind="note", dept=a["dept"])
        return self.get_agent(aid)

    def rename_department(self, did, new_name):
        """Display name only: the department id (and its knowledge-base folder) stays the same."""
        d = self.get_department(did)
        n = self.clean_name(new_name, "department name")
        if d["status"] != "active":
            raise Conflict(f"Department {d['name']} is retired")
        if n == d["name"]:
            return d
        if self.db.one("SELECT id FROM departments WHERE status='active' AND lower(name)=lower(?) AND id!=?",
                       (n, did)):
            raise Conflict(f"Another department is already called {n}")
        with self.db.tx() as c:
            c.execute("UPDATE departments SET name=? WHERE id=?", (n, did))
            head = self.get_agent(d["head_id"])
            if head["role"].endswith(f", {d['name']}"):
                c.execute("UPDATE agents SET role=? WHERE id=?", (head["role"][: -len(d["name"])] + n, head["id"]))
            self.add_event("department.renamed", {"id": did, "old": d["name"], "new": n})
            self.add_message(SYSTEM_ID, d["head_id"], f"The Owner renamed the department {d['name']} to {n}.",
                             kind="note", dept=did)
        return self.get_department(did)

    def retire_agent(self, aid):
        a = self.get_agent(aid)
        if a["kind"] == "chief":
            raise Conflict("The Chief of Flight Safety cannot be retired")
        if a["kind"] == "head":
            d = self.db.one("SELECT status FROM departments WHERE id=?", (a["dept"],))
            if d and d["status"] == "active":
                raise Conflict("Retire the department to retire its Vertical Head")
        with self.db.tx() as c:
            c.execute("UPDATE agents SET status='retired' WHERE id=?", (aid,))
            self.add_event("agent.retired", {"id": aid})
        return self.get_agent(aid)

    # ---------- departments ----------
    def get_department(self, did):
        d = self.db.one("SELECT * FROM departments WHERE id=?", (did,))
        if not d:
            raise NotFound(f"Unknown department {did}")
        h = self.db.one("SELECT name FROM agents WHERE id=?", (d["head_id"],))
        d["head_name"] = h["name"] if h else None
        return d

    def list_departments(self, include_retired=False):
        sql = "SELECT id FROM departments" + ("" if include_retired else " WHERE status='active'")
        return [self.get_department(r["id"]) for r in self.db.q(sql + " ORDER BY rowid")]

    def next_dept_id(self, name):
        """Id the next department called `name` will get; Conflict if an active one has that name."""
        did = slug((name or "").strip())
        ex = self.db.one("SELECT status FROM departments WHERE id=?", (did,))
        if ex and ex["status"] == "active":
            raise Conflict(f"Department '{name}' already exists")
        if ex:
            n = 2
            while self.db.one("SELECT 1 FROM departments WHERE id=?", (f"{did}-{n}",)):
                n += 1
            did = f"{did}-{n}"
        return did

    def create_department(self, name, head_name, source=None, head_role="Vertical Head"):
        name, head_name = (name or "").strip(), (head_name or "").strip()
        if not name:
            raise Invalid("Department name is required")
        if not head_name:
            raise Invalid("Vertical Head name is required")
        with self.db.tx() as c:
            did = self.next_dept_id(name)
            hid = self._new_agent_id()
            c.execute("INSERT INTO agents(id,name,role,kind,dept,status,created_at) VALUES(?,?,?,?,?,?,?)",
                      (hid, head_name, f"{head_role}, {name}", "head", did, "active", now()))
            c.execute("INSERT INTO departments(id,name,head_id,source,status,created_at) VALUES(?,?,?,?,?,?)",
                      (did, name, hid, source, "active", now()))
            self.add_event("department.created", {"id": did, "head_id": hid})
            self.add_message(CHIEF_ID, hid, f"Welcome {head_name}. You head {name}; "
                             "I will route tasks to you.", kind="note", dept=did)
        return self.get_department(did), self.get_agent(hid)

    def retire_department(self, did):
        d = self.get_department(did)
        if d["status"] == "retired":
            raise Conflict(f"Department {did} is already retired")
        with self.db.tx() as c:
            ids = [a["id"] for a in self.list_agents(dept=did)]
            open_tasks = self.db.q("SELECT seq FROM tasks WHERE dept=? AND status!='done'", (did,))
            for t in open_tasks:
                self.set_task_status(f"TK-{t['seq']}", "blocked", f"Department {d['name']} was retired",
                                     author=CHIEF_ID)
            c.execute("UPDATE agents SET status='retired' WHERE dept=?", (did,))
            c.execute("UPDATE departments SET status='retired' WHERE id=?", (did,))
            self.add_event("department.retired", {"id": did, "retired_agents": ids})
        return self.get_department(did), ids

    def active_count(self, did):
        return self.db.one("SELECT COUNT(*) n FROM agents WHERE dept=? AND status='active'", (did,))["n"]

    def hire_agent(self, dept, name, role, reason, task_id=None, cap=HIRE_CAP):
        d = self.get_department(dept)
        name, role, reason = (name or "").strip(), (role or "").strip(), (reason or "").strip()
        if not (name and role and reason):
            raise Invalid("Hire needs name, role and reason")
        if d["status"] != "active":
            raise Conflict(f"Department {dept} is retired")
        refusal = None
        with self.db.tx() as c:
            if self.active_count(dept) >= cap:
                refusal = (f"Hire refused: {d['name']} already has {cap} active agents (cap). "
                           f"Could not hire {name} as {role}.")
                self.add_message(d["head_id"], CHIEF_ID, refusal, kind="refusal", dept=dept,
                                 task_id=task_id)
                self.add_event("agent.hire_refused", {"dept": dept, "name": name, "cap": cap})
            else:
                aid = self._new_agent_id()
                c.execute("INSERT INTO agents(id,name,role,kind,dept,status,reason,created_at)"
                          " VALUES(?,?,?,?,?,?,?,?)", (aid, name, role, "hired", dept, "active", reason, now()))
                self.add_event("agent.hired", {"id": aid, "dept": dept})
                self.add_message(d["head_id"], CHIEF_ID, f"Hired {name} as {role}. Reason: {reason}",
                                 kind="hire", dept=dept, task_id=task_id)
        if refusal:
            raise Conflict(refusal)
        if task_id:
            self.assign_task(task_id, aid)
        return self.get_agent(aid)

    def org_chart(self, include_retired=False):
        out = []
        for d in self.list_departments(include_retired):
            sql = "SELECT * FROM agents WHERE dept=? AND kind='hired'"
            if not include_retired:
                sql += " AND status='active'"
            out.append({"department": d, "head": self.get_agent(d["head_id"]),
                        "agents": self.db.q(sql + " ORDER BY rowid", (d["id"],)),
                        "active_count": self.active_count(d["id"]), "hire_cap": HIRE_CAP})
        return {"chief": self.get_agent(CHIEF_ID), "departments": out}

    # ---------- work requests / briefs ----------
    @staticmethod
    def _seq(ident, prefix):
        m = re.fullmatch(prefix + r"-(\d+)", str(ident))
        if not m:
            raise NotFound(f"Unknown id {ident}")
        return int(m.group(1))

    def _wr(self, r):
        wid = f"WR-{r['seq']}"
        tasks = self.db.q("SELECT status FROM tasks WHERE work_request_id=?", (wid,))
        done = sum(1 for t in tasks if t["status"] == "done")
        b = self.db.one("SELECT MAX(version) v FROM briefs WHERE work_request_id=?", (wid,))
        return {"id": wid, "text": r["text"], "status": r["status"], "turns": r["turns"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
                "brief_version": b["v"],
                "progress": {"total": len(tasks), "done": done,
                             "percent": int(100 * done / len(tasks)) if tasks else 0}}

    def create_work_request(self, text):
        if not text or not text.strip():
            raise Invalid("Work request text is required")
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO work_requests(text,created_at,updated_at) VALUES(?,?,?)",
                            (text.strip(), now(), now()))
            wid = f"WR-{cur.lastrowid}"
            self.add_event("work_request.created", {"id": wid})
        return self.get_work_request(wid)

    def get_work_request(self, wid):
        r = self.db.one("SELECT * FROM work_requests WHERE seq=?", (self._seq(wid, "WR"),))
        if not r:
            raise NotFound(f"Unknown work request {wid}")
        return self._wr(r)

    def list_work_requests(self):
        return [self._wr(r) for r in self.db.q("SELECT * FROM work_requests ORDER BY seq DESC")]

    def set_wr_status(self, wid, status):
        if self.get_work_request(wid)["status"] == status:
            return self.get_work_request(wid)
        with self.db.tx() as c:
            c.execute("UPDATE work_requests SET status=?, updated_at=? WHERE seq=?",
                      (status, now(), self._seq(wid, "WR")))
            self.add_event("work_request.updated", {"id": wid, "status": status})
        return self.get_work_request(wid)

    def bump_turns(self, wid, n=1):
        with self.db.tx() as c:
            c.execute("UPDATE work_requests SET turns=turns+? WHERE seq=?", (n, self._seq(wid, "WR")))

    def add_brief(self, wid, summary, goals, departments, needs_department=False,
                  question=None, change_note=None, deliverables=None):
        self.get_work_request(wid)
        with self.db.tx() as c:
            v = (self.db.one("SELECT MAX(version) v FROM briefs WHERE work_request_id=?", (wid,))["v"] or 0) + 1
            c.execute("INSERT INTO briefs(work_request_id,version,summary,goals,departments,needs_department,"
                      "question,change_note,deliverables,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (wid, v, summary, json.dumps(goals), json.dumps(departments),
                       int(needs_department), question, change_note, json.dumps(deliverables or []), now()))
            self.add_event("brief.created", {"work_request_id": wid, "version": v})
        return self.get_brief(wid, v)

    @staticmethod
    def _brief(r):
        return {"work_request_id": r["work_request_id"], "version": r["version"], "summary": r["summary"],
                "goals": json.loads(r["goals"]), "departments": json.loads(r["departments"]),
                "needs_department": bool(r["needs_department"]), "question": r["question"],
                "change_note": r["change_note"], "deliverables": json.loads(r.get("deliverables") or "[]"),
                "created_at": r["created_at"]}

    def get_brief(self, wid, version=None):
        if version is None:
            r = self.db.one("SELECT * FROM briefs WHERE work_request_id=? ORDER BY version DESC", (wid,))
        else:
            r = self.db.one("SELECT * FROM briefs WHERE work_request_id=? AND version=?", (wid, version))
        return self._brief(r) if r else None

    def list_briefs(self, wid):
        return [self._brief(r) for r in
                self.db.q("SELECT * FROM briefs WHERE work_request_id=? ORDER BY version", (wid,))]

    # ---------- tasks ----------
    def _task(self, r):
        tid = f"TK-{r['seq']}"
        agent = self.db.one("SELECT name FROM agents WHERE id=?", (r["agent_id"],)) if r["agent_id"] else None
        return {"id": tid, "title": r["title"], "description": r["description"],
                "acceptance": r["acceptance"], "dept": r["dept"], "agent_id": r["agent_id"],
                "agent_name": agent["name"] if agent else None, "status": r["status"],
                "work_request_id": r["work_request_id"], "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "notes": self.db.q("SELECT * FROM task_notes WHERE task_id=? ORDER BY id", (tid,)),
                "message_count": self.count_task_messages(tid)}

    def create_task(self, title, dept, description="", acceptance="", work_request_id=None):
        d = self.get_department(dept)
        if d["status"] != "active":
            raise Conflict(f"Department {dept} is retired")
        if not title or not title.strip():
            raise Invalid("Task title is required")
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO tasks(title,description,acceptance,dept,agent_id,status,"
                            "work_request_id,created_at,updated_at) VALUES(?,?,?,?,?,'todo',?,?,?)",
                            (title.strip(), description, acceptance, dept, d["head_id"],
                             work_request_id, now(), now()))
            tid = f"TK-{cur.lastrowid}"
            self.add_event("task.created", {"id": tid, "dept": dept, "work_request_id": work_request_id})
        return self.get_task(tid)

    def get_task(self, tid):
        r = self.db.one("SELECT * FROM tasks WHERE seq=?", (self._seq(tid, "TK"),))
        if not r:
            raise NotFound(f"Unknown task {tid}")
        return self._task(r)

    def list_tasks(self, status=None, dept=None, work_request_id=None):
        sql, args = "SELECT * FROM tasks WHERE 1=1", []
        for col, val in (("status", status), ("dept", dept), ("work_request_id", work_request_id)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        return [self._task(r) for r in self.db.q(sql + " ORDER BY seq", args)]

    def set_task_status(self, tid, status, note, author=None):
        if status not in TASK_STATUSES:
            raise Invalid(f"Status must be one of {', '.join(TASK_STATUSES)}")
        if not note or not note.strip():
            raise Invalid("A note is required for every status change")
        t = self.get_task(tid)
        author = author or self.get_department(t["dept"])["head_id"]
        with self.db.tx() as c:
            c.execute("UPDATE tasks SET status=?, updated_at=? WHERE seq=?",
                      (status, now(), self._seq(tid, "TK")))
            c.execute("INSERT INTO task_notes(task_id,author,status,note,ts) VALUES(?,?,?,?,?)",
                      (tid, author, status, note.strip(), now()))
            self.add_event("task.updated", {"id": tid, "status": status, "dept": t["dept"],
                                            "work_request_id": t["work_request_id"]})
            if author != CHIEF_ID:  # a blocked task needs the Chief; other changes are for information
                self.add_message(author, CHIEF_ID, f"{tid} -> {status}: {note.strip()}",
                                 kind="blocked" if status == "blocked" else "status",
                                 task_id=tid, dept=t["dept"], work_request_id=t["work_request_id"])
            else:
                self.add_message(author, t["agent_id"] or self.get_department(t["dept"])["head_id"],
                                 f"{tid} -> {status}: {note.strip()}", kind="status", task_id=tid,
                                 dept=t["dept"], work_request_id=t["work_request_id"])
        return self.get_task(tid)

    def assign_task(self, tid, agent_id):
        t = self.get_task(tid)
        a = self.get_agent(agent_id)
        if a["status"] != "active" or a["dept"] != t["dept"]:
            raise Conflict("Agent must be active and in the task's department")
        with self.db.tx() as c:
            c.execute("UPDATE tasks SET agent_id=?, updated_at=? WHERE seq=?",
                      (agent_id, now(), self._seq(tid, "TK")))
            self.add_event("task.updated", {"id": tid, "agent_id": agent_id, "dept": t["dept"]})
            head = self.get_department(t["dept"])["head_id"]
            if agent_id != head:
                self.add_message(head, agent_id, f"Assigned {tid}: {t['title']}", kind="assign",
                                 task_id=tid, dept=t["dept"], work_request_id=t["work_request_id"])
        return self.get_task(tid)

    # ---------- files (PPT / Word / Excel the agents built) ----------
    def add_file(self, path, fmt, title, work_request_id=None, task_id=None, created_by=None, size=None):
        with self.db.tx() as c:
            c.execute("INSERT INTO files(work_request_id,task_id,format,title,path,size,created_by,created_at)"
                      " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET title=excluded.title,"
                      " size=excluded.size, created_by=excluded.created_by, created_at=excluded.created_at",
                      (work_request_id, task_id, fmt, title, path, size, created_by, now()))
            f = self.db.one("SELECT * FROM files WHERE path=?", (path,))
            self.add_event("file.created", {"id": f["id"], "work_request_id": work_request_id, "format": fmt})
        return self._file(f)

    def _file(self, f):
        f["name"] = f["path"].replace("\\", "/").rsplit("/", 1)[-1]
        f["created_by_name"] = self._name(f["created_by"]) if f["created_by"] else None
        return f

    def get_file(self, fid):
        f = self.db.one("SELECT * FROM files WHERE id=?", (int(fid),))
        if not f:
            raise NotFound(f"Unknown file {fid}")
        return self._file(f)

    def list_files(self, work_request_id=None):
        sql, args = "SELECT * FROM files", []
        if work_request_id:
            sql += " WHERE work_request_id=?"
            args.append(work_request_id)
        return [self._file(f) for f in self.db.q(sql + " ORDER BY id", args)]

    # ---------- meta (cursors) ----------
    def get_meta(self, key, default=None):
        r = self.db.one("SELECT value FROM meta WHERE key=?", (key,))
        return r["value"] if r else default

    def set_meta(self, key, value):
        with self.db.tx() as c:
            c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    # ---------- activations (one subagent run) ----------
    def create_activation(self, aid, agent_id, work_request_id, first_message, last_message):
        """watermark = the newest message id when the run started (orders runs against messages)."""
        with self.db.tx() as c:
            c.execute("INSERT INTO activations(id,agent_id,status,work_request_id,first_message,last_message,"
                      "watermark,started_at) VALUES(?,?,'running',?,?,?,?,?)",
                      (aid, agent_id, work_request_id, first_message, last_message, self.last_message_id(), now()))
            self.add_event("activation.started", {"id": aid, "agent_id": agent_id})
        return self.get_activation(aid)

    def get_activation(self, aid):
        a = self.db.one("SELECT * FROM activations WHERE id=?", (aid,))
        if not a:
            raise NotFound(f"Unknown activation {aid}")
        return a

    def list_activations(self, status=None, limit=50):
        sql, args = "SELECT * FROM activations", []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        rows = self.db.q(sql + " ORDER BY started_at DESC, rowid DESC LIMIT ?", args + [limit])
        for r in rows:
            r["agent_name"] = self._name(r["agent_id"])
        return rows

    def end_activation(self, aid, status, report=None):
        with self.db.tx() as c:
            c.execute("UPDATE activations SET status=?, ended_at=?, report=? WHERE id=?",
                      (status, now(), report, aid))
            self.add_event("activation." + status, {"id": aid})
        return self.get_activation(aid)

    def count_activations(self, work_request_id):
        return self.db.one("SELECT COUNT(*) n FROM activations WHERE work_request_id=? AND status!='cancelled'",
                           (work_request_id,))["n"]

    def inbox(self, agent_id, after_id=0):
        rows = self.db.q("SELECT * FROM messages WHERE recipient=? AND id>? AND sender!=? ORDER BY id",
                         (agent_id, after_id, agent_id))
        return [self._msg(r) for r in rows]

    def last_message_id(self):
        return self.db.one("SELECT MAX(id) m FROM messages")["m"] or 0

    # ---------- overview ----------
    def overview(self):
        counts = {s: 0 for s in TASK_STATUSES}
        for r in self.db.q("SELECT status, COUNT(*) n FROM tasks GROUP BY status"):
            counts[r["status"]] = r["n"]
        wrs = self.list_work_requests()
        return {"chief": self.get_agent(CHIEF_ID),
                "counts": {"departments": len(self.list_departments()),
                           "agents": len(self.list_agents()),
                           "work_requests": len(wrs), "tasks": counts,
                           "messages": self.db.one("SELECT COUNT(*) n FROM messages")["n"]},
                "work_requests": wrs, "last_event_id": self.last_event_id()}
