"""Flight Safety Command command line (run from the plugin folder):

  python3 -m backend.fsa start [--kb PATH] [--port N] [--open]   start the dashboard in the background
  python3 -m backend.fsa stop|status [--kb PATH]
  python3 -m backend.fsa serve [--port N] [--token T]             run the dashboard server in the foreground
  python3 -m backend.fsa mcp                                      run the MCP server on stdio
"""
import argparse
import json
import os
import signal
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m backend.fsa", description="Flight Safety Command")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("start", "stop", "status"):
        s = sub.add_parser(name)
        s.add_argument("--kb", help="knowledge base folder (default: ./safety-kb)")
        if name == "start":
            s.add_argument("--port", type=int)
            s.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=4810)
    s.add_argument("--token", default=os.environ.get("FSA_DASHBOARD_TOKEN"),
                   help="dashboard token (default $FSA_DASHBOARD_TOKEN; empty = no token, for development)")
    sub.add_parser("mcp")
    a = p.parse_args(argv)

    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main()
    if a.cmd == "serve":
        from .server import App, serve
        app = App(token=a.token or None)
        httpd = serve(app, a.host, a.port)
        def _term(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, _term)
        print(f"Flight Safety Command dashboard on http://{a.host}:{a.port} (KB {app.kb.root})", flush=True)
        try:
            httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
            app.close()
        return 0
    from . import daemon
    if a.cmd == "start":
        out = daemon.start(a.kb, a.port, a.open)
    elif a.cmd == "stop":
        out = daemon.stop(a.kb)
    else:
        out = daemon.status(a.kb)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
