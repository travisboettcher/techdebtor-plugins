# Test levels: classifying tests and reporting by level

Read by the level-aware verification specialists of `agent-loop` when their brief or Job says so. The contract, with what each level proves and how the levels relate, is `docs/DESIGN.md`, "Test levels". The rule behind all of it: prove each behaviour at the lowest level that can prove it.

## The levels

| Level | Its real dependencies |
|---|---|
| `unit` | None: pure code, no I/O, no clock or randomness it does not control. |
| `component` | One module or service through its public interface, its boundaries faked or in memory. |
| `contract` | One side of an interface checked against the other side's expectations or a shared schema, without running both. |
| `integration` | A real collaborator: a database, queue, cache, filesystem or network service. |
| `system` | The whole app through a real user path: HTTP to a running server, the CLI run as a process, a browser. |

## Classify

The test runner classifies, since it runs commands. Every other specialist uses the test runner's per-level report, and never runs a command to classify; where it must place one test the report does not name, it reads that test's code by the rules below.

Classify each test in this order, and say which way you used:

1. **Real dependencies**, where the stack shows them:
   - The test's setup. In pytest, its fixture closure: `pytest --fixtures-per-test` or `pytest --setup-plan` on the selected tests list the fixtures without running test bodies, but both import the test code and conftest files, so treat them like running the suite. Neither marks which fixtures are autouse: find those with a grep for `autouse=True` in conftest and fixture files, and leave them out, since every test has them. Elsewhere, its setup and imports: a container or server start, a database or HTTP client, a subprocess of the app.
   - The test's body. Grep it for resources it opens itself: database clients or connections, sockets, HTTP clients, `subprocess` calls, network addresses.
   - The most real dependency decides: a test that opens a database is `integration`, whatever its marker says. A process-local temporary directory (`tmp_path`, `tmpdir`, `tempfile`, and their equivalents) is not a real collaborator: such a test stays `unit` or `component`.
2. **The project's own convention**, only where real dependencies cannot be seen: directories (`tests/unit/`, `tests/e2e/`), naming, markers, separate CI jobs. Say that the level comes from convention.
3. Otherwise **`unclassified`**. Report it as such; never guess.

A contract test is recognised by what it checks (one side against the other's expectations or a schema), or by the project's contract tooling: consumer-driven contract files, a schema compatibility step, a broker.

## Report by level

The test runner reports one check per level that has tests, in the shared report's Checks list, with the numbers in its evidence line even when it passes:

```
- `<command for the level, or "classified from the full run">` (level <unit | component | contract | integration | system | unclassified>, by <real dependencies | convention>): PASS | FAIL | ...
  <tests> tests, <failed> failed, <skipped> skipped, <seconds> s
```
