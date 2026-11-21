# Verify skills: finding and choosing them

Read by `/agent-loop:lead` at step 3. A verify skill (`verify-<category>`) is a project's or the human's `check`-rung rule: a read-only procedure that reports violations as `path:line` lines and ends PASS or FAIL. The contract is `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md`, "Verify skills".

1. **Find** them with Glob: `.claude/skills/verify-*/SKILL.md` under the repo root, and `~/.claude/skills/verify-*/SKILL.md`. None found: the plan says so in one line and nothing else changes.
2. **Read only the frontmatter** of each (`name`, `description`, `paths`); the procedure is the check runner's to read.
3. **Choose per unit**, from the files that unit changes: a skill applies when one of those files matches its `paths` globs, or, without `paths`, when its "Use when ..." clause clearly covers them. When unsure, leave it out and say why in the plan. Never choose every skill for every unit: each costs a read and a pass.
4. **List** the chosen skills under each unit in the plan, so the human sees which repository procedures will be followed, and in the run record as `plan.verify_skills` (`unit` and `skills` per entry). A unit with none chosen is left out.
5. **Brief the tester** (step 5) with each chosen skill's path and `<base>`; it hands them to its `check-runner` specialist, which follows each procedure on the change since `<base>`, read-only by rule (a step that would run anything else is reported BLOCKED, not executed), and reports PASS, FAIL or BLOCKED like any verifier; it never runs a fix step. A FAIL is a finding in the skill's category, `caught_by: check`, at the stage where the mistake was made; a BLOCKED one is handled like any BLOCKED verifier (step 7).
