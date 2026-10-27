---
name: start
description: Start Flight Safety Command: the live dashboard (work, task board, org chart, agent chats, Owner console) for the Chief of Flight Safety, Vertical Heads and their agents. Use when the Owner asks to start, open or show Flight Safety Command or its dashboard.
allowed-tools: mcp__plugin_flight-safety-agents_fsc__open_dashboard, mcp__plugin_flight-safety-agents_fsc__status
---

# Start Flight Safety Command

1. Call `open_dashboard` (Flight Safety Command `fsc` MCP server).
2. Call `status`.
3. Tell the Owner, in a few short lines:
   - The dashboard link from step 1, in full (it carries the access token), and that it updates live.
   - Who is in the organisation: Dhruv Rebbapragada (Chief of Flight Safety), each department and its Vertical
     Head, hired agents, and any open work.
   - What they can do next:
     - `/flight-safety-agents:add-dept <department name> | <Vertical Head name> | <PDF paths>` to add a department.
     - `/flight-safety-agents:work <what to do>` to give the Chief work.
     - `/flight-safety-agents:tell <instruction>` to steer mid-way (to the Chief, or `@<department id>`).
     - `/flight-safety-agents:run` after giving work or instructions from the dashboard.
   - The agents run as subagents in this Claude Code session, on its own login.

Don't run any other commands.
