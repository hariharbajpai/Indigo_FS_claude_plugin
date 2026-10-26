---
name: safety-add-department
description: Create a new custom department (specialist skill + agent + knowledge folder) for the flight-safety team. Use when the user wants another team beyond Audit, SMS and FDM, such as Flight Operations Safety, Investigation, Cabin Safety, Ground Safety, Maintenance Safety, Training, Security, Emergency Response, Dangerous Goods, Fatigue Risk Management, or says "add a department", "make an agent for X team", "create a skill for our X department".
---

# Add a department

Creates everything a new department needs so it works with the others in `safety-team`:

1. a knowledge folder `safety-kb/<dept>/`,
2. a specialist skill `<dept>-dept` (what the team does, workflows, outputs),
3. an agent `<dept>-agent` (so the coordinator can run it as a subagent).

## Steps

1. **Interview the user briefly (one message, not a questionnaire).** You need:
   - Department name and a short code (`ops-safety`, `cabin`, `investigation`). Lower-case, hyphens.
   - What the team does day to day: its 3-6 main tasks (these become the workflows).
   - The documents they work from (manuals, regulations, forms), so you can tell the user what to ingest.
   - Their usual outputs (reports, registers, checklists, briefs) and any mandatory format.
   - Which other departments they depend on or feed.
   If the user already described the department, do not ask again; fill gaps with sensible defaults and say what you assumed.

2. **Generate the files from the templates** in `assets/` (next to this file):
   - `assets/dept-skill.template.md` → `.claude/skills/<code>-dept/SKILL.md`
   - `assets/dept-agent.template.md` → `.claude/agents/<code>-agent.md`

   Put them in the **user's project** `.claude/` folder (create it if needed), not in the plugin folder, so plugin updates do not erase them. Replace every `{{PLACEHOLDER}}`. Write real workflows for the tasks the user described: concrete steps, the output table or template, what to cite, which departments to cross-reference. Do not leave generic filler.

3. **Create the knowledge folder:** `mkdir -p safety-kb/<code>` (the KB root is `./safety-kb` or `$SAFETY_KB_DIR`).

4. **Tell the user what to do next:**
   - Restart or reload Claude Code so the new skill and agent are picked up.
   - Ingest the department's documents: "ingest this into `<code>`" (safety-kb skill).
   - Try it: "@`<code>` ...", or include it in a `safety-team` request.

5. **Check your work:** open the generated files once more and confirm no placeholders remain, the `name:` fields match the file/folder names, and the description names the triggers a user would actually say.

## Quality bar for the generated skill

- The description lists concrete task words and the department's name, so it triggers.
- It starts with "Before you answer": read the department INDEX, search own folder + `shared`, cross-reference named departments.
- Workflows have steps and an output template (table or headed sections).
- It keeps the shared rules: cite everything, label general knowledge, de-identify people, decision support only, response contract from the safety-kb skill's `references/conventions.md`.
- No invented regulations or numbers. If the user's documents are not ingested, the skill says to ask for them.
