"""The work loop: which agent runs next and what it is told.

The main Claude Code session is the office manager. It calls next_work, starts one subagent per
activation (all in parallel) and calls activation_done when each one finishes. The agents act
through the MCP tools, passing their activation id. An agent wakes when a message that needs it
arrives (WAKE_KINDS); other messages for it are shown the next time it wakes.
"""
import secrets
from datetime import datetime, timedelta, timezone

from . import CHIEF_ID, HIRE_CAP, PLUGIN
from .store import Conflict, Invalid, NotFound, TASK_STATUSES

WAKE_KINDS = {"request", "instruction", "assign", "chat", "question", "review", "blocked"}
MAX_PARALLEL = 4
BUDGET = 60  # agent runs per work request since the Owner last wrote about it
STALE_MINUTES = 90

AGENT_TYPES = {"chief": f"{PLUGIN}:chief-of-flight-safety", "head": f"{PLUGIN}:vertical-head",
               "hired": f"{PLUGIN}:dept-specialist"}

LOOP_INSTRUCTIONS = (
    "Start one Agent call per activation below, all in this same message so they run in parallel. "
    "Use subagent_type = agent, description = description and prompt = prompt, copied exactly. When each "
    "finishes, call activation_done with its activation_id and the agent's final report, then call "
    "next_work again.")


def _ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Office:
    def __init__(self, store, workflow, kb, dashboard_url=None):
        self.store, self.wf, self.kb = store, workflow, kb
        self.kb_root, self.kb_script = kb.root, kb.kb_script
        self.dashboard_url = dashboard_url or (lambda: None)

    # ---------- cursors ----------
    def cursor(self, key):
        return int(self.store.get_meta(f"cursor:{key}", 0))

    def set_cursor(self, key, value):
        self.store.set_meta(f"cursor:{key}", int(value))

    # ---------- who is due ----------
    def running(self):
        return self.store.list_activations("running", limit=200)

    def due(self):
        busy = {a["agent_id"] for a in self.running()}
        out = []
        for a in self.store.list_agents():  # active agents, the Chief first
            if a["id"] in busy:
                continue
            msgs = self.store.inbox(a["id"], self.cursor(a["id"]))
            if any(m["kind"] in WAKE_KINDS for m in msgs):
                out.append((a, msgs))
        return out

    def _cancel(self, act):
        self.store.end_activation(act["id"], "cancelled", "Cancelled: the run did not finish")
        if act["first_message"]:  # hand the messages back so the next run sees them again
            self.set_cursor(act["agent_id"], act["first_message"] - 1)

    def _over_budget(self, wid):
        last = self.store.db.one("SELECT MAX(id) m FROM messages WHERE sender='owner' AND work_request_id=?",
                                 (wid,))["m"] or 0
        n = self.store.db.one("SELECT COUNT(*) n FROM activations WHERE work_request_id=? AND status!='cancelled'"
                              " AND watermark>=?", (wid, last))["n"]
        return n >= BUDGET

    def _budget_notice(self, wid):
        key = f"budget:{wid}"
        last = self.store.db.one("SELECT MAX(id) m FROM messages WHERE sender='owner' AND work_request_id=?",
                                 (wid,))["m"] or 0
        if self.store.get_meta(key) == str(last):
            return
        self.store.set_meta(key, last)
        self.store.add_message("system", "owner",
                               f"{wid} reached {BUDGET} agent runs since your last message, so the team has paused. "
                               "Send an instruction (/flight-safety-agents:tell) to let it continue.",
                               kind="question", work_request_id=wid)

    # ---------- the loop ----------
    def next_work(self, reset_running=False):
        now = datetime.now(timezone.utc)
        for act in self.running():
            if reset_running or now - _ts(act["started_at"]) > timedelta(minutes=STALE_MINUTES):
                self._cancel(act)
        running, due = self.running(), self.due()
        if not running and not due and not self.store.list_work_requests():
            if not self.store.list_departments():
                return {"status": "no_run", "message":
                        "No departments yet. Add one with /flight-safety-agents:add-dept (department PDFs, "
                        "department name and Vertical Head name), then give the Chief work with "
                        "/flight-safety-agents:work <request>.", "dashboard": self.dashboard_url()}
            return {"status": "no_run", "message": "No work yet. Give the Chief work with "
                    "/flight-safety-agents:work <request>, or from the dashboard.",
                    "dashboard": self.dashboard_url()}
        acts = []
        for agent, msgs in due:
            if len(running) + len(acts) >= MAX_PARALLEL:
                break
            wid = next((m["work_request_id"] for m in reversed(msgs)
                        if m["kind"] in WAKE_KINDS and m["work_request_id"]), None)
            if wid and self._over_budget(wid):
                self._budget_notice(wid)
                continue
            acts.append(self._activate(agent, msgs, wid))
        if acts:
            return {"status": "work", "instructions": LOOP_INSTRUCTIONS, "activations": acts}
        if running:
            return {"status": "busy", "running": [{"activation_id": a["id"], "agent": a["agent_name"],
                                                   "started_at": a["started_at"]} for a in running],
                    "message": f"{len(running)} agent(s) still running. When each returns, call activation_done, "
                               "then next_work. If no agents are running in this session any more (for example "
                               "after a restart), call next_work with reset_running=true."}
        return {"status": "finished", "waitingFor": self._waiting_for(), "message": self._finished_text(),
                "ownerMessages": self._owner_messages(), "dashboard": self.dashboard_url()}

    def _activate(self, agent, msgs, wid):
        aid = "act-" + secrets.token_hex(4)
        self.store.create_activation(aid, agent["id"], wid, msgs[0]["id"], msgs[-1]["id"])
        self.set_cursor(agent["id"], msgs[-1]["id"])
        n = len(msgs)
        return {"activation_id": aid, "agent": AGENT_TYPES[agent["kind"]],
                "description": f"{agent['name']} ({agent['role']}): {n} new message{'s' if n != 1 else ''}",
                "prompt": self.build_prompt(agent, aid, msgs, wid)}

    def activity(self):
        """For the dashboard: who is working, who has work waiting, recent runs."""
        running = self.running()
        busy = {a["agent_id"] for a in running}
        waiting = [{"agent_id": a["id"], "agent_name": a["name"],
                    "messages": sum(1 for m in msgs if m["kind"] in WAKE_KINDS)}
                   for a, msgs in self.due() if a["id"] not in busy]
        recent = [{k: a[k] for k in ("id", "agent_id", "agent_name", "status", "started_at", "ended_at", "report")}
                  for a in self.store.list_activations(limit=12) if a["status"] != "running"][:8]
        return {"running": [{"activation_id": a["id"], "agent_id": a["agent_id"], "agent_name": a["agent_name"],
                             "started_at": a["started_at"]} for a in running],
                "waiting": waiting, "recent": recent}

    def activation_done(self, aid, report):
        act = self.store.get_activation(aid)
        if act["status"] != "running":
            return {"ok": True, "message": f"{aid} was already {act['status']}. Call next_work again."}
        self.store.end_activation(aid, "done", (report or "").strip()[:4000])
        return {"ok": True, "message": "Recorded. Call next_work again."}

    def _owner_messages(self):
        c = self.cursor("owner")
        rows = self.store.db.q("SELECT id FROM messages WHERE recipient='owner' AND id>? ORDER BY id", (c,))
        if not rows:
            return []
        self.set_cursor("owner", rows[-1]["id"])
        out = []
        for r in rows[-15:]:
            m = self.store.get_message(r["id"])
            out.append(f"{m['sender_name']} ({m['kind']}): {m['body']}")
        return out

    def _waiting_for(self):
        q = self.store.db.one("SELECT MAX(id) m FROM messages WHERE recipient='owner' AND kind='question'")["m"] or 0
        o = self.store.db.one("SELECT MAX(id) m FROM messages WHERE sender='owner'")["m"] or 0
        return "owner" if q > o else None

    def _finished_text(self):
        open_wrs = [w for w in self.store.list_work_requests() if w["status"] != "Done"]
        if self._waiting_for():
            return "The team is waiting for the Owner's answer (see ownerMessages)."
        if open_wrs:
            return ("No agent has anything to act on right now. Open work: "
                    + ", ".join(f"{w['id']} ({w['status']})" for w in open_wrs))
        return "All work requests are done."

    # ---------- acting as an agent ----------
    def require(self, aid, kinds=None):
        try:
            act = self.store.get_activation(aid)
        except NotFound:
            raise Conflict(f"Unknown activation {aid}. Stop now.")
        if act["status"] != "running":
            raise Conflict(f"Activation {aid} has ended. Stop now.")
        agent = self.store.get_agent(act["agent_id"])
        if agent["status"] != "active":
            raise Conflict(f"{agent['name']} no longer works here. Stop now.")
        if kinds and agent["kind"] not in kinds:
            raise Conflict(f"{agent['name']} ({agent['kind']}) cannot use this tool.")
        return act, agent

    def _task_for(self, agent, tid):
        t = self.store.get_task(tid)
        if agent["kind"] == "head" and t["dept"] != agent["dept"]:
            raise Conflict(f"{tid} belongs to {t['dept']}, not your department")
        if agent["kind"] == "hired" and t["agent_id"] != agent["id"]:
            raise Conflict(f"{tid} is not assigned to you")
        return t

    def tool_briefing(self, aid):
        act, agent = self.require(aid)
        return {"context": self.build_prompt(agent, aid, [], act["work_request_id"], briefing_only=True)}

    def tool_submit_brief(self, aid, work_request_id, summary, goals=None, tasks=None, change_note=None,
                          block_task_ids=None, question=None):
        self.require(aid, ("chief",))
        r = self.wf.submit_brief(work_request_id, summary, goals, tasks, change_note, block_task_ids, question)
        return {"brief_version": r["brief"]["version"],
                "tasks_created": [{"id": t["id"], "title": t["title"], "dept": t["dept"]} for t in r["tasks"]],
                "blocked": r["blocked"]}

    def tool_report(self, aid, work_request_id, text):
        self.require(aid, ("chief",))
        m = self.wf.report_to_owner(work_request_id, text)
        return {"ok": True, "message_id": m["id"]}

    def tool_send_message(self, aid, to, text, task_id=None, work_request_id=None):
        act, agent = self.require(aid)
        to = (to or "").strip()
        if to.lower() == "owner":
            recipient = "owner"
        elif to.lower() == "chief":
            recipient = CHIEF_ID
        else:
            try:
                recipient = self.store.get_agent(to)["id"]
            except NotFound:
                try:
                    recipient = self.store.get_department(to)["head_id"]
                except NotFound:
                    raise Invalid(f"Unknown recipient '{to}'. Use owner, chief, an agent id or a department id.")
        if recipient == agent["id"]:
            raise Invalid("You cannot message yourself")
        kind = "question" if recipient == "owner" else "chat"
        if task_id:
            m = self.wf.post_task_message(agent["id"], recipient, task_id, text, kind=kind)
        else:
            m = self.store.add_message(agent["id"], recipient, text, kind=kind, dept=agent["dept"],
                                       work_request_id=work_request_id or act["work_request_id"])
        return {"ok": True, "message_id": m["id"], "to": m["recipient_name"]}

    def tool_update_task(self, aid, task_id, status, note):
        _, agent = self.require(aid, ("head", "hired"))
        self._task_for(agent, task_id)
        if status not in TASK_STATUSES:
            raise Invalid(f"status must be one of {', '.join(TASK_STATUSES)}")
        t = self.wf.update_task(task_id, status, note, author=agent["id"])
        return {"id": t["id"], "status": t["status"]}

    def tool_hire(self, aid, name, role, reason, task_id=None):
        _, agent = self.require(aid, ("head",))
        if task_id:
            self._task_for(agent, task_id)
        a = self.wf.hire(agent["dept"], name, role, reason, task_id)
        return {"id": a["id"], "name": a["name"], "role": a["role"], "assigned": task_id,
                "active_in_department": self.store.active_count(agent["dept"]), "cap": HIRE_CAP}

    def tool_search(self, aid, query, dept=None, top=8):
        _, agent = self.require(aid)
        if dept:
            depts = [dept]
        elif agent["kind"] == "chief":
            depts = None  # everything
        else:
            depts = [agent["dept"], "shared"]
        return {"results": self.kb.search(query, depts, min(max(int(top or 8), 1), 20))}

    def tool_read(self, aid, file):
        self.require(aid)
        return self.kb.read_file(file)

    def tool_save_output(self, aid, task_id, title, content):
        act, agent = self.require(aid)
        if task_id.startswith("WR-"):
            if agent["kind"] != "chief":
                raise Conflict("Only the Chief saves work-request level outputs; use a task id")
            folder = self.store.get_work_request(task_id)["id"]
            name = f"{task_id}-{title}"
        else:
            t = self.store.get_task(task_id) if agent["kind"] == "chief" else self._task_for(agent, task_id)
            folder = t["work_request_id"] or "general"
            name = f"{t['id']}-{title}"
        path = self.kb.save_output(folder, name, content)
        self.store.add_event("output.saved", {"path": path, "task_id": task_id, "agent_id": agent["id"]})
        return {"path": path}

    def tool_assign(self, aid, task_id, agent_id):
        _, agent = self.require(aid, ("head",))
        self._task_for(agent, task_id)
        t = self.store.assign_task(task_id, agent_id)
        return {"id": t["id"], "agent_id": t["agent_id"], "agent_name": t["agent_name"]}

    # ---------- what an agent is told ----------
    def _docs(self, dept):
        return self.kb.list_docs(dept)

    def _team_lines(self):
        lines = [f"- Dhruv Rebbapragada, Chief of Flight Safety: id \"{CHIEF_ID}\", reports to the Owner"]
        for row in self.store.org_chart()["departments"]:
            d, h = row["department"], row["head"]
            lines.append(f"- {h['name']}, Vertical Head of {d['name']}: id \"{h['id']}\", department id "
                         f"\"{d['id']}\", reports to the Chief")
            for a in row["agents"]:
                lines.append(f"  - {a['name']}, {a['role']}: id \"{a['id']}\", reports to {h['name']}")
        return lines

    def _task_line(self, t):
        who = t["agent_name"] or t["dept"]
        last = t["notes"][-1]["note"] if t["notes"] else ""
        s = f"- {t['id']} [{t['status']}] {t['title']} (dept {t['dept']}, owner {who})"
        if t["acceptance"]:
            s += f"\n  Acceptance: {t['acceptance']}"
        if t["description"]:
            s += f"\n  Details: {t['description']}"
        if last:
            s += f"\n  Last note: {last}"
        return s

    def _request_block(self, wid, tasks_filter=None):
        wr = self.store.get_work_request(wid)
        b = self.store.get_brief(wid)
        lines = [f"### {wid} ({wr['status']})", f"Owner's request: {wr['text']}"]
        if b:
            lines.append(f"Brief v{b['version']}: {b['summary']}")
            for g in b["goals"]:
                lines.append(f"  Goal: {g}")
            if b["change_note"]:
                lines.append(f"  Last change: {b['change_note']}")
        else:
            lines.append("No brief yet.")
        tasks = [t for t in self.store.list_tasks(work_request_id=wid) if not tasks_filter or tasks_filter(t)]
        if tasks:
            lines.append("Tasks:")
            lines += [self._task_line(t) for t in tasks]
        return lines

    def build_prompt(self, agent, aid, msgs, wid, briefing_only=False):
        kind = agent["kind"]
        dept = self.store.get_department(agent["dept"]) if agent["dept"] else None
        out = []
        if not briefing_only:
            out += [f"You are {agent['name']}, {agent['role']} in Flight Safety Command (agent id \"{agent['id']}\").",
                    "",
                    f"Your activation id is {aid}. Pass it as the `activation` argument in every Flight Safety "
                    "Command tool call.", ""]
        out += ["## Team", "- The Owner: the flight-safety manager, the only human. Speaks English or Hinglish."]
        out += self._team_lines()
        out += ["", "## Knowledge base (the department manuals)",
                "search_manuals finds sections (department, document, revision, section, page, file); read_section "
                "reads a whole section file. Work from what the manuals say, cite document, section and page, and "
                "say so plainly when the manuals do not cover something. Never invent manual content.",
                "save_output saves a report or other longer result as markdown and returns its path; put that path "
                "in your task note."]
        if kind == "chief":
            for d in self.store.list_departments():
                docs = self._docs(d["id"])
                out.append(f"- {d['name']} (department id {d['id']}): " + (", ".join(docs) if docs else "no documents yet"))
        elif dept:
            docs = self._docs(dept["id"])
            out.append(f"- Your department {dept['name']} (department id {dept['id']}): "
                       + (", ".join(docs) if docs else "no documents yet"))
        out += ["", "## Work"]
        if kind == "chief":
            wids = [w["id"] for w in self.store.list_work_requests() if w["status"] != "Done"]
            if wid and wid not in wids:
                wids.insert(0, wid)
            for w in wids[:6]:
                out += self._request_block(w)
            if not wids:
                out.append("No open work requests.")
        else:
            mine = (lambda t: t["dept"] == agent["dept"]) if kind == "head" else (lambda t: t["agent_id"] == agent["id"])
            wids = sorted({t["work_request_id"] for t in self.store.list_tasks() if mine(t) and t["work_request_id"]
                           and t["status"] != "done"} | ({wid} if wid else set()))
            for w in wids[:6]:
                out += self._request_block(w, mine)
            if not wids:
                out.append("You have no open tasks.")
        if not briefing_only:
            out += ["", f"## New messages ({len(msgs)})"]
            for i, m in enumerate(msgs, 1):
                tag = f" · task {m['task_id']}" if m["task_id"] else ""
                out += [f"--- Message {i} · from {m['sender_name']} · {m['kind']}{tag} · {m['ts']} ---", m["body"]]
            out += ["", "## What to do now"] + ROLE_GUIDE[kind] + ["", RULES]
        return "\n".join(out)


ROLE_GUIDE = {
    "chief": [
        "You lead. You plan and coordinate; the departments do the work.",
        "1. A work request with no brief: check what each department's manuals cover (search_manuals), then call "
        "submit_brief with a "
        "short summary, goals and tasks. Each task has exactly one department (dept = department id), a clear title, "
        "details and acceptance criteria. Split work that needs two departments into two tasks.",
        "2. No department fits: call submit_brief with no tasks and a question asking the Owner which department to "
        "add (its PDFs and Vertical Head name). Never guess.",
        "3. An Owner instruction: re-plan with submit_brief: a change_note, block_task_ids for tasks that conflict "
        "with it, and any new tasks. If it changes nothing, say so with send_message to the Owner.",
        "4. A blocked task or a question from a Head: answer with send_message, or re-plan.",
        "5. A review message (all tasks done): read the task notes and their output files (read_section), then call "
        "report_to_owner with the outcome of each task and the output paths. Keep it short and factual.",
    ],
    "head": [
        "You run your department. For each new task:",
        "1. update_task to in_progress with a short note.",
        "2. Do it yourself from your department's manuals, or hire a specialist with hire_agent (name, role, reason, "
        f"task_id) when it needs a separate skill or parallel work. At most {HIRE_CAP} active agents per department, "
        "you included. A hire with task_id also assigns the task; the specialist then does it and reports.",
        "3. When finished: save_output, then update_task to done with a note that sums up the result and gives the "
        "output path. Blocked or unclear: update_task to blocked with the reason, or ask with send_message.",
        "Answer messages addressed to you. Don't redo work a specialist already marked done.",
    ],
    "hired": [
        "You are a specialist hired for specific tasks. For each task assigned to you:",
        "1. update_task to in_progress with a short note.",
        "2. Do the work from your department's manuals (search_manuals, read_section) and save_output.",
        "3. update_task to done with a note that sums up the result and gives the output path, or to blocked with "
        "the reason. Ask your Vertical Head with send_message if something is unclear.",
    ],
}

RULES = ("Rules: act only through the Flight Safety Command tools. Every status change needs "
         "a note. Only send a message when someone must act on it or needs the answer; no thanks or "
         "acknowledgements. Never claim work is done unless it is. If a tool says the activation has ended, stop "
         "at once. When you are done, end with a report of one to three lines saying what you did.")
