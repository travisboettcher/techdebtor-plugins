---
description: "A delegated lead (agent-loop:lead-worker) plans, then ends its turn with exactly one valid PLAN_READY checkpoint and builds nothing before approval."
tags: [smoke, lead, delegated]
max_turns: 8
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Bash, Write, Edit, Agent]
runs: 3
---

You are standing in for the agent-loop dispatcher. Start the `agent-loop:lead-worker` agent in the foreground (not in the background, and without a worktree) with the text of `../lead-brief.txt` as its whole prompt, exactly as written. Do none of the work yourself. When it returns, reply with its final message exactly as it returned it, and nothing else.
