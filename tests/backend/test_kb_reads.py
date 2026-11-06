"""Cheap reads: search_manuals gives the line, read_section reads a small window from it (backend/fsa/kb_bridge.py)."""
import json
import os
import tempfile
import unittest

from helpers import REPO  # noqa: F401  (puts the repo on sys.path)

from backend.fsa import mcp_server
from backend.fsa.kb_bridge import KbBridge, MAX_READ_CHARS
from backend.fsa.store import Invalid, Store


def manual_text():
    """One long chapter (about 21,000 characters) so a whole-chunk read is bigger than a window."""
    out = ["# Chapter 1 Operations", ""]
    for n in range(1, 31):
        out += [f"## 1.{n} Topic number {n}", ""]
        for k in range(3):
            filler = " ".join(f"routine{n}x{k}x{i}" for i in range(14))
            out += [f"Paragraph {k} of topic {n}: {filler}.", ""]
        if n == 17:
            out += ["The zebrafish protocol requires a second check before release.", ""]
    return "\n".join(out)


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kb = KbBridge(os.path.join(self.tmp.name, "kb"))
        self.kb.ingest("sms", [("Ops_Manual.md", manual_text().encode())])
        [self.hit] = self.kb.search("zebrafish protocol", ["sms"], 1)

    def test_long_similar_department_names_keep_their_own_manuals(self):
        s = Store(os.path.join(self.tmp.name, "fsa.db"))
        self.addCleanup(s.close)
        (north, _), (south, _) = (s.create_department(f"Flight Operations Safety Reporting {x}", "H") for x in ("North", "South"))
        self.kb.ingest(north["id"], [("North Manual.md", b"# North Manual\n\n## 1 Scope\n\nNorth only.\n")])
        self.kb.ingest(south["id"], [("South Manual.md", b"# South Manual\n\n## 1 Scope\n\nSouth only.\n")])
        self.assertEqual(self.kb.list_docs(north["id"]), ["north-manual"])
        self.assertEqual(self.kb.list_docs(south["id"]), ["south-manual"])
        self.kb.retire(south["id"])
        self.assertEqual(self.kb.list_docs(north["id"]), ["north-manual"])  # retiring South leaves North alone

    def raw(self):
        with open(self.kb.inside(self.hit["file"]), encoding="utf-8") as f:
            return f.read()

    def whole(self):
        return self.kb.read_file(self.hit["file"])

    def test_search_gives_a_short_relative_path_and_the_line(self):
        self.assertFalse(os.path.isabs(self.hit["file"]))
        self.assertTrue(self.hit["line"] > 1)
        self.assertEqual(self.kb.read_file(self.hit["file"])["file"], os.path.realpath(self.kb.inside(self.hit["file"])))

    def test_reading_from_a_line_is_a_small_window_with_context(self):
        w = self.kb.read_file(self.hit["file"], self.hit["line"])
        self.assertIn("zebrafish", w["text"])
        self.assertEqual(w["from_line"], self.hit["line"])
        self.assertLess(len(w["text"]), 4000 + 300)  # the budget plus at most one more line
        self.assertTrue(w["truncated"])
        self.assertEqual(w["next_line"], w["to_line"] + 1)
        self.assertEqual(w["context"]["doc"], "Ops Manual")
        self.assertIn("Topic number 17", w["context"]["section"])

    def test_a_whole_file_read_is_capped_and_says_where_to_carry_on(self):
        full_size = len(self.raw())
        self.assertGreater(full_size, 16000)  # otherwise this test proves nothing
        r = self.whole()
        self.assertTrue(r["truncated"])
        self.assertLessEqual(len(r["text"]), 16000 + 300)
        self.assertEqual(r["from_line"], 1)
        self.assertTrue(r["text"].startswith("---"))  # the front matter is part of a from-the-top read
        self.assertNotIn("context", r)

    def test_carrying_on_from_next_line_has_no_gap_and_no_overlap(self):
        first = self.kb.read_file(self.hit["file"], 1, 3000)
        second = self.kb.read_file(self.hit["file"], first["next_line"], 3000)
        self.assertEqual(second["from_line"], first["to_line"] + 1)
        lines = self.raw().splitlines()
        self.assertEqual(first["text"] + "\n" + second["text"], "\n".join(lines[: second["to_line"]]))

    def test_the_last_window_says_it_is_the_end(self):
        total = self.whole()["total_lines"]
        r = self.kb.read_file(self.hit["file"], total)
        self.assertFalse(r["truncated"])
        self.assertNotIn("next_line", r)
        self.assertEqual(r["to_line"], total)

    def test_chars_is_clamped_and_a_line_past_the_end_is_safe(self):
        self.assertGreaterEqual(len(self.kb.read_file(self.hit["file"], 1, 5)["text"]), 100)
        self.assertLessEqual(len(self.kb.read_file(self.hit["file"], 1, 10 ** 9)["text"]), MAX_READ_CHARS + 300)
        past = self.kb.read_file(self.hit["file"], 10 ** 6)
        self.assertEqual(past["from_line"], past["total_lines"])

    def test_small_files_come_back_whole_and_bad_input_is_refused(self):
        out = self.kb.save_output("TK-1", "note", "# Note\nshort result\n")
        r = self.kb.read_file(out if isinstance(out, str) else out["path"])
        self.assertFalse(r["truncated"])
        self.assertIn("short result", r["text"])
        with self.assertRaises(Invalid):
            self.kb.read_file(self.hit["file"], "abc")
        with self.assertRaises(Invalid):
            self.kb.read_file("../../etc/hosts")

    def test_the_tool_schema_offers_line_and_chars(self):
        [(_, desc, schema)] = [t for t in mcp_server.TOOLS if t[0] == "read_section"]
        self.assertEqual(schema["properties"]["line"]["type"], "integer")
        self.assertEqual(schema["properties"]["chars"]["type"], "integer")
        self.assertEqual(schema["required"], ["activation", "file"])
        self.assertIn("line", desc)


if __name__ == "__main__":
    unittest.main()
