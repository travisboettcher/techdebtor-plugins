---
description: "The reviewer coordinator chooses review specialists from tags and changed files, keeps floors and the baseline against an override, and says why (a selection-only dry run)."
tags: [full, reviewer]
max_turns: 8
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Agent]
runs: 3
---

You are standing in for the agent-loop lead. Start the `agent-loop:reviewer` agent with the text of `../reviewer-brief.txt` as its prompt, exactly as written, followed by this paragraph:

"Selection dry run: do steps Choose only. Start no specialist. End with your report's Tags, Chosen and Override problems lines, and nothing else."

Do none of the work yourself. When it returns, reply with its report exactly as it returned it, and nothing else.
