"""The work loop: which agent runs next and what it is told.

The main Claude Code session is the office manager. It calls next_work, starts one subagent per
activation (all in parallel) and calls activation_done when each one finishes. The agents act
through the MCP tools, passing their activation id. An agent wakes when a message that needs it
arrives (WAKE_KINDS); other messages for it are shown the next time it wakes.
"""
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import CHECKER_ID, CHIEF_ID, HIRE_CAP, MODEL_CHOICES, MODEL_ROLES, PLUGIN, SYSTEM_ID, office
from .store import Conflict, Invalid, NotFound, TASK_STATUSES
from .workflow import FORMAT_NAMES

WAKE_KINDS = {"request", "instruction", "assign", "chat", "question", "review", "blocked", "check"}
MAX_PARALLEL = 4
BUDGET = 60  # agent runs per work request since the Owner last wrote about it
STALE_MINUTES = 90

AGENT_TYPES = {"chief": f"{PLUGIN}:chief-of-flight-safety", "checker": f"{PLUGIN}:file-checker",
               "head": f"{PLUGIN}:vertical-head", "hired": f"{PLUGIN}:dept-specialist"}

MAX_CHECK_TRIES = 2         # times the File Checker is asked again before the departments start without its pack
MAX_PACK_SOURCES = 8        # sections per task in a source pack
PACK_PROMPT_CHARS = 12000   # how much of a task's pack goes into the Head's prompt (the rest is a pointer)
LINK_TEXT_CHARS = 1500

MODEL_INFO = {
    "inherit": "Same Claude as your Claude Code session",
    "haiku": "Fastest and cheapest. Fine for simple look-ups; weakest on long manuals.",
    "sonnet": "Balanced speed and quality. A good default for the departments.",
    "opus": "Strongest reasoning. Slowest and uses the most of your plan; best for planning and documentation checks.",
}
MODEL_PRESETS = {
    "recommended": {"label": "Recommended", "roles": {"chief": "opus", "checker": "opus", "head": "sonnet", "hired": "sonnet"},
                    "note": "The Chief and the File Checker (planning and documentation) on Opus, the departments on Sonnet."},
    "best": {"label": "Best quality", "roles": {"chief": "opus", "checker": "opus", "head": "opus", "hired": "opus"},
             "note": "Everyone on Opus. Highest quality, slowest, uses the most of your plan."},
    "economy": {"label": "Economy", "roles": {"chief": "sonnet", "checker": "sonnet", "head": "sonnet", "hired": "haiku"},
                "note": "Sonnet for the leads, Haiku for hired specialists. Faster and lighter."},
    "inherit": {"label": "Same as my session", "roles": {r: "inherit" for r in MODEL_ROLES},
                "note": "Every agent uses whatever model your Claude Code session uses."},
}

LOOP_INSTRUCTIONS = (
    "Start one Agent call per activation below, all in this same message so they run in parallel. "
    "Use subagent_type = agent, description = description and prompt = prompt, copied exactly. If an "
    "activation has a model, pass it as the Agent call's model. When each "
    "finishes, call activation_done with its activation_id and the agent's final report, then call "
    "next_work again.")


FORMAT_HINTS = (("pptx", r"\b(ppt|pptx|powerpoint|presentation|slides?|deck)\b"),
                ("docx", r"\b(word|docx|doc file|document)\b"),
                ("xlsx", r"\b(excel|xlsx|spreadsheet|sheet|workbook)\b"))


def wanted_formats(text):
    """Formats the Owner's words point at (a hint for the Chief, not a decision)."""
    t = (text or "").lower()
    return [f for f, rx in FORMAT_HINTS if re.search(rx, t)]


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
    # ---------- which Claude each kind of agent uses ----------
    def model_for(self, kind):
        """The model alias to run `kind` on, or None to inherit the session's."""
        v = self.store.get_meta(f"model:{kind}", "inherit")
        return v if v in MODEL_CHOICES and v != "inherit" else None

    def models(self):
        session = self.store.get_meta("session_model")
        roles = {}
        for kind in MODEL_ROLES:
            setting = self.store.get_meta(f"model:{kind}", "inherit")
            if setting not in MODEL_CHOICES:
                setting = "inherit"
            roles[kind] = {"setting": setting,
                           "effective": setting if setting != "inherit" else (session or "session model (not reported yet)")}
        current = {k: v["setting"] for k, v in roles.items()}
        preset = next((n for n, p in MODEL_PRESETS.items() if p["roles"] == current), None)
        low = (session or "").lower()
        if all(v == "inherit" for v in current.values()):
            if "haiku" in low or "sonnet" in low:
                hint = (f"Your session runs {session}. The agents use the same model. To upgrade, pick Recommended or "
                        "Best quality: the agents then run on Opus even while your session stays as it is.")
            elif "opus" in low:
                hint = f"Your session runs {session} and every agent uses it."
            else:
                hint = "Every agent uses your session's model. Pick a preset to choose a stronger or a lighter one."
        else:
            hint = ("Settings apply to the next run. Opus, Sonnet and Haiku always mean the newest version your "
                    "Claude plan offers. If a run fails with a model error, set that role back to 'inherit'.")
        return {"session_model": session, "session_reported_at": self.store.get_meta("session_model_at"),
                "roles": roles, "preset": preset, "hint": hint,
                "options": [{"id": k, "note": v} for k, v in MODEL_INFO.items()],
                "presets": [{"id": k, "label": v["label"], "note": v["note"], "roles": v["roles"]}
                            for k, v in MODEL_PRESETS.items()]}

    def set_models(self, roles=None, preset=None):
        """Owner: choose the model per kind of agent (chief, checker, head, hired), or a whole preset."""
        chosen = {}
        if preset:
            if preset not in MODEL_PRESETS:
                raise Invalid(f"preset must be one of: {', '.join(MODEL_PRESETS)}")
            chosen.update(MODEL_PRESETS[preset]["roles"])
        for kind, value in (roles or {}).items():
            kind, value = str(kind).strip().lower(), str(value).strip().lower()
            if kind == "all":
                chosen.update({r: value for r in MODEL_ROLES})
                continue
            if kind not in MODEL_ROLES:
                raise Invalid(f"unknown role '{kind}'. Use: {', '.join(MODEL_ROLES)} or all")
            chosen[kind] = value
        if not chosen:
            raise Invalid("Give a preset or at least one role")
        for kind, value in chosen.items():
            if value not in MODEL_CHOICES:
                raise Invalid(f"model for {kind} must be one of: {', '.join(MODEL_CHOICES)}")
        for kind, value in chosen.items():
            self.store.set_meta(f"model:{kind}", value)
        self.store.add_event("models.changed", chosen)
        return self.models()

    def _checker_nudge(self):
        """Tasks still waiting for a source pack although the File Checker has nothing new to act on (its run ended
        without delivering): ask again, up to MAX_CHECK_TRIES times; then release them without a pack (coverage
        none, flagged), so the work never stalls on a documentation step."""
        if not self.store.checker_active() or any(a["agent_id"] == CHECKER_ID for a in self.running()):
            return
        waiting = self.store.tasks_awaiting_pack()
        if not waiting or any(m["kind"] in WAKE_KINDS for m in self.store.inbox(CHECKER_ID, self.cursor(CHECKER_ID))):
            return
        tries = int(self.store.get_meta("checker_tries", 0))
        if tries < MAX_CHECK_TRIES:
            self.store.set_meta("checker_tries", tries + 1)
            self.store.add_message(SYSTEM_ID, CHECKER_ID,
                                   "Still waiting for a source pack for: " + ", ".join(t["id"] for t in waiting)
                                   + ". Search the manuals and call submit_source_pack for each of them "
                                   "(coverage none, with `issues`, if the manuals do not cover a task).",
                                   kind="check", work_request_id=waiting[0]["work_request_id"])
            return
        for t in waiting:
            issue = ("The File Checker did not deliver a source pack for this task. Search the manuals yourself "
                     "and say which sections you used.")
            pack, _ = self.store.save_source_pack(t["id"], CHECKER_ID, "", "none", [issue], [])
            self.wf.release_task(t["id"], pack)
        self.store.set_meta("checker_tries", 0)
        self.store.add_message(SYSTEM_ID, "owner", "The File Checker did not deliver source packs for "
                               + ", ".join(t["id"] for t in waiting) + ", so the departments start without them.",
                               kind="note", work_request_id=waiting[0]["work_request_id"])

    def next_work(self, reset_running=False, session_model=None):
        if session_model and str(session_model).strip():
            sm = " ".join(str(session_model).split())[:80]
            if self.store.get_meta("session_model") != sm:
                self.store.set_meta("session_model", sm)
                self.store.set_meta("session_model_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        now = datetime.now(timezone.utc)
        for act in self.running():
            if reset_running or now - _ts(act["started_at"]) > timedelta(minutes=STALE_MINUTES):
                self._cancel(act)
        self._checker_nudge()
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
        model = self.model_for(agent["kind"])
        self.store.create_activation(aid, agent["id"], wid, msgs[0]["id"], msgs[-1]["id"], model)
        self.set_cursor(agent["id"], msgs[-1]["id"])
        n = len(msgs)
        act = {"activation_id": aid, "agent": AGENT_TYPES[agent["kind"]],
               "description": f"{agent['name']} ({agent['role']}): {n} new message{'s' if n != 1 else ''}",
               "prompt": self.build_prompt(agent, aid, msgs, wid)}
        if model:
            act["model"] = model
        return act

    def activity(self):
        """For the dashboard: who is working, who has work waiting, recent runs."""
        running = self.running()
        busy = {a["agent_id"] for a in running}
        waiting = [{"agent_id": a["id"], "agent_name": a["name"],
                    "messages": sum(1 for m in msgs if m["kind"] in WAKE_KINDS)}
                   for a, msgs in self.due() if a["id"] not in busy]
        recent = [{k: a[k] for k in ("id", "agent_id", "agent_name", "status", "started_at", "ended_at", "report", "model")}
                  for a in self.store.list_activations(limit=12) if a["status"] != "running"][:8]
        return {"running": [{"activation_id": a["id"], "agent_id": a["agent_id"], "agent_name": a["agent_name"],
                             "started_at": a["started_at"], "model": a["model"]} for a in running],
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
                          block_task_ids=None, question=None, deliverables=None):
        self.require(aid, ("chief",))
        r = self.wf.submit_brief(work_request_id, summary, goals, tasks, change_note, block_task_ids, question,
                                 deliverables=deliverables)
        for t in tasks or []:  # a task's words now belong to the department that got it
            self.kb.links_learn(f"{t.get('title', '')}. {t.get('description', '')}", str(t.get("dept", "")), "task")
        return {"brief_version": r["brief"]["version"],
                "tasks_created": [{"id": t["id"], "title": t["title"], "dept": t["dept"]} for t in r["tasks"]],
                "blocked": r["blocked"], "deliverables": r["brief"]["deliverables"]}

    def tool_report(self, aid, work_request_id, text, missing_reason=None):
        self.require(aid, ("chief",))
        m = self.wf.report_to_owner(work_request_id, text, missing_reason=missing_reason)
        return {"ok": True, "message_id": m["id"], "files": [f["path"] for f in self.store.list_files(work_request_id)]}

    def tool_build_file(self, aid, task_id, format, title, content, sources=None):
        """Build a PPT/Word/Excel file for a task (or, for the Chief, a work request) in _outputs/<WR>/."""
        act, agent = self.require(aid)
        fmt = str(format or "").lower().strip().lstrip(".")
        fmt = {"ppt": "pptx", "doc": "docx", "word": "docx", "xls": "xlsx", "excel": "xlsx"}.get(fmt, fmt)
        if fmt not in office.FORMATS:
            raise Invalid("format must be pptx, docx or xlsx")
        if task_id.startswith("WR-"):
            if agent["kind"] != "chief":
                raise Conflict("Only the Chief builds work-request level files; use one of your task ids")
            wid, tid, prefix = self.store.get_work_request(task_id)["id"], None, ""
        else:
            t = self.store.get_task(task_id) if agent["kind"] == "chief" else self._task_for(agent, task_id)
            wid, tid, prefix = t["work_request_id"], t["id"], f"{t['id']}-"
        folder = os.path.join(self.kb.root, "_outputs", re.sub(r"[^A-Za-z0-9._-]+", "-", wid or "general"))
        os.makedirs(folder, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", str(title or "")).strip("-")[:70] or "file"
        path = os.path.join(folder, f"{prefix}{slug}.{fmt}")
        info = office.build(path, fmt, title, content, sources)
        f = self.store.add_file(path, fmt, str(title).strip(), wid, tid, agent["id"], os.path.getsize(path))
        return dict(info, path=path, format=fmt, file_id=f["id"], size_bytes=f["size"])

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
        if recipient not in ("owner", CHIEF_ID, CHECKER_ID):
            target = self.store.get_agent(recipient)
            if target["dept"] and target["dept"] != agent["dept"]:
                self.kb.links_learn(text, target["dept"], "ask")
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
        elif agent["kind"] in ("chief", "checker"):
            depts = None  # everything
        else:
            depts = [agent["dept"], "shared"]
        return {"results": self.kb.search(query, depts, min(max(int(top or 8), 1), 20))}

    def tool_read(self, aid, file, line=None, chars=None, again=False):
        """Read part of a file, once. A part this run already read, or one that is already in the agent's source
        pack, is not sent again (its text is already in the agent's hands) unless `again` is true."""
        _, agent = self.require(aid)
        if again:
            return self.kb.read_file(file, line, chars)
        rel = os.path.relpath(self.kb.inside(file), os.path.realpath(self.kb.root)).replace(os.sep, "/")
        try:
            at = int(line) if line else 0
        except (TypeError, ValueError):
            raise Invalid("line must be a whole number")
        hit = self._in_pack(agent, rel, at or 1) if agent["kind"] in ("head", "hired") else None
        if hit:
            return {"file": rel, "from_line": at or 1, "already_in_source_pack": hit,
                    "note": f"This part is already in your briefing ({hit}), so it is not read again. Use it, or "
                            "read a different part. Pass again=true only if you really need it a second time."}
        if self.store.note_read(aid, rel, at):
            return {"file": rel, "from_line": at or 1, "already_read": True,
                    "note": "You already read this part in this run. Use what you have, or read a different part "
                            "(next_line carries on). Pass again=true only if you really need it a second time."}
        return self.kb.read_file(file, line, chars)

    def _in_pack(self, agent, rel, line):
        """'Source pack for TK-3, source 2' when the part from `line` of `rel` is in the prompt of one of the agent's
        tasks, else None."""
        for t in self.store.list_tasks():
            if t["status"] == "done" or not (t["dept"] == agent["dept"] if agent["kind"] == "head"
                                             else t["agent_id"] == agent["id"]):
                continue
            pack = self.store.get_source_pack(t["id"])
            for i, src in enumerate(self._shown_sources(pack), 1):
                if src["file"] == rel and src["line"] <= line <= src["to_line"]:
                    return f"source pack for {t['id']}, source {i}"
        return None

    @staticmethod
    def _shown_sources(pack):
        """The sections of a pack that fit in a prompt (the rest are pointers the agent can read)."""
        shown, used = [], 0
        for src in (pack["sources"] if pack else []):
            if used + len(src["extract"]) > PACK_PROMPT_CHARS and shown:
                break
            shown.append(src)
            used += len(src["extract"])
        return shown

    def tool_related(self, aid, text, top=3):
        """Which other departments do the words in `text` point at, and what do they know about it?"""
        _, agent = self.require(aid)
        if not (text or "").strip():
            raise Invalid("Give the words (a task, a question) to look up")
        return self.kb.links_find(text, dept=agent["dept"], top=min(max(int(top or 3), 1), 5))

    def tool_submit_source_pack(self, aid, packs):
        """File Checker: one source pack per task. The system reads every section once (exact document, revision,
        section and page), stores it, and only then lets the department start."""
        _, agent = self.require(aid, ("checker",))
        if not isinstance(packs, list) or not packs:
            raise Invalid("packs must be a list with one entry per task")
        saved, rejected = [], []
        for p in packs:
            tid = str((p or {}).get("task_id", "")).strip()
            try:
                saved.append(self._save_pack(agent, tid, p))
            except (Invalid, NotFound) as e:
                rejected.append({"task_id": tid or "?", "error": str(e)})
        if not saved:
            raise Invalid("No pack was saved. " + " ".join(f"{r['task_id']}: {r['error']}" for r in rejected))
        self.store.set_meta("checker_tries", 0)
        waiting = [t["id"] for t in self.store.tasks_awaiting_pack()]
        if saved:
            lines = [f"{x['task_id']} {x['coverage']} ({x['sections']} section{'s' if x['sections'] != 1 else ''})"
                     + (f", issues: {'; '.join(x['issues'])}" if x["issues"] else "") for x in saved]
            self.store.add_message(agent["id"], CHIEF_ID, "Sources checked: " + " | ".join(lines), kind="status",
                                   work_request_id=saved[0]["work_request_id"])
        return {"saved": [{k: x[k] for k in ("task_id", "coverage", "sections", "issues", "file")} for x in saved],
                "rejected": rejected, "still_waiting": waiting}

    def _save_pack(self, agent, tid, p):
        t = self.store.get_task(tid)  # NotFound for a wrong id
        if t["status"] not in ("todo", "in_progress"):
            raise Invalid(f"{tid} is {t['status']}; no pack needed")
        coverage = str(p.get("coverage") or "full").strip().lower()
        if coverage not in ("full", "partial", "none"):
            raise Invalid("coverage must be full, partial or none")
        issues = [str(x).strip() for x in (p.get("issues") or []) if str(x).strip()]
        summary = str(p.get("summary") or "").strip()
        wanted = p.get("sources") or []
        if len(wanted) > MAX_PACK_SOURCES:
            raise Invalid(f"at most {MAX_PACK_SOURCES} sections per task; pick the best")
        sources, seen = [], set()
        for src in wanted:
            try:
                s = self.kb.pack_source((src or {}).get("file"), (src or {}).get("line"))
            except Invalid as e:
                raise Invalid(f"{e} (use the `file` and `line` from search_manuals)")
            if (s["file"], s["line"]) in seen:
                continue
            seen.add((s["file"], s["line"]))
            for i in s.pop("issues"):
                if i not in issues:
                    issues.append(i)
            s["why"] = str((src or {}).get("why") or "").strip()[:300]
            sources.append(s)
        if not sources and coverage != "none":
            raise Invalid("no sections given: use coverage 'none' and say in `issues` what the manuals lack")
        if coverage == "none" and not (issues or summary):
            raise Invalid("coverage 'none' needs `issues` or `summary` saying what the manuals lack")
        pack, updated = self.store.save_source_pack(tid, agent["id"], summary, coverage, issues, sources)
        path = self.kb.save_output(t["work_request_id"] or "general", f"{tid}-source-pack", self._pack_markdown(t, pack))
        if updated:
            if t["status"] in ("todo", "in_progress"):
                self.store.add_message(agent["id"], t["agent_id"] or self.store.get_department(t["dept"])["head_id"],
                                       f"Source pack for {tid} updated ({len(sources)} sections, {coverage}). "
                                       "It is in your briefing.", kind="chat", task_id=tid, dept=t["dept"],
                                       work_request_id=t["work_request_id"])
        else:
            self.wf.release_task(t["id"], pack)
        return {"task_id": tid, "coverage": coverage, "sections": len(sources), "issues": issues, "file": path,
                "work_request_id": t["work_request_id"]}

    @staticmethod
    def _pack_markdown(t, pack):
        out = [f"# Source pack for {t['id']}: {t['title']}", "",
               f"Department: {t['dept']} · coverage: {pack['coverage']} · version {pack['version']}", ""]
        if pack["summary"]:
            out += [pack["summary"], ""]
        if pack["issues"]:
            out += ["## Issues flagged by the File Checker", ""] + [f"- {i}" for i in pack["issues"]] + [""]
        for i, s in enumerate(pack["sources"], 1):
            pg = f"p.{s['page']}" if s.get("page") else "p.n/a"
            out += [f"## {i}. {s.get('doc') or s['file']} · rev {s.get('revision') or '?'} · §{s.get('section') or '?'} · {pg}",
                    f"`{s['file']}` lines {s['line']}-{s['to_line']}" + (f" · {s['why']}" if s.get("why") else ""), "",
                    s["extract"], ""]
        return "\n".join(out)

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
        chief = self.store.get_agent(CHIEF_ID)
        lines = [f"- {chief['name']}, {chief['role']}: id \"{CHIEF_ID}\", reports to the Owner"]
        if self.store.checker_active():
            ck = self.store.get_agent(CHECKER_ID)
            lines.append(f"- {ck['name']}, {ck['role']} (the File Checker): id \"{CHECKER_ID}\", reports to the Chief. "
                         "Every task passes through the File Checker before its department starts: it reads the "
                         "manuals once and hands the department a source pack.")
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

    def _pack_lines(self, t):
        """The File Checker's source pack for a task, as it goes into a department's prompt."""
        pack = self.store.get_source_pack(t["id"])
        if not pack:
            return [f"Source pack for {t['id']}: none yet. Search the manuals yourself for this task."]
        out = [f"Source pack for {t['id']} (File Checker, coverage {pack['coverage']}): the sections below were read "
               "once for you. Use them and cite them; do not search or read them again."]
        if pack["summary"]:
            out.append(f"Checker's summary: {pack['summary']}")
        for i in pack["issues"]:
            out.append(f"ISSUE flagged: {i}")
        shown = self._shown_sources(pack)
        for n, src in enumerate(shown, 1):
            pg = f"p.{src['page']}" if src.get("page") else "p.n/a"
            out.append(f"--- Source {n}: {src.get('doc') or src['file']}, rev {src.get('revision') or '?'}, "
                       f"section {src.get('section') or '?'}, {pg} · file {src['file']} lines {src['line']}-{src['to_line']}"
                       + (f" · {src['why']}" if src.get("why") else ""))
            out.append(src["extract"])
        for src in pack["sources"][len(shown):]:
            out.append(f"--- More (read with read_section when needed): {src.get('doc') or src['file']} "
                       f"§{src.get('section') or '?'} · file {src['file']} line {src['line']}")
        return out

    def _links_lines(self, agent, tasks):
        """Other departments the words of these tasks point at: only what matches is shown (keyword-triggered)."""
        text = " ".join(f"{t['title']}. {t['description']}" for t in tasks)[:LINK_TEXT_CHARS]
        found = self.kb.links_find(text, dept=agent["dept"])
        if not found["related"]:
            return []
        out = ["## Linked by keywords (other departments)",
               "Words in your task point at these departments. Only what matches is listed; it is a hint, so confirm "
               "in the manual. Call related_departments with other words if you need more."]
        for e in found["related"]:
            out.append(f"- {e['dept']}, via: {', '.join(e['via'])}")
            for m in e["memory"]:
                out.append(f"    note ({m['kind']}): {m['text']} [{m['src']}]" + (" (verify: source superseded)" if m["verify"] else ""))
            for b in e["board"]:
                out.append(f"    board {b['id']}: {b['from']} -> {b['to']}: {b['subject']}")
            for m in e["manuals"]:
                pg = f"p.{m['page']}" if m["page"] else "p.n/a"
                out.append(f"    manual: {m['doc']} rev {m['revision']} §{m['section']} {pg} · file {m['file']} line {m['line']}")
        return out

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
            hint = wanted_formats(wr["text"])
            if hint:
                lines.append("The Owner's words suggest a file: " + ", ".join(f"{FORMAT_NAMES[f]} ({f})" for f in hint)
                             + ". If so, list it in the brief's deliverables.")
        if b and b["deliverables"]:
            built = {f["format"]: f["path"] for f in self.store.list_files(wid)}
            lines.append("Deliverables: " + "; ".join(
                f"{FORMAT_NAMES[d['format']]} \"{d['title']}\" ({'built: ' + built[d['format']] if d['format'] in built else 'not built yet'})"
                for d in b["deliverables"]))
        files = self.store.list_files(wid)
        if files:
            lines.append("Files built: " + "; ".join(f"{f['title']} ({f['format']}): {f['path']}" for f in files))
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
                "search_manuals finds sections (department, document, revision, section, page, file, line); read_section "
                "with that file and line reads just that part (about 4,000 characters). Do not read whole files: "
                "search first, read the lines you need, and carry on from next_line only if the text is cut off. "
                "Work from what the manuals say, cite document, section and page, and say so plainly when the "
                "manuals do not cover something. Never invent manual content. Every part is read once: the File "
                "Checker's source pack (under Work) already holds the sections a task needs, and read_section will "
                "not send a part you already have.",
                "save_output saves a report or other longer result as markdown and returns its path; put that path "
                "in your task note. build_file makes a real PowerPoint (pptx), Word (docx) or Excel (xlsx) file "
                "from structured content when the Owner wants one."]
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
        elif kind == "checker":
            queue = {t["id"]: t for t in self.store.tasks_awaiting_pack()}
            wids = sorted({t["work_request_id"] for t in queue.values()}, key=lambda x: int(x.split("-")[1]))
            for w in wids[:6]:
                out += self._request_block(w, lambda t: t["id"] in queue)
            if queue:
                out += ["", "### Tasks waiting for a source pack"]
                for t in list(queue.values())[:12]:
                    d = self.store.get_department(t["dept"])
                    out.append(f"- {t['id']} for {d['name']} (department id {d['id']}; documents: "
                               + (", ".join(self._docs(d["id"])) or "none yet") + ")")
                hints = self._links_lines(agent, list(queue.values())[:6])
                out += [""] + hints if hints else []
            else:
                out.append("No task is waiting for a source pack.")
        else:
            mine = (lambda t: t["dept"] == agent["dept"]) if kind == "head" else (lambda t: t["agent_id"] == agent["id"])
            wids = sorted({t["work_request_id"] for t in self.store.list_tasks() if mine(t) and t["work_request_id"]
                           and t["status"] != "done"} | ({wid} if wid else set()))
            for w in wids[:6]:
                out += self._request_block(w, mine)
            if not wids:
                out.append("You have no open tasks.")
            open_tasks = [t for t in self.store.list_tasks() if mine(t) and t["status"] in ("todo", "in_progress", "blocked")]
            if open_tasks:
                out += ["", "## Source packs (read once by the File Checker)"]
                for t in open_tasks[:6]:
                    out += self._pack_lines(t)
                out += [""] + self._links_lines(agent, open_tasks[:6])
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
        "0. Files: when the Owner asks for a presentation/PPT, a Word document or an Excel sheet, put it in the "
        "brief's deliverables (format pptx, docx or xlsx, and a title) and ask the departments for the content "
        "(slide points, sections or table rows, with sources) in their tasks.",
        "1. A work request with no brief: check what each department's manuals cover (search_manuals), then call "
        "submit_brief with a "
        "short summary, goals and tasks. Each task has exactly one department (dept = department id), a clear title, "
        "details and acceptance criteria. Split work that needs two departments into two tasks.",
        "1b. After your brief the File Checker reads the manuals once for each task and hands the department a source "
        "pack; the Vertical Heads start when it is ready, so you do not need to read the manuals for them. When a "
        "task spans two departments' words, related_departments shows which department owns a term.",
        "2. No department fits: call submit_brief with no tasks and a question asking the Owner which department to "
        "add (its PDFs and Vertical Head name). Never guess.",
        "3. An Owner instruction: re-plan with submit_brief: a change_note, block_task_ids for tasks that conflict "
        "with it, and any new tasks. If it changes nothing, say so with send_message to the Owner.",
        "4. A blocked task or a question from a Head: answer with send_message, or re-plan.",
        "5. A review message (all tasks done): read the task notes and their output files (read_section). If the "
        "brief has deliverables, build each one with build_file (task_id = the work request id) from the team's "
        "content: a clear title slide subtitle, one idea per slide, at most 6 short bullets, tables for numbers, "
        "and sources from the manuals. Then call report_to_owner with the outcome of each task; the file paths are "
        "added to the report for you. Keep it short and factual.",
    ],
    "head": [
        "You run your department. For each new task:",
        "1. update_task to in_progress with a short note.",
        "1b. Start from the source pack in your briefing: the File Checker already read those sections once, with "
        "document, revision, section and page. Use and cite them; search_manuals / read_section only for what the pack "
        "lacks (read_section will not send a part you already have). If a task mentions another department's words, "
        "see 'Linked by keywords' or call related_departments: it reads only what matches. If the pack is thin, ask "
        "the File Checker (send_message to 'checker') for more sources instead of reading around.",
        "2. Do it yourself from your department's manuals, or hire a specialist with hire_agent (name, role, reason, "
        f"task_id) when it needs a separate skill or parallel work. At most {HIRE_CAP} active agents per department, "
        "you included. A hire with task_id also assigns the task; the specialist then does it and reports.",
        "3. When finished: save_output (and build_file if the task asks for a PPT, Word or Excel file), then "
        "update_task to done with a note that sums up the result and gives the paths. Blocked or unclear: "
        "update_task to blocked with the reason, or ask with send_message.",
        "When the Chief needs material for a presentation, document or sheet, write it so it drops straight in: "
        "slide titles with short bullet points, section headings with paragraphs, or table columns and rows, each "
        "with its manual source.",
        "Answer messages addressed to you. Don't redo work a specialist already marked done.",
    ],
    "checker": [
        "You are the File Checker. Every task passes through you before its department starts, and you own the "
        "documentation: the right sections of the right revision, read once, so nobody reads them again.",
        "1. For each task under Work: search_manuals in the task's department (and `shared`), and in any other "
        "department its words point at (see 'Linked by keywords' or call related_departments). Two or three "
        "phrasings are enough.",
        "2. Pick the sections that answer the task, usually 3 to 6, at most 8: pass each one's `file` and `line` from "
        "the search result, with a short `why`. You rarely need read_section; use it only when a snippet cannot say "
        "whether a section is relevant. The system reads each section once and records the exact document, revision, "
        "section and page.",
        "3. Check what you found: prefer the current revision; list in `issues` any sections that disagree, a "
        "superseded or unclear revision, a part of the task the manuals do not cover, or a department with no "
        "documents. coverage = full, partial or none.",
        "4. Call submit_source_pack once with a pack for every task listed. Departments start only after you submit, "
        "so be quick: a pack takes a few searches, not a full read. If a Head asks for more sources, search again "
        "and submit that task's pack again.",
        "You do the documentation work only: never plan, never do a department's task, never invent manual content.",
    ],
    "hired": [
        "You are a specialist hired for specific tasks. For each task assigned to you:",
        "1. update_task to in_progress with a short note.",
        "2. Start from the source pack in your briefing (read once by the File Checker; use and cite it). Search "
        "(search_manuals, read_section) only for what it lacks, and call related_departments for another department's "
        "words. Then save_output; use build_file when the task asks for a PPT, Word or Excel file.",
        "3. update_task to done with a note that sums up the result and gives the output path, or to blocked with "
        "the reason. Ask your Vertical Head with send_message if something is unclear.",
    ],
}

RULES = ("Rules: act only through the Flight Safety Command tools. Every status change needs "
         "a note. Only send a message when someone must act on it or needs the answer; no thanks or "
         "acknowledgements. Never claim work is done unless it is. If a tool says the activation has ended, stop "
         "at once. When you are done, end with a report of one to three lines saying what you did.")
