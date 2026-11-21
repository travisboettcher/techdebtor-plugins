import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_ready_scan import scan, CHECK_PATTERNS, scan_line_checks

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "agent_ready_scan.py"


def jobs(result):
    return [j for wf in result["ci"]["workflows"] for j in wf["jobs"]]


def job(result, name):
    matches = [j for j in jobs(result) if j["name"] == name]
    assert matches, f"no job {name!r} in {[j['name'] for j in jobs(result)]}"
    return matches[0]


def ci_kinds(result):
    return {k for j in jobs(result) for k in j["checks"]}


def tools(result, kind=None):
    return {t["tool"] for t in result["tools"] if kind is None or t["kind"] == kind}


# ---------------------------------------------------------------------------
# A Python repo with GitHub Actions running pytest and mypy
# ---------------------------------------------------------------------------

PY_WORKFLOW = """\
name: CI
on:
  pull_request:
    paths:
      - "src/**"
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      PYTHONHASHSEED: "0"
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .[dev]
      - run: pytest --cov=src --cov-report=xml
      - uses: actions/upload-artifact@v4
        with:
          name: coverage
          path: coverage.xml
  types:
    runs-on: ubuntu-latest
    steps:
      - run: mypy src
  # - run: mutmut run   (commented out, must not count)
  report:
    needs: [test, types]
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/download-artifact@v4
      - run: echo "::warning::coverage below target"
"""

PY_REPO = {
    "pyproject.toml": """\
[project]
name = "demo"
dependencies = ["requests"]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "mypy", "hypothesis", "schemathesis"]

[tool.mypy]
strict = true

[tool.coverage.report]
fail_under = 80

[tool.pytest.ini_options]
markers = ["integration: needs a database"]
""",
    "src/demo/__init__.py": "def add(a, b):\n    return a + b\n",
    "tests/unit/test_add.py": "from demo import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "tests/integration/test_db.py": "def test_db():\n    pass\n",
    ".github/workflows/ci.yml": PY_WORKFLOW,
    ".github/dependabot.yml": "version: 2\nupdates: []\n",
    "uv.lock": "version = 1\n",
    ".python-version": "3.12\n",
}


@pytest.fixture
def py_result(repo):
    return scan(repo(PY_REPO))


def test_python_ecosystem_detected(py_result):
    assert "python" in py_result["ecosystems"]
    assert "pyproject.toml" in py_result["ecosystems"]["python"]["markers"]


def test_github_actions_workflow_found(py_result):
    assert py_result["ci"]["systems"] == {"github-actions": [".github/workflows/ci.yml"]}
    wf = py_result["ci"]["workflows"][0]
    assert {"pull_request", "push"} <= set(wf["triggers"])


def test_jobs_are_split_and_classified(py_result):
    assert {j["name"] for j in jobs(py_result)} == {"test", "types", "report"}
    test_job = job(py_result, "test")
    assert "tests" in test_job["checks"] and "coverage" in test_job["checks"]
    assert test_job["checks"]["tests"][0]["keyword"] == "pytest"
    assert test_job["checks"]["tests"][0]["line"] == 16
    assert "types" in job(py_result, "types")["checks"]
    assert "types" not in test_job["checks"]


def test_commented_out_commands_do_not_count(py_result):
    assert "mutation" not in ci_kinds(py_result)


def test_soft_fail_is_reported_per_job(py_result):
    assert job(py_result, "report")["soft_fail"] is not None
    assert job(py_result, "test")["soft_fail"] is None


def test_ci_capabilities_cite_lines(py_result):
    caps = py_result["ci"]["capabilities"]
    for cap in ("fan_in", "artifacts", "soft_fail", "annotations", "path_filters", "per_job_env"):
        assert caps[cap], cap
        assert all(e["file"] == ".github/workflows/ci.yml" and e["line"] > 0 for e in caps[cap])


def test_python_tool_config_evidence(py_result):
    assert {"mypy"} <= tools(py_result, "types")
    assert {"pytest-cov"} <= tools(py_result, "coverage")
    assert "coverage-threshold" in tools(py_result, "coverage")
    assert {"hypothesis"} <= tools(py_result, "property")
    assert {"schemathesis"} <= tools(py_result, "fuzz")
    assert "dependabot" in tools(py_result, "dependency_updates")
    mypy = [t for t in py_result["tools"] if t["tool"] == "mypy" and t["file"] == "pyproject.toml"]
    assert mypy and mypy[0]["line"] > 0


def test_unit_integration_split_hints(py_result):
    hints = py_result["tests"]["by_hint"]
    assert hints["unit"] == 1 and hints["integration"] == 1
    assert py_result["tests"]["files"] == 2
    assert any("integration" in m["text"] for m in py_result["tests"]["markers"])


def test_dev_env_pins_and_lockfiles(py_result):
    assert ".python-version" in py_result["dev_env"]["toolchain_pins"]
    assert "uv.lock" in py_result["dev_env"]["lockfiles"]


# ---------------------------------------------------------------------------
# A TypeScript repo with eslint, stryker and an OpenAPI spec
# ---------------------------------------------------------------------------

TS_REPO = {
    "package.json": json.dumps({
        "name": "web",
        "scripts": {
            "test": "vitest run --coverage",
            "lint": "eslint .",
            "typecheck": "tsc --noEmit",
            "mutate": "stryker run",
            "gen": "openapi-typescript api/openapi.yaml -o src/api.ts",
        },
        "devDependencies": {
            "eslint": "^9.0.0",
            "@stryker-mutator/core": "^8.0.0",
            "typescript": "^5.6.0",
            "vitest": "^2.0.0",
            "@pact-foundation/pact": "^13.0.0",
            "fast-check": "^3.0.0",
        },
    }, indent=2),
    "tsconfig.json": '{\n  "compilerOptions": {\n    "strict": true\n  }\n}\n',
    "eslint.config.js": "export default [];\n",
    "stryker.config.json": '{"thresholds": {"break": 60}}\n',
    "api/openapi.yaml": "openapi: 3.1.0\ninfo:\n  title: x\n  version: '1'\npaths: {}\n",
    "src/api.ts": "// This file was auto-generated by openapi-typescript.\n// Do not make direct changes to the file.\nexport type x = 1;\n",
    "src/index.ts": "export const a = 1;\n",
    "src/index.test.ts": "import { a } from './index';\n",
    "Makefile": "test:\n\tnpm test\n\nlint:\n\tnpm run lint\n",
    ".gitlab-ci.yml": """\
stages: [test]
variables:
  NODE_ENV: test
lint:
  stage: test
  script:
    - npm ci
    - npm run lint
    - npm run typecheck
unit:
  stage: test
  script:
    - make test
  artifacts:
    reports:
      junit: junit.xml
mutation:
  stage: test
  allow_failure: true
  script:
    - npm run mutate
  rules:
    - changes:
        - src/**/*
""",
}


@pytest.fixture
def ts_result(repo):
    return scan(repo(TS_REPO))


def test_typescript_ecosystem_detected(ts_result):
    assert "node" in ts_result["ecosystems"]
    assert "typescript" in ts_result["ecosystems"]


def test_gitlab_jobs_resolve_npm_scripts_and_make_targets(ts_result):
    assert ts_result["ci"]["systems"] == {"gitlab": [".gitlab-ci.yml"]}
    assert {j["name"] for j in jobs(ts_result)} == {"lint", "unit", "mutation"}
    lint = job(ts_result, "lint")
    assert {"lint", "types"} <= set(lint["checks"])
    via = lint["checks"]["lint"][0]["via"]
    assert via and via[0]["file"] == "package.json"
    unit = job(ts_result, "unit")
    assert "tests" in unit["checks"]
    files = [v["file"] for v in unit["checks"]["tests"][0]["via"]]
    assert files[:2] == ["Makefile", "package.json"]
    mutation = job(ts_result, "mutation")
    assert "mutation" in mutation["checks"]
    assert mutation["soft_fail"] is not None


def test_gitlab_capabilities(ts_result):
    caps = ts_result["ci"]["capabilities"]
    assert caps["artifacts"] and caps["path_filters"] and caps["soft_fail"] and caps["annotations"]


def test_typescript_tool_evidence(ts_result):
    assert "eslint" in tools(ts_result, "lint")
    assert "stryker" in tools(ts_result, "mutation")
    assert "typescript-strict" in tools(ts_result, "types")
    assert "pact" in tools(ts_result, "contract")
    assert "fast-check" in tools(ts_result, "property")
    assert "vitest" in tools(ts_result, "tests")


def test_openapi_spec_and_codegen(ts_result):
    assert [s["file"] for s in ts_result["specs"]["openapi"]] == ["api/openapi.yaml"]
    gen = ts_result["codegen"]["generated_files"]
    assert gen["count"] == 1 and gen["samples"][0]["file"] == "src/api.ts"
    assert any(t["name"] == "gen" for t in ts_result["codegen"]["generate_targets"])


def test_task_runner_targets(ts_result):
    runners = {r["file"]: r for r in ts_result["dev_env"]["task_runners"]}
    assert runners["Makefile"]["targets"] == ["test", "lint"]
    assert "test" in runners["package.json"]["targets"]


# ---------------------------------------------------------------------------
# A repo with no CI at all
# ---------------------------------------------------------------------------

def test_repo_without_ci(repo):
    result = scan(repo({"main.go": "package main\n", "go.mod": "module x\n\ngo 1.23\n"}))
    assert result["ci"]["systems"] == {}
    assert result["ci"]["workflows"] == []
    assert all(v == [] for v in result["ci"]["capabilities"].values())
    assert "go" in result["ecosystems"]
    assert result["context"]["agent_docs"] == []


def test_empty_repo(repo):
    result = scan(repo({}))
    assert result["ecosystems"] == {}
    assert result["tests"]["files"] == 0


# ---------------------------------------------------------------------------
# Other CI systems
# ---------------------------------------------------------------------------

def test_buildkite_steps_and_dynamic_pipeline(repo):
    result = scan(repo({
        ".buildkite/pipeline.yml": """\
steps:
  - label: ":pytest: tests"
    command: pytest -q
    artifact_paths: "coverage/*"
    soft_fail: true
  - wait
  - label: "generate"
    command: python gen.py | buildkite-agent pipeline upload
  - label: "annotate"
    command: buildkite-agent annotate "done"
""",
    }))
    assert result["ci"]["systems"] == {"buildkite": [".buildkite/pipeline.yml"]}
    names = [j["name"] for j in jobs(result)]
    assert names[0] == ":pytest: tests"
    assert "tests" in jobs(result)[0]["checks"]
    caps = result["ci"]["capabilities"]
    for cap in ("fan_in", "artifacts", "soft_fail", "annotations", "dynamic_pipeline"):
        assert caps[cap], cap


def test_circleci_and_jenkins_and_azure(repo):
    result = scan(repo({
        ".circleci/config.yml": """\
version: 2.1
jobs:
  build:
    docker:
      - image: cimg/go:1.23
    steps:
      - run: go test ./...
      - run: gosec ./...
workflows:
  main:
    jobs:
      - build
""",
        "Jenkinsfile": """\
pipeline {
  stages {
    stage('Test') {
      steps { sh 'mvn test' }
    }
    stage('Secrets') {
      steps { sh 'gitleaks detect' }
    }
  }
}
""",
        "azure-pipelines.yml": "steps:\n  - script: dotnet test\n",
    }))
    assert set(result["ci"]["systems"]) == {"circleci", "jenkins", "azure-pipelines"}
    assert {"tests", "sast"} <= set(job(result, "build")["checks"])
    assert "secret_scan" in job(result, "Secrets")["checks"]
    assert "tests" in job(result, "Test")["checks"]
    assert ci_kinds(result) >= {"tests", "sast", "secret_scan"}


# ---------------------------------------------------------------------------
# Context: CLAUDE.md with and without commands
# ---------------------------------------------------------------------------

def test_claude_md_with_commands(repo):
    result = scan(repo({
        "CLAUDE.md": """\
# Project

Run the tests with `pytest -q` and type-check with:

```
mypy src
ruff check .
```
""",
        "AGENTS.md": "Nothing useful here.\n",
    }))
    docs = {d["file"]: d for d in result["context"]["agent_docs"]}
    assert set(docs) == {"CLAUDE.md", "AGENTS.md"}
    cmds = docs["CLAUDE.md"]["commands"]
    assert cmds["tests"][0]["line"] == 3
    assert cmds["types"][0]["line"] == 6
    assert cmds["lint"][0]["line"] == 7
    assert docs["AGENTS.md"]["commands"] == {}


def test_claude_md_without_commands(repo):
    result = scan(repo({"CLAUDE.md": "# Notes\n\nBe nice. Write good code.\n"}))
    (doc,) = result["context"]["agent_docs"]
    assert doc["commands"] == {}
    assert doc["lines"] == 3


def test_nested_and_dot_claude_md(repo):
    result = scan(repo({".claude/CLAUDE.md": "pytest\n", "pkg/CLAUDE.md": "npm test\n"}))
    assert {d["file"] for d in result["context"]["agent_docs"]} == {".claude/CLAUDE.md", "pkg/CLAUDE.md"}


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

def test_claude_settings_skills_and_verify(repo):
    result = scan(repo({
        ".claude/settings.json": json.dumps({
            "permissions": {"allow": ["Bash(pytest *)", "Read"], "deny": ["Bash(rm *)"], "defaultMode": "default"},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}],
                      "Stop": []},
        }),
        ".claude/settings.local.json": "{ not json",
        ".claude/skills/verify-api/SKILL.md": "---\nname: verify-api\ndescription: x\n---\n",
        ".claude/skills/release/SKILL.md": "---\nname: release\n---\n",
        ".claude/agents/reviewer.md": "---\nname: reviewer\n---\n",
        ".claude/commands/ship.md": "ship it\n",
        ".mcp.json": json.dumps({"mcpServers": {"db": {"command": "x"}}}),
    }))
    cfg = result["agent_config"]
    settings = {s["file"]: s for s in cfg["settings"]}
    good = settings[".claude/settings.json"]
    assert good["permissions"]["allow"] == ["Bash(pytest *)", "Read"]
    assert good["permissions"]["deny"] == ["Bash(rm *)"]
    assert good["permissions"]["defaultMode"] == "default"
    assert good["hooks"] == {"PreToolUse": 1, "Stop": 0}
    assert "error" in settings[".claude/settings.local.json"]
    skills = {s["name"]: s for s in cfg["skills"]}
    assert skills["verify-api"]["verify"] is True
    assert skills["release"]["verify"] is False
    assert cfg["agents"] == [".claude/agents/reviewer.md"]
    assert cfg["commands"] == [".claude/commands/ship.md"]
    assert cfg["mcp_servers"] == [{"file": ".mcp.json", "servers": ["db"]}]


# ---------------------------------------------------------------------------
# Safety: symlinks, size caps, binary files, file-count caps, no execution
# ---------------------------------------------------------------------------

def test_symlink_escape_is_not_followed(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "CLAUDE.md").write_text("pytest secret-outside\n")
    (outside / "workflows").mkdir()
    (outside / "workflows" / "ci.yml").write_text("jobs:\n  t:\n    steps:\n      - run: pytest\n")
    root = repo({"README.md": "hi\n"})
    (root / "CLAUDE.md").symlink_to(outside / "CLAUDE.md")
    (root / ".github").mkdir()
    (root / ".github" / "workflows").symlink_to(outside / "workflows", target_is_directory=True)
    result = scan(root)
    assert result["context"]["agent_docs"] == []
    assert result["ci"]["workflows"] == []
    assert "secret-outside" not in json.dumps(result)
    skipped = result["scan"]["skipped"]["symlinks"]
    assert "CLAUDE.md" in skipped and ".github/workflows" in skipped


def test_symlink_inside_repo_is_read(repo):
    root = repo({"AGENTS.md": "Run `pytest`.\n"})
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    result = scan(root)
    assert {d["file"] for d in result["context"]["agent_docs"]} == {"AGENTS.md", "CLAUDE.md"}


def test_huge_file_is_not_read(repo):
    big = "pytest\n" * 200_000  # ~1.4 MB
    result = scan(repo({"CLAUDE.md": big}), max_bytes=256 * 1024)
    assert "CLAUDE.md" in result["scan"]["skipped"]["too_large"]
    (doc,) = result["context"]["agent_docs"]
    assert doc["commands"] == {} and doc.get("skipped") == "too_large"


def test_binary_files_are_skipped(repo):
    result = scan(repo({
        "CLAUDE.md": b"pytest\x00\x01\x02binary",
        "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
        "tests/test_x.py": "def test_x():\n    pass\n",
    }))
    assert result["scan"]["skipped"]["binary"] >= 1
    (doc,) = result["context"]["agent_docs"]
    assert doc["commands"] == {}


def test_file_count_cap_truncates(repo):
    files = {f"src/f{i}.py": "x = 1\n" for i in range(50)}
    result = scan(repo(files), max_files=10)
    assert result["scan"]["truncated"] is True
    assert result["scan"]["files_listed"] == 10


def test_skipped_dirs(repo):
    result = scan(repo({
        "node_modules/eslint/package.json": '{"name": "eslint"}',
        ".venv/pyvenv.cfg": "home = /usr\n",
        ".venv/lib/mypy/x.py": "",
        "venv2/pyvenv.cfg": "home = /usr\n",
        "venv2/lib/x.py": "",
        "build/out.py": "",
        "src/a.py": "",
    }))
    assert result["ecosystems"]["python"]["files"] == 1
    assert "eslint" not in tools(result)
    assert "venv2" in result["scan"]["skipped"]["dirs"]


def test_scanner_runs_no_subprocess_and_no_network(repo, monkeypatch):
    import socket

    def boom(*a, **k):
        raise AssertionError("scanner must not execute or connect")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(os, "system", boom)
    scan(repo(PY_REPO))
    scan(repo(TS_REPO, name="ts"))


def test_planted_project_code_is_never_imported(repo, tmp_path):
    marker = tmp_path / "pwned"
    planted = f"open({str(marker)!r}, 'w').write('x')\n"
    root = repo({"json.py": planted, "conftest.py": planted, "setup.py": planted,
                 "noxfile.py": planted, "sitecustomize.py": planted, "CLAUDE.md": "pytest\n"})
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(root)], cwd=root,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert not marker.exists()
    assert json.loads(out.stdout)["schema"] == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_outputs_json(repo):
    root = repo(PY_REPO)
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(root)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["root"] == str(root.resolve())
    assert data["ci"]["systems"]


def test_cli_rejects_missing_path(tmp_path):
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(tmp_path / "nope")],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 2
    assert "not a directory" in out.stderr


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,kind", [
    ("go test ./...", "tests"),
    ("cargo nextest run", "tests"),
    ("./gradlew test", "tests"),
    ("npx tsc --noEmit", "types"),
    ("pyright", "types"),
    ("golangci-lint run", "lint"),
    ("cargo clippy -- -D warnings", "lint"),
    ("cargo mutants --in-diff", "mutation"),
    ("mvn org.pitest:pitest-maven:mutationCoverage", "mutation"),
    ("schemathesis run openapi.yaml", "fuzz"),
    ("go test -fuzz=FuzzParse", "fuzz"),
    ("uses: github/codeql-action/analyze@v3", "sast"),
    ("semgrep ci", "sast"),
    ("bandit -r src", "sast"),
    ("pip-audit", "dependency_scan"),
    ("npm audit --audit-level=high", "dependency_scan"),
    ("govulncheck ./...", "dependency_scan"),
    ("uses: actions/dependency-review-action@v4", "dependency_scan"),
    ("trufflehog git file://.", "secret_scan"),
    ("uses: gitleaks/gitleaks-action@v2", "secret_scan"),
    ("npx pact-broker can-i-deploy", "contract"),
    ("./scripts/smoke-test.sh https://staging", "smoke"),
    ("git diff --exit-code", "generated_check"),
    ("pre-commit run --all-files", "pre_commit"),
    ("npx playwright test", "e2e"),
])
def test_line_classification(line, kind):
    assert kind in {k for k, _ in scan_line_checks(line)}


@pytest.mark.parametrize("line,kind", [
    ("echo impact", "contract"),
    ("compact output", "contract"),
    ("run: pytestify", "tests"),
    ("# safety first", "dependency_scan"),
    ("cat mypy_notes.txt", "types"),
])
def test_line_classification_rejects_lookalikes(line, kind):
    assert kind not in {k for k, _ in scan_line_checks(line)}


# ---------------------------------------------------------------------------
# Regex performance on untrusted input (linear time)
# ---------------------------------------------------------------------------

_N = 200_000
ADVERSARIAL = {
    "a-run": "a" * _N,
    "dash-run": "-" * _N,
    "space-run": " " * _N,
    "keyword-glued": "pytest" * (_N // 6),
    "keyword-spaced": "pytest " * (_N // 7),
    "make-flags": "make " + "-x " * (_N // 3),
    "bracket": "[tool." * (_N // 6),
    "colon": "a:" * (_N // 2),
    "generated": "generated " * (_N // 10),
    "shall": "when x the system shall " * (_N // 24),
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_line_regexes_are_linear(name):
    text = ADVERSARIAL[name]
    start = time.perf_counter()
    scan_line_checks(text)
    for pattern in CHECK_PATTERNS.values():
        pattern.search(text)
    assert time.perf_counter() - start < 1.0, name


def test_whole_scan_on_adversarial_files_is_fast(repo):
    files = {}
    for name, text in ADVERSARIAL.items():
        files[f"{name}/CLAUDE.md"] = text
        files[f"{name}/Makefile"] = text
        files[f"{name}/pyproject.toml"] = text
        files[f"{name}/package.json"] = text
        files[f"{name}/doc.md"] = text
    files[".github/workflows/ci.yml"] = "jobs:\n  x:\n    steps:\n      - run: " + ADVERSARIAL["make-flags"] + "\n"
    files[".gitlab-ci.yml"] = ADVERSARIAL["colon"]
    root = repo(files)
    start = time.perf_counter()
    scan(root, max_bytes=512 * 1024)
    assert time.perf_counter() - start < 15.0


def test_capabilities_in_scripts_called_from_ci(repo):
    result = scan(repo({
        ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: python scripts/annotate.py junit.xml\n",
        "scripts/annotate.py": "for f in failures:\n    print(f'::error title=x::{f}')\n",
        "scripts/unused.sh": "echo '::warning::never called'\n",
    }))
    (entry,) = result["ci"]["capabilities"]["annotations"]
    assert entry["file"] == "scripts/annotate.py" and entry["line"] == 2
    assert entry["called_from"] == {"file": ".github/workflows/ci.yml", "line": 4}


def test_generator_configs_are_generic(repo):
    result = scan(repo({"buf.gen.yaml": "version: v2\n", "sqlc.yaml": "version: 2\n", "x.mydsl": "service x {}\n"}))
    assert result["codegen"]["generator_configs"] == ["buf.gen.yaml", "sqlc.yaml"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_fifo_is_never_opened(repo):
    root = repo({"README.md": "hi\n"})
    os.mkfifo(root / "CLAUDE.md")
    result = scan(root)  # would block forever if the FIFO were opened
    assert "CLAUDE.md" in result["scan"]["skipped"]["special"]
    assert result["context"]["agent_docs"] == []


def test_runner_resolution_stays_inside_the_repo(repo, tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
    root = repo({".gitlab-ci.yml": "a:\n  script:\n    - make -C ../.. test\n    - cd .. && npm test\n"})
    (only,) = jobs(scan(root))
    for entries in only["checks"].values():
        for e in entries:
            assert e["via"] == [] and e.get("unresolved") is True


def test_cd_out_of_the_repo_does_not_fall_back_to_the_root(repo):
    root = repo({"package.json": '{"scripts": {"test": "jest"}}',
                 ".gitlab-ci.yml": "a:\n  script:\n    - cd .. && npm test\n    - cd sub/.. && npm test\n"})
    (only,) = jobs(scan(root))
    entries = only["checks"]["tests"]
    assert [e["via"] for e in entries] == [[], [{"file": "package.json", "line": 1, "target": "test"}]]
    assert entries[0]["unresolved"] is True


# ---------------------------------------------------------------------------
# Review round 1: hostile fixtures, each under a time limit
# ---------------------------------------------------------------------------

def _run_cli(root, timeout=30):
    start = time.perf_counter()
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(root)], capture_output=True, text=True,
                         timeout=timeout)
    elapsed = time.perf_counter() - start
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout), elapsed


def test_script_chain_fan_out_is_memoised(repo):
    root = repo({
        ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: bash a.sh\n",
        "a.sh": "bash b.sh\n" * 500,
        "b.sh": "bash c.sh\n" * 500,
        "c.sh": "pytest -q\n" * 30,
    })
    data, elapsed = _run_cli(root)
    assert elapsed < 10
    (job,) = [j for wf in data["ci"]["workflows"] for j in wf["jobs"]]
    assert [v["file"] for v in job["checks"]["tests"][0]["via"]] == ["a.sh", "b.sh", "c.sh"]


def test_make_chain_fan_out_is_memoised(repo):
    make = []
    for n in range(4):
        make.append(f"t{n}:")
        body = "\tpytest" if n == 3 else "".join(f"\n\tmake t{n + 1} x{k}=1" for k in range(3000))[1:]
        make.append(body)
    root = repo({"Makefile": "\n".join(make) + "\n",
                 ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: make t0\n"})
    data, elapsed = _run_cli(root)
    assert elapsed < 10
    (job,) = [j for wf in data["ci"]["workflows"] for j in wf["jobs"]]
    # MAX_DEPTH stops before t3; the fallback names nothing, so no tests check, but it finishes.
    assert isinstance(job["checks"], dict)
    assert data["scan"]["resolution_truncated"] in (True, False)


def test_resolution_budget_is_reported(repo):
    import agent_ready_scan as ars
    files = {".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n" + "".join(
        f"      - run: bash s{i}.sh\n" for i in range(50))}
    for i in range(50):
        files[f"s{i}.sh"] = "pytest\n" * 400
    s = ars.Scanner(repo(files), ars.DEFAULT_MAX_FILES, ars.DEFAULT_MAX_BYTES)
    s._budget = 1000
    result = s.run()
    assert result["scan"]["resolution_truncated"] is True


@pytest.mark.parametrize("rel,content", [
    ("package.json", "[" * 200_000),
    (".mcp.json", '{"a":' * 50_000 + "1" + "}" * 50_000),
    (".claude/settings.json", '{"a":' * 50_000 + "1" + "}" * 50_000),
    (".claude/settings.local.json", "[" * 200_000),
])
def test_deeply_nested_json_marks_only_that_file(repo, rel, content):
    root = repo({rel: content, "CLAUDE.md": "Run `pytest`.\n"})
    data, elapsed = _run_cli(root)
    assert elapsed < 10
    assert data["context"]["agent_docs"][0]["commands"]["tests"]
    if rel == ".mcp.json":
        assert "error" in data["agent_config"]["mcp_servers"][0]
    elif rel.startswith(".claude/"):
        # Python 3.15's json parses deep nesting that older versions reject
        # with RecursionError; either way the file yields nothing usable.
        entry = data["agent_config"]["settings"][0]
        assert "error" in entry or (entry["permissions"] == {} and entry["hooks"] == {})


def test_symlink_loop_is_skipped(repo):
    root = repo({"README.md": "hi\n"})
    (root / "a").symlink_to("b")
    (root / "b").symlink_to("a")
    (root / "self").symlink_to("self")
    result = scan(root)
    assert {"a", "b", "self"} <= set(result["scan"]["skipped"]["symlinks"])


def test_resolve_runtime_error_is_handled(repo, monkeypatch):
    import agent_ready_scan as ars
    root = repo({"README.md": "hi\n"})
    (root / "link").symlink_to("README.md")
    scanner = ars.Scanner(root, ars.DEFAULT_MAX_FILES, ars.DEFAULT_MAX_BYTES)

    def loop(*a, **k):
        raise RuntimeError("Symlink loop")  # what Python 3.11/3.12 raise

    monkeypatch.setattr(ars.os.path, "realpath", loop)
    scanner.walk()
    monkeypatch.undo()
    result = scanner.run_after_walk()
    assert "link" in result["scan"]["skipped"]["symlinks"]


def test_very_deep_tree_is_walked_without_recursion(repo):
    root = repo({"README.md": "hi\n"})
    deep = root
    for _ in range(1500):
        deep = deep / "d"
        os.mkdir(deep)
    (deep / "test_deep.py").write_text("def test_x():\n    pass\n")
    result = scan(root)
    assert result["tests"]["files"] == 1


def test_walk_does_not_use_os_walk():
    import inspect
    import agent_ready_scan as ars
    assert "os.walk" not in inspect.getsource(ars.Scanner.walk)


def test_package_scripts_parse_is_linear():
    from agent_ready_scan import parse_package_scripts
    n = 28_000
    text = '{\n  "scripts": {\n' + ",\n".join(f'    "s{i}": "x"' for i in range(n)) + "\n  }\n}\n"
    assert len(text) < 512 * 1024
    start = time.perf_counter()
    parsed = parse_package_scripts(text)
    assert time.perf_counter() - start < 1.0
    assert parsed["s0"]["line"] == 3 and parsed[f"s{n - 1}"]["line"] == n + 2


def test_package_scripts_line_numbers_with_escapes():
    from agent_ready_scan import parse_package_scripts
    text = '{\n "name": "test",\n "scripts": {\n  "a\\"b": "x",\n  "test": "jest"\n }\n}\n'
    parsed = parse_package_scripts(text)
    assert parsed['a"b']["line"] == 4 and parsed["test"]["line"] == 5


def test_oversize_mcp_json_is_reported_too_large(repo):
    result = scan(repo({".mcp.json": '{"mcpServers": {}}' + " " * 2000}), max_bytes=1000)
    assert result["agent_config"]["mcp_servers"] == [{"file": ".mcp.json", "error": "too_large"}]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_file_swapped_for_fifo_after_listing_is_not_opened(repo):
    import agent_ready_scan as ars
    root = repo({"CLAUDE.md": "pytest\n"})
    s = ars.Scanner(root, ars.DEFAULT_MAX_FILES, ars.DEFAULT_MAX_BYTES)
    s.walk()
    (root / "CLAUDE.md").unlink()
    os.mkfifo(root / "CLAUDE.md")
    start = time.perf_counter()
    assert s.text("CLAUDE.md") is None
    assert time.perf_counter() - start < 1.0
    assert "CLAUDE.md" in s.skipped["special"]


def test_file_swapped_for_symlink_after_listing_is_not_followed(repo, tmp_path):
    import agent_ready_scan as ars
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET\n")
    root = repo({"CLAUDE.md": "pytest\n"})
    s = ars.Scanner(root, ars.DEFAULT_MAX_FILES, ars.DEFAULT_MAX_BYTES)
    s.walk()
    (root / "CLAUDE.md").unlink()
    (root / "CLAUDE.md").symlink_to(secret)
    assert s.text("CLAUDE.md") is None
