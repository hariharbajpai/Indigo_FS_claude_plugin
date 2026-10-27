"""FastAPI app implementing backend/API.md."""
import asyncio
import json
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import CHIEF_ID, HIRE_CAP, VERSION
from .kb_bridge import KbBridge
from .store import Conflict, Invalid, Store, StoreError
from .workflow import Workflow


class WorkIn(BaseModel):
    text: str


class InstructionIn(BaseModel):
    target: str
    text: str
    work_request_id: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    note: str
    author: Optional[str] = None


class AssignIn(BaseModel):
    agent_id: str


class HireIn(BaseModel):
    name: str
    role: str
    reason: str
    task_id: Optional[str] = None


def sse_frame(ev):
    return f"id: {ev['id']}\nevent: {ev['type']}\ndata: {json.dumps(ev)}\n\n"


def create_app(db_path=None, planner=None, kb_root=None, kb_script=None, message_cap=30):
    store = Store(db_path)
    kb = KbBridge(kb_root, kb_script)
    wf = Workflow(store, planner, message_cap=message_cap, scope_provider=kb.keywords)
    app = FastAPI(title="Flight Safety Command", version=VERSION)
    app.state.store, app.state.workflow, app.state.kb = store, wf, kb
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(StoreError)
    async def _store_error(_: Request, exc: StoreError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    def sync():
        try:
            wf.sync_board(kb.board_entries())
        except Exception:
            pass

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION}

    @app.get("/api/overview")
    def overview():
        sync()
        return store.overview()

    @app.get("/api/org")
    def org(include_retired: bool = False):
        return store.org_chart(include_retired)

    @app.get("/api/work-requests")
    def work_requests():
        return store.list_work_requests()

    @app.get("/api/work-requests/{wid}")
    def work_request(wid: str):
        return wf.request_detail(wid)

    @app.post("/api/work-requests", status_code=201)
    def post_work(body: WorkIn, bg: BackgroundTasks, wait: bool = False):
        wr = wf.submit_work_request(body.text)
        if wait:
            wf.chief_plan(wr["id"])
            d = wf.request_detail(wr["id"])
            return {"request": d["request"], "brief": d["brief"], "tasks": d["tasks"]}
        bg.add_task(wf.chief_plan, wr["id"])
        return wr

    @app.post("/api/instructions", status_code=201)
    def post_instruction(body: InstructionIn):
        return wf.send_instruction(body.target, body.text, body.work_request_id)

    @app.get("/api/tasks")
    def tasks(status: Optional[str] = None, dept: Optional[str] = None,
              work_request_id: Optional[str] = None):
        return store.list_tasks(status, dept, work_request_id)

    @app.get("/api/tasks/{tid}")
    def task(tid: str):
        return store.get_task(tid)

    @app.post("/api/tasks/{tid}/status")
    def task_status(tid: str, body: StatusIn):
        return wf.update_task(tid, body.status, body.note, body.author)

    @app.post("/api/tasks/{tid}/assign")
    def task_assign(tid: str, body: AssignIn):
        return store.assign_task(tid, body.agent_id)

    @app.post("/api/departments/{did}/hire", status_code=201)
    def hire(did: str, body: HireIn):
        return wf.hire(did, body.name, body.role, body.reason, body.task_id)

    @app.get("/api/messages")
    def messages(dept: Optional[str] = None, agent: Optional[str] = None, task: Optional[str] = None,
                 work_request_id: Optional[str] = None, since_id: int = 0, limit: int = Query(500, le=5000)):
        sync()
        return store.list_messages(dept, agent, task, work_request_id, since_id, limit)

    @app.get("/api/departments")
    def departments(include_retired: bool = False):
        return store.list_departments(include_retired)

    async def read_files(files):
        out = []
        for f in files or []:
            if f.filename:
                out.append((f.filename, await f.read()))
        return out

    @app.post("/api/departments")
    async def add_department(files: List[UploadFile] = File(default=None), name: str = Form(""),
                             head_name: str = Form(""), decision: str = Form(""), target: str = Form("")):
        uploads = await read_files(files)
        kb.validate(uploads)
        if not name.strip():
            raise Invalid("Department name is required")
        if not head_name.strip():
            raise Invalid("Vertical Head name is required")
        if decision not in ("", "new", "replace"):
            raise Invalid("decision must be 'new' or 'replace'")
        active = [d["id"] for d in store.list_departments()]
        matches = kb.match(uploads, active)
        if decision == "replace":
            if target not in active:
                raise Invalid("decision=replace needs target=<existing department id>")
            kb.replace(target, uploads)
            store.add_event("department.updated", {"id": target})
            return {"status": "replaced", "department": store.get_department(target), "matches": matches}
        if not decision and any(m["result"] != "new" for m in matches):
            return JSONResponse({"status": "needs_decision", "matches": matches}, status_code=409)
        did = store.next_dept_id(name)
        kb.ingest(did, uploads)  # first, so an unreadable PDF leaves no empty department behind
        dept, head = store.create_department(name, head_name)
        return JSONResponse({"status": "created", "department": dept, "head": head, "matches": matches},
                            status_code=201)

    @app.post("/api/departments/{did}/replace")
    async def replace_department(did: str, files: List[UploadFile] = File(default=None)):
        dept = store.get_department(did)
        if dept["status"] != "active":
            raise Conflict(f"Department {did} is retired")
        uploads = await read_files(files)
        kb.validate(uploads)
        kb.replace(did, uploads)
        store.add_event("department.updated", {"id": did})
        return {"status": "replaced", "department": store.get_department(did)}

    @app.post("/api/departments/{did}/retire")
    def retire_department(did: str):
        dept, ids = store.retire_department(did)
        kb.retire(did)
        return {"department": dept, "retired_agents": ids}

    @app.post("/api/agents/{aid}/retire")
    def retire_agent(aid: str):
        return store.retire_agent(aid)

    @app.get("/api/events")
    async def events(request: Request, since_id: Optional[int] = None, max_seconds: Optional[float] = None):
        last = since_id
        if last is None:
            hdr = request.headers.get("last-event-id")
            last = int(hdr) if hdr and hdr.isdigit() else store.last_event_id()

        async def gen():
            cursor, idle, waited = last, 0.0, 0.0
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    return
                evs = store.list_events(cursor)
                for ev in evs:
                    cursor = ev["id"]
                    yield sse_frame(ev)
                    idle = 0.0
                if max_seconds is not None and waited >= max_seconds:
                    return
                await asyncio.sleep(0.5)
                idle += 0.5
                waited += 0.5
                if idle >= 15:
                    yield ": keepalive\n\n"
                    idle = 0.0

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def app_factory():
    return create_app()
