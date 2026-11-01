"""End-to-end tests for kb.py. Run:  python3 -m unittest discover -s tests -v"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures  # noqa: E402

KB_PY = Path(__file__).resolve().parents[1] / "skills" / "safety-kb" / "scripts" / "kb.py"
HAVE_PDF = bool(shutil.which("pdftotext"))
try:
    import pypdf  # noqa: F401
    HAVE_PDF = True
except ImportError:
    pass


def kb(tmp: Path, *args, check=True, env=None):
    r = subprocess.run([sys.executable, "-I", str(KB_PY), *args, "--kb", str(tmp / "safety-kb")],
                       capture_output=True, text=True, env={**os.environ, **env} if env else None)
    if check and r.returncode:
        raise AssertionError(f"kb.py {args} failed:\n{r.stdout}\n{r.stderr}")
    return r


class KbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_docx_ingest_and_search(self):
        f = fixtures.make_docx(self.tmp / "sms.docx")
        r = kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "Sample SMS Manual", "--rev", "Rev 2", "--effective", "2026-01-01")
        self.assertIn("ingested", r.stdout)
        docdir = self.tmp / "safety-kb" / "sms" / "sample-sms-manual"
        self.assertTrue((docdir / "_doc.md").exists())
        self.assertTrue((self.tmp / "safety-kb" / "INDEX.md").exists())
        hits = json.loads(kb(self.tmp, "search", "risk index intolerable Accountable Manager", "--json").stdout)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["revision"], "Rev 2")
        self.assertIn("Risk assessment", hits[0]["section"])
        table = "".join(p.read_text() for p in docdir.glob("*.md"))
        self.assertIn("| A | Catastrophic |", table)

    @unittest.skipUnless(HAVE_PDF, "no PDF backend installed")
    def test_pdf_ingest_pages_and_header_stripping(self):
        f = fixtures.make_pdf(self.tmp / "sms.pdf")
        r = kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "Sample SMS Manual", "--rev", "Rev 2")
        self.assertNotIn("WARNING: very few", r.stdout)
        text = "".join(p.read_text() for p in (self.tmp / "safety-kb" / "sms" / "sample-sms-manual").glob("0*.md"))
        self.assertNotIn("Sample Airline Fictional SMS Manual", text)  # running header removed
        self.assertNotIn("Page 3 of", text)                            # footer removed
        doc = (self.tmp / "safety-kb" / "sms" / "sample-sms-manual")
        self.assertIn('pages: "1-2"', next(doc.glob("01-*.md")).read_text())  # heading's page marker must not leak into prior chunk
        self.assertIn('pages: "3"', next(doc.glob("02-*.md")).read_text())
        hits = json.loads(kb(self.tmp, "search", "unstable approach rate per 1000 flights", "--json").stdout)
        self.assertEqual(hits[0]["page"], 7)
        self.assertIn("Safety Assurance", hits[0]["section"])

    def test_revision_control(self):
        f = fixtures.make_md(self.tmp / "sms.md")
        kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "Sample SMS Manual", "--rev", "Rev 1")
        dup = kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "Sample SMS Manual", "--rev", "Rev 1", check=False)
        self.assertNotEqual(dup.returncode, 0)
        self.assertIn("already ingested", dup.stderr)

        f.write_text(f.read_text().replace("24 hours", "12 hours"))
        r = kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "Sample SMS Manual", "--rev", "Rev 2")
        self.assertIn("archived previous revision", r.stdout)
        sup = list((self.tmp / "safety-kb" / "sms" / "_superseded").iterdir())
        self.assertEqual(len(sup), 1)

        current = json.loads(kb(self.tmp, "search", "submit a safety report within hours", "--json").stdout)
        self.assertIn("12 hours", current[0]["snippet"])
        self.assertTrue(all(not h["superseded"] for h in current))
        both = json.loads(kb(self.tmp, "search", "submit a safety report within hours", "--include-superseded", "--json").stdout)
        self.assertTrue(any(h["superseded"] for h in both))

    def test_dept_filter_and_status(self):
        f = fixtures.make_md(self.tmp / "m.md")
        kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "SMS", "--rev", "1")
        kb(self.tmp, "ingest", str(f), "--dept", "audit", "--title", "Audit", "--rev", "1")
        hits = json.loads(kb(self.tmp, "search", "risk matrix", "--dept", "audit", "--json").stdout)
        self.assertTrue(hits and all(h["dept"] == "audit" for h in hits))
        st = kb(self.tmp, "status").stdout
        self.assertIn("[sms]", st)
        self.assertIn("[audit]", st)


class MatchReplaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.r05 = fixtures.make_md(self.tmp / "SMS_Manual_R05.md")
        kb(self.tmp, "ingest", str(self.r05), "--dept", "sms", "--title", "SMS Manual", "--rev", "Rev 5")
        self.r06 = self.tmp / "SMS_Manual_R06.md"
        self.r06.write_text(self.r05.read_text().replace("within 24 hours", "within 12 hours"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def match(self, *files):
        return json.loads(kb(self.tmp, "match", *map(str, files), "--json").stdout)

    def test_batch_match_classifies_each_file(self):
        copy = self.tmp / "copy of manual FINAL.md"
        shutil.copy(self.r05, copy)
        other = self.tmp / "Audit_Handbook_2026.md"
        other.write_text("# Audit Handbook\n\nSomething else entirely about audit programmes.\n")
        res = self.match(self.r06, copy, other)
        self.assertEqual([r["action"] for r in res], ["ask_update_or_new", "skip_duplicate", "new"])
        self.assertEqual(res[0]["candidates"][0]["doc_id"], "sms-manual")
        self.assertEqual(res[1]["doc_id"], "sms-manual")

    def test_names_that_differ_only_by_revision_still_match(self):
        for name in ("SMS Manual v7.pdf", "sms-manual_Rev_06_2026-11-01.docx", "SMS_Manual (1).md"):
            f = self.tmp / name
            f.write_text("x")
            self.assertEqual(self.match(f)[0]["action"], "ask_update_or_new", name)

    def test_different_chapter_is_not_mistaken_for_same_document(self):
        kb(self.tmp, "ingest", str(self.r05), "--dept", "sms", "--title", "Annex 19", "--rev", "1", "--doc-id", "annex-19")
        f = self.tmp / "Annex_13.md"
        f.write_text("x")
        self.assertEqual(self.match(f)[0]["action"], "new")

    def test_replace_updates_in_place_and_archives_old(self):
        out = kb(self.tmp, "ingest", str(self.r06), "--replace", "sms-manual", "--rev", "Rev 6").stdout
        self.assertIn("archived previous revision 'Rev 5'", out)
        doc = (self.tmp / "safety-kb" / "sms" / "sms-manual" / "_doc.md").read_text()
        self.assertIn('revision: "Rev 6"', doc)
        self.assertIn('replaces_revision: "Rev 5"', doc)
        self.assertIn('source_file: "SMS_Manual_R06.md"', doc)
        hit = json.loads(kb(self.tmp, "search", "submit safety report hours", "--json").stdout)[0]
        self.assertIn("12 hours", hit["snippet"])
        self.assertEqual(len(list((self.tmp / "safety-kb" / "sms" / "_superseded").iterdir())), 1)

    def test_replace_works_with_a_completely_different_file_name(self):
        f = self.tmp / "Safety_Management_System_Issue6_FINAL.md"
        f.write_text(self.r06.read_text())
        kb(self.tmp, "ingest", str(f), "--replace", "sms-manual", "--rev", "Rev 6")
        self.assertTrue((self.tmp / "safety-kb" / "sms" / "sms-manual" / "_doc.md").exists())
        self.assertFalse((self.tmp / "safety-kb" / "sms" / "safety-management-system-issue6-final").exists())

    def test_replace_refusals_leave_the_old_document_untouched(self):
        same = kb(self.tmp, "ingest", str(self.r06), "--replace", "sms-manual", "--rev", "Rev 5", check=False)
        self.assertIn("already ingested", same.stderr)
        self.assertIn("--force", same.stderr)
        unknown = kb(self.tmp, "ingest", str(self.r06), "--replace", "nope", "--rev", "Rev 6", check=False)
        self.assertIn("Known ids: sms-manual", unknown.stderr)
        wrong_dept = kb(self.tmp, "ingest", str(self.r06), "--replace", "sms-manual", "--dept", "audit", "--rev", "Rev 6", check=False)
        self.assertNotEqual(wrong_dept.returncode, 0)
        bad = self.tmp / "legacy.doc"
        bad.write_text("binary")
        legacy = kb(self.tmp, "ingest", str(bad), "--replace", "sms-manual", "--rev", "Rev 6", check=False)
        self.assertNotEqual(legacy.returncode, 0)
        doc = (self.tmp / "safety-kb" / "sms" / "sms-manual" / "_doc.md").read_text()
        self.assertIn('revision: "Rev 5"', doc)  # a failed replace must not archive the good document
        self.assertFalse((self.tmp / "safety-kb" / "sms" / "_superseded").exists())

    def test_force_replaces_same_revision_corrected_reissue(self):
        kb(self.tmp, "ingest", str(self.r06), "--replace", "sms-manual", "--rev", "Rev 5", "--force")
        hit = json.loads(kb(self.tmp, "search", "submit safety report hours", "--json").stdout)[0]
        self.assertIn("12 hours", hit["snippet"])

    def test_old_revision_is_recognised_so_nobody_rolls_back_by_accident(self):
        kb(self.tmp, "ingest", str(self.r06), "--replace", "sms-manual", "--rev", "Rev 6")
        res = self.match(self.r05)
        self.assertEqual(res[0]["action"], "ask_old_revision")

    def test_new_document_in_same_dept_does_not_disturb_existing_one(self):
        extra = self.tmp / "Hazard_Register_Procedure.md"
        extra.write_text("# Hazard Register Procedure\n\nEntries are reviewed monthly.\n")
        kb(self.tmp, "ingest", str(extra), "--dept", "sms", "--rev", "Rev 1")
        status = kb(self.tmp, "status").stdout
        self.assertIn("2 document(s)", status)
        self.assertIn("id=sms-manual", status)

    def test_retire_withdraws_without_deleting_and_flags_memory(self):
        kb(self.tmp, "mem", "add", "--dept", "sms", "--kind", "source-map", "--text", "Ack deadline in 3.1",
           "--src", "[SMS Manual Rev 5 §3.1]", "--doc", "sms-manual", "--rev", "Rev 5")
        out = kb(self.tmp, "retire", "sms-manual", "--reason", "replaced by company-wide manual").stdout
        self.assertIn("withdrew sms/sms-manual", out)
        self.assertIn("1 memory note", out)
        self.assertFalse((self.tmp / "safety-kb" / "sms" / "sms-manual").exists())
        archived = next((self.tmp / "safety-kb" / "sms" / "_superseded").iterdir())
        self.assertIn('status: "withdrawn"', (archived / "_doc.md").read_text())
        self.assertIn("withdrawn", (self.tmp / "safety-kb" / "sms" / "INDEX.md").read_text())
        self.assertNotEqual(kb(self.tmp, "search", "safety report", check=False).returncode, 0)  # nothing current to search


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, frm, to, subject, thread=None, check=True, kind="request"):
        args = ["board", "post", "--from", frm, "--to", to, "--kind", kind, "--subject", subject, "--text", "details"]
        if thread:
            args += ["--thread", thread]
        return kb(self.tmp, *args, check=check)

    def test_request_answer_flow(self):
        r = self.post("sms", "fdm", "Unstable approach rate")
        bid = r.stdout.split()[1]
        self.assertIn("fdm: 1 open", kb(self.tmp, "board", "pending").stdout)
        self.assertIn(bid, kb(self.tmp, "board", "inbox", "--dept", "fdm").stdout)

        wrong = kb(self.tmp, "board", "answer", bid, "--from", "audit", "--text", "x", check=False)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("addressed to fdm", wrong.stderr)

        kb(self.tmp, "board", "answer", bid, "--from", "fdm", "--text", "1.8 per 1000 flights")
        pend = kb(self.tmp, "board", "pending").stdout
        self.assertNotIn("open request", pend)
        self.assertIn("sms: 1 unread answer", pend)  # requester must be re-run to use the answer
        first = kb(self.tmp, "board", "inbox", "--dept", "sms").stdout
        self.assertIn("1.8 per 1000", first)
        self.assertIn("empty", kb(self.tmp, "board", "inbox", "--dept", "sms").stdout)  # answers are marked read
        self.assertIn("pending: none", kb(self.tmp, "board", "pending").stdout)

    def test_guards(self):
        self.post("sms", "fdm", "Same question")
        dup = self.post("sms", "fdm", "same question", check=False)
        self.assertIn("identical open request", dup.stderr)
        self.assertNotEqual(self.post("sms", "all", "x", check=False).returncode, 0)  # requests need one addressee
        self.assertNotEqual(self.post("sms", "sms", "x", check=False).returncode, 0)
        thread = None
        for i in range(8):
            out = self.post("sms", "audit", f"q{i}", thread=thread).stdout
            thread = thread or out.split("thread ")[1].split(")")[0]
        loop = self.post("sms", "audit", "q-extra", thread=thread, check=False)
        self.assertIn("loop", loop.stderr)

    def test_escalate_to_user(self):
        self.post("audit", "user", "Need the approved risk matrix")
        self.assertIn("for the USER", kb(self.tmp, "board", "pending").stdout)

    def test_parallel_writers_do_not_lose_data(self):
        procs = [subprocess.Popen([sys.executable, "-I", str(KB_PY), "board", "post", "--from", "sms", "--to", "fdm",
                                   "--subject", f"s{i}", "--text", "t", "--kb", str(self.tmp / "safety-kb")],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(10)]
        for p in procs:
            p.communicate()
            self.assertEqual(p.returncode, 0)
        rows = json.loads(kb(self.tmp, "board", "pending", "--json").stdout)
        self.assertEqual(len(rows["requests"]["fdm"]), 10)
        self.assertEqual(len(set(rows["requests"]["fdm"])), 10)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, text, check=True, kind="term", dept="sms", extra=()):
        return kb(self.tmp, "mem", "add", "--dept", dept, "--kind", kind, "--text", text, "--src", "[SMS Manual Rev 1 §2, p.3]", *extra, check=check)

    def test_add_dedupe_show_forget(self):
        r = self.add("SRB means Safety Review Board")
        mid = r.stdout.split()[1]
        self.assertIn("confirmed x2", self.add("SRB means Safety Review Board").stdout)
        shown = kb(self.tmp, "mem", "show", "--dept", "sms").stdout
        self.assertIn("SRB means", shown)
        self.assertIn("confirmed 2x", shown)
        kb(self.tmp, "mem", "forget", mid, "--reason", "wrong")
        self.assertIn("memory: empty", kb(self.tmp, "mem", "show", "--dept", "sms").stdout)

    def test_guardrails(self):
        self.assertIn("personal data", self.add("Ask john.doe@example.com for the matrix", check=False).stderr)
        self.assertIn("personal data", self.add("Call 9876543210 for the register", check=False).stderr)
        self.assertIn("short pointers", self.add("x" * 401, check=False).stderr)
        self.assertNotEqual(self.add("ok", kind="gossip", check=False).returncode, 0)
        self.assertEqual(self.add("Revision dated 2026-03-01 applies").returncode, 0)  # a date is not a phone number

    def test_note_goes_stale_when_manual_is_reissued(self):
        f = fixtures.make_md(self.tmp / "sms.md")
        kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "SMS Manual", "--rev", "Rev 1")
        self.add("Report acknowledgement deadline is in section 3.1", kind="source-map", extra=("--doc", "sms-manual", "--rev", "Rev 1"))
        self.add("Unrelated note without a document link", kind="lesson")
        out = kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "SMS Manual", "--rev", "Rev 2").stdout
        self.assertIn("1 memory note(s)", out)
        shown = kb(self.tmp, "mem", "show", "--dept", "sms").stdout
        self.assertIn("VERIFY BEFORE USE", shown)
        self.assertIn("Unrelated note", shown.split("VERIFY BEFORE USE")[0])  # unaffected note stays active

    def test_parallel_writers_do_not_lose_data(self):
        procs = [subprocess.Popen([sys.executable, "-I", str(KB_PY), "mem", "add", "--dept", "fdm", "--kind", "lesson",
                                   "--text", f"note {i}", "--src", "user, 2026-10-26", "--kb", str(self.tmp / "safety-kb")],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(10)]
        for p in procs:
            p.communicate()
            self.assertEqual(p.returncode, 0)
        rows = json.loads(kb(self.tmp, "mem", "show", "--dept", "fdm", "--json").stdout)
        self.assertEqual(len(rows), 10)


NO_INDEX = {"SAFETY_KB_NO_INDEX": "1"}


class IndexTests(unittest.TestCase):
    """The saved search index (<kb>/_index/search.db): same answers as scanning the files, but it follows every change."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.f = fixtures.make_md(self.tmp / "sms.md")
        kb(self.tmp, "ingest", str(self.f), "--dept", "sms", "--title", "SMS Manual", "--rev", "Rev 1")
        self.root = self.tmp / "safety-kb"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def search(self, query, *extra, env=None):
        return json.loads(kb(self.tmp, "search", query, "--json", *extra, env=env).stdout)

    def test_ingest_builds_the_index_and_it_gives_the_same_answers_as_a_scan(self):
        self.assertTrue((self.root / "_index" / "search.db").exists())
        for q in ("risk index intolerable Accountable Manager", "submit a safety report within hours",
                  "unstable approach rate per 1000 flights", "management of change"):
            fast, slow = self.search(q), self.search(q, env=NO_INDEX)
            self.assertTrue(fast, q)
            key = lambda h: (h["file"], h["line"], h["section"], h["page"], h["revision"])  # noqa: E731
            self.assertEqual(key(fast[0]), key(slow[0]), q)
            self.assertEqual({key(h) for h in fast[:3]}, {key(h) for h in slow[:3]}, q)

    def test_scan_fallback_creates_no_index(self):
        shutil.rmtree(self.root / "_index")
        self.assertTrue(self.search("risk matrix", env=NO_INDEX))
        self.assertFalse((self.root / "_index").exists())

    def test_edits_are_picked_up_without_reindexing(self):
        self.assertTrue(self.search("submit report 24 hours"))
        chunk = next(self.root.glob("sms/sms-manual/*reporting*.md"), None) or next(
            c for c in sorted(self.root.glob("sms/sms-manual/0*.md")) if "24 hours" in c.read_text())
        chunk.write_text(chunk.read_text().replace("24 hours", "twelve hours"))  # a different size, so the index notices
        hit = self.search("submit a safety report within twelve hours")[0]
        self.assertIn("twelve hours", hit["snippet"])

    def test_second_document_and_retire_are_followed(self):
        other = self.tmp / "audit.md"
        other.write_text("# Audit Handbook\n\n## 1 Scope\n\nThe quokka audit programme covers every base annually.\n")
        kb(self.tmp, "ingest", str(other), "--dept", "audit", "--title", "Audit Handbook", "--rev", "1")
        self.assertEqual(self.search("quokka audit programme")[0]["dept"], "audit")
        kb(self.tmp, "retire", "audit-handbook", "--reason", "test")
        gone = kb(self.tmp, "search", "quokka audit programme", "--dept", "audit", "--json", check=False)
        self.assertIn("nothing to search", gone.stderr)  # nothing left in the audit department...
        self.assertFalse([h for h in self.search("quokka audit programme") if "quokka" in h["snippet"]])  # ...nothing of it is left
        self.assertTrue(self.search("risk matrix"))  # the other department is untouched
        old = self.search("quokka audit programme", "--include-superseded")
        self.assertTrue(old and old[0]["superseded"])

    def test_replace_hides_the_old_revision(self):
        new = self.tmp / "sms6.md"
        new.write_text(self.f.read_text().replace("within 24 hours", "within 6 hours"))
        kb(self.tmp, "ingest", str(new), "--replace", "sms-manual", "--rev", "Rev 2")
        hit = self.search("submit a safety report within hours")[0]
        self.assertIn("6 hours", hit["snippet"])
        self.assertEqual(hit["revision"], "Rev 2")
        both = self.search("submit a safety report within hours", "--include-superseded")
        self.assertEqual({h["revision"] for h in both}, {"Rev 1", "Rev 2"})

    def test_filters_work_through_the_index(self):
        self.assertTrue(self.search("risk matrix", "--dept", "sms"))
        self.assertTrue(self.search("risk matrix", "--doc", "sms-man"))
        miss = kb(self.tmp, "search", "risk matrix", "--dept", "fdm", "--json", check=False)
        self.assertIn("nothing to search", miss.stderr)

    def test_reindex_and_a_deleted_index_are_both_fine(self):
        self.assertIn("indexed", kb(self.tmp, "reindex").stdout)
        shutil.rmtree(self.root / "_index")
        self.assertTrue(self.search("risk matrix"))
        self.assertTrue((self.root / "_index" / "search.db").exists())

    def test_a_broken_index_never_breaks_search(self):
        (self.root / "_index" / "search.db").write_bytes(b"this is not a database")
        self.assertTrue(self.search("risk matrix"))


class LinksTests(unittest.TestCase):
    """kb.py links: departments connect by words, and the map teaches itself."""

    FDM = ("# Chapter 1 Exceedances\n## 1.1 Unstable approach monitoring\nAn unstable approach is flagged when speed deviates. "
           "Unstable approach events are reviewed weekly.\n## 1.2 Event rates\nUnstable approach rate is trended per airport.\n")
    SMS = ("# Chapter 1 Hazards\n## 1.1 Hazard register\nEvery hazard is logged in the hazard register. "
           "Unstable approach hazards are assessed with the risk matrix.\n## 1.2 Indicators\nSPIs are reviewed monthly.\n")
    AUD = "# Chapter 1 Audit\n## 1.1 Findings\nFindings are categorised level 1 or 2.\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for dept, text in (("fdm", self.FDM), ("sms", self.SMS), ("audit", self.AUD)):
            f = self.tmp / f"{dept}.md"
            f.write_text(text)
            kb(self.tmp, "ingest", str(f), "--dept", dept, "--title", f"{dept.upper()} Manual")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def find(self, text, dept=None, *extra):
        args = ["links", "find", "--text", text, "--json", *extra] + (["--dept", dept] if dept else [])
        return json.loads(kb(self.tmp, *args).stdout)

    def test_a_word_points_at_the_department_whose_manual_uses_it(self):
        res = self.find("The unstable approach rate at Delhi is rising", "audit")
        self.assertEqual(res["related"][0]["dept"], "fdm")
        self.assertIn("unstable approach", res["related"][0]["via"])
        self.assertTrue(res["related"][0]["manuals"])
        self.assertEqual(res["related"][0]["manuals"][0]["file"].split("/")[0], "fdm")
        self.assertEqual(self.find("Please prepare the summary and the status report", "audit")["related"], [])  # filler only

    def test_it_learns_from_the_manuals_tasks_and_questions(self):
        self.find("unstable approach", "audit")  # discovered from the saved index
        shown = json.loads(kb(self.tmp, "links", "show", "--json").stdout)["links"]
        self.assertTrue(any(x["term"] == "unstable approach" and x["dept"] == "fdm" and "manuals" in x["src"] for x in shown))
        kb(self.tmp, "links", "learn", "--dept", "audit", "--text", "Prepare the corrective action plan for bird strikes", "--src", "task")
        res = self.find("Check the bird strike corrective action", "sms")
        self.assertEqual(res["related"][0]["dept"], "audit")
        self.find("Wildlife hazard review", "sms", "--learn")  # one mention is only a weak hint...
        self.assertEqual(self.find("wildlife", "audit")["related"], [])
        self.find("Wildlife hazard review", "sms", "--learn")  # ...a second one makes it a link
        self.assertEqual(self.find("wildlife", "audit")["related"][0]["dept"], "sms")
        kb(self.tmp, "links", "forget", "wildlife", "--dept", "sms")
        self.assertEqual(self.find("wildlife", "audit")["related"], [])

    def test_naming_a_department_and_the_asker_is_left_out(self):
        res = self.find("Check the SMS hazard register against the audit checklist", "audit")
        self.assertEqual([e["dept"] for e in res["related"]], ["sms"])  # audit is the asker; sms is named
        self.assertGreaterEqual(res["related"][0]["score"], 3.0)

    def test_memory_and_open_board_items_come_only_when_their_words_match(self):
        kb(self.tmp, "mem", "add", "--dept", "fdm", "--kind", "source-map", "--text",
           "Unstable approach thresholds: FDM Manual 1.1", "--src", "[FDM Manual §1.1]")
        kb(self.tmp, "mem", "add", "--dept", "fdm", "--kind", "lesson", "--text", "Hangar doors close at night", "--src", "user")
        kb(self.tmp, "board", "post", "--from", "sms", "--to", "fdm", "--subject", "Unstable approach trend",
           "--text", "Need the airport trend")
        kb(self.tmp, "board", "post", "--from", "sms", "--to", "fdm", "--subject", "Cafeteria menu", "--text", "Lunch?")
        res = self.find("Assess the unstable approach hazard", "sms")
        fdm = res["related"][0]
        self.assertEqual([m["text"] for m in fdm["memory"]], ["Unstable approach thresholds: FDM Manual 1.1"])
        self.assertEqual([b["subject"] for b in fdm["board"]], ["Unstable approach trend"])
        text = kb(self.tmp, "links", "find", "--text", "Assess the unstable approach hazard", "--dept", "sms").stdout
        self.assertIn("Linked by keywords", text)
        self.assertNotIn("Hangar doors", text)

    def test_empty_kb_and_bad_input_are_calm(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, True)
        r = kb(empty, "links", "find", "--text", "anything at all", "--json")
        self.assertEqual(json.loads(r.stdout)["related"], [])
        self.assertNotEqual(kb(self.tmp, "links", "learn", "--dept", "sms", check=False).returncode, 0)
        self.assertNotEqual(kb(self.tmp, "links", "forget", "never-learned", check=False).returncode, 0)
        self.assertIn("nothing learned", kb(empty, "links", "show").stdout)


class DetectTests(unittest.TestCase):
    """match reads title, revision and date from the first pages, so nobody has to open every file."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def detect(self, name, text):
        f = self.tmp / name
        f.write_text(text)
        return json.loads(kb(self.tmp, "match", str(f), "--json").stdout)[0]["detected"]

    def test_cover_page(self):
        d = self.detect("manual.md", "Sample Airline\n\nSAFETY MANAGEMENT MANUAL\n\nRevision 05\nEffective date: 14 February 2026\n"
                                     "\n# Chapter 1\nIssue of reports and version control come later.\n")
        self.assertEqual((d["title"], d["title_source"]), ("Safety Management Manual", "cover"))
        self.assertEqual((d["revision"], d["revision_source"]), ("Rev 05", "cover"))
        self.assertEqual(d["effective"], "2026-02-14")

    def test_iso_date_and_issue_number(self):
        d = self.detect("x.md", "Hazard Register Procedure\nIssue 2 - Date of issue: 2026-03-01\n")
        self.assertEqual((d["title"], d["revision"], d["effective"]), ("Hazard Register Procedure", "Issue 2", "2026-03-01"))

    def test_ambiguous_numeric_date_is_not_guessed(self):
        d = self.detect("x.md", "Flight Data Monitoring Procedure\nAmendment 3\nEffective: 03/04/2026\n")
        self.assertIsNone(d["effective"])
        self.assertEqual(d["effective_raw"], "03/04/2026")
        d = self.detect("y.md", "Flight Data Monitoring Procedure\nEffective: 25/04/2026\n")
        self.assertEqual(d["effective"], "2026-04-25")

    def test_no_cover_means_not_found_not_a_wrong_guess(self):
        d = self.detect("plain_notes.txt", "Some notes.\nRevenue grew. Issued a statement. Version of the plan is unclear.\n")
        self.assertIsNone(d["revision"])
        self.assertIsNone(d["effective"])
        self.assertEqual((d["title"], d["title_source"]), ("plain notes", "file name"))

    def test_revision_falls_back_to_the_file_name(self):
        d = self.detect("SMS_Manual_R06.md", "Some text without a cover.\n")
        self.assertEqual((d["revision"], d["revision_source"]), ("Rev 6", "file name"))

    @unittest.skipUnless(HAVE_PDF, "no PDF backend installed")
    def test_pdf_reads_only_the_first_pages(self):
        f = fixtures.make_pdf(self.tmp / "sms.pdf")
        d = json.loads(kb(self.tmp, "match", str(f), "--json").stdout)[0]["detected"]
        self.assertEqual(d["revision"], "Rev 2")
        self.assertFalse(d["scanned"])

    def test_text_output_and_switches(self):
        f = self.tmp / "m.md"
        f.write_text("Audit Handbook\nRevision 3\n")
        out = kb(self.tmp, "match", str(f)).stdout
        self.assertIn('read from the file: title "Audit Handbook" (cover) · rev "Rev 3" (cover)', out)
        raw = json.loads(kb(self.tmp, "match", str(f), "--json", "--no-detect").stdout)[0]
        self.assertNotIn("detected", raw)

    def test_duplicates_are_not_read(self):
        f = fixtures.make_md(self.tmp / "sms.md")
        kb(self.tmp, "ingest", str(f), "--dept", "sms", "--title", "SMS Manual", "--rev", "1")
        dup = self.tmp / "same.md"
        shutil.copy(f, dup)
        rep = json.loads(kb(self.tmp, "match", str(dup), "--json").stdout)[0]
        self.assertEqual(rep["action"], "skip_duplicate")
        self.assertNotIn("detected", rep)



if __name__ == "__main__":
    unittest.main()
