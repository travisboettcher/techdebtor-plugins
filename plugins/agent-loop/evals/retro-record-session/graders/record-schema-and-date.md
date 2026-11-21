---
type: regex
target: trace
---
"name":"(?:Write|Bash)","input":\{(?=[^}]*\.claude/runs/)(?=[^}]*schema: 1\b[^}]{0,200}?date: \d{4}-\d{2}-\d{2})
