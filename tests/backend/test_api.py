import os
import sys
import tempfile
import unittest

import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))  # tests/fixtures.py builds real PDFs
import fixtures  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.fsa.api import create_app  # noqa: E402
from backend.fsa.kb_bridge import parse_board  # noqa: E402
from backend.fsa.planner import KeywordPlanner  # noqa: E402

_BASE = {}


def pdf(tag=""):
    """A real, text-extractable PDF (tests/fixtures.py); the tag makes the bytes (and SHA-256) differ."""
    if "pdf" not in _BASE:
        d = tempfile.mkdtemp()
        try:
            _BASE["pdf"] = fixtures.make_pdf(__import__("pathlib").Path(d) / "base.pdf").read_bytes()
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return _BASE["pdf"] + b"\n% " + tag.encode()


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n"  # looks like a PDF, but has no text



@unittest.skipUnless(shutil.which("pdftotext"), "kb.py needs pdftotext (or pypdf/PyMuPDF)")
class ApiBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(os.path.join(self.tmp.name, "fsa.db"), KeywordPlanner(),
                              kb_root=os.path.join(self.tmp.name, "kb"))
        self.c = TestClient(self.app)

    def tearDown(self):
        self.app.state.store.close()
        self.tmp.cleanup()

    def add_dept(self, name, head, content="a", fname="manual.pdf", **extra):
        data = {"name": name, "head_name": head, **extra}
        return self.c.post("/api/departments", data=data, files=[("files", (fname, pdf(content), "application/pdf"))])


class DepartmentTests(ApiBase):
    def test_chief_in_org_and_cannot_retire(self):
        org = self.c.get("/api/org").json()
        self.assertEqual(org["chief"]["name"], "Dhruv Rebbapragada")
        r = self.c.post("/api/agents/chief/retire")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.c.get("/api/health").json()["ok"])

    def test_create_requires_pdf_and_head(self):
        r = self.c.post("/api/departments", data={"name": "Eng", "head_name": "A"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("PDF", r.json()["detail"])
        r = self.add_dept("Eng", " ")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "Vertical Head name is required"))
        r = self.add_dept("", "A")
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/departments", data={"name": "E", "head_name": "A"},
                        files=[("files", ("x.txt", b"hello", "text/plain"))])
        self.assertEqual(r.status_code, 400)
        r = self.add_dept("E", "A", decision="bogus")
        self.assertEqual(r.status_code, 400)

    def test_create_ok_and_org(self):
        r = self.add_dept("Engine Maintenance", "Asha Verma")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["head"]["name"], "Asha Verma")
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "kb", "engine-maintenance", "manual", "_doc.md")))
        org = self.c.get("/api/org").json()
        self.assertEqual(org["departments"][0]["head"]["name"], "Asha Verma")
        self.assertEqual(len(self.c.get("/api/departments").json()), 1)

    def test_match_duplicate_and_new_version_need_decision(self):
        self.add_dept("Engine Maintenance", "Asha")
        r = self.add_dept("Other", "Bob", content="a")
        self.assertEqual(r.status_code, 409)
        j = r.json()
        self.assertEqual(j["status"], "needs_decision")
        self.assertEqual(j["matches"][0]["result"], "duplicate")
        self.assertEqual(len(self.c.get("/api/departments").json()), 1)
        r = self.add_dept("Other", "Bob", content="b")
        self.assertEqual(r.json()["matches"][0]["result"], "new_version")
        self.assertEqual(r.status_code, 409)
        # force new
        r = self.add_dept("Other", "Bob", content="b", decision="new")
        self.assertEqual(r.status_code, 201)
        # replace existing
        r = self.add_dept("x", "y", content="c", decision="replace", target="engine-maintenance")
        self.assertEqual(r.json()["status"], "replaced")
        r = self.add_dept("x", "y", content="c", decision="replace", target="zzz")
        self.assertEqual(r.status_code, 400)

    def test_replace_and_retire(self):
        self.add_dept("Ops", "Om")
        r = self.c.post("/api/departments/ops/replace", files=[("files", ("new.pdf", pdf("n"), "application/pdf"))])
        self.assertEqual(r.json()["status"], "replaced")
        self.assertEqual(self.app.state.kb.list_docs("ops"), ["manual", "new"])
        self.assertEqual(self.c.post("/api/departments/ops/replace").status_code, 400)
        self.c.post("/api/departments/ops/hire", json={"name": "Z", "role": "r", "reason": "w"})
        r = self.c.post("/api/departments/ops/retire")
        self.assertEqual(len(r.json()["retired_agents"]), 2)
        self.assertEqual(self.c.get("/api/org").json()["departments"], [])
        self.assertEqual(self.c.post("/api/departments/ops/retire").status_code, 409)
        self.assertEqual(self.c.post("/api/departments/ops/replace",
                                     files=[("files", ("n.pdf", pdf("z"), "application/pdf"))]).status_code, 409)
        self.assertEqual(self.app.state.kb.list_docs("ops"), [])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp.name, "kb", "ops", "_superseded")))
        self.assertEqual(self.c.post("/api/departments/nope/retire").status_code, 404)


class FlowTests(ApiBase):
    def test_full_flow(self):
        self.add_dept("Engine Maintenance", "Asha Verma", "e", "engine.pdf")
        self.add_dept("Crew Training", "Kabir Singh", "c", "crew.pdf")
        r = self.c.post("/api/work-requests?wait=true", json={"text": "Engine maintenance aur crew training audit karo"})
        self.assertEqual(r.status_code, 201)
        j = r.json()
        self.assertEqual(j["brief"]["version"], 1)
        self.assertEqual(len(j["tasks"]), 2)
        wid = j["request"]["id"]
        t1, t2 = [t["id"] for t in j["tasks"]]
        # hire
        h = self.c.post("/api/departments/engine-maintenance/hire",
                        json={"name": "Ravi", "role": "Analyst", "reason": "need one", "task_id": t1})
        self.assertEqual(h.status_code, 201)
        self.assertEqual(self.c.get(f"/api/tasks/{t1}").json()["agent_name"], "Ravi")
        # status needs note
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "done", "note": ""}).status_code, 400)
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "x", "note": "n"}).status_code, 400)
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "in_progress", "note": "go"}).status_code, 200)
        # instruction
        i = self.c.post("/api/instructions", json={"target": "chief", "text": "Cancel crew training", "work_request_id": wid})
        self.assertEqual(i.status_code, 201)
        self.assertEqual(i.json()["brief"]["version"], 2)
        self.assertEqual(i.json()["blocked_tasks"], [t2])
        self.assertEqual(self.c.post("/api/instructions", json={"target": "nope", "text": "x"}).status_code, 404)
        self.assertEqual(self.c.post("/api/instructions", json={"target": "chief", "text": ""}).status_code, 400)
        # finish
        self.c.post(f"/api/tasks/{t1}/status", json={"status": "done", "note": "ok"})
        self.c.post(f"/api/tasks/{t2}/status", json={"status": "done", "note": "skipped"})
        d = self.c.get(f"/api/work-requests/{wid}").json()
        self.assertEqual(d["request"]["status"], "Done")
        self.assertEqual(d["report"]["recipient"], "owner")
        ov = self.c.get("/api/overview").json()
        self.assertEqual(ov["counts"]["tasks"]["done"], 2)
        self.assertEqual(self.c.get("/api/tasks?status=done").json().__len__(), 2)
        self.assertEqual(len(self.c.get("/api/work-requests").json()), 1)
        # messages
        self.assertTrue(self.c.get(f"/api/messages?task={t1}").json())
        self.assertTrue(self.c.get("/api/messages?dept=engine-maintenance").json())
        self.assertTrue(self.c.get("/api/messages?agent=chief").json())

    def test_async_submit_and_no_dept_match(self):
        self.add_dept("Engine Maintenance", "Asha")
        r = self.c.post("/api/work-requests", json={"text": "wildlife bird strike review"})
        self.assertEqual(r.status_code, 201)
        d = self.c.get(f"/api/work-requests/{r.json()['id']}").json()
        self.assertTrue(d["brief"]["needs_department"])
        self.assertEqual(d["tasks"], [])
        self.assertEqual(self.c.post("/api/work-requests", json={"text": " "}).status_code, 400)
        self.assertEqual(self.c.post("/api/work-requests", json={}).status_code, 422)
        self.assertEqual(self.c.get("/api/work-requests/WR-99").status_code, 404)

    def test_hire_cap_409_and_assign_errors(self):
        self.add_dept("Ops", "Om")
        for i in range(4):
            self.assertEqual(self.c.post("/api/departments/ops/hire",
                                         json={"name": f"A{i}", "role": "r", "reason": "w"}).status_code, 201)
        r = self.c.post("/api/departments/ops/hire", json={"name": "Z", "role": "r", "reason": "w"})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.c.get("/api/messages?dept=ops").json()[-1]["kind"] == "refusal")
        self.assertEqual(self.c.post("/api/tasks/TK-1/assign", json={"agent_id": "chief"}).status_code, 404)


class EventTests(ApiBase):
    def test_sse_replays_events(self):
        self.add_dept("Ops", "Om")
        with self.c.stream("GET", "/api/events?since_id=0&max_seconds=0") as r:
            self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
            body = "".join(r.iter_text())
        self.assertIn("event: department.created", body)
        self.assertIn("event: message.created", body)
        self.assertIn("\nid: ", body)

    def test_cors_header(self):
        r = self.c.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(r.headers["access-control-allow-origin"], "http://localhost:5173")


class BoardTests(ApiBase):
    def test_parse_board_lines(self):
        text = ("[b-1] thread b-1 \u00b7 ops \u2192 fuel \u00b7 request \u00b7 open \u00b7 Need data\n"
                "    Please send Q3 numbers\nnoise\n")
        self.assertEqual(parse_board(text), [{"id": "b-1", "from": "ops", "to": "fuel", "ts": "",
                                              "text": "Need data: Please send Q3 numbers"}])

    def test_mirror_real_kb_board(self):
        self.add_dept("Ops", "Om", "o", "ops.pdf")
        self.add_dept("Fuel", "Fay", "f", "fuel.pdf")
        self.app.state.kb.run("board", "post", "--from", "ops", "--to", "fuel", "--subject", "Burn data",
                              "--text", "Need Q3 fuel burn")
        self.c.get("/api/messages")
        self.c.get("/api/messages")  # idempotent
        board = [m for m in self.c.get("/api/messages").json() if m["kind"] == "board"]
        self.assertEqual(len(board), 1)
        self.assertIn("Burn data", board[0]["body"])

    def test_unreadable_pdf_creates_nothing(self):
        r = self.c.post("/api/departments", data={"name": "Bad", "head_name": "B"},
                        files=[("files", ("bad.pdf", PDF, "application/pdf"))])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.get("/api/departments").json(), [])

    def test_match_report_via_kb(self):
        self.add_dept("Ops", "Om", "o", "ops_manual_rev1.pdf")
        m = self.app.state.kb.match([("ops_manual_rev2.pdf", pdf("o2")), ("ops_manual_rev1.pdf", pdf("o")),
                                     ("other.pdf", pdf("x"))], ["ops"])
        self.assertEqual([x["result"] for x in m], ["new_version", "duplicate", "new"])
        self.assertEqual(m[0]["existing_dept"], "ops")


if __name__ == "__main__":
    unittest.main()
