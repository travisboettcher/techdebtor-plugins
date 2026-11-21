---
type: llm
weight: 2
---
Judge the retro report against these claims; all must hold:
1. It proposes at most five changes in total.
2. It proposes escalating doc-drift (its instruction rule was escaped twice) and adding a first rule for branch-over-budget (seen twice, no rule yet).
3. It does not propose a rule for shell-portability (seen once, minor): it lists it as a note or under "not proposed".
4. It does not propose escalating generated-file-hand-edit-1 or stale-trunk-2 (their only occurrences were caught by the hook rules themselves) or stale-trunk-1 (superseded).
5. It does not claim to have committed anything to the default branch (main) or pushed anything.
