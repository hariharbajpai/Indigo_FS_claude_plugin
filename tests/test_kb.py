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


if __name__ == "__main__":
    unittest.main()
