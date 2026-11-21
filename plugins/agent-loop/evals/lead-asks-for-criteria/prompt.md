---
description: "The lead stops and asks when the task gives no testable criteria, and starts nothing."
tags: [smoke, lead]
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit, Agent]
runs: 3
---

/agent-loop:lead make textutil better
