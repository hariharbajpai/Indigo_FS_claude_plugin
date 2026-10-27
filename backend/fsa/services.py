"""Department operations shared by the dashboard server and the MCP tools.

uploads are [(file name, bytes)]. Each function returns (http status, payload)."""
import os

from .store import Conflict, Invalid


def read_paths(paths):
    """MCP callers pass local file paths."""
    out = []
    for p in paths or []:
        p = os.path.expanduser(str(p).strip())
        if not os.path.isfile(p):
            raise Invalid(f"File not found: {p}")
        with open(p, "rb") as f:
            out.append((os.path.basename(p), f.read()))
    return out


def add_department(store, kb, uploads, name, head_name, decision="", target=""):
    name, head_name, decision, target = ((name or "").strip(), (head_name or "").strip(),
                                         (decision or "").strip(), (target or "").strip())
    kb.validate(uploads)
    if not name:
        raise Invalid("Department name is required")
    if not head_name:
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
        return 200, {"status": "replaced", "department": store.get_department(target), "matches": matches}
    if not decision and any(m["result"] != "new" for m in matches):
        return 409, {"status": "needs_decision", "matches": matches}
    did = store.next_dept_id(name)
    docs = kb.ingest(did, uploads)  # first, so an unreadable PDF leaves no empty department behind
    dept, head = store.create_department(name, head_name)
    return 201, {"status": "created", "department": dept, "head": head, "matches": matches, "documents": docs}


def replace_documents(store, kb, did, uploads):
    dept = store.get_department(did)
    if dept["status"] != "active":
        raise Conflict(f"Department {did} is retired")
    kb.validate(uploads)
    docs = kb.replace(did, uploads)
    store.add_event("department.updated", {"id": did})
    return 200, {"status": "replaced", "department": store.get_department(did), "documents": docs}


def retire_department(store, kb, did):
    dept, ids = store.retire_department(did)
    kb.retire(did)
    return 200, {"department": dept, "retired_agents": ids}
