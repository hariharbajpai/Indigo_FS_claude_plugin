"""Workflow engine: Owner -> Chief brief -> tasks -> Vertical Heads -> report."""
import hashlib

from . import CHIEF_ID
from .planner import default_planner
from .store import Conflict, Invalid, Store

MESSAGE_CAP = 30


class Workflow:
    def __init__(self, store: Store, planner=None, message_cap=MESSAGE_CAP, scope_provider=None):
        self.store = store
        self.planner = planner or default_planner()
        self.message_cap = message_cap
        self.scope_provider = scope_provider  # optional: dept id -> keyword text (from the PDF)

    # ---------- helpers ----------
    def _departments(self):
        out = []
        for d in self.store.list_departments():
            kw = self.scope_provider(d["id"]) if self.scope_provider else ""
            out.append({"id": d["id"], "name": d["name"], "head_name": d["head_name"],
                        "head_id": d["head_id"], "keywords": kw or ""})
        return out

    def _latest_open_request(self):
        for w in self.store.list_work_requests():  # newest first
            if w["status"] != "Done":
                return w["id"]
        rows = self.store.list_work_requests()
        return rows[0]["id"] if rows else None

    # ---------- US3 / US4 ----------
    def submit_work_request(self, text):
        wr = self.store.create_work_request(text)
        self.store.add_message("owner", CHIEF_ID, wr["text"], kind="request", work_request_id=wr["id"])
        return wr

    def chief_plan(self, wid):
        wr = self.store.get_work_request(wid)
        if self.store.get_brief(wid):
            return self.store.get_brief(wid)  # already briefed
        depts = self._departments()
        plan = self.planner.plan(wr["text"], depts)
        self.store.bump_turns(wid)
        by_id = {d["id"]: d for d in depts}
        used = []
        for pt in plan.tasks:
            if pt.dept in by_id and pt.dept not in used:
                used.append(pt.dept)
        brief = self.store.add_brief(wid, plan.summary, plan.goals, used,
                                     needs_department=plan.needs_department or not used,
                                     question=plan.question)
        if not used:
            q = plan.question or "No department matches. Which department should I add?"
            self.store.add_message(CHIEF_ID, "owner", f"Brief v{brief['version']}: {plan.summary}\n{q}",
                                   kind="brief", work_request_id=wid)
            self.store.set_wr_status(wid, "Briefed")
            return brief
        self.store.add_message(CHIEF_ID, "owner",
                               f"Brief v{brief['version']}: {plan.summary} "
                               f"Departments: {', '.join(by_id[u]['name'] for u in used)}.",
                               kind="brief", work_request_id=wid)
        for pt in plan.tasks:
            if pt.dept in by_id:
                self._create_task(wid, pt, by_id[pt.dept])
        self.store.set_wr_status(wid, "Briefed")
        return brief

    def _create_task(self, wid, pt, dept):
        t = self.store.create_task(pt.title, pt.dept, pt.description, pt.acceptance, wid)
        self.store.add_message(CHIEF_ID, dept["head_id"],
                               f"Task {t['id']} for you: {t['title']}. Acceptance: {t['acceptance']}",
                               kind="assign", task_id=t["id"], dept=pt.dept, work_request_id=wid)
        return t

    def request_detail(self, wid):
        wr = self.store.get_work_request(wid)
        reports = self.store.list_messages(work_request_id=wid, kind="report")
        return {"request": wr, "briefs": self.store.list_briefs(wid), "brief": self.store.get_brief(wid),
                "tasks": self.store.list_tasks(work_request_id=wid),
                "report": reports[-1] if reports else None}

    # ---------- US5 ----------
    def update_task(self, tid, status, note, author=None):
        t = self.store.get_task(tid)
        if t["status"] == status and status == "done":
            raise Conflict(f"{tid} is already done")
        wid = t["work_request_id"]
        if wid:
            self.store.bump_turns(wid)
        t = self.store.set_task_status(tid, status, note, author)
        if wid:
            self._refresh_request(wid)
        return t

    def _refresh_request(self, wid):
        tasks = self.store.list_tasks(work_request_id=wid)
        if not tasks:
            return
        if all(t["status"] == "done" for t in tasks):
            if self.store.get_work_request(wid)["status"] != "Done":
                self.store.set_wr_status(wid, "Done")
                self._report(wid, tasks)
        elif any(t["status"] != "todo" for t in tasks):
            if self.store.get_work_request(wid)["status"] in ("Briefed", "Done"):
                self.store.set_wr_status(wid, "In progress")

    def _report(self, wid, tasks):
        lines = []
        for t in tasks:
            last = t["notes"][-1]["note"] if t["notes"] else "completed"
            who = t["agent_name"] or t["dept"]
            lines.append(f"- {t['id']} {t['title']} ({who}): {last}")
        wr = self.store.get_work_request(wid)
        body = (f"Completion report for {wid} (brief v{wr['brief_version']}). All {len(tasks)} tasks done.\n"
                + "\n".join(lines))
        self.store.add_message(CHIEF_ID, "owner", body, kind="report", work_request_id=wid)
        self.store.add_event("report.posted", {"work_request_id": wid})

    # ---------- US6 ----------
    def hire(self, dept, name, role, reason, task_id=None):
        return self.store.hire_agent(dept, name, role, reason, task_id)

    # ---------- US7: capped agent chat ----------
    def post_task_message(self, sender, recipient, task_id, body, kind="chat"):
        t = self.store.get_task(task_id)
        if self.store.count_task_messages(task_id) >= self.message_cap:
            raise Conflict(f"Message cap of {self.message_cap} reached for {task_id}")
        if t["work_request_id"]:
            self.store.bump_turns(t["work_request_id"])
        return self.store.add_message(sender, recipient, body, kind=kind, task_id=task_id,
                                      dept=t["dept"], work_request_id=t["work_request_id"])

    # ---------- US8 ----------
    def send_instruction(self, target, text, work_request_id=None):
        if not text or not text.strip():
            raise Invalid("Instruction text is required")
        if target == "chief":
            recipient, dept = CHIEF_ID, None
        else:
            d = self.store.get_department(target)
            if d["status"] != "active":
                raise Conflict(f"Department {target} is retired")
            recipient, dept = d["head_id"], target
        wid = work_request_id or self._latest_open_request()
        if work_request_id:
            self.store.get_work_request(work_request_id)
        msg = self.store.add_message("owner", recipient, text.strip(), kind="instruction",
                                     dept=dept, work_request_id=wid)
        if dept:  # the Chief is told so the plan stays consistent
            self.store.add_message(recipient, CHIEF_ID,
                                   f"Owner instructed {dept}: {text.strip()}", kind="chat",
                                   dept=dept, work_request_id=wid)
        brief, blocked = None, []
        if wid and self.store.get_brief(wid):
            brief, blocked = self._replan(wid, text.strip())
        else:
            self.store.add_message(CHIEF_ID, "owner",
                                   "Noted your instruction. There is no briefed work request to update yet.",
                                   kind="chat", work_request_id=wid)
        return {"message": msg, "brief": brief, "blocked_tasks": blocked}

    def _replan(self, wid, instruction):
        wr = self.store.get_work_request(wid)
        tasks = self.store.list_tasks(work_request_id=wid)
        depts = self._departments()
        by_id = {d["id"]: d for d in depts}
        rp = self.planner.replan(wr["text"], instruction, depts, tasks)
        self.store.bump_turns(wid)
        blocked = []
        for tid in rp.conflicting_task_ids:
            t = self.store.get_task(tid)
            if t["status"] not in ("done", "blocked"):
                self.store.set_task_status(tid, "blocked",
                                           f"Conflicts with Owner instruction: {instruction[:150]}",
                                           author=CHIEF_ID)
                blocked.append(tid)
        new = [self._create_task(wid, pt, by_id[pt.dept]) for pt in rp.new_tasks if pt.dept in by_id]
        prev = self.store.get_brief(wid)
        used = sorted(set(prev["departments"]) | {t["dept"] for t in new})
        brief = self.store.add_brief(wid, rp.summary, rp.goals, used,
                                     needs_department=False, change_note=rp.change_note)
        detail = []
        if blocked:
            detail.append("blocked " + ", ".join(blocked))
        if new:
            detail.append("added " + ", ".join(t["id"] for t in new))
        self.store.add_message(CHIEF_ID, "owner",
                               f"Brief updated to v{brief['version']}"
                               + (f" ({'; '.join(detail)})" if detail else " (no task changes)"),
                               kind="brief", work_request_id=wid)
        if new and self.store.get_work_request(wid)["status"] == "Done":
            self.store.set_wr_status(wid, "In progress")
        elif self.store.get_work_request(wid)["status"] == "Received":
            self.store.set_wr_status(wid, "Briefed")
        self._refresh_request(wid)
        return brief, blocked

    # ---------- inter-department board mirror ----------
    def sync_board(self, entries):
        """entries: [{id?, from, to, text, ts?}] read from `kb.py board`. Idempotent. Returns count added."""
        added = 0
        by_key = {}
        for d in self.store.list_departments(include_retired=True):
            by_key[d["id"]] = d
            by_key[d["name"].lower()] = d

        def resolve(x):
            d = by_key.get(str(x).strip().lower()) or by_key.get(str(x).strip().lower().replace(" ", "-"))
            return (d["head_id"], d["id"]) if d else (str(x), None)

        for e in entries:
            body = str(e.get("text", "")).strip()
            if not body:
                continue
            raw = f"{e.get('id', '')}|{e.get('from')}|{e.get('to')}|{e.get('ts', '')}|{body}"
            ref = "board:" + hashlib.sha1(raw.encode()).hexdigest()[:16]
            s, sd = resolve(e.get("from", "unknown"))
            r, rd = resolve(e.get("to", "unknown"))
            if self.store.add_message(s, r, body, kind="board", dept=sd or rd, ref=ref):
                added += 1
        return added
