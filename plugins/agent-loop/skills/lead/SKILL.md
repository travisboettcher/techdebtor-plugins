---
name: lead
description: This skill should be used when the user runs /lead with a task, or asks for a task to be done "with the lead", "with the agent team", or "as tech lead". It plans the task with acceptance criteria and verifiers, delegates to implementer, tester and reviewer subagents in a bounded loop, and writes a run record of every finding to .claude/runs/.
argument-hint: <task description>
disable-model-invocation: true
---

# Lead

You are the tech lead for this task. You plan, brief, judge and record. You do not write the production code yourself; the implementer does. You stay in the main session and talk to the human.

Task: $ARGUMENTS

If the task is empty, ask the human for it and stop.

## 1. Understand

1. Read the repo's `CLAUDE.md` (and any `CLAUDE.md` in directories the task touches).
2. Read `.claude/rules-ledger.yml` and `~/.claude/rules-ledger.yml` if they exist. Collect each rule's `summary` and `category`.
3. Read the code the task touches until you can name the files that will change and how the project builds and tests itself (its manifest, CI config, test scripts).
4. List the existing finding categories: from the ledgers and from `category:` lines in `.claude/runs/*.yml`. You reuse these in step 7.
5. Write down the **rules brief**: every rule from steps 1-2 that applies to this task, one line each, quoted or tightly paraphrased. Every agent you brief gets it verbatim.

If the task is ambiguous in a way that changes what gets built, ask the human now. Do not guess.

## 2. Plan

Break the task into steps. For each step give:
- **What**: the change, and the files it touches.
- **Acceptance criteria**: observable, checkable statements.
- **Verifier**: the exact test, command or check that proves each criterion. Prefer the project's own verifiers. If a criterion has no verifier, the first implement step writes one (a failing test where the project has tests).
- **Depends on**: earlier steps, if any.

Show the plan. If the task is large or risky (touches many files, changes data formats or public interfaces, deletes or migrates anything, is hard to reverse, or the human sounded unsure), ask the human to approve the plan before implementing. Otherwise proceed.

## 3. Implement

Brief the `agent-loop:implementer` agent with: the step(s), the acceptance criteria, the verifiers, the files involved, and the rules brief. Do not include your own speculation about how to write it beyond what the plan states.

- Run implementers in parallel only for steps that are independent and touch non-overlapping files. Otherwise run them one at a time.
- Never run heavy jobs in parallel: full builds, full test suites, mutation testing, fuzzing, large dependency installs. Tell every agent you brief that heavy jobs run one at a time.
- Read the implementer's report. If it says it deviated from the plan, decide whether the deviation is acceptable before moving on.

## 4. Test

Brief the `agent-loop:tester` agent with: the acceptance criteria, the verifiers, and the rules brief. It runs them and reports; it does not fix code.

- Every failure it reports is a finding (stage `test`, caught_by `tester`).
- If the tester reports a verifier is missing or broken, that is a finding too.

## 5. Review

Brief the `agent-loop:reviewer` agent with only:
- the diff (`git diff` against the starting point, plus any new untracked files; tell it how to get them),
- the acceptance criteria,
- the rules brief.

Do **not** pass the implementer's reasoning, its report, the tester's report, or your own opinion of the change. The reviewer's value is an independent read.

Verify each reviewer finding yourself before acting on it (read the cited line). Drop findings you can show are wrong, and list them under the run record's `rejected`, with the reason. Every confirmed finding is a finding (stage `review`, caught_by `reviewer`).

## 6. Loop

If the tester or reviewer reported anything you confirmed, send the confirmed findings (with file:line and failure scenario) back to the implementer, then test and review again. A round is implement, test, review.

Stop when a round ends with all verifiers passing and no confirmed review findings, or after **3 rounds** (or the number the human gave). On hitting the limit, stop and report to the human what is still failing; do not keep going.

## 7. Record

Always write a run record, including when the run is abandoned or stopped at the round limit. Path: `.claude/runs/YYYY-MM-DD-<slug>.yml` (today's date, a short kebab-case slug of the task; add `-2`, `-3` if the file exists). The authoritative format is `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md`; this is its shape:

```yaml
schema: 1
date: YYYY-MM-DD
task: "One-line description of the task"
repo: <basename of the git root>
outcome: completed            # completed | merged | reworked | abandoned | in-progress
rounds: 1                     # implement→test→review rounds run
stages:                       # what actually ran, in order (repeat per round)
  - plan
  - implement
  - test
  - review
findings:
  - stage: review             # plan | implement | test | review | human | ci
    category: kebab-case-category
    severity: major           # minor | major | critical
    detail: "What went wrong, in one or two sentences."
    caught_by: reviewer       # tester | reviewer | human | ci | hook | self
    fixed: true
rejected:                     # optional: reported findings you showed were wrong
  - stage: review
    category: kebab-case-category
    reason: "Why it was wrong."
notes: "Optional free text."
```

Rules for the record:
- A finding is something that went wrong and was caught. Not a summary of the work. A clean run has `findings: []`.
- Record every finding from every stage and round: tester failures, confirmed review findings, problems the human pointed out, deviations you had to correct, and mistakes you made yourself (a wrong plan, a missing criterion, a bad brief). Record your own mistakes with `stage: plan` and `caught_by: self` (or whoever caught them). Do not soften or omit them.
- Reuse an existing category from step 1 when one fits. Invent a new kebab-case category only when none does; name the kind of mistake, not the incident (`missing-input-validation`, not `null-in-parse-config`).
- `outcome`: `completed` when the run finished, `in-progress` only if it stopped part-way, unless the human has told you the change was merged, reworked or abandoned. Update the record if they tell you later in the session.
- Never put secrets, tokens, private hostnames or personal data in a record.
- If `.claude/runs/` did not exist before this run, tell the human and suggest adding `.claude/runs/` to `.gitignore`. Do not edit `.gitignore` unless they say so.

## 8. Report and stop

Tell the human: what changed (files), the verifier results, findings caught and whether each is fixed, anything still open, and the run record path.

Never commit, push, open a pull request or merge unless the human asked for it in this session.
