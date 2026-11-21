---
type: llm
---
The report explains the choice: correctness-reviewer runs as the baseline even though the project override tries to change the baseline. It also says that security-reviewer runs for the untrusted-input tag as its floor even though the override's run list for that tag leaves it out, and that permissions-reviewer runs because the permissions tag was added from the changed CI workflow's permissions block. The override's attempt to change the baseline is listed as an override problem. No specialist was started.
