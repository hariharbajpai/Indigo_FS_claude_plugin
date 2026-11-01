---
name: update
description: Update Flight Safety Agents to the latest version from GitHub. Use when the Owner asks to update, upgrade or refresh the plugin, or asks for the latest version (for example "plugin update karo").
allowed-tools: Bash(claude plugin marketplace update flight-safety-agents), Bash(claude plugin update flight-safety-agents@flight-safety-agents), Bash(claude plugin update flight-safety-agents@flight-safety-agents *), Bash(claude plugin list), Bash(claude plugin list *)
---

# Update the plugin

1. Run `claude plugin marketplace update flight-safety-agents` to fetch the latest catalog from GitHub.
2. Run `claude plugin update flight-safety-agents@flight-safety-agents`.
   If it says the plugin is not installed at that scope, run `claude plugin list`, find the scope shown for
   `flight-safety-agents@flight-safety-agents`, and run the update again with `--scope <that scope>`.
3. Tell the Owner, in two or three short lines:
   - The version before and after (from the command output), or that they already have the latest.
   - To run `/reload-plugins` or start a new session to use it; this session keeps the version it loaded.
   - The dashboard switches to the new version the next time `/flight-safety-agents:start` runs.
4. If `claude` is not found or a step fails, show the error in one line and give these two commands to run in
   a terminal instead:
   `claude plugin marketplace update flight-safety-agents`
   `claude plugin update flight-safety-agents@flight-safety-agents`

To get future versions automatically, tell them once: in a Claude Code terminal session run `/plugin`, open the
**Marketplaces** tab, select `flight-safety-agents` and choose **Enable auto-update**.

Don't run any other commands.
