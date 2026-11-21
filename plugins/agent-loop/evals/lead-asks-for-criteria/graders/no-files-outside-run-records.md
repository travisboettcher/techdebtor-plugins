---
type: regex
target: files
match: not_contains
flags: m
---
^(?!\.claude/|\.git/)(?!.*__pycache__/).+
