import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.fsa.planner import ClaudePlanner, KeywordPlanner, default_planner, tokens  # noqa: E402
from backend.fsa.store import Conflict, Invalid, Store  # noqa: E402
from backend.fsa.workflow import Workflow  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(os.path.join(self.tmp.name, "fsa.db"))
        self.w = Workflow(self.s, KeywordPlanner(), message_cap=5)
        self.s.create_department("Engine Maintenance", "Asha Verma")
        self.s.create_department("Crew Training", "Kabir Singh")

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def plan(self, text):
        wr = self.w.submit_work_request(text)
        self.w.chief_plan(wr["id"])
        return wr["id"]


class WorkRequestTests(Base):
    def test_submit_received_and_message_to_chief(self):
        wr = self.w.submit_work_request("Engine inspection karo")
        self.assertEqual(wr["status"], "Received")
        m = self.s.list_messages(work_request_id=wr["id"])[0]
        self.assertEqual((m["sender"], m["recipient"]), ("owner", "chief"))
        with self.assertRaises(Invalid):
            self.w.submit_work_request("  ")

    def test_plan_creates_versioned_brief_and_tasks(self):
        wid = self.plan("Please check engine maintenance backlog and crew training records")
        d = self.w.request_detail(wid)
        self.assertEqual(d["request"]["status"], "Briefed")
        self.assertEqual(d["brief"]["version"], 1)
        self.assertCountEqual(d["brief"]["departments"], ["engine-maintenance", "crew-training"])
        self.assertEqual(len(d["tasks"]), 2)
        for t in d["tasks"]:
            self.assertEqual(t["status"], "todo")
            self.assertTrue(t["acceptance"])
        self.assertEqual(self.w.chief_plan(wid)["version"], 1)  # idempotent

    def test_hinglish_request_matches(self):
        wid = self.plan("Engine maintenance ka audit karwao jaldi")
        self.assertEqual([t["dept"] for t in self.s.list_tasks(work_request_id=wid)], ["engine-maintenance"])

    def test_no_matching_department(self):
        wid = self.plan("Review bird strike wildlife hazard around runway")
        d = self.w.request_detail(wid)
        self.assertTrue(d["brief"]["needs_department"])
        self.assertIn("Which department", d["brief"]["question"])
        self.assertEqual(d["tasks"], [])
        msgs = self.s.list_messages(work_request_id=wid, kind="brief")
        self.assertEqual(msgs[0]["recipient"], "owner")

    def test_no_departments_at_all(self):
        s2 = Store(os.path.join(self.tmp.name, "b.db"))
        w2 = Workflow(s2, KeywordPlanner())
        wr = w2.submit_work_request("anything")
        self.assertTrue(w2.chief_plan(wr["id"])["needs_department"])
        s2.close()


class TaskRunTests(Base):
    def test_status_flow_notes_messages_events_and_done_report(self):
        wid = self.plan("engine maintenance backlog")
        tid = self.s.list_tasks(work_request_id=wid)[0]["id"]
        ev0 = self.s.last_event_id()
        with self.assertRaises(Invalid):
            self.w.update_task(tid, "in_progress", "")
        self.w.update_task(tid, "in_progress", "starting")
        self.assertEqual(self.s.get_work_request(wid)["status"], "In progress")
        self.w.update_task(tid, "blocked", "waiting for parts")
        self.w.update_task(tid, "review", "parts arrived")
        self.assertEqual(len(self.s.get_task(tid)["notes"]), 3)
        self.assertGreater(self.s.last_event_id(), ev0)
        self.assertIsNone(self.w.request_detail(wid)["report"])
        self.w.update_task(tid, "done", "all engines inspected")
        d = self.w.request_detail(wid)
        self.assertEqual(d["request"]["status"], "Done")
        self.assertEqual(d["request"]["progress"]["percent"], 100)
        self.assertIn("all engines inspected", d["report"]["body"])
        self.assertEqual((d["report"]["sender"], d["report"]["recipient"]), ("chief", "owner"))
        with self.assertRaises(Conflict):
            self.w.update_task(tid, "done", "again")
        self.assertGreater(d["request"]["turns"], 0)

    def test_report_only_after_last_task(self):
        wid = self.plan("engine maintenance and crew training")
        a, b = [t["id"] for t in self.s.list_tasks(work_request_id=wid)]
        self.w.update_task(a, "done", "ok")
        self.assertEqual(self.s.get_work_request(wid)["status"], "In progress")
        self.assertEqual(self.s.get_work_request(wid)["progress"]["percent"], 50)
        self.assertIsNone(self.w.request_detail(wid)["report"])
        self.w.update_task(b, "done", "ok")
        self.assertIsNotNone(self.w.request_detail(wid)["report"])

    def test_hire_and_assign(self):
        wid = self.plan("engine maintenance")
        tid = self.s.list_tasks(work_request_id=wid)[0]["id"]
        a = self.w.hire("engine-maintenance", "Ravi", "Borescope analyst", "needs specialist", tid)
        self.assertEqual(self.s.get_task(tid)["agent_id"], a["id"])
        org = self.s.org_chart()["departments"][0]
        self.assertEqual([x["name"] for x in org["agents"]], ["Ravi"])
        for i in range(3):
            self.w.hire("engine-maintenance", f"X{i}", "r", "why")
        with self.assertRaises(Conflict):
            self.w.hire("engine-maintenance", "Over", "r", "why")
        self.assertTrue(self.s.list_messages(kind="refusal"))

    def test_message_cap(self):
        wid = self.plan("engine maintenance")
        tid = self.s.list_tasks(work_request_id=wid)[0]["id"]
        head = self.s.get_department("engine-maintenance")["head_id"]
        hired = self.w.hire("engine-maintenance", "Ravi", "r", "why", tid)["id"]  # 1 assign + 1 hire + 1 brief-assign
        base = self.s.count_task_messages(tid)
        for i in range(5 - base):
            self.w.post_task_message(head, hired, tid, f"m{i}")
        with self.assertRaises(Conflict):
            self.w.post_task_message(hired, head, tid, "too many")


class InstructionTests(Base):
    def test_instruction_to_chief_creates_new_brief_version_and_blocks_conflict(self):
        wid = self.plan("engine maintenance and crew training")
        tasks = self.s.list_tasks(work_request_id=wid)
        eng = [t for t in tasks if t["dept"] == "engine-maintenance"][0]
        self.w.update_task(eng["id"], "in_progress", "go")
        r = self.w.send_instruction("chief", "Stop the engine maintenance work, cancel it", wid)
        self.assertEqual(r["message"]["sender"], "owner")
        self.assertEqual(r["brief"]["version"], 2)
        self.assertIn("Owner instruction", r["brief"]["change_note"])
        self.assertEqual(r["blocked_tasks"], [eng["id"]])
        t = self.s.get_task(eng["id"])
        self.assertEqual(t["status"], "blocked")
        self.assertIn("Conflicts", t["notes"][-1]["note"])
        crew = [x for x in tasks if x["dept"] == "crew-training"][0]
        self.assertEqual(self.s.get_task(crew["id"])["status"], "todo")

    def test_instruction_to_department_adds_task_and_reopens(self):
        wid = self.plan("engine maintenance")
        tid = self.s.list_tasks(work_request_id=wid)[0]["id"]
        self.w.update_task(tid, "done", "ok")
        self.assertEqual(self.s.get_work_request(wid)["status"], "Done")
        r = self.w.send_instruction("crew-training", "Also run crew training refresher")
        self.assertEqual(r["brief"]["version"], 2)
        self.assertEqual(self.s.get_work_request(wid)["status"], "In progress")
        self.assertEqual(len(self.s.list_tasks(work_request_id=wid)), 2)
        head = self.s.get_department("crew-training")["head_id"]
        self.assertTrue(any(m["recipient"] == head and m["sender"] == "owner"
                            for m in self.s.list_messages(kind="instruction")))

    def test_instruction_without_work_and_validation(self):
        r = self.w.send_instruction("chief", "hello chief")
        self.assertIsNone(r["brief"])
        with self.assertRaises(Invalid):
            self.w.send_instruction("chief", " ")
        with self.assertRaises(Exception):
            self.w.send_instruction("nope", "x")
        self.s.retire_department("crew-training")
        with self.assertRaises(Conflict):
            self.w.send_instruction("crew-training", "x")

    def test_instruction_without_task_changes(self):
        wid = self.plan("engine maintenance")
        r = self.w.send_instruction("chief", "please be extra careful", wid)
        self.assertEqual(r["brief"]["version"], 2)
        self.assertEqual(r["blocked_tasks"], [])


class BoardSyncTests(Base):
    def test_sync_board_idempotent(self):
        entries = [{"id": 1, "from": "Engine Maintenance", "to": "crew-training", "text": "need crew list"},
                   {"id": 2, "from": "crew-training", "to": "engine-maintenance", "text": "sent"},
                   {"id": 3, "from": "x", "to": "y", "text": ""}]
        self.assertEqual(self.w.sync_board(entries), 2)
        self.assertEqual(self.w.sync_board(entries), 0)
        msgs = self.s.list_messages(kind="board")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["sender_name"], "Asha Verma")
        self.assertEqual(msgs[0]["recipient_name"], "Kabir Singh")


class PlannerTests(unittest.TestCase):
    def test_tokens_and_default(self):
        self.assertIn("engin", tokens("Engines please"))
        self.assertIsInstance(default_planner(), (KeywordPlanner, ClaudePlanner))

    def test_claude_planner_fallback_and_stub_client(self):
        depts = [{"id": "ops", "name": "Ops", "head_name": "O", "keywords": "runway"}]
        p = ClaudePlanner(client=None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertEqual(p.plan("runway check", depts).tasks[0].dept, "ops")
        self.assertEqual(p.replan("t", "stop runway", depts, [{"id": "TK-1", "title": "Ops runway",
                                                                 "status": "todo", "dept": "ops"}])
                         .conflicting_task_ids, ["TK-1"])

        class Msg:
            content = [type("B", (), {"text": '{"summary":"s","goals":["g"],"needs_department":false,'
                                              '"tasks":[{"title":"T","dept":"ops"},{"title":"bad","dept":"zz"}]}'})]

        class Client:
            class messages:
                @staticmethod
                def create(**kw):
                    return Msg

        plan = ClaudePlanner(client=Client).plan("x", depts)
        self.assertEqual([t.dept for t in plan.tasks], ["ops"])

        class Bad:
            class messages:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("down")

        self.assertEqual(ClaudePlanner(client=Bad).plan("runway", depts).tasks[0].dept, "ops")


if __name__ == "__main__":
    unittest.main()
