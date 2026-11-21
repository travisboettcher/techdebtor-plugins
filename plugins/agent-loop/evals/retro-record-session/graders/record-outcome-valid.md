---
type: regex
target: trace
---
"name":"(?:Write|Bash)","input":\{(?=[^}]*\.claude/runs/)(?=[^}]*outcome: "?(?:completed|merged|reworked|abandoned|in-progress)\b)
