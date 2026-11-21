---
type: llm
focus: trace
---
Find the run record the agent wrote for this session (a YAML file under .claude/runs/, written with the Write tool or a shell command; the eval refuses writes there, so judge the content the agent wrote or tried to write, not whether the file exists). If there is none, fail. Otherwise all must hold:
1. It has the keys schema, date, task, repo, outcome, rounds, stages and findings, as plain block YAML (no flow mappings in braces).
2. Its findings hold the hand edit of a generated file as one finding with category generated-file-hand-edit, stage implement and caught_by human; work that went fine is not listed as a finding.
3. Its outcome says the change was not completed (abandoned, or in-progress), since the human decided not to go ahead.
4. It paraphrases: it does not quote the human's words, and it contains no token or secret-looking string (saying that a secret was left out is fine).
