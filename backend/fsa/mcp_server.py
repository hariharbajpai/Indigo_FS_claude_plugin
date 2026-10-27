"""MCP server for Claude Code (stdio, JSON-RPC 2.0, one JSON message per line). Standard library only.

Owner tools are called by the main Claude Code session (the slash commands). Agent tools are called by the
Chief, Vertical Head and specialist subagents and need their activation id. Nothing is created on disk until a
tool needs it, so the server can start in any project without leaving a safety-kb folder behind.
"""
import json
import os
import sys
import traceback

from . import VERSION, daemon, paths
from .kb_bridge import KbBridge
from .loop import Office
from .services import add_department, read_paths, rename, replace_documents
from .store import Store, StoreError
from .workflow import Workflow

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Flight Safety Command runs a flight-safety organisation as subagents in this Claude Code session: the Chief "
    "of Flight Safety, one Vertical Head per department and the specialists they hire (the Owner can rename any "
    "of them). The Owner works through /flight-safety-agents:start, add-dept, work, tell, run, rename and status. When a command "
    "runs the work loop, call next_work, start one Agent per activation exactly as given, and call "
    "activation_done with each agent's final report. The agent tools (get_briefing, send_message, submit_brief, "
    "report_to_owner, update_task, hire_agent, assign_task, search_manuals, read_section, save_output, build_file) "
    "belong to the subagents and need their activation id. Files the team builds (PPT, Word, Excel) are listed with "
    "their paths in the Chief's report.")

S = {"type": "string"}
ACT = {"type": "string", "description": "Your activation id (from your prompt)"}


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TASK_ITEM = obj({"title": S, "dept": {"type": "string", "description": "Department id"},
                 "description": S, "acceptance": {"type": "string", "description": "Acceptance criteria"}},
                ["title", "dept"])

CONTENT_HELP = (
    "pptx: {\"subtitle\": str, \"slides\": [{\"title\": str, \"bullets\": [str or {\"text\": str, \"level\": 1}], "
    "\"table\": {\"columns\": [str], \"rows\": [[cell]]}, \"note\": str (e.g. the source)}]} (at most 12 bullets and "
    "15 table rows per slide). docx: {\"subtitle\": str, \"sections\": [{\"heading\": str, \"level\": 1-3, "
    "\"paragraphs\": [str], \"bullets\": [...], \"table\": {...}}]}. xlsx: {\"sheets\": [{\"name\": str, "
    "\"columns\": [str], \"rows\": [[text or number]]}]}. Text may use **bold**.")
DELIVERABLE = obj({"format": {"type": "string", "enum": ["pptx", "docx", "xlsx"]}, "title": S}, ["format"])

TOOLS = [
    # ---- Owner / office manager ----
    ("status", "Show Flight Safety Command: departments and Vertical Heads, hired agents, work requests and "
               "progress, who is working, and the dashboard link.", obj({})),
    ("open_dashboard", "Start the live dashboard (if needed) and return its link. The link carries the access token.",
     obj({"open_browser": {"type": "boolean", "description": "Also open it in the browser (default true)"}})),
    ("stop_dashboard", "Stop the dashboard server.", obj({})),
    ("add_department", "Owner: add a department from its PDF manuals plus the Vertical Head's name. Checks every "
                       "PDF against the knowledge base first; answers needs_decision for duplicates or new "
                       "versions (then call again with decision 'new', or 'replace' with target).",
     obj({"name": S, "head_name": S, "files": {"type": "array", "items": S, "description": "Absolute PDF paths"},
          "decision": {"type": "string", "enum": ["", "new", "replace"]}, "target": S},
         ["name", "head_name", "files"])),
    ("update_department_docs", "Owner: update a department's manuals with new PDFs (new versions replace "
                                    "the old revision; identical files are skipped; others are added).",
     obj({"department": S, "files": {"type": "array", "items": S}}, ["department", "files"])),
    ("rename", "Owner: rename anyone: the Chief of Flight Safety, a Vertical Head, a hired specialist, or a "
               "department. target = current name, a unique part of it, an agent id (ag-2), 'chief', or a "
               "department id. Display name only; ids, tasks and history stay.",
     obj({"target": S, "new_name": S}, ["target", "new_name"])),
    ("submit_work", "Owner: give the Chief of Flight Safety a work request (English or Hinglish).",
     obj({"text": S}, ["text"])),
    ("owner_instruction", "Owner: send an instruction mid-way, to the Chief (target 'chief') or a department "
                          "(target = department id). The Chief re-plans.",
     obj({"text": S, "target": S, "work_request_id": S}, ["text"])),
    ("next_work", "Office manager: get the agent runs that are ready. status work = start one Agent per "
                  "activation; busy = wait for running agents; finished / no_run = stop and tell the Owner.",
     obj({"reset_running": {"type": "boolean", "description": "Cancel runs left over from an earlier session"}})),
    ("activation_done", "Office manager: report that a subagent finished. Pass its final report.",
     obj({"activation_id": S, "report": S}, ["activation_id", "report"])),
    # ---- agents ----
    ("get_briefing", "Agent: your current briefing again (team, knowledge base, work, tasks).",
     obj({"activation": ACT}, ["activation"])),
    ("send_message", "Agent: message the Owner ('owner'), the Chief ('chief'), an agent id or a department id "
                     "(goes to its Vertical Head). Only when someone must act or answer.",
     obj({"activation": ACT, "to": S, "text": S, "task_id": S}, ["activation", "to", "text"])),
    ("submit_brief", "Chief only: publish the brief for a work request (v1) or a re-plan (v2+): summary, goals and "
                     "tasks (one department each). No department fits: no tasks and a question for the Owner. "
                     "Re-plan: change_note, block_task_ids for conflicting tasks, new tasks.",
     obj({"activation": ACT, "work_request_id": S, "summary": S, "goals": {"type": "array", "items": S},
          "tasks": {"type": "array", "items": TASK_ITEM}, "change_note": S,
          "block_task_ids": {"type": "array", "items": S}, "question": S,
          "deliverables": {"type": "array", "items": DELIVERABLE,
                           "description": "Files the Owner asked for (PPT, Word, Excel); kept from the last brief "
                                          "if omitted"}},
         ["activation", "work_request_id", "summary"])),
    ("report_to_owner", "Chief only: send the Owner the completion report for a work request. Paths of the files "
                        "built are added for you. Refused while a requested deliverable is missing, unless "
                        "missing_reason says why it cannot be made.",
     obj({"activation": ACT, "work_request_id": S, "text": S, "missing_reason": S},
         ["activation", "work_request_id", "text"])),
    ("update_task", "Vertical Head or specialist: change a task's status (todo, in_progress, review, blocked, done) "
                    "with a note. Done notes sum up the result and give the output file path.",
     obj({"activation": ACT, "task_id": S, "status": {"type": "string",
                                                      "enum": ["todo", "in_progress", "review", "blocked", "done"]},
          "note": S}, ["activation", "task_id", "status", "note"])),
    ("hire_agent", "Vertical Head only: hire a specialist into your department (max 5 active agents per department, "
                   "you included). With task_id the task is assigned to the new hire.",
     obj({"activation": ACT, "name": S, "role": S, "reason": S, "task_id": S},
         ["activation", "name", "role", "reason"])),
    ("assign_task", "Vertical Head only: assign one of your department's tasks to an agent in your department.",
     obj({"activation": ACT, "task_id": S, "agent_id": S}, ["activation", "task_id", "agent_id"])),
    ("search_manuals", "Agent: search the department manuals. Returns sections with department, document, revision, "
                       "section, page, file and a snippet. Defaults to your own department (the Chief: all).",
     obj({"activation": ACT, "query": S, "dept": {"type": "string", "description": "Department id (optional)"},
          "top": {"type": "integer", "description": "Max results, 1-20 (default 8)"}}, ["activation", "query"])),
    ("read_section", "Agent: read a manual section or saved output file (a `file` from search_manuals or a path "
                     "from save_output).",
     obj({"activation": ACT, "file": S}, ["activation", "file"])),
    ("save_output", "Agent: save a report or other longer result as markdown for a task (or, for the Chief, a work "
                    "request id). Returns the file path to put in your task note.",
     obj({"activation": ACT, "task_id": S, "title": S, "content": {"type": "string", "description": "Markdown"}},
         ["activation", "task_id", "title", "content"])),
    ("build_file", "Agent: build a real PowerPoint (pptx), Word (docx) or Excel (xlsx) file for a task (or, for the "
                   "Chief, a work request id) from structured content; sources become a final Sources slide, section "
                   "or sheet. Returns the path. Content: " + CONTENT_HELP,
     obj({"activation": ACT, "task_id": S, "format": {"type": "string", "enum": ["pptx", "docx", "xlsx"]},
          "title": S, "content": {"type": "object", "description": CONTENT_HELP},
          "sources": {"type": "array", "items": S, "description": "Citations: document, revision, section, page"}},
         ["activation", "task_id", "format", "title", "content"])),
]


class Company:
    def __init__(self, kb_root=None, db_path=None, kb_script=None):
        self.kb = KbBridge(kb_root, kb_script)
        self.db_path = db_path or os.environ.get("FSA_DB") or paths.db_path(self.kb.root)
        self._office = None

    def exists(self):
        return self._office is not None or os.path.isfile(self.db_path)

    @property
    def office(self):
        if self._office is None:
            store = Store(self.db_path)
            wf = Workflow(store, message_cap=30, scope_provider=self.kb.keywords, agent_mode=True)
            self._office = Office(store, wf, self.kb, dashboard_url=lambda: daemon.url(self.kb.root))
        return self._office

    # ---- owner tools ----
    def status(self):
        dash = daemon.status(self.kb.root)
        out = {"kb_root": self.kb.root, "dashboard": dash.get("url") if dash["running"] else None}
        if not self.exists():
            out["message"] = ("Not set up yet. Add a department with /flight-safety-agents:add-dept, then give work "
                              "with /flight-safety-agents:work.")
            return out
        o, s = self.office, self.office.store
        chief = s.get_agent("chief")
        out["chief"] = f"{chief['name']}, {chief['role']} (id chief)"
        out["departments"] = [{"id": r["department"]["id"], "name": r["department"]["name"],
                               "vertical_head": f"{r['head']['name']} ({r['head']['id']})",
                               "documents": len(self.kb.list_docs(r["department"]["id"])),
                               "hired": [f"{a['name']} ({a['role']}, {a['id']})" for a in r["agents"]],
                               "active_agents": r["active_count"]} for r in s.org_chart()["departments"]]
        out["work_requests"] = [{"id": w["id"], "status": w["status"], "text": w["text"][:200],
                                 "brief_version": w["brief_version"], "progress": w["progress"],
                                 "files": [f["path"] for f in s.list_files(w["id"])]}
                                for w in s.list_work_requests()[:10]]
        act = o.activity()
        out["working_now"] = [a["agent_name"] for a in act["running"]]
        out["waiting_to_run"] = [a["agent_name"] for a in act["waiting"]]
        return out

    def open_dashboard(self, open_browser=True):
        self.office  # create the database so the dashboard has something to show
        st = daemon.start(self.kb.root, open_browser=open_browser)
        return {"url": st["url"], "started": st["started"], "kb_root": self.kb.root}

    def stop_dashboard(self):
        return daemon.stop(self.kb.root)

    def add_department(self, name, head_name, files, decision="", target=""):
        status, payload = add_department(self.office.store, self.kb, read_paths(files), name, head_name,
                                         decision, target)
        return payload

    def update_department_docs(self, department, files):
        return replace_documents(self.office.store, self.kb, department, read_paths(files))[1]

    def rename(self, target, new_name):
        r = rename(self.office.store, target, new_name)
        return dict(r, message=f"Renamed {r['old']} to {r['new']}. The dashboard, chat feed and agents use the "
                               "new name from now on.")

    def submit_work(self, text):
        wr = self.office.wf.submit_work_request(text)
        return {"work_request": wr, "next": "Run the work loop (next_work) so the Chief writes the brief."}

    def owner_instruction(self, text, target="chief", work_request_id=None):
        r = self.office.wf.send_instruction(target or "chief", text, work_request_id)
        return {"delivered_to": r["message"]["recipient_name"], "work_request_id": r["message"]["work_request_id"],
                "next": "Run the work loop (next_work) so the team acts on it."}

    def next_work(self, reset_running=False):
        if not self.exists():
            return {"status": "no_run", "message": "Not set up yet. Add a department with "
                    "/flight-safety-agents:add-dept, then give the Chief work with /flight-safety-agents:work."}
        return self.office.next_work(bool(reset_running))

    def activation_done(self, activation_id, report):
        return self.office.activation_done(activation_id, report)

    # ---- agent tools ----
    def get_briefing(self, activation):
        return self.office.tool_briefing(activation)

    def send_message(self, activation, to, text, task_id=None):
        return self.office.tool_send_message(activation, to, text, task_id or None)

    def submit_brief(self, activation, work_request_id, summary, goals=None, tasks=None, change_note=None,
                     block_task_ids=None, question=None, deliverables=None):
        return self.office.tool_submit_brief(activation, work_request_id, summary, goals, tasks, change_note or None,
                                             block_task_ids, question or None, deliverables)

    def report_to_owner(self, activation, work_request_id, text, missing_reason=None):
        return self.office.tool_report(activation, work_request_id, text, missing_reason or None)

    def build_file(self, activation, task_id, format, title, content, sources=None):
        return self.office.tool_build_file(activation, task_id, format, title, content, sources)

    def update_task(self, activation, task_id, status, note):
        return self.office.tool_update_task(activation, task_id, status, note)

    def hire_agent(self, activation, name, role, reason, task_id=None):
        return self.office.tool_hire(activation, name, role, reason, task_id or None)

    def assign_task(self, activation, task_id, agent_id):
        return self.office.tool_assign(activation, task_id, agent_id)

    def search_manuals(self, activation, query, dept=None, top=8):
        return self.office.tool_search(activation, query, dept or None, top)

    def read_section(self, activation, file):
        return self.office.tool_read(activation, file)

    def save_output(self, activation, task_id, title, content):
        return self.office.tool_save_output(activation, task_id, title, content)

    def call(self, name, args):
        if name not in {t[0] for t in TOOLS}:
            raise KeyError(name)
        return getattr(self, name)(**(args or {}))


class Server:
    def __init__(self, company=None, out=None):
        self.company = company or Company()
        self.out = out or sys.stdout

    def send(self, msg):
        self.out.write(json.dumps(msg, default=str) + "\n")
        self.out.flush()

    def handle(self, msg):
        """Returns a response dict, or None for notifications."""
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:
            return None
        try:
            if method == "initialize":
                want = params.get("protocolVersion")
                result = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "flight-safety-command", "version": VERSION},
                          "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
            elif method == "tools/call":
                result = self.call_tool(params.get("name"), params.get("arguments") or {})
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method {method}"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}

    def call_tool(self, name, args):
        try:
            data = self.company.call(name, args)
            return {"content": [{"type": "text", "text": json.dumps(data, indent=1, default=str)}], "isError": False}
        except KeyError:
            return {"content": [{"type": "text", "text": f"Unknown tool {name}"}], "isError": True}
        except TypeError as e:  # wrong or missing arguments
            return {"content": [{"type": "text", "text": f"Bad arguments for {name}: {e}"}], "isError": True}
        except StoreError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except RuntimeError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return {"content": [{"type": "text", "text": f"{name} failed: {e}"}], "isError": True}

    def run(self, inp=None):
        for line in (inp or sys.stdin):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue
            batch = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (self.handle(m) for m in batch if isinstance(m, dict)) if r]
            if isinstance(msg, list) and replies:
                self.send(replies)
            else:
                for r in replies:
                    self.send(r)


def main():
    Server().run()
    return 0
