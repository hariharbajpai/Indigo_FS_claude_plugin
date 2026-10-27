"""The plugin's MCP server over real stdio, the way Claude Code runs it (backend/mcp_main.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import HAS_PDFTOTEXT, REPO, fixtures

PREFIX = "mcp__plugin_flight-safety-agents_fsc__"


class McpProcess:
    def __init__(self, cwd, env=None):
        e = dict(os.environ)
        for k in ("FSA_KB_ROOT", "FSA_DB", "SAFETY_KB_DIR", "CLAUDE_PROJECT_DIR"):
            e.pop(k, None)
        e.update(env or {})
        self.p = subprocess.Popen([sys.executable, os.path.join(REPO, "backend", "mcp_main.py")], cwd=cwd, env=e,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.n = 0

    def send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def rpc(self, method, params=None):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        return json.loads(self.p.stdout.readline())

    def call(self, tool, **args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})["result"]
        text = r["content"][0]["text"]
        return (True, text) if r["isError"] else (False, json.loads(text))

    def ok(self, tool, **args):
        err, data = self.call(tool, **args)
        if err:
            raise AssertionError(f"{tool}: {data}")
        return data

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)
        self.p.stdout.close()
        self.p.stderr.close()


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.m = McpProcess(self.tmp.name)
        self.addCleanup(self.m.close)

    def test_handshake_and_tools(self):
        init = self.m.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "test", "version": "1"}})["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertIn("tools", init["capabilities"])
        self.assertIn("next_work", init["instructions"])
        self.m.send({"jsonrpc": "2.0", "method": "notifications/initialized"})  # no reply expected
        self.assertEqual(self.m.rpc("ping")["result"], {})
        tools = self.m.rpc("tools/list")["result"]["tools"]
        self.assertEqual(len(tools), 19)
        for t in tools:
            self.assertLessEqual(len(PREFIX + t["name"]), 64, t["name"])  # Claude's tool-name limit
            self.assertEqual(t["inputSchema"]["type"], "object")
        self.assertIn("error", self.m.rpc("nope/method"))
        old = self.m.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(old["protocolVersion"], "2025-06-18")

    def test_nothing_created_until_needed_and_errors(self):
        st = self.m.ok("status")
        self.assertIn("Not set up yet", st["message"])
        self.assertEqual(self.m.ok("next_work")["status"], "no_run")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "safety-kb")))  # cwd = the project
        err, text = self.m.call("submit_work")
        self.assertTrue(err)
        self.assertIn("Bad arguments", text)
        err, text = self.m.call("does_not_exist")
        self.assertTrue(err)
        err, text = self.m.call("add_department", name="X", head_name="Y", files=["/nope.pdf"])
        self.assertTrue(err)
        self.assertIn("File not found", text)
        err, text = self.m.call("send_message", activation="act-x", to="owner", text="hi")
        self.assertTrue(err)
        self.assertIn("Stop now", text)

    def test_kb_root_from_env(self):
        m = McpProcess(self.tmp.name, {"CLAUDE_PROJECT_DIR": os.path.join(self.tmp.name, "proj")})
        self.addCleanup(m.close)
        self.assertEqual(m.ok("status")["kb_root"], os.path.join(self.tmp.name, "proj", "safety-kb"))


@unittest.skipUnless(HAS_PDFTOTEXT, "kb.py needs pdftotext (or pypdf/PyMuPDF)")
class FullFlowTests(unittest.TestCase):
    """Owner -> Chief brief -> Head hires -> specialist does it -> Chief reports, all through MCP tools."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.m = McpProcess(self.tmp.name)
        self.addCleanup(self.m.close)
        self.m.rpc("initialize", {"protocolVersion": "2025-06-18"})
        import pathlib
        self.pdf = str(fixtures.make_pdf(pathlib.Path(self.tmp.name) / "engine_manual.pdf"))

    def test_flow(self):
        m = self.m
        r = m.ok("add_department", name="Engine Maintenance", head_name="Asha Verma", files=[self.pdf])
        self.assertEqual(r["status"], "created")
        self.assertTrue(os.path.isdir(os.path.join(self.tmp.name, "safety-kb", "engine-maintenance")))
        dup = m.ok("add_department", name="Engine Two", head_name="Nina", files=[self.pdf])
        self.assertEqual(dup["status"], "needs_decision")
        wr = m.ok("submit_work", text="Engine hazard identification process check karo")["work_request"]
        [c] = m.ok("next_work")["activations"]
        self.assertEqual(c["agent"], "flight-safety-agents:chief-of-flight-safety")
        hits = m.ok("search_manuals", activation=c["activation_id"], query="hazard identification")["results"]
        self.assertTrue(hits)
        m.ok("submit_brief", activation=c["activation_id"], work_request_id=wr["id"], summary="Check hazard ID",
             goals=["Gaps listed"], tasks=[{"title": "Review hazard ID", "dept": "engine-maintenance",
                                            "acceptance": "Gaps with manual refs"}])
        m.ok("activation_done", activation_id=c["activation_id"], report="Brief v1")
        [h] = m.ok("next_work")["activations"]
        self.assertEqual(h["agent"], "flight-safety-agents:vertical-head")
        m.ok("hire_agent", activation=h["activation_id"], name="Ravi", role="Hazard analyst", reason="Depth",
             task_id="TK-1")
        m.ok("activation_done", activation_id=h["activation_id"], report="Hired Ravi")
        [s] = m.ok("next_work")["activations"]
        self.assertEqual(s["agent"], "flight-safety-agents:dept-specialist")
        sec = m.ok("read_section", activation=s["activation_id"], file=hits[0]["file"])
        self.assertIn("Hazard", sec["text"])
        out = m.ok("save_output", activation=s["activation_id"], task_id="TK-1", title="hazard id review",
                   content="# Hazard ID review\nNo gaps (engine manual §3, p.4).")["path"]
        m.ok("update_task", activation=s["activation_id"], task_id="TK-1", status="done", note=f"No gaps. {out}")
        m.ok("activation_done", activation_id=s["activation_id"], report="Done")
        [c2] = m.ok("next_work")["activations"]
        self.assertIn("are done", c2["prompt"])
        m.ok("report_to_owner", activation=c2["activation_id"], work_request_id=wr["id"], text="No gaps found.")
        m.ok("activation_done", activation_id=c2["activation_id"], report="Reported")
        fin = m.ok("next_work")
        self.assertEqual(fin["status"], "finished")
        self.assertTrue(any("No gaps found." in x for x in fin["ownerMessages"]))
        st = m.ok("status")
        self.assertEqual(st["work_requests"][0]["status"], "Done")
        self.assertEqual(st["departments"][0]["hired"], ["Ravi (Hazard analyst)"])
        ins = m.ok("owner_instruction", text="Ab cabin safety bhi dekho", target="chief")
        self.assertEqual(ins["delivered_to"], "Dhruv Rebbapragada")


if __name__ == "__main__":
    unittest.main()
