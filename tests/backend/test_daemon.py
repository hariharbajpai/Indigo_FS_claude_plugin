"""The background dashboard server (backend/fsa/daemon.py): start, reuse, token, stop."""
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

import helpers  # noqa: F401  (puts the repo on sys.path)

from backend.fsa import VERSION, daemon


def get(url, token=None):
    req = urllib.request.Request(url, headers={"X-FSA-Token": token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "safety-kb")
        self.addCleanup(daemon.stop, self.root)

    def test_start_reuse_stop(self):
        self.assertFalse(daemon.status(self.root)["running"])
        st = daemon.start(self.root, port=48100)
        self.assertTrue(st["started"])
        self.assertIn(f"?token={st['token']}", st["url"])
        base = f"http://127.0.0.1:{st['port']}"
        self.assertEqual(json.loads(get(base + "/api/health")[1])["version"], VERSION)
        self.assertEqual(get(base + "/api/overview")[0], 401)
        code, body = get(base + "/api/overview", st["token"])
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["kb_root"], self.root)
        self.assertEqual(get(base + "/")[0], 200)
        again = daemon.start(self.root)
        self.assertFalse(again["started"])
        self.assertEqual(again["url"], st["url"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, "_team", "fsa.db")))
        self.assertTrue(daemon.stop(self.root)["stopped"])
        self.assertFalse(daemon.status(self.root)["running"])
        self.assertIsNone(daemon.url(self.root))

    def test_dead_server_is_replaced(self):
        st = daemon.start(self.root, port=48120)
        os.kill(st["pid"], 15)
        import time
        for _ in range(40):
            if not daemon.status(self.root)["running"]:
                break
            time.sleep(0.1)
        st2 = daemon.start(self.root, port=48120)
        self.assertTrue(st2["started"])
        self.assertNotEqual(st2["token"], st["token"])


if __name__ == "__main__":
    unittest.main()
