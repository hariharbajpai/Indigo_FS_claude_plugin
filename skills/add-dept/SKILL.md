---
name: add-dept
description: Add a department to Flight Safety Command from its PDF manuals plus the name of its Vertical Head. Use when the Owner wants to add a department, upload a department's PDFs, or name a Vertical Head.
argument-hint: <department name> | <Vertical Head name> | <PDF path> [more PDF paths]
allowed-tools: mcp__plugin_flight-safety-agents_fsc__add_department, mcp__plugin_flight-safety-agents_fsc__update_department_docs, mcp__plugin_flight-safety-agents_fsc__status, Glob
---

# Add a department

The Owner's input: $ARGUMENTS

1. Work out three things from the input and the conversation: the department name, the Vertical Head's name, and
   the PDF files (absolute paths; files the Owner attached or dropped in count). If any of the three is missing,
   ask for all missing items in one short question and stop. Use Glob only to find PDF paths the Owner described.
2. Call `add_department` with `name`, `head_name` and `files`.
3. The answer is `created`: tell the Owner the department id, its Vertical Head, and the documents ingested.
   The answer is `needs_decision`: show one short line per file (duplicate, or a new version of a document in
   department X) and ask the Owner whether to **update** that department's document or **add a new department**
   anyway. Then call `add_department` again with `decision: "replace"` and `target: <department id>`, or
   `decision: "new"`. Never decide for the Owner.
4. An error (not a PDF, no text in the PDF, missing name): tell the Owner what to fix.

End by saying they can now give work with `/flight-safety-agents:work <what to do>`.
