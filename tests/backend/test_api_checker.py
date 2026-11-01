"""Dashboard API for the File Checker, models and learned links (backend/API.md)."""
import unittest

from helpers import start_server

from backend.fsa.loop import AGENT_TYPES


class ApiCheckerTests(unittest.TestCase):
    def setUp(self):
        self.app, self.c, self.tmp = start_server(self, agent_mode=True)

    def test_org_and_overview_show_the_file_checker(self):
        org = self.c.get("/api/org").json()
        self.assertEqual((org["checker"]["name"], org["checker"]["role"]), ("File Checker", "Documentation Controller"))
        self.assertEqual(self.c.get("/api/overview").json()["checker"]["id"], "checker")
        self.assertEqual(self.c.post("/api/agents/checker/retire").status_code, 409)
        r = self.c.post("/api/agents/checker/rename", json={"name": "Meera Iyer"})
        self.assertEqual(r.json()["name"], "Meera Iyer")
        self.assertEqual(self.c.get("/api/org").json()["checker"]["name"], "Meera Iyer")

    def test_models_read_and_change(self):
        m = self.c.get("/api/models").json()
        self.assertEqual(set(m["roles"]), {"chief", "checker", "head", "hired"})
        self.assertTrue(all(v["setting"] == "inherit" for v in m["roles"].values()))
        self.assertEqual({o["id"] for o in m["options"]}, {"inherit", "haiku", "sonnet", "opus"})
        r = self.c.post("/api/models", json={"preset": "recommended"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["roles"]["checker"]["setting"], "opus")
        self.assertEqual(r.json()["preset"], "recommended")
        r = self.c.post("/api/models", json={"roles": {"head": "haiku"}})
        self.assertEqual(r.json()["roles"]["head"]["setting"], "haiku")
        self.assertEqual(self.c.get("/api/models").json()["roles"]["chief"]["setting"], "opus")
        self.assertEqual(self.c.post("/api/models", json={}).status_code, 422)
        self.assertEqual(self.c.post("/api/models", json={"preset": "turbo"}).status_code, 400)
        self.assertEqual(self.c.post("/api/models", json={"roles": {"chief": "gpt"}}).status_code, 400)
        self.assertEqual(self.c.get("/api/models", token=False).status_code, 401)

    def test_links_and_source_packs_endpoints(self):
        self.assertEqual(self.c.get("/api/links").json(), {"links": [], "ignored": []})
        self.assertEqual(self.c.get("/api/source-packs").json(), [])
        d, h = self.app.store.create_department("Engine Maintenance", "Asha Verma")
        wr = self.app.wf.submit_work_request("Engine check")
        self.app.wf.submit_brief(wr["id"], "Plan", tasks=[{"title": "Engine backlog", "dept": d["id"]}])
        t = self.c.get("/api/tasks/TK-1").json()
        self.assertIsNone(t["source_pack"])  # not checked yet: the department waits
        self.assertEqual(self.app.store.list_messages(kind="assign"), [])
        self.app.store.save_source_pack("TK-1", "checker", "s", "none", ["no manuals"], [])
        self.assertEqual(self.c.get("/api/tasks/TK-1").json()["source_pack"]["coverage"], "none")
        self.assertEqual(self.c.get("/api/source-packs?work_request_id=WR-1").json()[0]["issues"], ["no manuals"])
        self.assertIn("File Checker", [w["agent_name"] for w in self.app.office.activity()["waiting"]])
        self.assertEqual(AGENT_TYPES["checker"], "flight-safety-agents:file-checker")


if __name__ == "__main__":
    unittest.main()
