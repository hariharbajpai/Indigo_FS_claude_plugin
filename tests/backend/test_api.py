"""Dashboard server (backend/fsa/server.py) against backend/API.md, over real HTTP."""
import os
import unittest

from helpers import HAS_PDFTOTEXT, PDF, pdf, start_server

from backend.fsa.kb_bridge import parse_board
from backend.fsa.planner import KeywordPlanner


@unittest.skipUnless(HAS_PDFTOTEXT, "kb.py needs pdftotext (or pypdf/PyMuPDF)")
class ApiBase(unittest.TestCase):
    agent_mode = False  # most API tests use the offline planner; AgentModeTests cover the plugin's mode

    def setUp(self):
        self.app, self.c, self.tmp = start_server(self, planner=KeywordPlanner(), agent_mode=self.agent_mode)

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
        self.assertEqual(self.add_dept("", "A").status_code, 400)
        r = self.c.post("/api/departments", data={"name": "E", "head_name": "A"},
                        files=[("files", ("x.txt", b"hello", "text/plain"))])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.add_dept("E", "A", decision="bogus").status_code, 400)
        self.assertEqual(self.c.post("/api/departments", json={"name": "x"}).status_code, 400)

    def test_create_ok_and_org(self):
        r = self.add_dept("Engine Maintenance", "Asha Verma")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["head"]["name"], "Asha Verma")
        self.assertEqual(r.json()["documents"], ["manual"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "kb", "engine-maintenance", "manual", "_doc.md")))
        org = self.c.get("/api/org").json()
        self.assertEqual(org["departments"][0]["head"]["name"], "Asha Verma")
        self.assertEqual(len(self.c.get("/api/departments").json()), 1)

    def test_upload_keeps_pdf_bytes_exact(self):
        self.add_dept("Engine Maintenance", "Asha")
        # same bytes again -> the KB sees an identical file (proves the multipart parser keeps bytes intact)
        r = self.add_dept("Other", "Bob", content="a")
        self.assertEqual(r.json()["matches"][0]["result"], "duplicate")

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
        self.assertEqual(self.add_dept("Other", "Bob", content="b", decision="new").status_code, 201)
        r = self.add_dept("x", "y", content="c", decision="replace", target="engine-maintenance")
        self.assertEqual(r.json()["status"], "replaced")
        r = self.add_dept("x", "y", content="c", decision="replace", target="zzz")
        self.assertEqual(r.status_code, 400)

    def test_replace_and_retire(self):
        self.add_dept("Ops", "Om")
        r = self.c.post("/api/departments/ops/replace", files=[("files", ("new.pdf", pdf("n"), "application/pdf"))])
        self.assertEqual(r.json()["status"], "replaced")
        self.assertEqual(self.app.kb.list_docs("ops"), ["manual", "new"])
        self.assertEqual(self.c.post("/api/departments/ops/replace").status_code, 400)
        self.c.post("/api/departments/ops/hire", json={"name": "Z", "role": "r", "reason": "w"})
        r = self.c.post("/api/departments/ops/retire")
        self.assertEqual(len(r.json()["retired_agents"]), 2)
        self.assertEqual(self.c.get("/api/org").json()["departments"], [])
        self.assertEqual(self.c.post("/api/departments/ops/retire").status_code, 409)
        self.assertEqual(self.c.post("/api/departments/ops/replace",
                                     files=[("files", ("n.pdf", pdf("z"), "application/pdf"))]).status_code, 409)
        self.assertEqual(self.app.kb.list_docs("ops"), [])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "kb", "ops", "_superseded")))
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
        h = self.c.post("/api/departments/engine-maintenance/hire",
                        json={"name": "Ravi", "role": "Analyst", "reason": "need one", "task_id": t1})
        self.assertEqual(h.status_code, 201)
        self.assertEqual(self.c.get(f"/api/tasks/{t1}").json()["agent_name"], "Ravi")
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "done", "note": ""}).status_code, 400)
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "x", "note": "n"}).status_code, 400)
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "in_progress"}).status_code, 422)
        self.assertEqual(self.c.post(f"/api/tasks/{t1}/status", json={"status": "in_progress", "note": "go"}).status_code, 200)
        i = self.c.post("/api/instructions", json={"target": "chief", "text": "Cancel crew training", "work_request_id": wid})
        self.assertEqual(i.status_code, 201)
        self.assertEqual(i.json()["brief"]["version"], 2)
        self.assertEqual(i.json()["blocked_tasks"], [t2])
        self.assertEqual(self.c.post("/api/instructions", json={"target": "nope", "text": "x"}).status_code, 404)
        self.assertEqual(self.c.post("/api/instructions", json={"target": "chief", "text": ""}).status_code, 400)
        self.c.post(f"/api/tasks/{t1}/status", json={"status": "done", "note": "ok"})
        self.c.post(f"/api/tasks/{t2}/status", json={"status": "done", "note": "skipped"})
        d = self.c.get(f"/api/work-requests/{wid}").json()
        self.assertEqual(d["request"]["status"], "Done")
        self.assertEqual(d["report"]["recipient"], "owner")
        self.assertEqual(self.c.get("/api/overview").json()["counts"]["tasks"]["done"], 2)
        self.assertEqual(len(self.c.get("/api/tasks?status=done").json()), 2)
        self.assertEqual(len(self.c.get("/api/work-requests").json()), 1)
        self.assertTrue(self.c.get(f"/api/messages?task={t1}").json())
        self.assertTrue(self.c.get("/api/messages?dept=engine-maintenance").json())
        self.assertTrue(self.c.get("/api/messages?agent=chief").json())
        self.assertEqual(self.c.get("/api/messages?limit=6000").status_code, 422)

    def test_submit_no_dept_match_and_validation(self):
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
        self.assertEqual(self.c.get("/api/messages?dept=ops").json()[-1]["kind"], "refusal")
        self.assertEqual(self.c.post("/api/tasks/TK-1/assign", json={"agent_id": "chief"}).status_code, 404)


class AgentModeTests(ApiBase):
    agent_mode = True

    def test_work_waits_for_the_chief_agent(self):
        self.add_dept("Engine Maintenance", "Asha")
        r = self.c.post("/api/work-requests", json={"text": "Engine backlog check karo"})
        self.assertEqual(r.status_code, 201)
        self.assertIn("/flight-safety-agents:run", r.json()["hint"])
        d = self.c.get(f"/api/work-requests/{r.json()['id']}").json()
        self.assertIsNone(d["brief"])  # the Chief subagent writes it
        act = self.c.get("/api/activity").json()
        self.assertEqual([a["agent_id"] for a in act["waiting"]], ["chief"])
        ov = self.c.get("/api/overview").json()
        self.assertEqual(ov["activity"]["waiting"][0]["agent_name"], "Dhruv Rebbapragada")
        i = self.c.post("/api/instructions", json={"target": "engine-maintenance", "text": "Pehle A320 fleet"})
        self.assertEqual(i.status_code, 201)
        self.assertIsNone(i.json()["brief"])
        kinds = [(m["recipient"], m["kind"]) for m in self.c.get("/api/messages").json() if m["sender"] == "owner"]
        self.assertIn(("chief", "instruction"), kinds)


class SecurityAndUiTests(unittest.TestCase):
    def setUp(self):
        self.app, self.c, self.tmp = start_server(self)

    def test_token_required_except_health(self):
        self.assertEqual(self.c.get("/api/health", token=False).status_code, 200)
        r = self.c.get("/api/overview", token=False)
        self.assertEqual(r.status_code, 401)
        self.assertIn("/flight-safety-agents:start", r.json()["detail"])
        self.assertEqual(self.c.get("/api/overview", headers={"X-FSA-Token": "wrong"}).status_code, 401)
        self.assertEqual(self.c.get("/api/overview?token=test-token", token=False).status_code, 200)
        self.assertEqual(self.c.post("/api/work-requests", json={"text": "x"}, token=False).status_code, 401)

    def test_only_local_hosts(self):
        self.assertEqual(self.c.get("/api/health", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.c.get("/api/health", headers={"Host": "localhost:1234"}).status_code, 200)

    def test_ui_and_spa_routes(self):
        for path in ("/", "/board", "/org"):
            r = self.c.get(path, token=False)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("text/html", r.headers["Content-Type"])
            self.assertIn('<div id="root">', r.text)
        r = self.c.get("/../../etc/passwd", token=False)
        self.assertIn('<div id="root">', r.text)  # never a file outside the UI folder
        self.assertEqual(self.c.get("/api/nope").status_code, 404)
        self.assertEqual(self.c.post("/api/overview").status_code, 405)
        self.assertEqual(self.c.post("/api/work-requests", data={"x": "1"}).status_code, 422)

    def test_sse_replays_events(self):
        self.c.post("/api/work-requests", json={"text": "hello"})
        r = self.c.get("/api/events?since_id=0&max_seconds=0")
        self.assertTrue(r.headers["Content-Type"].startswith("text/event-stream"))
        self.assertIn("event: work_request.created", r.text)
        self.assertIn("event: message.created", r.text)
        self.assertIn("\nid: ", r.text)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.app, self.c, self.tmp = start_server(self)
        from backend.fsa import office
        self.c.post("/api/work-requests", json={"text": "PPT banao"})
        self.path = os.path.join(self.tmp, "kb", "_outputs", "WR-1", "Deck.pptx")
        os.makedirs(os.path.dirname(self.path))
        office.build(self.path, "pptx", "Deck", {"slides": [{"title": "One", "bullets": ["a"]}]})
        self.f = self.app.store.add_file(self.path, "pptx", "Deck", "WR-1", None, "chief", os.path.getsize(self.path))

    def test_list_detail_and_download(self):
        files = self.c.get("/api/files?work_request_id=WR-1").json()
        self.assertEqual([(f["name"], f["format"], f["created_by_name"]) for f in files],
                         [("Deck.pptx", "pptx", "Dhruv Rebbapragada")])
        self.assertEqual(self.c.get("/api/work-requests/WR-1").json()["files"][0]["path"], self.path)
        r = self.c.get(f"/api/files/{self.f['id']}/download")
        self.assertEqual(r.status_code, 200)
        self.assertIn("presentationml", r.headers["Content-Type"])
        self.assertIn('filename="Deck.pptx"', r.headers["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"PK"))
        self.assertEqual(self.c.get(f"/api/files/{self.f['id']}/download", token=False).status_code, 401)
        self.assertEqual(self.c.get(f"/api/files/{self.f['id']}/download?token=test-token", token=False).status_code, 200)
        self.assertEqual(self.c.get("/api/files/999/download").status_code, 404)
        self.assertEqual(self.c.get("/api/files/abc/download").status_code, 404)
        os.remove(self.path)
        self.assertEqual(self.c.get(f"/api/files/{self.f['id']}/download").status_code, 404)


@unittest.skipUnless(HAS_PDFTOTEXT, "kb.py needs pdftotext (or pypdf/PyMuPDF)")
class BoardTests(ApiBase):
    def test_parse_board_lines(self):
        text = ("[b-1] thread b-1 · ops → fuel · request · open · Need data\n"
                "    Please send Q3 numbers\nnoise\n")
        self.assertEqual(parse_board(text), [{"id": "b-1", "from": "ops", "to": "fuel", "ts": "",
                                              "text": "Need data: Please send Q3 numbers"}])

    def test_mirror_real_kb_board(self):
        self.add_dept("Ops", "Om", "o", "ops.pdf")
        self.add_dept("Fuel", "Fay", "f", "fuel.pdf")
        self.app.kb.run("board", "post", "--from", "ops", "--to", "fuel", "--subject", "Burn data",
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
        m = self.app.kb.match([("ops_manual_rev2.pdf", pdf("o2")), ("ops_manual_rev1.pdf", pdf("o")),
                               ("other.pdf", pdf("x"))], ["ops"])
        self.assertEqual([x["result"] for x in m], ["new_version", "duplicate", "new"])
        self.assertEqual(m[0]["existing_dept"], "ops")


if __name__ == "__main__":
    unittest.main()
