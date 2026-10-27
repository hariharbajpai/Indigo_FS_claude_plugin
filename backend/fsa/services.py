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


def rename(store, target, new_name):
    """Rename an agent (the Chief, a Vertical Head, a specialist) or a department, found by id, `chief`,
    current name, or a unique part of a name. Returns {kind, id, old, new}."""
    t = " ".join(str(target or "").split())
    if not t:
        raise Invalid("Say who to rename (a name, an agent id like ag-2, 'chief', or a department)")
    tl = t.lower()
    agents = store.list_agents()
    depts = store.list_departments()

    def agent_hit(a):
        new = store.rename_agent(a["id"], new_name)
        return {"kind": "agent", "id": a["id"], "role": new["role"], "old": a["name"], "new": new["name"]}

    def dept_hit(d):
        new = store.rename_department(d["id"], new_name)
        return {"kind": "department", "id": d["id"], "old": d["name"], "new": new["name"]}

    for a in agents:  # exact: id or name
        if tl in (a["id"].lower(), a["name"].lower()):
            return agent_hit(a)
    if tl in ("chief of flight safety", "the chief"):
        return agent_hit(store.get_agent("chief"))
    for d in depts:
        if tl in (d["id"].lower(), d["name"].lower()):
            return dept_hit(d)
    near = [("agent", a) for a in agents if tl in a["name"].lower()] + \
           [("department", d) for d in depts if tl in d["name"].lower()]
    if len(near) == 1:
        kind, x = near[0]
        return agent_hit(x) if kind == "agent" else dept_hit(x)
    names = ", ".join(f"{a['name']} ({a['id']})" for a in agents) + "; departments: " + \
        ", ".join(f"{d['name']} ({d['id']})" for d in depts)
    if near:
        raise Invalid(f"'{t}' matches several: " + ", ".join(f"{x['name']} ({x['id']})" for _, x in near)
                      + ". Use the full name or the id.")
    raise Invalid(f"No one called '{t}'. Current names: {names}")
