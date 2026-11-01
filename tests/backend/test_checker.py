"""File Checker (after the Chief, before the departments), read-once reads, models and keyword links."""
import os
import unittest

from test_loop import Base

from backend.fsa import loop as loopmod
from backend.fsa.loop import AGENT_TYPES
from backend.fsa.store import Conflict, Invalid, NotFound

ENGINE = """# Chapter 1 Borescope inspection
## 1.1 Borescope intervals
Borescope inspections of the hot section are due every 400 flight hours. The borescope report is filed with
engineering within 24 hours.

## 1.2 Unstable approach damage
After an unstable approach with a hard landing a borescope check is mandatory.
"""
CREW = """# Chapter 1 Crew records
## 1.1 Recurrent training
Recurrent training records are reviewed monthly. Expired licences ground the crew member.
"""


class KbBase(Base):
    """Two departments with real manuals (markdown), so source packs have something to point at."""

    def setUp(self):
        super().setUp()
        self.kb.ingest("engine-maintenance", [("Engine_Manual.md", ENGINE.encode())])
        self.kb.ingest("crew-training", [("Crew_Manual.md", CREW.encode())])
        self.w.submit_work_request("Engine borescope aur crew records check karo")
        [c] = self.run_one("chief")
        self.chief = c["activation_id"]
        self.brief(self.chief)
        self.o.activation_done(self.chief, "")

    def checker(self):
        nw = self.o.next_work()
        self.assertEqual(nw["status"], "work", nw)
        [ck] = [a for a in nw["activations"] if a["agent"] == AGENT_TYPES["checker"]]
        return ck

    def hit(self, query, dept):
        [h] = self.kb.search(query, [dept], 1)
        return {"file": h["file"], "line": h["line"], "why": query}


class GateTests(KbBase):
    def test_departments_wait_for_the_source_pack(self):
        self.assertEqual(self.s.list_messages(kind="assign"), [])
        ck = self.checker()
        self.assertEqual(ck["description"].split(" (")[0], "File Checker")
        for tid in ("TK-1", "TK-2"):
            self.assertIn(tid, ck["prompt"])
        self.assertIn("Tasks waiting for a source pack", ck["prompt"])
        self.assertIn("engine-manual", ck["prompt"])  # the departments' documents are listed
        self.assertEqual(self.o.next_work()["status"], "busy")  # the Heads have not been woken
        r = self.o.tool_submit_source_pack(ck["activation_id"], [
            {"task_id": "TK-1", "coverage": "full", "summary": "Borescope intervals",
             "sources": [self.hit("borescope intervals", "engine-maintenance")]},
            {"task_id": "TK-2", "coverage": "full", "sources": [self.hit("recurrent training", "crew-training")]}])
        self.assertEqual([x["task_id"] for x in r["saved"]], ["TK-1", "TK-2"])
        self.assertEqual(r["still_waiting"], [])
        self.assertTrue(all(os.path.isfile(x["file"]) for x in r["saved"]))  # a copy for the Owner under _outputs
        self.o.activation_done(ck["activation_id"], "")
        heads = {a["description"].split(" (")[0]: a for a in self.o.next_work()["activations"]}
        eng = heads["Asha Verma"]["prompt"]
        self.assertIn("Source pack for TK-1 (File Checker, coverage full)", eng)
        self.assertIn("Borescope inspections of the hot section are due every 400 flight hours", eng)
        self.assertIn("Engine Manual", eng)  # the citation comes from the file, not from the Checker
        self.assertIn("section 1.1 Borescope intervals", eng)
        self.assertNotIn("Recurrent training records", eng)  # only the department's own task
        self.assertIn("Source pack for TK-2", heads["Kabir Singh"]["prompt"])
        self.assertIn("File Checker has read the manuals", self.s.list_messages(kind="assign")[0]["body"])
        self.assertEqual(self.s.get_task("TK-1")["source_pack"], {"coverage": "full", "sources": 1, "issues": 0, "version": 1})

    def test_only_the_checker_submits_and_bad_packs_are_rejected(self):
        ck = self.checker()["activation_id"]
        with self.assertRaises(Conflict):
            self.o.tool_submit_source_pack(self.chief, [])
        with self.assertRaises(Invalid):
            self.o.tool_submit_source_pack(ck, [])
        with self.assertRaises(Invalid) as e:  # a file outside the knowledge base
            self.o.tool_submit_source_pack(ck, [{"task_id": "TK-1", "sources": [{"file": "/etc/passwd"}]}])
        self.assertIn("No pack was saved", str(e.exception))
        with self.assertRaises(Invalid) as e:  # no sections and not coverage none
            self.o.tool_submit_source_pack(ck, [{"task_id": "TK-1", "coverage": "full", "sources": []}])
        self.assertIn("coverage 'none'", str(e.exception))
        with self.assertRaises(Invalid):  # coverage none must say what is missing
            self.o.tool_submit_source_pack(ck, [{"task_id": "TK-1", "coverage": "none"}])
        with self.assertRaises(Invalid):
            self.o.tool_submit_source_pack(ck, [{"task_id": "TK-1", "coverage": "great", "issues": ["x"]}])
        too_many = [self.hit("borescope intervals", "engine-maintenance")] * 2
        with self.assertRaises(Invalid):
            self.o.tool_submit_source_pack(ck, [{"task_id": "TK-1", "sources": too_many * 5}])
        # one bad task does not cost the good one
        r = self.o.tool_submit_source_pack(ck, [
            {"task_id": "TK-1", "sources": [self.hit("borescope intervals", "engine-maintenance")]},
            {"task_id": "TK-2", "sources": [{"file": "nope/missing.md", "line": 1}]},
            {"task_id": "TK-99", "coverage": "none", "issues": ["x"]}])
        self.assertEqual([x["task_id"] for x in r["saved"]], ["TK-1"])
        self.assertEqual(sorted(x["task_id"] for x in r["rejected"]), ["TK-2", "TK-99"])
        self.assertEqual(r["still_waiting"], ["TK-2"])
        self.assertEqual(len(self.s.list_messages(kind="assign")), 1)  # only TK-1's department was released

    def test_superseded_sections_and_gaps_are_flagged_to_the_chief(self):
        self.kb.run("retire", "engine-manual", "--dept", "engine-maintenance", "--reason", "replaced")
        old = None
        for root, _, names in os.walk(os.path.join(self.kb.root, "engine-maintenance", "_superseded")):
            for n in names:
                if n != "_doc.md" and n.endswith(".md"):
                    old = os.path.join(root, n)
        rel = os.path.relpath(old, self.kb.root)
        ck = self.checker()["activation_id"]
        r = self.o.tool_submit_source_pack(ck, [
            {"task_id": "TK-1", "coverage": "partial", "sources": [{"file": rel, "line": 5}], "issues": ["Only one manual"]},
            {"task_id": "TK-2", "coverage": "none", "issues": ["Crew manual says nothing about licences"]}])
        issues = r["saved"][0]["issues"]
        self.assertTrue(any("superseded or withdrawn" in i for i in issues))
        self.assertIn("Only one manual", issues)
        self.o.activation_done(ck, "")
        for h in self.o.next_work()["activations"]:
            self.assertIn("ISSUE flagged", h["prompt"])
            self.o.activation_done(h["activation_id"], "")
        self.w.update_task("TK-1", "done", "ok", author=self.asha["id"])
        self.w.update_task("TK-2", "done", "ok", author=self.kabir["id"])
        [c] = self.run_one("chief")
        self.assertIn("The File Checker flagged documentation problems", c["prompt"])
        self.assertIn("Crew manual says nothing about licences", c["prompt"])

    def test_a_pack_update_tells_the_department_again(self):
        ck = self.checker()["activation_id"]
        packs = [{"task_id": tid, "sources": [self.hit(q, d)]} for tid, q, d in
                 (("TK-1", "borescope intervals", "engine-maintenance"), ("TK-2", "recurrent training", "crew-training"))]
        self.o.tool_submit_source_pack(ck, packs)
        self.o.activation_done(ck, "")
        acts = self.o.next_work()["activations"]
        asha = next(a for a in acts if "Asha" in a["description"])
        self.o.tool_send_message(asha["activation_id"], "checker", "TK-1 needs the damage section too")  # asks for more
        for a in acts:
            self.o.activation_done(a["activation_id"], "")
        ck2 = self.checker()
        self.assertIn("TK-1 needs the damage section too", ck2["prompt"])
        r = self.o.tool_submit_source_pack(ck2["activation_id"], [
            {"task_id": "TK-1", "sources": [self.hit("unstable approach damage", "engine-maintenance")]}])
        self.assertEqual(self.s.get_source_pack("TK-1")["version"], 2)
        self.assertEqual(r["saved"][0]["sections"], 1)
        last = self.s.list_messages(kind="chat")[-1]
        self.assertIn("Source pack for TK-1 updated", last["body"])
        self.assertEqual(last["recipient"], self.asha["id"])


class NudgeTests(KbBase):
    def test_a_run_that_delivers_nothing_is_asked_again_then_the_work_goes_on(self):
        ck = self.checker()
        self.o.activation_done(ck["activation_id"], "I looked but forgot to submit")
        for n in range(loopmod.MAX_CHECK_TRIES):
            nw = self.o.next_work()  # asked again
            self.assertEqual([a["agent"] for a in nw["activations"]], [AGENT_TYPES["checker"]], n)
            self.assertIn("Still waiting for a source pack", nw["activations"][0]["prompt"])
            self.o.activation_done(nw["activations"][0]["activation_id"], "")
        nw = self.o.next_work()  # then the departments start without a pack, flagged
        self.assertEqual(sorted(a["agent"] for a in nw["activations"]), [AGENT_TYPES["head"]] * 2)
        self.assertEqual(self.s.get_source_pack("TK-1")["coverage"], "none")
        for a in nw["activations"]:
            self.assertIn("did not deliver a source pack", a["prompt"])
        fin = self.o.next_work()
        self.assertTrue(any("did not deliver source packs" in m for m in fin.get("ownerMessages", [])) or
                        any("did not deliver source packs" in m["body"] for m in self.s.list_messages()))

    def test_a_replan_asks_for_packs_only_for_new_tasks(self):
        ck = self.checker()["activation_id"]
        self.o.tool_submit_source_pack(ck, [{"task_id": t, "coverage": "none", "issues": ["x"]} for t in ("TK-1", "TK-2")])
        self.o.activation_done(ck, "")
        for h in self.o.next_work()["activations"]:
            self.o.activation_done(h["activation_id"], "")
        self.w.send_instruction("chief", "Ek aur engine task")
        [c] = self.run_one("chief")
        self.o.tool_submit_brief(c["activation_id"], "WR-1", "More engine", change_note="more",
                                 tasks=[{"title": "Engine extra", "dept": "engine-maintenance"}])
        self.o.activation_done(c["activation_id"], "")
        ck2 = self.checker()
        self.assertIn("TK-3", ck2["prompt"])
        self.assertNotIn("TK-1 for", ck2["prompt"].split("Tasks waiting for a source pack")[1])
        self.assertEqual([t["id"] for t in self.s.tasks_awaiting_pack()], ["TK-3"])


class ReadOnceTests(KbBase):
    def setUp(self):
        super().setUp()
        ck = self.checker()["activation_id"]
        self.o.tool_submit_source_pack(ck, [
            {"task_id": "TK-1", "sources": [self.hit("borescope intervals", "engine-maintenance")]},
            {"task_id": "TK-2", "coverage": "none", "issues": ["no crew sections"]}])
        self.o.activation_done(ck, "")
        acts = self.o.next_work()["activations"]
        self.h_eng = next(a for a in acts if "Asha" in a["description"])["activation_id"]
        self.pack = self.s.get_source_pack("TK-1")["sources"][0]

    def test_a_part_in_the_source_pack_is_not_read_again(self):
        r = self.o.tool_read(self.h_eng, self.pack["file"], self.pack["line"])
        self.assertIn("already_in_source_pack", r)
        self.assertNotIn("text", r)
        forced = self.o.tool_read(self.h_eng, self.pack["file"], self.pack["line"], again=True)
        self.assertIn("Borescope", forced["text"])

    def test_the_same_part_is_not_read_twice_in_one_run(self):
        crew = self.hit("recurrent training", "crew-training")
        first = self.o.tool_read(self.h_eng, crew["file"], crew["line"])
        self.assertIn("Recurrent training", first["text"])
        second = self.o.tool_read(self.h_eng, crew["file"], crew["line"])
        self.assertTrue(second["already_read"])
        self.assertNotIn("text", second)
        self.assertIn("Recurrent", self.o.tool_read(self.h_eng, crew["file"], crew["line"], again=True)["text"])
        self.assertNotIn("already_read", self.o.tool_read(self.h_eng, crew["file"], 1))  # another part is fine

    def test_a_new_run_may_read_it_and_the_file_is_cached(self):
        crew = self.hit("recurrent training", "crew-training")
        self.o.tool_read(self.h_eng, crew["file"], crew["line"])
        full = self.kb.inside(crew["file"])
        self.assertIn(full, self.kb._cache)
        cached = self.kb._cache[full][2]
        self.kb.read_file(crew["file"], crew["line"])
        self.assertIs(self.kb._cache[full][2], cached)  # not read from disk again while unchanged
        self.o.activation_done(self.h_eng, "")
        self.w.send_instruction("engine-maintenance", "ek aur baat")
        h2 = next(a for a in self.o.next_work()["activations"] if "Asha" in a["description"])
        self.assertIn("Recurrent", self.o.tool_read(h2["activation_id"], crew["file"], crew["line"])["text"])
        with open(full, "a", encoding="utf-8") as f:  # an edit is picked up
            f.write("\nA new paragraph.\n")
        self.assertIn("A new paragraph", self.kb.read_file(crew["file"])["text"])


class ModelTests(Base):
    def test_default_is_the_session_model_and_it_is_reported(self):
        m = self.o.models()
        self.assertTrue(all(v["setting"] == "inherit" for v in m["roles"].values()))
        self.assertEqual(m["roles"]["chief"]["effective"], "session model (not reported yet)")
        self.w.submit_work_request("x")
        nw = self.o.next_work(session_model="claude-sonnet-5-5")
        self.assertNotIn("model", nw["activations"][0])  # inherit: the Agent call gets no model
        m = self.o.models()
        self.assertEqual(m["session_model"], "claude-sonnet-5-5")
        self.assertEqual(m["roles"]["head"]["effective"], "claude-sonnet-5-5")
        self.assertIn("To upgrade", m["hint"])
        self.assertEqual(sorted(p["id"] for p in m["presets"]), ["best", "economy", "inherit", "recommended"])

    def test_upgrade_by_preset_or_role_reaches_the_activation(self):
        self.o.set_models(preset="recommended")
        self.w.submit_work_request("x")
        [c] = self.run_one("chief")
        self.assertEqual(c["model"], "opus")
        self.assertEqual(self.s.get_activation(c["activation_id"])["model"], "opus")
        self.assertEqual(self.o.activity()["running"][0]["model"], "opus")
        self.assertIn("pass it as the Agent call's model", loopmod.LOOP_INSTRUCTIONS)
        self.brief(c["activation_id"])
        self.o.activation_done(c["activation_id"], "")
        ck = self.o.next_work()["activations"][0]
        self.assertEqual((ck["agent"], ck["model"]), (AGENT_TYPES["checker"], "opus"))
        self.o.set_models(roles={"checker": "sonnet", "head": "haiku"})
        m = self.o.models()
        self.assertEqual((m["roles"]["checker"]["setting"], m["roles"]["head"]["setting"]), ("sonnet", "haiku"))
        self.assertIsNone(m["preset"])
        self.assertIn("newest version", m["hint"])
        self.o.set_models(roles={"all": "inherit"})
        self.assertEqual(self.o.models()["preset"], "inherit")
        self.assertIsNone(self.o.model_for("chief"))

    def test_bad_choices_are_refused(self):
        for kw in ({}, {"preset": "turbo"}, {"roles": {"chief": "gpt"}}, {"roles": {"janitor": "opus"}}):
            with self.assertRaises(Invalid):
                self.o.set_models(**kw)
        self.assertTrue(all(v["setting"] == "inherit" for v in self.o.models()["roles"].values()))


class LinkTests(KbBase):
    def test_tasks_and_questions_teach_the_map_and_prompts_show_only_what_matches(self):
        learned = {(x["term"], x["dept"]) for x in self.kb.links_show()["links"]}
        self.assertTrue(any(d == "engine-maintenance" for _, d in learned))  # from the Chief's tasks
        self.assertTrue(any(d == "crew-training" for _, d in learned))
        # the Crew department's task mentions a borescope: the map knows that belongs to Engine
        found = self.kb.links_find("Check whether the unstable approach needs a borescope", dept="crew-training")
        self.assertEqual([e["dept"] for e in found["related"]], ["engine-maintenance"])
        e = found["related"][0]
        self.assertTrue(any("borescope" in v for v in e["via"]))
        self.assertTrue(e["manuals"] and e["manuals"][0]["file"].startswith("engine-maintenance/"))
        self.assertEqual(self.kb.links_find("Check the training register", dept="crew-training")["related"], [])
        # a department's note and an open board request come along only when their words match
        self.kb.run("mem", "add", "--dept", "engine-maintenance", "--kind", "source-map", "--text",
                    "Borescope intervals are in Engine Manual 1.1", "--src", "[Engine Manual §1.1]")
        self.kb.run("mem", "add", "--dept", "engine-maintenance", "--kind", "lesson", "--text",
                    "Hangar doors are closed at night", "--src", "user")
        self.kb.run("board", "post", "--from", "crew-training", "--to", "engine-maintenance", "--subject",
                    "Borescope backlog", "--text", "Do you have the borescope backlog?")
        e = self.kb.links_find("Prepare a borescope summary", dept="crew-training")["related"][0]
        self.assertEqual([m["text"] for m in e["memory"]], ["Borescope intervals are in Engine Manual 1.1"])
        self.assertEqual(e["board"][0]["subject"], "Borescope backlog")

    def test_heads_see_linked_departments_and_can_ask(self):
        self.s.create_task("Borescope results for crew", "crew-training", "Does crew need a borescope result?", "", "WR-1")
        self.s.add_message("chief", self.kabir["id"], "Task TK-3", kind="assign", task_id="TK-3")
        act = next(a for a in self.o.next_work()["activations"] if "Kabir" in a["description"])
        self.assertIn("## Linked by keywords (other departments)", act["prompt"])
        self.assertIn("- engine-maintenance, via:", act["prompt"])
        rel = self.o.tool_related(act["activation_id"], "borescope intervals")
        self.assertEqual(rel["related"][0]["dept"], "engine-maintenance")
        with self.assertRaises(Invalid):
            self.o.tool_related(act["activation_id"], "  ")
        # asking another department teaches the map: 'turbine blade' now belongs to Engine
        self.o.tool_send_message(act["activation_id"], self.asha["id"], "Turbine blade erosion limits?")
        links = {(x["term"], x["dept"]) for x in self.kb.links_show()["links"]}
        self.assertIn(("turbine blade", "engine-maintenance"), links)


class MigrationTests(unittest.TestCase):
    def test_a_database_from_v0_9_gets_the_file_checker_without_losing_anything(self):
        import sqlite3
        import tempfile
        from backend.fsa.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            old = sqlite3.connect(path)
            old.executescript("""
              CREATE TABLE agents(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('chief','head','hired')), dept TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')), reason TEXT,
                created_at TEXT NOT NULL);
              CREATE TABLE activations(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running', work_request_id TEXT, first_message INTEGER,
                last_message INTEGER, watermark INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL,
                ended_at TEXT, report TEXT);
              INSERT INTO agents VALUES('chief','Dhruv Rebbapragada','Chief of Flight Safety','chief',NULL,'active',NULL,'2026-01-01T00:00:00Z');
              INSERT INTO agents VALUES('ag-1','Asha Verma','Vertical Head, Engine','head','engine','active',NULL,'2026-01-02T00:00:00Z');
              INSERT INTO agents VALUES('ag-2','Ravi','Analyst','hired','engine','active','depth','2026-01-03T00:00:00Z');
              INSERT INTO activations(id,agent_id,started_at) VALUES('act-old','chief','2026-01-01T00:00:00Z');
            """)
            old.commit()
            old.close()
            s = Store(path)
            self.addCleanup(s.close)
            self.assertEqual([a["id"] for a in s.list_agents()], ["chief", "ag-1", "ag-2", "checker"])
            self.assertEqual(s.get_agent("ag-1")["name"], "Asha Verma")
            self.assertEqual(s.get_activation("act-old")["model"], None)
            self.assertTrue(s.checker_active())
            s.db.conn.execute("UPDATE agents SET name='x' WHERE id='checker'")  # the new kind is accepted
            Store(path).close()  # opening again is a no-op
            self.assertEqual(s._new_agent_id(), "ag-3")  # ids carry on where they were


if __name__ == "__main__":
    unittest.main()
