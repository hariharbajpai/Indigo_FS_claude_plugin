---
name: model
description: Show which Claude (Opus, Sonnet or Haiku) each agent of Flight Safety Command uses, and upgrade or change it. Use when the Owner asks which Claude or model the team is on, wants a stronger or faster model, or says "upgrade the Claude", "use opus", "sonnet use karo".
argument-hint: [recommended | best | economy | inherit | opus | sonnet | haiku | <role>=<model> ...]
allowed-tools: mcp__plugin_flight-safety-agents_fsc__models, mcp__plugin_flight-safety-agents_fsc__set_models
---

# Which Claude is the team using

The Owner's input: $ARGUMENTS

1. Call `models`. It gives the model of this Claude Code session (as last reported by the work loop; "not reported yet" until the team has run once), the model each kind of agent uses (`chief`, `checker` = the File Checker, `head` = Vertical Heads, `hired` = specialists), the presets and a hint.
2. If the input is empty: tell the Owner in a few short lines which Claude the session and each kind of agent use, then offer the choices: **recommended** (Chief and File Checker on Opus, departments on Sonnet), **best** (everyone on Opus), **economy** (Sonnet, hired specialists on Haiku) and **inherit** (everyone uses the session's model). Say that the Opus/Sonnet/Haiku settings always mean the newest version of that model available to their plan, and that they can change the session's own model with `/model` in Claude Code.
3. If the input names a preset (`recommended`, `best`, `economy`, `inherit`), call `set_models` with `preset`. If it is just a model (`opus`, `sonnet`, `haiku`), call `set_models` with `roles` = `{"all": "<model>"}`. If it is `role=model` pairs (for example `chief=opus head=sonnet`), call `set_models` with those `roles`. Accept natural wording ("chief ko opus kar do", "sab sonnet").
4. After `set_models`, tell the Owner the new setting per kind of agent in one short list and that it applies from the next run (`/flight-safety-agents:work` or `:run`). If a run later fails with a model error, the plan may not include that model: set that role back to `inherit`.
5. The dashboard's Overview shows the same table with buttons to change it.
