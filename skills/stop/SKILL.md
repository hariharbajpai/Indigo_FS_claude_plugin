---
name: stop
description: Stop the Flight Safety Command dashboard server. Use when the Owner asks to stop or shut down the dashboard.
allowed-tools: mcp__plugin_flight-safety-agents_fsc__stop_dashboard
---

# Stop the dashboard

Call `stop_dashboard` and tell the Owner it is stopped. Their departments, work and history are kept;
`/flight-safety-agents:start` opens it again.
