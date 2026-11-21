# lead

A tech lead for Claude Code. `/lead <task>` plans the task, delegates it to three subagents (implementer, tester, reviewer) in a bounded loop, and writes a run record of every mistake any stage caught.

## What it does

1. **Understand.** Reads `CLAUDE.md` and, if present, `.claude/rules-ledger.yml` and `~/.claude/rules-ledger.yml`. Every applicable rule goes into a rules brief that every agent receives.
2. **Plan.** Steps, each with acceptance criteria and a verifier (a test, command or check). Large or risky tasks wait for your approval.
3. **Implement.** The `implementer` agent makes the change and runs the verifiers. Parallel only for independent, non-overlapping steps; heavy jobs (full builds, mutation testing) never run in parallel.
4. **Test.** The `tester` agent runs the project's real verifiers and reports pass/fail with output. It does not fix code.
5. **Review.** The `reviewer` agent gets the diff, the acceptance criteria and the rules brief, and nothing else: no implementer reasoning, no lead conclusions. It reports only findings it has verified, each with category, severity, file:line and a failure scenario, or "no findings".
6. **Loop.** Implement, test, review until clean, or 3 rounds, then stop and report.
7. **Record.** Writes `.claude/runs/YYYY-MM-DD-<slug>.yml`.

It never commits, pushes or opens pull requests unless you ask.

## Install

```
/plugin marketplace add travisboettcher/agent-loops
/plugin install lead@agent-loops
```

## Usage

```
/lead add a --dry-run flag to the export command
```

Plugin skills are namespaced, so it may appear as `/lead:lead`. Give a round limit in the task if 3 is wrong ("... stop after 2 rounds"). The skill is user-invoked only; Claude does not start it on its own.

The agents (`lead:implementer`, `lead:tester`, `lead:reviewer`) can also be used directly, but they expect a brief with acceptance criteria and rules.

## Run record

Every run, including abandoned ones, ends with a YAML record in `.claude/runs/` in the format defined in [`docs/DESIGN.md`](../../docs/DESIGN.md):

```yaml
schema: 1
date: 2026-11-21
task: "Add a --dry-run flag to the export command"
repo: my-project
outcome: in-progress
stages: [plan, implement, test, review, implement, test, review]
findings:
  - stage: review
    category: missing-error-handling
    severity: major
    detail: "Dry run still opened the output file for writing."
    caught_by: reviewer
    fixed: true
notes: ""
```

A finding is something that went wrong and was caught, by any stage, by you, or by the lead itself. Categories are reused from earlier records and the rules ledger so they can be counted across runs. Records hold no secrets or personal data.

On first use the lead suggests adding `.claude/runs/` to `.gitignore`; it does not change it without asking. Commit the records instead if you want them shared.

## With retro

`lead` produces evidence; [`retro`](../retro) uses it. `/retro` reads run records (and ordinary session transcripts), finds categories that recur, and proposes rules on a promotion ladder (note, instruction, hook, test) for you to merge. Merged rules go into the rules ledger, which the next `/lead` run reads and passes to every agent. The next retro checks whether each rule's category stopped recurring.

## License

MIT
