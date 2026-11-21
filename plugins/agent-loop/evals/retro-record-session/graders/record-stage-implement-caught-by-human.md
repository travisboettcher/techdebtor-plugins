---
type: regex
target: trace
---
"name":"(?:Write|Bash)","input":\{(?=[^}]*\.claude/runs/)(?=[^}]*(?:stage: implement[^}]{0,400}?caught_by: human|caught_by: human[^}]{0,400}?stage: implement))
