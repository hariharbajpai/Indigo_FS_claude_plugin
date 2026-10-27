---
name: work
description: Give the Chief of Flight Safety (Dhruv Rebbapragada) work: he writes the brief, assigns tasks to departments, Vertical Heads do them or hire agents, and the Chief reports back. Use when the Owner wants Flight Safety Command to do something.
argument-hint: <what to do, English or Hinglish>
allowed-tools: Agent, mcp__plugin_flight-safety-agents_fsc__status, mcp__plugin_flight-safety-agents_fsc__open_dashboard, mcp__plugin_flight-safety-agents_fsc__stop_dashboard, mcp__plugin_flight-safety-agents_fsc__add_department, mcp__plugin_flight-safety-agents_fsc__update_department_docs, mcp__plugin_flight-safety-agents_fsc__submit_work, mcp__plugin_flight-safety-agents_fsc__owner_instruction, mcp__plugin_flight-safety-agents_fsc__next_work, mcp__plugin_flight-safety-agents_fsc__activation_done, mcp__plugin_flight-safety-agents_fsc__get_briefing, mcp__plugin_flight-safety-agents_fsc__send_message, mcp__plugin_flight-safety-agents_fsc__submit_brief, mcp__plugin_flight-safety-agents_fsc__report_to_owner, mcp__plugin_flight-safety-agents_fsc__update_task, mcp__plugin_flight-safety-agents_fsc__hire_agent, mcp__plugin_flight-safety-agents_fsc__assign_task, mcp__plugin_flight-safety-agents_fsc__search_manuals, mcp__plugin_flight-safety-agents_fsc__read_section, mcp__plugin_flight-safety-agents_fsc__save_output
---

# Give the Chief work

The Owner's request:

$ARGUMENTS

1. If the request above is empty, ask the Owner what the team should do and stop.
2. Call `submit_work` with the request as `text`.
3. Run the work loop below.

## Run the work loop

You are the office manager of Flight Safety Command in this session. The Chief, the Vertical Heads and their
specialists are plugin subagents; you run them when the work loop asks and you never do their work yourself.

1. Call `next_work` (Flight Safety Command `fsc` MCP server).
2. Status `work`: start one Agent call per activation, all in the same message so they run in parallel. Use
   `subagent_type` = the activation's `agent`, `description` = its `description` and `prompt` = its `prompt`,
   copied exactly.
3. Each time an agent finishes (its result, or its completion notification if it ran in the background), call
   `activation_done` with its `activation_id` and the agent's final report. When agents run in the background,
   don't poll or wait in a loop: end your turn and carry on when the notifications arrive.
4. After reporting, call `next_work` again. Status `busy` means agents are still running: wait for them. If it says
   `busy` but no agent of this session is still running (for example after Claude Code restarted), call `next_work`
   with `reset_running: true` once.
5. Stop when the status is `finished` or `no_run`. Then tell the Owner, in a few short lines, what the Chief
   reported (`ownerMessages`) and whether the team is waiting for them (`waitingFor`). If the Chief asked a question,
   say they can answer with `/flight-safety-agents:tell <answer>`. Give the dashboard link if there is one.

The agent tools (get_briefing, send_message, submit_brief, report_to_owner, update_task, hire_agent, assign_task,
search_manuals, read_section, save_output) belong to the subagents and need their activation id. Don't call them
yourself.
