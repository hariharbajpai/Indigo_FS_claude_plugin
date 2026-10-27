"""Workflow engine: Owner -> Chief brief -> tasks -> Vertical Heads -> report.

Two modes:
  agent_mode=True  (the plugin): the Chief, Vertical Heads and hired agents are Claude Code subagents.
                   They write briefs, update tasks and report through the MCP tools (see loop.py).
  agent_mode=False (offline/tests): a planner turns requests and instructions into briefs and tasks.
"""
import hashlib

from . import CHIEF_ID, SYSTEM_ID
from .planner import default_planner
from .store import Conflict, Invalid, Store

MESSAGE_CAP = 30


class Workflow:
    def __init__(self, store: Store, planner=None, message_cap=MESSAGE_CAP, scope_provider=None,
                 agent_mode=False):
        self.store = store
        self.agent_mode = agent_mode
        self.planner = planner or (None if agent_mode else default_planner())
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

    # ---------- agent mode: the Chief's own brief ----------
    def submit_brief(self, wid, summary, goals=None, tasks=None, change_note=None, block_task_ids=None,
                     question=None, author=CHIEF_ID):
        """The Chief publishes a brief (v1) or a re-plan (v2+). tasks: [{title, description, acceptance, dept}].
        No tasks and a question = no department fits; the Owner is asked. Returns {brief, tasks, blocked}."""
        wr = self.store.get_work_request(wid)
        summary = (summary or "").strip()
        if not summary:
            raise Invalid("A brief needs a summary")
        goals = [str(g).strip() for g in (goals or []) if str(g).strip()]
        tasks = tasks or []
        by_id = {d["id"]: d for d in self._departments()}
        cleaned = []
        for i, t in enumerate(tasks, 1):
            title, dept = str(t.get("title", "")).strip(), str(t.get("dept", "")).strip()
            if not title:
                raise Invalid(f"Task {i} needs a title")
            if dept not in by_id:
                raise Invalid(f"Task {i} ({title}): unknown department '{dept}'. "
                              f"Use one of: {', '.join(by_id) or 'none yet'}")
            cleaned.append((title, dept, str(t.get("description", "")).strip(),
                            str(t.get("acceptance", "")).strip()))
        existing = {t["id"]: t for t in self.store.list_tasks(work_request_id=wid)}
        for tid in block_task_ids or []:
            if tid not in existing:
                raise Invalid(f"{tid} is not a task of {wid}")
        if not cleaned and not question and not existing and not block_task_ids:
            raise Invalid("Give tasks, or a question for the Owner when no department fits")
        self.store.bump_turns(wid)
        blocked = []
        for tid in block_task_ids or []:
            if existing[tid]["status"] not in ("done", "blocked"):
                self.store.set_task_status(tid, "blocked", change_note or "Stopped by the Chief's new brief",
                                           author=author)
                blocked.append(tid)
        prev = self.store.get_brief(wid)
        used = list(prev["departments"]) if prev else []
        for _, dept, _, _ in cleaned:
            if dept not in used:
                used.append(dept)
        brief = self.store.add_brief(wid, summary, goals, used,
                                     needs_department=not used and bool(question),
                                     question=question, change_note=change_note)
        created = []
        for title, dept, desc, acc in cleaned:
            t = self.store.create_task(title, dept, desc, acc, wid)
            self.store.add_message(author, by_id[dept]["head_id"],
                                   f"Task {t['id']} for you: {title}. Acceptance: {acc or 'see description'}",
                                   kind="assign", task_id=t["id"], dept=dept, work_request_id=wid)
            created.append(t)
        lines = [f"Brief v{brief['version']}: {summary}"]
        if change_note:
            lines.append(f"Change: {change_note}")
        if created:
            lines.append("Tasks: " + "; ".join(f"{t['id']} {t['title']} ({by_id[t['dept']]['name']})"
                                               for t in created))
        if blocked:
            lines.append("Blocked: " + ", ".join(blocked))
        self.store.add_message(author, "owner", "\n".join(lines), kind="brief", work_request_id=wid)
        if question:
            self.store.add_message(author, "owner", question, kind="question", work_request_id=wid)
        if wr["status"] == "Received":
            self.store.set_wr_status(wid, "Briefed")
        elif created and wr["status"] == "Done":
            self.store.set_wr_status(wid, "In progress")
        self._refresh_request(wid)
        return {"brief": brief, "tasks": created, "blocked": blocked}

    def report_to_owner(self, wid, text, author=CHIEF_ID):
        self.store.get_work_request(wid)
        if not text or not text.strip():
            raise Invalid("The report needs text")
        m = self.store.add_message(author, "owner", text.strip(), kind="report", work_request_id=wid)
        self.store.add_event("report.posted", {"work_request_id": wid})
        return m

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
                if self.agent_mode:  # the Chief writes the report himself
                    self.store.add_message(
                        SYSTEM_ID, CHIEF_ID,
                        f"All tasks of {wid} are done ({len(tasks)}). Read the task notes and outputs, "
                        "then send the Owner a completion report with report_to_owner.",
                        kind="review", work_request_id=wid)
                else:
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
        if self.agent_mode:  # the agents act on it when the work loop runs
            if dept:
                self.store.add_message("owner", CHIEF_ID, f"(sent to {dept}) {text.strip()}",
                                       kind="instruction", dept=dept, work_request_id=wid)
            return {"message": msg, "brief": None, "blocked_tasks": []}
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
