---
description: "The test strategist, briefed as the tester coordinator would, assigns each criterion the lowest test level that can prove it and flags a criterion tested only end to end and a changed interface between components with no contract test."
tags: [full, tester]
max_turns: 8
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Agent]
runs: 3
---

You are standing in for the agent-loop tester coordinator. Start the `agent-loop:test-strategist` agent with the text of `../strategist-brief.txt` as its prompt, exactly as written.

Do none of the work yourself. When it returns, reply with its report exactly as it returned it, and nothing else.
