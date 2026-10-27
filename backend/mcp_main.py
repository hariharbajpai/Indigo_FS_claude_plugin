"""Entry point for the plugin's MCP server: python3 ${CLAUDE_PLUGIN_ROOT}/backend/mcp_main.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.fsa.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
