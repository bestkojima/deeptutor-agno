# Exam Team prompts

Each UTF-8 Markdown file is a project-owned instruction for one role in the Agno Team exam flow. Edit it here instead of editing the orchestrator.

| File | Role |
| --- | --- |
| chief.md | Broadcast the exam request to the type teams |
| type-leader.md | Dispatch slots and check completion by ID only |
| designer.md | Write the assigned problems; apply reviewer feedback only in a repair run |
| blind-solver.md | Solve without seeing the author answer |
| reviewer.md | Decide mathematical and pedagogical acceptance; return actionable feedback |

`type-leader.md` uses three placeholders: `${kind}`, `${required_slots}`, and `${member_ids}`. These are filled from the runtime type, locked blueprint and actual registered members. Keep the names exact. The blueprint, target difficulty, question data and feedback are passed separately as JSON. There is no arbitrary file selection from the user request.

The dispatch checklist is a prompt, not a guarantee. Existing backend coverage and duplicate checks remain authoritative. No Agno source, workflow retry behavior or legacy Exam prompt is changed by these templates.
