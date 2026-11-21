---
description: "With --json, the audit ends with one JSON block in the rubric's shape: its layer ids, answers and gates are the documented ones."
tags: [full, audit]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash]
runs: 3
---

/agent-ready:audit --json
