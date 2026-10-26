"""End-to-end tests for kb.py. Run:  python3 -m unittest discover -s tests -v"""
import json
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


def kb(tmp: Path, *args, check=True):
    r = subprocess.run([sys.executable, "-I", str(KB_PY), *args, "--kb", str(tmp / "safety-kb")],
                       capture_output=True, text=True)
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


if __name__ == "__main__":
    unittest.main()
