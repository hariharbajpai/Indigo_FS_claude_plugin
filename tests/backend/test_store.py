import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.fsa import store as S  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "t", "fsa.db")
        self.s = S.Store(self.path)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_chief_seeded_once_and_not_retirable(self):
        self.s.seed_chief()
        self.s.close()
        self.s = S.Store(self.path)
        chiefs = [a for a in self.s.list_agents() if a["kind"] == "chief"]
        self.assertEqual(len(chiefs), 1)
        self.assertEqual(chiefs[0]["name"], "Dhruv Rebbapragada")
        with self.assertRaises(S.Conflict):
            self.s.retire_agent("chief")
        self.assertEqual(self.s.org_chart()["chief"]["id"], "chief")

    def test_department_needs_head_and_name(self):
        with self.assertRaises(S.Invalid):
            self.s.create_department("Eng", " ")
        with self.assertRaises(S.Invalid):
            self.s.create_department("", "Asha")

    def test_create_duplicate_and_retire_cascade(self):
        d, h = self.s.create_department("Engine Maintenance", "Asha Verma")
        self.assertEqual(d["id"], "engine-maintenance")
        self.assertEqual(h["kind"], "head")
        with self.assertRaises(S.Conflict):
            self.s.create_department("engine maintenance", "X")
        a = self.s.hire_agent(d["id"], "Ravi", "Analyst", "needed")
        t = self.s.create_task("Do it", d["id"])
        _, ids = self.s.retire_department(d["id"])
        self.assertCountEqual(ids, [h["id"], a["id"]])
        self.assertEqual(self.s.get_agent(a["id"])["status"], "retired")
        self.assertEqual(self.s.get_task(t["id"])["status"], "blocked")
        self.assertEqual(self.s.org_chart()["departments"], [])
        with self.assertRaises(S.Conflict):
            self.s.retire_department(d["id"])
        d2, _ = self.s.create_department("Engine Maintenance", "New Head")
        self.assertEqual(d2["id"], "engine-maintenance-2")

    def test_head_cannot_be_retired_alone(self):
        d, h = self.s.create_department("Ops", "Om")
        with self.assertRaises(S.Conflict):
            self.s.retire_agent(h["id"])
        a = self.s.hire_agent("ops", "Z", "r", "why")
        self.assertEqual(self.s.retire_agent(a["id"])["status"], "retired")

    def test_hire_cap_enforced_and_logged(self):
        d, h = self.s.create_department("Ops", "Om")
        for i in range(4):
            self.s.hire_agent("ops", f"A{i}", "role", "reason")
        with self.assertRaises(S.Conflict):
            self.s.hire_agent("ops", "Extra", "role", "reason")
        self.assertEqual(self.s.active_count("ops"), 5)
        self.assertTrue(self.s.list_messages(kind="refusal"))
        self.assertIn("agent.hire_refused", [e["type"] for e in self.s.list_events()])
        with self.assertRaises(S.Invalid):
            self.s.hire_agent("ops", "", "r", "w")
        org = self.s.org_chart()["departments"][0]
        self.assertEqual(len(org["agents"]), 4)

    def test_hire_with_task_assigns(self):
        self.s.create_department("Ops", "Om")
        t = self.s.create_task("T", "ops")
        a = self.s.hire_agent("ops", "Ravi", "r", "why", task_id=t["id"])
        t = self.s.get_task(t["id"])
        self.assertEqual(t["agent_id"], a["id"])
        self.assertTrue(self.s.list_messages(task=t["id"], kind="assign"))
        other, _ = self.s.create_department("Other", "O")
        with self.assertRaises(S.Conflict):
            self.s.assign_task(t["id"], self.s.list_agents(dept="other")[0]["id"])

    def test_task_status_needs_note_and_writes_history(self):
        self.s.create_department("Ops", "Om")
        t = self.s.create_task("T", "ops", acceptance="ok")
        with self.assertRaises(S.Invalid):
            self.s.set_task_status(t["id"], "done", " ")
        with self.assertRaises(S.Invalid):
            self.s.set_task_status(t["id"], "bogus", "n")
        t = self.s.set_task_status(t["id"], "in_progress", "started")
        self.assertEqual(t["notes"][0]["note"], "started")
        self.assertEqual(len(self.s.list_messages(task=t["id"])), 1)
        self.assertEqual(len(self.s.list_tasks(status="in_progress")), 1)

    def test_work_request_brief_versions_and_progress(self):
        w = self.s.create_work_request("check things")
        self.assertEqual(w["status"], "Received")
        with self.assertRaises(S.Invalid):
            self.s.create_work_request("")
        b1 = self.s.add_brief(w["id"], "s", ["g"], [])
        b2 = self.s.add_brief(w["id"], "s2", ["g"], ["ops"], change_note="x")
        self.assertEqual((b1["version"], b2["version"]), (1, 2))
        self.assertEqual(len(self.s.list_briefs(w["id"])), 2)
        self.assertEqual(self.s.get_work_request(w["id"])["brief_version"], 2)
        self.s.create_department("Ops", "Om")
        t = self.s.create_task("T", "ops", work_request_id=w["id"])
        self.s.set_task_status(t["id"], "done", "ok")
        self.assertEqual(self.s.get_work_request(w["id"])["progress"]["percent"], 100)
        self.assertEqual(self.s.set_wr_status(w["id"], "Briefed")["status"], "Briefed")
        with self.assertRaises(S.NotFound):
            self.s.get_work_request("WR-99")
        with self.assertRaises(S.NotFound):
            self.s.get_task("nope")

    def test_messages_filters_and_ref_dedupe(self):
        d, h = self.s.create_department("Ops", "Om")
        d2, h2 = self.s.create_department("Fuel", "Fay")
        m = self.s.add_message(h["id"], h2["id"], "hi", kind="board", ref="board:1")
        self.assertIsNone(self.s.add_message(h["id"], h2["id"], "hi", ref="board:1"))
        self.assertEqual(len(self.s.list_messages(agent=h2["id"], kind="board")), 1)
        self.assertTrue(any(x["id"] == m["id"] for x in self.s.list_messages(dept="fuel")))
        self.assertEqual(m["sender_name"], "Om")
        with self.assertRaises(S.Invalid):
            self.s.add_message("owner", "chief", " ")

    def test_persistence_across_reopen_and_overview(self):
        self.s.create_department("Ops", "Om")
        self.s.create_work_request("w")
        self.s.close()
        self.s = S.Store(self.path)
        ov = self.s.overview()
        self.assertEqual(ov["counts"]["departments"], 1)
        self.assertEqual(ov["counts"]["work_requests"], 1)
        self.assertGreater(ov["last_event_id"], 0)


if __name__ == "__main__":
    unittest.main()
