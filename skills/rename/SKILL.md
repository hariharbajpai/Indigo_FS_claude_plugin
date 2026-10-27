---
name: rename
description: Rename anyone in Flight Safety Command, the Chief of Flight Safety, a Vertical Head, a hired specialist, or a department. Use when the Owner wants to change someone's name (for example "Chief ka naam Arjun Mehta kar do", "rename Asha to Asha Rao").
argument-hint: <current name, id or department> -> <new name>
allowed-tools: mcp__plugin_flight-safety-agents_fsc__rename, mcp__plugin_flight-safety-agents_fsc__status
---

# Rename

The Owner's input: $ARGUMENTS

1. Work out **who** (a current name or a unique part of it, an agent id such as `ag-2`, `chief`, or a department)
   and the **new name**. Accept any wording: "X -> Y", "X to Y", "X ka naam Y kar do", "rename X as Y". If either is
   missing or unclear, call `status`, show the current names in one short list, ask one question and stop.
2. Call `rename` with `target` and `new_name`.
3. Tell the Owner in one or two lines: old name → new name (and the role or department), and that the dashboard,
   chat feed and the agents use the new name from now on. Ids, tasks and history do not change.
4. If `rename` says the name was not found, matches several, or is already taken, show that message and the
   names to choose from, then ask which one.
