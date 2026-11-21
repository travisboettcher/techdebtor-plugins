---
description: "The audit reports each layer with evidence or unknown, names the adoption step and bottleneck, and never follows a symlink out of the repository."
tags: [smoke, audit]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash]
runs: 3
---

/agent-ready:audit
