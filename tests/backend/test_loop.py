"""The work loop (backend/fsa/loop.py): who wakes, parallel runs, permissions, budget, agent tools."""
import os
import tempfile
import unittest

from helpers import HAS_PDFTOTEXT, pdf

from backend.fsa import loop as loopmod
from backend.fsa.kb_bridge import KbBridge
from backend.fsa.loop import AGENT_TYPES, Office
from backend.fsa.store import Conflict, Invalid, Store
from backend.fsa.workflow import Workflow


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(os.path.join(self.tmp.name, "fsa.db"))
        self.addCleanup(self.s.close)
        self.kb = KbBridge(os.path.join(self.tmp.name, "kb"))
        self.w = Workflow(self.s, agent_mode=True)
        self.o = Office(self.s, self.w, self.kb)
        self.eng, self.asha = self.s.create_department("Engine Maintenance", "Asha Verma")
        self.crew, self.kabir = self.s.create_department("Crew Training", "Kabir Singh")

    def run_one(self, expect_agent):
        nw = self.o.next_work()
        self.assertEqual(nw["status"], "work", nw)
        agents = [a["agent"] for a in nw["activations"]]
        self.assertIn(AGENT_TYPES[expect_agent], agents)
        return nw["activations"]

    def brief(self, aid, wid="WR-1"):
        return self.o.tool_submit_brief(aid, wid, "Plan", ["g"], [
            {"title": "Engine backlog", "dept": "engine-maintenance", "acceptance": "list"},
            {"title": "Crew records", "dept": "crew-training", "acceptance": "list"}])


class WakeTests(Base):
    def test_no_run_before_work_and_welcome_notes_do_not_wake(self):
        nw = self.o.next_work()
        self.assertEqual(nw["status"], "no_run")
        self.assertIn("/flight-safety-agents:work", nw["message"])

    def test_no_run_without_departments(self):
        s = Store(os.path.join(self.tmp.name, "empty.db"))
        self.addCleanup(s.close)
        o = Office(s, Workflow(s, agent_mode=True), self.kb)
        self.assertIn("add-dept", o.next_work()["message"])

    def test_chief_then_heads_in_parallel_then_review(self):
        self.w.submit_work_request("Engine aur crew dono check karo")
        [chief] = self.run_one("chief")
        self.assertIn("## New messages (1)", chief["prompt"])
        self.assertIn(chief["activation_id"], chief["prompt"])
        self.assertEqual(self.o.next_work()["status"], "busy")  # nobody else has work yet
        r = self.brief(chief["activation_id"])
        self.assertEqual([t["id"] for t in r["tasks_created"]], ["TK-1", "TK-2"])
        self.o.activation_done(chief["activation_id"], "briefed")
        nw = self.o.next_work()
        self.assertEqual(sorted(a["agent"] for a in nw["activations"]), [AGENT_TYPES["head"]] * 2)
        acts = {a["prompt"].split("(agent id \"")[1].split('"')[0]: a for a in nw["activations"]}
        h1, h2 = acts[self.asha["id"]], acts[self.kabir["id"]]
        self.assertIn("TK-1", h1["prompt"])
        self.assertNotIn("TK-2 [", h1["prompt"])  # a Head sees its own department's tasks
        self.o.tool_update_task(h1["activation_id"], "TK-1", "done", "3 items")
        self.o.tool_update_task(h2["activation_id"], "TK-2", "in_progress", "start")
        self.o.tool_update_task(h2["activation_id"], "TK-2", "done", "ok")
        for a in (h1, h2):
            self.o.activation_done(a["activation_id"], "ok")
        [c] = self.run_one("chief")
        self.assertIn("review", c["prompt"])
        self.o.tool_report(c["activation_id"], "WR-1", "All done.")
        self.o.activation_done(c["activation_id"], "reported")
        fin = self.o.next_work()
        self.assertEqual(fin["status"], "finished")
        self.assertTrue(any("All done." in m for m in fin["ownerMessages"]))
        self.assertEqual(self.o.next_work()["ownerMessages"], [])  # each Owner message is reported once
        self.assertEqual(self.s.get_work_request("WR-1")["status"], "Done")

    def test_status_messages_do_not_wake_the_chief_but_blocked_does(self):
        self.w.submit_work_request("x")
        [c] = self.run_one("chief")
        self.brief(c["activation_id"])
        self.o.activation_done(c["activation_id"], "")
        heads = self.o.next_work()["activations"]
        h = next(a for a in heads if "Asha" in a["description"])
        self.o.tool_update_task(h["activation_id"], "TK-1", "in_progress", "go")
        for a in heads:
            self.o.activation_done(a["activation_id"], "")
        self.assertEqual(self.o.next_work()["status"], "finished")  # in_progress woke no one
        h = self.s.get_agent(self.asha["id"])
        self.w.update_task("TK-1", "blocked", "need data", author=h["id"])
        [c2] = self.run_one("chief")
        self.assertIn("blocked", c2["prompt"])

    def test_parallel_cap(self):
        for i in range(6):
            self.s.create_department(f"Dept {i}", f"Head {i}")
        self.w.submit_work_request("everything")
        [c] = self.run_one("chief")
        tasks = [{"title": f"t{d['id']}", "dept": d["id"]} for d in self.s.list_departments()]
        self.o.tool_submit_brief(c["activation_id"], "WR-1", "all", [], tasks)
        self.o.activation_done(c["activation_id"], "")
        nw = self.o.next_work()
        self.assertEqual(len(nw["activations"]), loopmod.MAX_PARALLEL)
        self.assertEqual(self.o.next_work()["status"], "busy")
        for a in nw["activations"]:
            self.o.activation_done(a["activation_id"], "")
        self.assertEqual(len(self.o.next_work()["activations"]), 8 - loopmod.MAX_PARALLEL)

    def test_reset_running_hands_messages_back(self):
        self.w.submit_work_request("x")
        [c] = self.run_one("chief")
        self.assertEqual(self.o.next_work()["status"], "busy")
        nw = self.o.next_work(reset_running=True)
        self.assertEqual(nw["status"], "work")
        self.assertIn("## New messages (1)", nw["activations"][0]["prompt"])
        self.assertEqual(self.s.get_activation(c["activation_id"])["status"], "cancelled")
        with self.assertRaises(Conflict):
            self.o.tool_send_message(c["activation_id"], "owner", "late")

    def test_budget_pauses_and_owner_message_resumes(self):
        old = loopmod.BUDGET
        loopmod.BUDGET = 2
        self.addCleanup(setattr, loopmod, "BUDGET", old)
        self.w.submit_work_request("x")
        [c] = self.run_one("chief")  # run 1
        self.o.tool_send_message(c["activation_id"], self.asha["id"], "ping")
        self.o.activation_done(c["activation_id"], "")
        [h] = self.run_one("head")  # run 2: the budget is used up
        self.o.tool_send_message(h["activation_id"], "chief", "pong")
        self.o.activation_done(h["activation_id"], "")
        fin = self.o.next_work()  # the Chief has a message, but the team pauses
        self.assertEqual(fin["status"], "finished")
        self.assertEqual(fin["waitingFor"], "owner")
        self.assertTrue(any("paused" in m for m in fin["ownerMessages"]))
        self.w.send_instruction("chief", "continue", "WR-1")
        self.assertEqual(self.o.next_work()["status"], "work")


class PermissionTests(Base):
    def setUp(self):
        super().setUp()
        self.w.submit_work_request("x")
        [c] = self.run_one("chief")
        self.chief = c["activation_id"]
        self.brief(self.chief)
        self.o.activation_done(self.chief, "")
        acts = self.o.next_work()["activations"]
        self.h_eng = next(a for a in acts if "Asha" in a["description"])["activation_id"]
        self.h_crew = next(a for a in acts if "Kabir" in a["description"])["activation_id"]

    def test_role_limits(self):
        with self.assertRaises(Conflict):
            self.o.tool_submit_brief(self.h_eng, "WR-1", "x")
        with self.assertRaises(Conflict):
            self.o.tool_update_task(self.h_eng, "TK-2", "done", "not mine")
        with self.assertRaises(Conflict):
            self.o.tool_hire(self.h_eng, "R", "analyst", "why", "TK-2")
        with self.assertRaises(Invalid):
            self.o.tool_update_task(self.h_eng, "TK-1", "finished", "bad status")
        with self.assertRaises(Invalid):
            self.o.tool_send_message(self.h_eng, self.asha["id"], "me")
        with self.assertRaises(Invalid):
            self.o.tool_send_message(self.h_eng, "nobody", "x")
        with self.assertRaises(Conflict):
            self.o.tool_send_message("act-unknown", "owner", "x")

    def test_hire_assign_and_specialist(self):
        r = self.o.tool_hire(self.h_eng, "Ravi", "Reliability analyst", "backlog", "TK-1")
        self.assertEqual(r["assigned"], "TK-1")
        self.o.activation_done(self.h_eng, "")
        self.o.activation_done(self.h_crew, "")
        [sp] = self.o.next_work()["activations"]
        self.assertEqual(sp["agent"], AGENT_TYPES["hired"])
        self.assertIn("Assigned TK-1", sp["prompt"])
        with self.assertRaises(Conflict):
            self.o.tool_update_task(sp["activation_id"], "TK-2", "done", "not assigned")
        with self.assertRaises(Conflict):
            self.o.tool_hire(sp["activation_id"], "X", "y", "z")
        self.o.tool_update_task(sp["activation_id"], "TK-1", "done", "3 overdue")
        self.assertEqual(self.s.get_task("TK-1")["status"], "done")

    def test_chief_replan_blocks_and_adds(self):
        self.o.activation_done(self.h_eng, "")
        self.o.activation_done(self.h_crew, "")
        self.w.send_instruction("chief", "Crew training chhodo, sirf engine")
        [c] = self.run_one("chief")
        r = self.o.tool_submit_brief(c["activation_id"], "WR-1", "Engine only", change_note="Owner: engine only",
                                     block_task_ids=["TK-2"])
        self.assertEqual((r["brief_version"], r["blocked"]), (2, ["TK-2"]))
        self.assertEqual(self.s.get_task("TK-2")["status"], "blocked")
        with self.assertRaises(Invalid):
            self.o.tool_submit_brief(c["activation_id"], "WR-1", "x", tasks=[{"title": "t", "dept": "nope"}])
        with self.assertRaises(Invalid):
            self.o.tool_submit_brief(c["activation_id"], "WR-1", "x", block_task_ids=["TK-99"])

    def test_no_department_fits_asks_owner(self):
        wr = self.w.submit_work_request("Bird strike wildlife review")
        self.o.activation_done(self.h_eng, "")
        self.o.activation_done(self.h_crew, "")
        [c] = self.run_one("chief")
        r = self.o.tool_submit_brief(c["activation_id"], wr["id"], "No wildlife department",
                                     question="Which department should handle wildlife? Send its PDFs and Head name.")
        self.assertEqual(r["tasks_created"], [])
        self.assertTrue(self.s.get_brief(wr["id"])["needs_department"])
        self.o.activation_done(c["activation_id"], "")
        fin = self.o.next_work()
        self.assertEqual(fin["waitingFor"], "owner")


@unittest.skipUnless(HAS_PDFTOTEXT, "kb.py needs pdftotext (or pypdf/PyMuPDF)")
class KnowledgeToolTests(Base):
    def test_search_read_and_save(self):
        self.kb.ingest("engine-maintenance", [("engine.pdf", pdf("e"))])
        self.w.submit_work_request("x")
        [c] = self.run_one("chief")
        self.assertIn("engine", c["prompt"])  # the Chief sees each department's documents
        hits = self.o.tool_search(c["activation_id"], "hazard identification")["results"]
        self.assertTrue(hits and hits[0]["dept"] == "engine-maintenance")
        sec = self.o.tool_read(c["activation_id"], hits[0]["file"])
        self.assertIn("Hazard", sec["text"])
        with self.assertRaises(Invalid):
            self.o.tool_read(c["activation_id"], "/etc/passwd")
        self.brief(c["activation_id"])
        p = self.o.tool_save_output(c["activation_id"], "WR-1", "plan", "# Plan")["path"]
        self.assertTrue(p.endswith(os.path.join("_outputs", "WR-1", "WR-1-plan.md")))
        self.o.activation_done(c["activation_id"], "")
        h = next(a for a in self.o.next_work()["activations"] if "Kabir" in a["description"])
        self.assertEqual(self.o.tool_search(h["activation_id"], "hazard identification")["results"], [])
        with self.assertRaises(Conflict):
            self.o.tool_save_output(h["activation_id"], "TK-1", "x", "not my task")
        out = self.o.tool_save_output(h["activation_id"], "TK-2", "Crew records", "# Result\nok")["path"]
        self.assertTrue(os.path.isfile(out))
        self.assertIn("TK-2-Crew-records.md", out)


if __name__ == "__main__":
    unittest.main()


class DeliverableTests(Base):
    """Owner asks for a PPT -> Chief lists it -> teams write content -> Chief builds the file -> report with path."""

    DECK = {"slides": [{"title": "Engine findings", "bullets": ["Backlog of 3 items"]},
                       {"title": "Crew findings", "table": {"columns": ["Item", "Status"], "rows": [["Records", "OK"]]}}]}

    def test_ppt_flow(self):
        self.w.submit_work_request("Engine aur crew hazard review ki PPT bana do safety board ke liye")
        [c] = self.run_one("chief")
        self.assertIn("suggest a file: PPT (pptx)", c["prompt"])
        r = self.o.tool_submit_brief(c["activation_id"], "WR-1", "Hazard review deck", ["Board-ready slides"], [
            {"title": "Engine slide content", "dept": "engine-maintenance"},
            {"title": "Crew slide content", "dept": "crew-training"}],
            deliverables=[{"format": "ppt", "title": "Hazard Review for the Safety Board"}])
        self.assertEqual(r["deliverables"], [{"format": "pptx", "title": "Hazard Review for the Safety Board"}])
        self.o.activation_done(c["activation_id"], "")
        heads = self.o.next_work()["activations"]
        for h in heads:
            self.assertIn('Deliverables: PPT "Hazard Review for the Safety Board" (not built yet)', h["prompt"])
            tid = "TK-1" if "Asha" in h["description"] else "TK-2"
            self.o.tool_update_task(h["activation_id"], tid, "done", "content ready")
            self.o.activation_done(h["activation_id"], "")
        [c2] = self.run_one("chief")
        self.assertIn("build it with build_file", c2["prompt"])
        with self.assertRaises(Invalid) as e:
            self.o.tool_report(c2["activation_id"], "WR-1", "Done.")
        self.assertIn("PPT", str(e.exception))
        f = self.o.tool_build_file(c2["activation_id"], "WR-1", "pptx", "Hazard Review for the Safety Board",
                                   self.DECK, ["Engine manual §3, p.4"])
        self.assertTrue(f["path"].endswith(os.path.join("_outputs", "WR-1", "Hazard-Review-for-the-Safety-Board.pptx")))
        self.assertTrue(os.path.isfile(f["path"]))
        self.assertEqual(f["slides"], 4)
        rep = self.o.tool_report(c2["activation_id"], "WR-1", "Deck ready.")
        self.assertEqual(rep["files"], [f["path"]])
        body = self.s.list_messages(kind="report")[-1]["body"]
        self.assertIn("Files:\n- Hazard Review for the Safety Board (PPT): " + f["path"], body)
        self.o.activation_done(c2["activation_id"], "")
        fin = self.o.next_work()
        self.assertTrue(any(f["path"] in m for m in fin["ownerMessages"]))
        detail = self.w.request_detail("WR-1")
        self.assertEqual([x["format"] for x in detail["files"]], ["pptx"])
        # the brief keeps its deliverables on a re-plan that does not mention them
        self.w.send_instruction("chief", "Ek Word summary bhi chahiye")
        [c3] = self.run_one("chief")
        r = self.o.tool_submit_brief(c3["activation_id"], "WR-1", "Deck plus summary", change_note="Add Word summary",
                                     deliverables=[{"format": "pptx", "title": "Hazard Review for the Safety Board"},
                                                   {"format": "docx", "title": "Summary"}])
        self.assertEqual(len(r["deliverables"]), 2)
        with self.assertRaises(Invalid):
            self.o.tool_report(c3["activation_id"], "WR-1", "x")
        self.o.tool_report(c3["activation_id"], "WR-1", "Deck only.", missing_reason="Owner cancelled the summary")
        self.assertIn("Not delivered: Owner cancelled", self.s.list_messages(kind="report")[-1]["body"])

    def test_heads_and_specialists_build_for_their_own_tasks(self):
        self.w.submit_work_request("Findings ka Excel do")
        [c] = self.run_one("chief")
        self.brief(c["activation_id"])
        self.o.activation_done(c["activation_id"], "")
        acts = self.o.next_work()["activations"]
        h = next(a for a in acts if "Asha" in a["description"])["activation_id"]
        sheet = {"sheets": [{"name": "Findings", "columns": ["ID", "Finding"], "rows": [["F-1", "Backlog"]]}]}
        f = self.o.tool_build_file(h, "TK-1", "excel", "Engine findings", sheet)
        self.assertTrue(f["path"].endswith("TK-1-Engine-findings.xlsx"))
        with self.assertRaises(Conflict):
            self.o.tool_build_file(h, "TK-2", "xlsx", "Not mine", sheet)
        with self.assertRaises(Conflict):
            self.o.tool_build_file(h, "WR-1", "xlsx", "Request level", sheet)
        with self.assertRaises(Invalid):
            self.o.tool_build_file(h, "TK-1", "csv", "x", sheet)
        with self.assertRaises(Invalid):
            self.w.submit_brief("WR-1", "x", deliverables=[{"format": "pdf"}])
        self.assertEqual(len(self.s.list_files("WR-1")), 1)
        again = self.o.tool_build_file(h, "TK-1", "xlsx", "Engine findings", sheet)  # rebuilding replaces it
        self.assertEqual(again["file_id"], f["file_id"])
        self.assertEqual(len(self.s.list_files("WR-1")), 1)

    def test_wanted_formats(self):
        self.assertEqual(loopmod.wanted_formats("SRB ke liye slides aur ek Excel sheet"), ["pptx", "xlsx"])
        self.assertEqual(loopmod.wanted_formats("Word document chahiye"), ["docx"])
        self.assertEqual(loopmod.wanted_formats("hazard log check karo"), [])
