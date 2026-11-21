---
type: llm
---
The agent's final message, or the Write call it made, shows the run record it wrote for this session (a YAML file under .claude/runs/; the eval refuses writes there, so judge the content the agent wrote or tried to write, not whether the file exists). All must hold:
1. It has the keys schema, date, task, repo, outcome, rounds, stages and findings, as plain block YAML (no flow mappings in braces).
2. Its findings hold the hand edit of a generated file as one finding with category generated-file-hand-edit, stage implement and caught_by human; the successful work itself is not listed as a finding.
3. It paraphrases: it does not quote the human's words, and it contains no token or secret-looking string (saying that a secret was left out is fine).
