"""Static checks that the plugin's pieces point at each other correctly (what Claude Code loads)."""
import json
import os
import re
import unittest

from helpers import REPO

from backend.fsa import VERSION
from backend.fsa.loop import AGENT_TYPES
from backend.fsa.mcp_server import TOOLS

PREFIX = "mcp__plugin_flight-safety-agents_fsc__"
BUILTIN = {"Agent", "Read", "Grep", "Glob", "Bash", "Write", "Edit"}


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out, text


class PluginTests(unittest.TestCase):
    def test_versions_agree(self):
        plugin = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
        market = json.load(open(os.path.join(REPO, ".claude-plugin", "marketplace.json")))
        front = json.load(open(os.path.join(REPO, "frontend", "package.json")))
        self.assertEqual(plugin["version"], VERSION)
        self.assertEqual(market["plugins"][0]["version"], VERSION)
        self.assertEqual(front["version"], VERSION)

    def test_mcp_config(self):
        cfg = json.load(open(os.path.join(REPO, ".mcp.json")))["mcpServers"]["fsc"]
        self.assertEqual(cfg["command"], "python3")
        path = cfg["args"][0].replace("${CLAUDE_PLUGIN_ROOT}", REPO)
        self.assertTrue(os.path.isfile(path))

    def test_agents_exist_and_use_real_tools(self):
        names = {t[0] for t in TOOLS}
        for kind, typ in AGENT_TYPES.items():
            plugin, agent = typ.split(":")
            self.assertEqual(plugin, "flight-safety-agents")
            fm, body = frontmatter(os.path.join(REPO, "agents", agent + ".md"))
            self.assertEqual(fm["name"], agent)
            self.assertIn("Never use this agent for anything else", fm["description"])
            tools = [t.strip() for t in fm["tools"].split(",")]
            for t in tools:
                if t.startswith(PREFIX):
                    self.assertIn(t[len(PREFIX):], names, f"{agent}: {t}")
                else:
                    self.assertIn(t, BUILTIN, f"{agent}: {t}")
            mine = {t[len(PREFIX):] for t in tools if t.startswith(PREFIX)}
            self.assertTrue({"get_briefing", "send_message", "search_manuals", "save_output"} <= mine, agent)
            self.assertNotIn("next_work", mine)  # agents never run the loop
        self.assertIn("submit_brief", frontmatter(os.path.join(REPO, "agents", "chief-of-flight-safety.md"))[0]["tools"])
        self.assertIn("hire_agent", frontmatter(os.path.join(REPO, "agents", "vertical-head.md"))[0]["tools"])
        self.assertNotIn("hire_agent", frontmatter(os.path.join(REPO, "agents", "dept-specialist.md"))[0]["tools"])

    def test_no_new_agent_looks_like_a_department(self):
        for typ in AGENT_TYPES.values():
            self.assertFalse(typ.endswith("-agent"), typ)  # safety-team treats *-agent as departments

    def test_commands(self):
        names = {t[0] for t in TOOLS}
        for cmd in ("start", "add-dept", "work", "tell", "run", "status", "stop"):
            fm, body = frontmatter(os.path.join(REPO, "skills", cmd, "SKILL.md"))
            self.assertEqual(fm["name"], cmd)
            allowed = [t.strip() for t in fm["allowed-tools"].split(",")]
            for t in allowed:
                if t.startswith(PREFIX):
                    self.assertIn(t[len(PREFIX):], names, f"{cmd}: {t}")
                else:
                    self.assertIn(t, BUILTIN, f"{cmd}: {t}")
            for tool in re.findall(r"`([a-z_]+)`", body):
                if tool.endswith(("_work", "_done", "_dashboard", "_department", "_instruction")):
                    self.assertIn(tool, names, f"{cmd} mentions unknown tool {tool}")
        for cmd in ("work", "tell", "run"):
            body = open(os.path.join(REPO, "skills", cmd, "SKILL.md")).read()
            self.assertIn("activation_done", body)
            self.assertIn("reset_running", body)

    def test_ui_is_bundled(self):
        web = os.path.join(REPO, "backend", "fsa", "web")
        self.assertTrue(os.path.isfile(os.path.join(web, "index.html")))
        assets = os.listdir(os.path.join(web, "assets"))
        self.assertTrue(any(a.endswith(".js") for a in assets))
        html = open(os.path.join(web, "index.html")).read()
        for ref in re.findall(r'(?:src|href)="/assets/([^"]+)"', html):
            self.assertIn(ref, assets)


if __name__ == "__main__":
    unittest.main()
