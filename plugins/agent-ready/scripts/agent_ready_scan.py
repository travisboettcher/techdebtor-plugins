#!/usr/bin/env python3
"""Collect evidence for /agent-ready:audit. Facts only; the skill does the judging.

Standard library only (Python 3.11+). Usage::

    python3 -I agent_ready_scan.py <repo path> [--max-files N] [--max-bytes N]

Prints one JSON document to stdout. Every fact carries the file (path
relative to the repo root) and, where it makes sense, the line it came from.

Safety: the scanner only lists and reads files. It never executes project
code, never imports anything from the scanned repo, never runs a
subprocess and never opens a network connection. It does not follow
symlinked directories, reads a symlinked file only when its target is a
regular file inside the repo, reads only regular files (no FIFOs or
devices), skips dependency, virtualenv, cache and build directories, stops
listing after ``--max-files`` files and never reads more than
``--max-bytes`` of any file. Regexes applied to file contents are linear
time (no nested or overlapping quantifiers) because the input is untrusted.

Top-level keys (see docs/RUBRIC.md for how the skill uses them):

- ``scan``: files listed and read operations (``reads``), whether listing was truncated, whether
  runner resolution hit its budget or a recipe line cap (``resolution_truncated``), the limits,
  and what was skipped (``dirs``, ``symlinks``, ``too_large``, ``binary``,
  ``unreadable``, ``special``).
- ``ecosystems``: per ecosystem, source ``files`` counted and ``markers``
  (manifest files that identify it).
- ``ci``: ``systems`` (system -> pipeline files); ``workflows`` (per file: the
  system, ``triggers`` for GitHub Actions, and ``jobs``, each with ``name``,
  ``line``, ``soft_fail`` and ``checks``: kind -> commands that look like that
  check, each with ``keyword``, ``line`` and ``via``, the chain of Makefile
  targets, package.json scripts, just recipes, Taskfile tasks or scripts it
  was resolved through); ``capabilities`` (fan_in, artifacts, soft_fail,
  annotations, path_filters, per_job_env, diff_base, dynamic_pipeline: each a
  list of file/line/marker); ``merge_gating`` (merge_queue, codeowners,
  protection_config).
- ``tools``: config and dependency evidence per tool: ``tool``, ``kind``,
  ``file``, ``line``, ``how``.
- ``tests``: test file count, ``by_hint`` (unit / integration / e2e / smoke /
  contract / fuzz / unclassified, from paths and names), ``samples`` and
  pytest ``markers`` lines.
- ``specs``: OpenAPI / Swagger and AsyncAPI documents, GraphQL and proto
  file counts.
- ``intent``: EARS-style "shall" lines and acceptance-criteria headings in
  docs, Gherkin feature files.
- ``dev_env``: devcontainers, Dockerfiles, compose files, task runners and
  their targets, toolchain pins, lockfiles, setup scripts.
- ``context``: agent docs (CLAUDE.md, AGENTS.md, ...) with the build, test,
  lint and type-check commands found in their code spans and blocks;
  architecture docs, ADR directories, CONTRIBUTING, README.
- ``agent_config``: ``.claude/settings*.json`` permissions and hook counts,
  ``.claude/skills`` (``verify`` true for verify-*), commands, agents, MCP
  servers.
- ``codegen``: files with generated-file headers, generator configs,
  ``//go:generate`` lines, generate targets, linguist-generated attributes.
- ``smoke``: files that look like smoke or post-deploy checks.
- ``flow``: pull request templates and CI lines that mention flow metrics.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import re
import stat
import sys
from pathlib import Path

SCHEMA = 1
DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_BYTES = 512 * 1024
HEAD_BYTES = 2048
LIST_CAP = 100
SAMPLE_CAP = 20
CHECK_CAP = 5
TEXT_CAP = 200
MAX_DEPTH = 3
RECIPE_LINE_CAP = 500
RESOLUTION_BUDGET = 50_000
MD_READ_CAP = 2000
HEAD_READ_CAP = 20_000

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "bower_components", "jspm_packages", ".venv", "venv", ".tox", ".nox",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis", ".eggs", "site-packages",
    "dist", "build", "target", "out", "vendor", "third_party", ".next", ".nuxt", ".svelte-kit", ".turbo",
    ".parcel-cache", ".angular", ".yarn", ".pnpm-store", "coverage", "htmlcov", ".gradle", ".idea", ".vscode",
    ".terraform", ".direnv", ".cache", "Pods", "DerivedData", "mutants", ".stryker-tmp",
})

# ---------------------------------------------------------------------------
# Command classification (CI lines, doc code spans, task-runner recipes)
# ---------------------------------------------------------------------------

CHECK_KEYWORDS = {
    "tests": [
        "pytest", "py.test", "python -m unittest", "tox", "nox", "jest", "vitest", "mocha", "go test",
        "cargo test", "cargo nextest", "mvn test", "mvn verify", "mvnw test", "mvnw verify", "gradle test",
        "gradlew test", "gradle check", "gradlew check", "dotnet test", "rspec", "rake test", "rails test",
        "phpunit", "mix test", "ctest", "swift test", "deno test", "bun test", "bats",
    ],
    "types": [
        "mypy", "dmypy", "pyright", "basedpyright", "pytype", "pyre", "tsc", "vue-tsc", "typecheck",
        "type-check", "flow check", "srb tc", "steep check", "phpstan", "psalm",
    ],
    "lint": [
        "ruff", "flake8", "pylint", "pyflakes", "eslint", "biome", "oxlint", "golangci-lint", "go vet",
        "staticcheck", "revive", "clippy", "rubocop", "standardrb", "shellcheck", "hadolint", "actionlint",
        "yamllint", "markdownlint", "stylelint", "ktlint", "detekt", "checkstyle", "swiftlint", "super-linter",
        "megalinter", "credo",
    ],
    "format": [
        "black", "isort", "ruff format", "prettier", "gofmt", "goimports", "rustfmt", "cargo fmt",
        "dotnet format", "clang-format", "biome format", "mix format", "terraform fmt", "shfmt",
    ],
    "coverage": [
        "--cov", "coverage", "c8", "nyc", "jacoco", "-coverprofile", "-cover", "tarpaulin", "llvm-cov",
        "codecov", "coveralls", "kover", "simplecov", "diff-cover", "coverlet",
    ],
    "mutation": [
        "mutmut", "cosmic-ray", "stryker", "pitest", "cargo mutants", "cargo-mutants", "go-mutesting",
        "gremlins", "mutatest", "mull-runner",
    ],
    "fuzz": [
        "schemathesis", "jazzer", "atheris", "-fuzz", "cargo fuzz", "cargo-fuzz", "restler", "go-fuzz",
        "oss-fuzz", "cifuzz", "clusterfuzzlite", "honggfuzz", "afl-fuzz", "libfuzzer",
    ],
    "sast": [
        "bandit", "semgrep", "opengrep", "gosec", "codeql", "brakeman", "sonar-scanner", "sonarqube",
        "sonarcloud", "snyk code", "spotbugs", "njsscan", "horusec", "checkov", "tfsec", "kics",
        "trivy config", "flawfinder", "cppcheck", "devskim",
    ],
    "dependency_scan": [
        "pip-audit", "safety check", "safety scan", "npm audit", "yarn audit", "pnpm audit", "osv-scanner",
        "cargo audit", "cargo-audit", "cargo deny", "cargo-deny", "govulncheck", "dependency-check",
        "trivy fs", "trivy image", "trivy repo", "snyk test", "dependency-review-action", "grype",
        "bundle audit", "bundler-audit", "composer audit", "audit-ci", "--vulnerable",
    ],
    "secret_scan": [
        "gitleaks", "trufflehog", "detect-secrets", "ggshield", "secretlint", "talisman", "git-secrets",
        "noseyparker",
    ],
    "contract": ["pact", "pact-broker", "can-i-deploy", "specmatic", "dredd", "pactflow", "spring-cloud-contract"],
    "smoke": ["smoke", "smoke-test", "smoke-tests", "post-deploy", "postdeploy", "synthetics"],
    "e2e": ["playwright", "cypress", "e2e", "selenium", "webdriverio", "wdio", "testcafe", "detox"],
    "build": [
        "go build", "cargo build", "mvn package", "gradle build", "gradlew build", "docker build",
        "docker buildx", "build-push-action", "python -m build", "dotnet build", "bazel build", "vite build", "next build",
        "hatch build", "uv build", "poetry build",
    ],
    "generated_check": ["--exit-code", "git diff --quiet", "git status --porcelain"],
    "pre_commit": ["pre-commit", "prek", "lefthook", "lint-staged"],
    "flow_metrics": ["dora", "four-keys", "fourkeys", "swarmia", "linearb", "sleuth"],
}


def _alternation(words):
    # Longest first so "cargo-mutants" wins over shorter overlaps. A flat
    # alternation of literals between two lookarounds is linear time.
    alts = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + alts + r")(?!\w)")


CHECK_PATTERNS = {kind: _alternation(words) for kind, words in CHECK_KEYWORDS.items()}

# Runner target names that say what an unresolved `make test` / `npm run lint` is for.
NAME_KINDS = {
    "test": "tests", "tests": "tests", "unit": "tests", "integration": "tests", "lint": "lint",
    "typecheck": "types", "types": "types", "mypy": "types", "tsc": "types", "coverage": "coverage",
    "cov": "coverage", "mutate": "mutation", "mutation": "mutation", "mutants": "mutation", "fuzz": "fuzz",
    "e2e": "e2e", "smoke": "smoke", "build": "build", "fmt": "format", "format": "format",
    "audit": "dependency_scan",
}

ECHO = frozenset({"echo", "printf", "print", "log"})
PKG_MANAGERS = frozenset({
    "pip", "pip3", "pipx", "uv", "poetry", "pdm", "npm", "pnpm", "yarn", "bun", "apt", "apt-get", "apk",
    "brew", "gem", "go", "cargo", "composer", "dnf", "yum", "choco", "tool",
})
INSTALL_VERBS = frozenset({"install", "add", "ci", "i", "sync", "get"})
PM_BUILTINS = frozenset({
    "install", "i", "add", "remove", "ci", "exec", "dlx", "x", "create", "init", "publish", "audit",
    "outdated", "update", "upgrade", "why", "link", "pack", "config", "set", "cache", "global", "workspace",
    "workspaces", "dedupe", "rebuild", "prune", "login", "logout", "version", "info", "list", "ls",
})
INTERPRETERS = frozenset({"bash", "sh", "zsh", "source", ".", "python", "python3", "node", "pwsh", "ruby", "perl"})
SCRIPT_SUFFIXES = frozenset({"", ".sh", ".bash", ".zsh", ".py", ".ps1", ".bat", ".cmd", ".js", ".mjs", ".rb", ".pl"})

_SPLIT_COMMANDS = re.compile(r"&&|\|\||[;|]")
_SPLIT_TOKENS = re.compile(r"[\s(){}]+")


def scan_line_checks(text: str):
    """Return [(kind, keyword)] for every check kind whose keyword appears in text."""
    lower = text.lower()
    found = []
    for kind, pattern in CHECK_PATTERNS.items():
        m = pattern.search(lower)
        if m:
            found.append((kind, m.group(0)))
    return found


def _command_tokens(segment: str):
    s = segment.strip()
    if s.startswith("- "):
        s = s[2:].lstrip()
    first, _, rest = s.partition(" ")
    if first.endswith(":") and first[:-1].replace("-", "").replace("_", "").isalnum():
        s = rest.strip()
    s = s.replace("$(MAKE)", "make").replace("${MAKE}", "make")
    toks = [t.strip("'\"`,") for t in _SPLIT_TOKENS.split(s)]
    return s, [t for t in toks if t]


def _is_install(toks) -> bool:
    for a, b in zip(toks, toks[1:]):
        if a in PKG_MANAGERS and b in INSTALL_VERBS:
            return True
    return False


def _name_kind(name: str):
    parts = re.split(r"[:_\-./]", name.lower())
    for part in parts:
        if part in NAME_KINDS:
            return NAME_KINDS[part]
    return None


# ---------------------------------------------------------------------------
# Small parsers (line based; never a full YAML parser)
# ---------------------------------------------------------------------------

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def yaml_key(line: str):
    """(indent, key, rest) for a `key: rest` line, else None. List items are not keys."""
    s = line.lstrip(" ")
    if not s or s.startswith("#") or s.startswith("-"):
        return None
    idx = s.find(":")
    if idx <= 0:
        return None
    rest = s[idx + 1:]
    if rest and not rest[0].isspace():
        return None
    key = s[:idx].strip().strip("'\"")
    rest = rest.strip()
    if rest.startswith("#"):
        rest = ""
    return _indent(line), key, rest


def yaml_blocks(lines, start, end, indent):
    """Keys at exactly `indent` in lines[start:end], each with the range of its block."""
    blocks = []
    for i in range(start, end):
        line = lines[i]
        if _is_blank_or_comment(line):
            continue
        ind = _indent(line)
        if ind < indent:
            break
        if ind == indent:
            k = yaml_key(line)
            if blocks:
                blocks[-1][3] = i
            if k:
                blocks.append([k[1], k[2], i, end])
            elif blocks:
                blocks[-1][3] = i
                blocks.append([None, "", i, end])
    for b in blocks:
        if b[3] > end:
            b[3] = end
    return [b for b in blocks if b[0] is not None]


def _child_indent(lines, start, end, parent_indent):
    for i in range(start, end):
        if not _is_blank_or_comment(lines[i]):
            ind = _indent(lines[i])
            return ind if ind > parent_indent else None
    return None


def parse_makefile(text: str):
    targets = {}
    current = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("\t"):
            body = line.strip().lstrip("@-+").strip()
            for t in current:
                targets[t]["recipe"].append((n, body))
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        head, sep, deps = line.partition(":")
        if not sep or deps.startswith("=") or "=" in head or head[:1].isspace():
            current = []
            continue
        names = [t for t in head.split() if t and not t.startswith(".") and "%" not in t and "$" not in t]
        dep_names = [d for d in deps.split(";")[0].split() if d and "$" not in d and "%" not in d]
        current = []
        for name in names:
            entry = targets.setdefault(name, {"line": n, "recipe": [], "deps": []})
            entry["deps"].extend(dep_names)
            current.append(name)
        recipe_inline = deps.partition(";")[2].strip()
        if recipe_inline:
            for t in current:
                targets[t]["recipe"].append((n, recipe_inline))
    return targets


_JUST_NAME = re.compile(r"@?([A-Za-z_][\w-]*)")


def parse_justfile(text: str):
    recipes = {}
    current = None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if current:
                recipes[current]["recipe"].append((n, line.strip().lstrip("@-").strip()))
            continue
        current = None
        m = _JUST_NAME.match(line)
        if not m:
            continue
        rest = line[m.end():]
        if ":" not in rest or ":=" in rest or m.group(1) in ("set", "export", "alias", "import", "mod"):
            continue
        deps = rest.split(":", 1)[1].split()
        current = m.group(1)
        recipes[current] = {"line": n, "recipe": [], "deps": [d for d in deps if re.fullmatch(r"[\w-]+", d)]}
    return recipes


def parse_taskfile(text: str):
    lines = text.splitlines()
    tasks = {}
    for key, rest, s, e in yaml_blocks(lines, 0, len(lines), 0):
        if key != "tasks":
            continue
        ci = _child_indent(lines, s + 1, e, 0)
        if ci is None:
            continue
        for name, _rest, ts, te in yaml_blocks(lines, s + 1, e, ci):
            tasks[name] = {"line": ts + 1, "recipe": [(i + 1, lines[i]) for i in range(ts + 1, te)
                                                     if not _is_blank_or_comment(lines[i])], "deps": []}
    return tasks


def load_json(text):
    """(data, None) or (None, error). Untrusted input: deep nesting must not crash the scan."""
    try:
        return json.loads(text), None
    except (ValueError, RecursionError, MemoryError):
        return None, "not valid JSON, too deeply nested or too large to parse"


# A JSON string key at the start of a line: alternatives start with different
# characters, so this is linear time.
_JSON_KEY = re.compile(r'\s*("(?:[^"\\\n]|\\.)*")\s*:')


def parse_package_scripts(text: str):
    data, _err = load_json(text)
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return {}
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if '"scripts"' in line), 0)
    key_lines = {}
    for i in range(start + 1, len(lines)):
        m = _JSON_KEY.match(lines[i])
        if m:
            key, err = load_json(m.group(1))
            if err is None and isinstance(key, str):
                key_lines.setdefault(key, i + 1)
    out = {}
    for name, cmd in scripts.items():
        if not isinstance(name, str) or not isinstance(cmd, str):
            continue
        ln = key_lines.get(name, start + 1)
        out[name] = {"line": ln, "recipe": [(ln, cmd)], "deps": []}
    return out


# ---------------------------------------------------------------------------
# Static tables for file detection
# ---------------------------------------------------------------------------

ECOSYSTEMS = {
    "python": ({"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "uv.lock", "poetry.lock"},
               {".py"}),
    "node": ({"package.json"}, {".js", ".mjs", ".cjs", ".jsx"}),
    "typescript": ({"tsconfig.json"}, {".ts", ".tsx", ".mts", ".cts"}),
    "go": ({"go.mod"}, {".go"}),
    "rust": ({"Cargo.toml"}, {".rs"}),
    "java": ({"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle"}, {".java"}),
    "kotlin": (set(), {".kt", ".kts"}),
    "ruby": ({"Gemfile"}, {".rb"}),
    "php": ({"composer.json"}, {".php"}),
    "dotnet": (set(), {".cs", ".fs", ".csproj", ".fsproj", ".sln"}),
    "elixir": ({"mix.exs"}, {".ex", ".exs"}),
    "swift": ({"Package.swift"}, {".swift"}),
    "c-cpp": ({"CMakeLists.txt", "meson.build"}, {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}),
    "shell": (set(), {".sh", ".bash"}),
    "terraform": (set(), {".tf"}),
}

FILE_TOOLS = [
    ("mypy", "types", ["mypy.ini", ".mypy.ini"]),
    ("pyright", "types", ["pyrightconfig.json"]),
    ("typescript", "types", ["tsconfig.json"]),
    ("ruff", "lint", ["ruff.toml", ".ruff.toml"]),
    ("flake8", "lint", [".flake8"]),
    ("pylint", "lint", [".pylintrc", "pylintrc"]),
    ("eslint", "lint", [".eslintrc", ".eslintrc.*", "eslint.config.*"]),
    ("biome", "lint", ["biome.json", "biome.jsonc"]),
    ("golangci-lint", "lint", [".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"]),
    ("clippy", "lint", ["clippy.toml", ".clippy.toml"]),
    ("rubocop", "lint", [".rubocop.yml"]),
    ("prettier", "format", [".prettierrc", ".prettierrc.*", "prettier.config.*"]),
    ("rustfmt", "format", ["rustfmt.toml", ".rustfmt.toml"]),
    ("editorconfig", "format", [".editorconfig"]),
    ("coverage.py", "coverage", [".coveragerc"]),
    ("nyc", "coverage", [".nycrc", ".nycrc.*"]),
    ("c8", "coverage", [".c8rc", ".c8rc.*"]),
    ("codecov", "coverage", ["codecov.yml", ".codecov.yml"]),
    ("tarpaulin", "coverage", ["tarpaulin.toml", ".tarpaulin.toml"]),
    ("stryker", "mutation", ["stryker.conf.*", "stryker.config.*", ".stryker.conf.*"]),
    ("cargo-mutants", "mutation", ["mutants.toml"]),
    ("bandit", "sast", [".bandit"]),
    ("semgrep", "sast", [".semgrep.yml", ".semgrep.yaml"]),
    ("codeql", "sast", ["codeql-config.yml", "codeql-config.yaml"]),
    ("dependabot", "dependency_updates", ["dependabot.yml", "dependabot.yaml"]),
    ("renovate", "dependency_updates", ["renovate.json", "renovate.json5", ".renovaterc", ".renovaterc.json"]),
    ("gitleaks", "secret_scan", [".gitleaks.toml", "gitleaks.toml", ".gitleaksignore"]),
    ("detect-secrets", "secret_scan", [".secrets.baseline"]),
    ("trufflehog", "secret_scan", [".trufflehogignore"]),
    ("pre-commit", "pre_commit", [".pre-commit-config.yaml", ".pre-commit-config.yml"]),
    ("lefthook", "pre_commit", ["lefthook.yml", "lefthook.yaml", ".lefthook.yml"]),
    ("pytest", "tests", ["pytest.ini", "conftest.py"]),
    ("jest", "tests", ["jest.config.*"]),
    ("vitest", "tests", ["vitest.config.*"]),
    ("tox", "tests", ["tox.ini"]),
    ("nox", "tests", ["noxfile.py"]),
    ("playwright", "e2e", ["playwright.config.*"]),
    ("cypress", "e2e", ["cypress.config.*", "cypress.json"]),
]

MANIFEST_NAMES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", "Pipfile", "package.json", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json", "mix.exs",
    ".pre-commit-config.yaml", ".pre-commit-config.yml", "dotnet-tools.json", "environment.yml", "lefthook.yml",
})
MANIFEST_GLOBS = ("requirements*.txt", "requirements*.in", "constraints*.txt", "*.csproj", "tsconfig*.json",
                  "jest.config.*", "vitest.config.*", "stryker.conf*", "stryker.config.*")


def _lit(word):
    # The literal comes first so `re` can scan for it quickly; the left-boundary
    # lookbehind (fixed width: one character plus the word) is checked after it.
    w = re.escape(word)
    return w + r"(?<![\w-]" + w + r")(?![\w-])"


# (tool, kind, regex over lowercased content, file globs it applies to or None for any manifest)
CONTENT_MARKERS = [
    ("mypy", "types", _lit("mypy"), None),
    ("pyright", "types", _lit("pyright"), None),
    ("basedpyright", "types", _lit("basedpyright"), None),
    ("typescript", "types", _lit("typescript"), ("package.json",)),
    ("typescript-strict", "types", r'"strict"\s*:\s*true', ("tsconfig*.json",)),
    ("phpstan", "types", _lit("phpstan"), None),
    ("psalm", "types", _lit("psalm"), None),
    ("sorbet", "types", _lit("sorbet"), None),
    ("ruff", "lint", _lit("ruff"), None),
    ("flake8", "lint", _lit("flake8"), None),
    ("pylint", "lint", _lit("pylint"), None),
    ("eslint", "lint", _lit("eslint"), None),
    ("biome", "lint", re.escape("@biomejs/biome"), None),
    ("rubocop", "lint", _lit("rubocop"), None),
    ("checkstyle", "lint", _lit("checkstyle"), None),
    ("detekt", "lint", _lit("detekt"), None),
    ("ktlint", "lint", _lit("ktlint"), None),
    ("golangci-lint", "lint", _lit("golangci-lint"), None),
    ("black", "format", r"\[tool\.black|[\"']black(?![\w-])", None),
    ("prettier", "format", _lit("prettier"), None),
    ("pytest", "tests", _lit("pytest"), None),
    ("jest", "tests", _lit("jest"), None),
    ("vitest", "tests", _lit("vitest"), None),
    ("mocha", "tests", _lit("mocha"), None),
    ("rspec", "tests", _lit("rspec"), None),
    ("phpunit", "tests", _lit("phpunit"), None),
    ("junit", "tests", _lit("junit"), None),
    ("xunit", "tests", _lit("xunit"), None),
    ("nunit", "tests", _lit("nunit"), None),
    ("pytest-cov", "coverage", _lit("pytest-cov"), None),
    ("coverage.py", "coverage", re.escape("[tool.coverage") + "|" + re.escape("[coverage:"), None),
    ("c8", "coverage", _lit("c8"), ("package.json",)),
    ("nyc", "coverage", _lit("nyc"), ("package.json",)),
    ("vitest-coverage", "coverage", re.escape("@vitest/coverage"), None),
    ("jacoco", "coverage", _lit("jacoco"), None),
    ("kover", "coverage", _lit("kover"), None),
    ("simplecov", "coverage", _lit("simplecov"), None),
    ("coverlet", "coverage", _lit("coverlet"), None),
    ("coverage-threshold", "coverage",
     _lit("fail_under") + "|" + _lit("--cov-fail-under") + "|" + _lit("coveragethreshold") + "|"
     + _lit("check-coverage") + "|" + _lit("--fail-under"), None),
    ("mutmut", "mutation", _lit("mutmut"), None),
    ("cosmic-ray", "mutation", _lit("cosmic-ray"), None),
    ("stryker", "mutation", re.escape("@stryker-mutator") + "|" + _lit("dotnet-stryker"), None),
    ("pitest", "mutation", _lit("pitest"), None),
    ("mutant", "mutation", _lit("mutant-rspec"), None),
    ("infection", "mutation", re.escape("infection/infection"), None),
    ("mutation-threshold", "mutation", r'"break"\s*:|' + _lit("mutationthreshold"), None),
    ("hypothesis", "property", _lit("hypothesis"), None),
    ("fast-check", "property", _lit("fast-check"), None),
    ("proptest", "property", _lit("proptest"), None),
    ("quickcheck", "property", _lit("quickcheck"), None),
    ("jqwik", "property", _lit("jqwik"), None),
    ("schemathesis", "fuzz", _lit("schemathesis"), None),
    ("atheris", "fuzz", _lit("atheris"), None),
    ("jazzer", "fuzz", _lit("jazzer"), None),
    ("cargo-fuzz", "fuzz", _lit("libfuzzer-sys"), None),
    ("bandit", "sast", _lit("bandit"), None),
    ("semgrep", "sast", _lit("semgrep"), None),
    ("spotbugs", "sast", _lit("spotbugs"), None),
    ("brakeman", "sast", _lit("brakeman"), None),
    ("eslint-plugin-security", "sast", _lit("eslint-plugin-security"), None),
    ("pip-audit", "dependency_scan", _lit("pip-audit"), None),
    ("audit-ci", "dependency_scan", _lit("audit-ci"), None),
    ("bundler-audit", "dependency_scan", _lit("bundler-audit"), None),
    ("dependency-check", "dependency_scan", _lit("dependency-check"), None),
    ("cargo-deny", "dependency_scan", _lit("cargo-deny"), None),
    ("gitleaks", "secret_scan", _lit("gitleaks"), None),
    ("detect-secrets", "secret_scan", _lit("detect-secrets"), None),
    ("trufflehog", "secret_scan", _lit("trufflehog"), None),
    ("secretlint", "secret_scan", _lit("secretlint"), None),
    ("pre-commit", "pre_commit", _lit("pre-commit"), None),
    ("husky", "pre_commit", _lit("husky"), None),
    ("lint-staged", "pre_commit", _lit("lint-staged"), None),
    ("pact", "contract", r"pact(?<![\w-]pact)(?!\w)|" + _lit("pact-python"), None),
    ("dredd", "contract", _lit("dredd"), None),
    ("playwright", "e2e", _lit("playwright") + "|" + re.escape("@playwright/test"), None),
    ("cypress", "e2e", _lit("cypress"), None),
]
_CONTENT_MARKERS = [(t, k, re.compile(rx), globs) for t, k, rx, globs in CONTENT_MARKERS]

DEVCONTAINER_GLOBS = (".devcontainer/devcontainer.json", ".devcontainer.json", ".devcontainer/*/devcontainer.json")
COMPOSE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml", "compose.*.yml",
                 "compose.*.yaml")
TOOLCHAIN_PINS = frozenset({
    ".tool-versions", ".python-version", ".nvmrc", ".node-version", ".ruby-version", ".go-version",
    ".java-version", ".sdkmanrc", "rust-toolchain", "rust-toolchain.toml", "mise.toml", ".mise.toml",
    ".prototools", "flake.nix", "shell.nix", "devbox.json", ".terraform-version", "global.json", ".bazelversion",
})
LOCKFILES = frozenset({
    "uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "package-lock.json", "npm-shrinkwrap.json",
    "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "composer.lock", "mix.lock", "packages.lock.json", "gradle.lockfile", "flake.lock", "Package.resolved",
})
MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
JUSTFILES = ("justfile", "Justfile", ".justfile")
TASKFILES = ("Taskfile.yml", "Taskfile.yaml", "taskfile.yml", "taskfile.yaml")

AGENT_DOCS = frozenset({"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".cursorrules", ".windsurfrules",
                        "copilot-instructions.md"})
GENERATOR_CONFIGS = ("buf.gen.yaml", "buf.gen.yml", "openapitools.json", ".openapi-generator-ignore", "sqlc.yaml",
                     "sqlc.yml", "sqlc.json", "gqlgen.yml", "codegen.yml", "codegen.yaml", "codegen.ts",
                     "orval.config.*", ".graphqlrc*", "schema.prisma")
GENERATED_MARKERS = re.compile(
    r"code generated|@generated|do not edit|auto-generated|autogenerated|automatically generated|generated by")
NOT_FOR_GENERATED = (".md", ".rst", ".txt", ".lock", ".sum", ".svg")
SOURCE_HEAD_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".php",
    ".cs", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".ex", ".exs", ".yml", ".yaml", ".json", ".toml",
    ".graphql", ".proto", ".sql", ".sh", ".dart", ".scala",
})
SPEC_HEAD = re.compile(r'^\s*"?(openapi|swagger|asyncapi)"?\s*:', re.MULTILINE)
DOC_SUFFIXES = (".md", ".markdown", ".rst", ".txt", ".adoc")

TEST_HINT_ORDER = ("fuzz", "contract", "smoke", "e2e", "integration", "unit")
TEST_HINT_PARTS = {
    "fuzz": {"fuzz", "fuzzing"},
    "contract": {"contract", "contracts", "pact", "pacts"},
    "smoke": {"smoke"},
    "e2e": {"e2e", "end-to-end", "end_to_end", "acceptance", "system", "functional"},
    "integration": {"integration", "integration_tests", "integration-tests", "it", "integ"},
    "unit": {"unit", "unit_tests", "unittests", "unit-tests"},
}
TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})

CI_SEGMENTATION = {
    "github-actions": "jobs", "circleci": "jobs", "gitlab": "toplevel", "buildkite": "steps",
    "azure-pipelines": "azure", "jenkins": "jenkins",
}
GITLAB_RESERVED = frozenset({"stages", "variables", "include", "default", "workflow", "image", "services", "cache",
                             "before_script", "after_script", "types"})

# Capability markers, matched case-insensitively as substrings of non-comment CI lines.
CAPABILITY_MARKERS = {
    "fan_in": ["needs:", "depends_on:", "dependson:", "requires:", "- wait", "wait:", "stages:", "parallel"],
    "artifacts": ["actions/upload-artifact", "actions/download-artifact", "artifacts:", "dependencies:",
                  "artifact_paths", "buildkite-agent artifact", "persist_to_workspace", "attach_workspace",
                  "store_artifacts", "publishpipelineartifact", "downloadpipelineartifact", "archiveartifacts",
                  "stash", "unstash"],
    "soft_fail": ["continue-on-error:", "allow_failure:", "soft_fail:", "continueonerror:", "catcherror",
                  "unstable("],
    "annotations": ["::error", "::warning", "::notice", "github_step_summary", "add-matcher", "reports:",
                    "buildkite-agent annotate", "store_test_results", "##vso[", "publishtestresults", "junit ",
                    "recordissues", "publishhtml"],
    "path_filters": ["paths:", "paths-ignore:", "dorny/paths-filter", "changed-files", "changes:", "if_changed:",
                     "monorepo-diff", "path-filtering", "changeset"],
    "per_job_env": ["env:", "variables:", "environment:", "environment {", "withenv"],
    "diff_base": ["github.base_ref", "pull_request.base.sha", "merge-base", "ci_merge_request_diff_base_sha",
                  "ci_merge_request_target_branch", "buildkite_pull_request_base_branch",
                  "system.pullrequest.targetbranch", "change_target"],
    "dynamic_pipeline": ["pipeline upload", "trigger:", "setup: true", "continuation", "fromjson("],
}
# Capabilities also looked for in scripts that a CI job calls.
SCRIPT_CAPABILITIES = ("annotations", "dynamic_pipeline", "diff_base")
# Markers that only mean the capability when not at the top level of the file.
INDENTED_ONLY = frozenset({"env:", "variables:", "environment:"})


def _soft_fail_disabled(lower_line: str, marker: str) -> bool:
    if not marker.endswith(":"):
        return False
    value = lower_line.split(marker, 1)[1].strip()
    return value.startswith("false") or value.startswith("0")


# ---------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------

class Scanner:
    def __init__(self, root: Path, max_files: int, max_bytes: int):
        self.root = root.resolve()
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.files: dict[str, Path] = {}
        self.by_name: dict[str, list[str]] = {}
        self.truncated = False
        self.skipped = {"dirs": [], "symlinks": [], "too_large": [], "binary": 0, "unreadable": [], "special": []}
        self.reads = 0
        self._called_scripts: dict[str, dict] = {}
        self._cache: dict[str, str | None] = {}
        self._parsed: dict[tuple[str, str], dict] = {}
        self._memo: dict[tuple, tuple | None] = {}
        self._active: set[tuple] = set()
        self._budget = RESOLUTION_BUDGET
        self.resolution_truncated = False

    # -- listing --------------------------------------------------------

    def _skip(self, key, rel):
        if len(self.skipped[key]) < LIST_CAP:
            self.skipped[key].append(rel)

    def walk(self):
        """List files depth first with an explicit stack rather than the standard library's
        walker (recursive on 3.11), so deep trees behave the same on 3.11 to 3.13."""
        root = self.root
        stack = [""]
        while stack:
            rel_dir = stack.pop()
            dpath = root / rel_dir if rel_dir else root
            try:
                with os.scandir(dpath) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                self._skip("unreadable", rel_dir or ".")
                continue
            subdirs = []
            for entry in entries:
                name = entry.name
                rel = f"{rel_dir}/{name}" if rel_dir else name
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    self._skip("unreadable", rel)
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if name in SKIP_DIRS or name.endswith(".egg-info") or os.path.lexists(
                            os.path.join(entry.path, "pyvenv.cfg")):
                        self._skip("dirs", rel)
                    else:
                        subdirs.append(rel)
                    continue
                if len(self.files) >= self.max_files:
                    self.truncated = True
                    return
                full = Path(entry.path)
                if stat.S_ISLNK(st.st_mode):
                    try:
                        target = Path(os.path.realpath(full))
                        ok = target.is_relative_to(root) and stat.S_ISREG(os.stat(target).st_mode)
                    except (OSError, RuntimeError, ValueError):
                        ok = False  # loops raise RuntimeError on 3.11/3.12, OSError on 3.13
                    if not ok:
                        self._skip("symlinks", rel)
                        continue
                    full = target
                elif not stat.S_ISREG(st.st_mode):
                    self._skip("special", rel)
                    continue
                self.files[rel] = full
                self.by_name.setdefault(name, []).append(rel)
            stack.extend(reversed(subdirs))

    # -- reading --------------------------------------------------------

    def text(self, rel: str, cache: bool = True):
        """Full text of a listed file, or None if missing, too large, binary or unreadable."""
        if rel in self._cache:
            return self._cache[rel]
        result = self._read(rel, None)
        if cache:
            self._cache[rel] = result
        return result

    def head(self, rel: str):
        if rel in self._cache:
            text = self._cache[rel]
            return None if text is None else text[:HEAD_BYTES]
        return self._read(rel, HEAD_BYTES)

    def _read(self, rel, limit):
        path = self.files.get(rel)
        if path is None:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path, flags)
        except OSError:
            self._skip("unreadable", rel)
            return None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                if rel not in self.skipped["special"]:
                    self._skip("special", rel)
                return None
            if limit is None and st.st_size > self.max_bytes:
                if rel not in self.skipped["too_large"]:
                    self._skip("too_large", rel)
                return None
            want = limit if limit is not None else self.max_bytes
            chunks, got = [], 0
            while got < want:
                chunk = os.read(fd, want - got)
                if not chunk:
                    break
                chunks.append(chunk)
                got += len(chunk)
            data = b"".join(chunks)
        except OSError:
            self._skip("unreadable", rel)
            return None
        finally:
            os.close(fd)
        self.reads += 1
        if b"\0" in data[:8192]:
            self.skipped["binary"] += 1
            return None
        return data.decode("utf-8", errors="replace")

    def skip_reason(self, rel):
        if rel in self.skipped["too_large"]:
            return "too_large"
        return "binary_or_unreadable"

    # -- helpers --------------------------------------------------------

    def match(self, *globs, basename=True):
        out = []
        for rel in self.files:
            name = rel.rsplit("/", 1)[-1] if basename else rel
            if any(fnmatch.fnmatchcase(name, g) for g in globs):
                out.append(rel)
        return out

    def _parsed_runner(self, kind, rel):
        key = (kind, rel)
        if key not in self._parsed:
            text = self.text(rel)
            if text is None:
                self._parsed[key] = {}
            elif kind == "make":
                self._parsed[key] = parse_makefile(text)
            elif kind == "just":
                self._parsed[key] = parse_justfile(text)
            elif kind == "task":
                self._parsed[key] = parse_taskfile(text)
            else:
                self._parsed[key] = parse_package_scripts(text)
        return self._parsed[key]

    @staticmethod
    def _join(base, path):
        """Repo-relative path, "" for the root, or None if it leaves the repo (or base already did)."""
        if base is None or path is None:
            return None
        joined = posixpath.normpath(posixpath.join(base, path)) if base else posixpath.normpath(path)
        if joined.startswith("..") or joined.startswith("/"):
            return None
        return "" if joined == "." else joined

    def _find(self, base, names):
        for name in names:
            rel = self._join(base, name)
            if rel is not None and rel in self.files:
                return rel
        return None

    # -- command classification ------------------------------------------

    def _invocation(self, toks, base):
        """Find the first task-runner or script invocation in a command.

        Returns (label, runner_kind, file or None, [targets]) or None."""
        for i, tok in enumerate(toks):
            rest = toks[i + 1:]
            if tok in ("make", "gmake"):
                mk_base, mk_file, targets = base, None, []
                j = 0
                while j < len(rest):
                    a = rest[j]
                    if a in ("-C", "--directory", "-f", "--file", "--makefile") and j + 1 < len(rest):
                        if a in ("-C", "--directory"):
                            mk_base = self._join(mk_base, rest[j + 1])
                        else:
                            mk_file = rest[j + 1]
                        j += 2
                        continue
                    if not a.startswith("-") and "=" not in a:
                        targets.append(a)
                    j += 1
                rel = self._find(mk_base, [mk_file] if mk_file else MAKEFILES)
                return (f"make {' '.join(targets)}".strip(), "make", rel, targets[:3])
            if tok in ("npm", "pnpm", "yarn", "bun"):
                pm_base, j, verb = base, 0, None
                while j < len(rest):
                    a = rest[j]
                    if a in ("--prefix", "-C", "--dir", "--cwd") and j + 1 < len(rest):
                        pm_base = self._join(pm_base, rest[j + 1])
                        j += 2
                        continue
                    if a in ("--filter", "-F", "--workspace", "-w") and j + 1 < len(rest):
                        j += 2
                        continue
                    if a.startswith("-"):
                        j += 1
                        continue
                    verb = a
                    break
                if verb is None:
                    return None
                script = None
                if verb in ("run", "run-script"):
                    script = next((a for a in rest[j + 1:] if not a.startswith("-")), None)
                elif verb in ("test", "t", "tst", "start") and tok != "bun":
                    script = "test" if verb in ("t", "tst") else verb
                elif tok in ("yarn", "pnpm") and verb not in PM_BUILTINS:
                    script = verb
                if script is None:
                    return None
                rel = self._find(pm_base, ["package.json"])
                return (f"{tok} run {script}", "npm", rel, [script])
            if tok == "just":
                target = next((a for a in rest if not a.startswith("-") and "=" not in a), None)
                rel = self._find(base, JUSTFILES)
                return (f"just {target or ''}".strip(), "just", rel, [target] if target else [])
            if tok in ("task", "go-task"):
                target = next((a for a in rest if not a.startswith("-")), None)
                rel = self._find(base, TASKFILES)
                return (f"task {target or ''}".strip(), "task", rel, [target] if target else [])
            path = None
            if tok in INTERPRETERS:
                path = next((a for a in rest if not a.startswith("-")), None)
                if tok in ("python", "python3") and rest[:1] == ["-m"]:
                    path = None
            elif "/" in tok or tok.endswith((".sh", ".py")):
                path = tok
            if path:
                rel = self._join(base, path[2:] if path.startswith("./") else path)
                if rel and rel in self.files and posixpath.splitext(rel)[1] in SCRIPT_SUFFIXES:
                    return (path, "script", rel, [])
            if i == 0 and tok in INTERPRETERS:
                return None
        return None

    def _runner_lines(self, kind, rel, targets):
        """[(target, line, recipe lines)] for a resolved invocation."""
        if kind == "script":
            text = self.text(rel)
            if text is None:
                return []
            lines = [(n, line) for n, line in enumerate(text.splitlines()[:RECIPE_LINE_CAP], 1)
                     if line.strip() and not line.lstrip().startswith("#")]
            return [(posixpath.basename(rel), 1, lines)]
        parsed = self._parsed_runner(kind, rel)
        if not parsed:
            return []
        if not targets:
            targets = [next(iter(parsed))]
        out = []
        seen = set()
        queue = list(targets)
        while queue and len(out) < 6:
            name = queue.pop(0)
            if name in seen or name not in parsed:
                continue
            seen.add(name)
            entry = parsed[name]
            out.append((name, entry["line"], entry["recipe"]))
            queue.extend(entry.get("deps", []))
        return out

    def _resolve(self, kind, rel, targets, remaining):
        """Checks reached through one runner invocation, as ([(kind, keyword, via)], [scripts]).

        Memoised per (runner, file, targets, remaining depth) across the whole scan, so
        a file that calls the same target thousands of times is expanded once; deduplicated
        to one entry per (kind, keyword) and capped, so results stay small; and bounded by a
        global line budget (``scan.resolution_truncated`` says when it ran out). None when
        nothing resolved, or on a cycle."""
        key = (kind, rel, targets, remaining)
        if key in self._memo:
            return self._memo[key]
        if key in self._active:
            return None
        self._active.add(key)
        result = None
        try:
            runner = self._runner_lines(kind, rel, list(targets))
            if runner:
                results, seen, per_kind = [], set(), {}
                scripts = [rel] if kind == "script" else []
                new_base = posixpath.dirname(rel)
                for name, _ln, lines in runner:
                    for n, line in lines[:RECIPE_LINE_CAP]:
                        if self._budget <= 0:
                            self.resolution_truncated = True
                            break
                        self._budget -= 1
                        sub_touched = []
                        link = {"file": rel, "line": n, "target": name}
                        for k, kw, via in self.classify(line, new_base, MAX_DEPTH - remaining, (link,),
                                                        touched=sub_touched):
                            if (k, kw) in seen or per_kind.get(k, 0) >= CHECK_CAP:
                                continue
                            seen.add((k, kw))
                            per_kind[k] = per_kind.get(k, 0) + 1
                            results.append((k, kw, via))
                        for script in sub_touched:
                            if script not in scripts and len(scripts) < LIST_CAP:
                                scripts.append(script)
                    if len(lines) > RECIPE_LINE_CAP:
                        self.resolution_truncated = True
                result = (results, scripts)
        finally:
            self._active.discard(key)
        self._memo[key] = result
        return result

    def classify(self, text, base="", depth=0, chain=(), touched=None):
        """[(kind, keyword, via)] for one line of commands.

        Scripts resolved along the way are appended to `touched` when given."""
        out = []
        for segment in _SPLIT_COMMANDS.split(text):
            content, toks = _command_tokens(segment)
            if not toks:
                continue
            if toks[0] == "cd" and len(toks) > 1:
                base = self._join(base, toks[1])
                continue
            if toks[0].lower() in ECHO or _is_install(toks):
                continue
            for kind, kw in scan_line_checks(content):
                out.append((kind, kw, chain))
            inv = self._invocation(toks, base)
            if inv is None:
                continue
            label, kind, rel, targets = inv
            resolved = None
            if rel is not None and depth < MAX_DEPTH:
                resolved = self._resolve(kind, rel, tuple(targets), MAX_DEPTH - depth - 1)
            if resolved is not None:
                results, scripts = resolved
                if touched is not None:
                    touched.extend(scripts)
                out.extend((k, kw, chain + via) for k, kw, via in results)
            else:
                for target in targets:
                    nk = _name_kind(target)
                    if nk:
                        out.append((nk, label, chain + ({"unresolved": True},)))
        return out

    # -- sections ---------------------------------------------------------

    def ecosystems(self):
        result = {}
        counts = {name: 0 for name in ECOSYSTEMS}
        for rel in self.files:
            ext = posixpath.splitext(rel)[1]
            for name, (_m, exts) in ECOSYSTEMS.items():
                if ext in exts:
                    counts[name] += 1
        for name, (markers, _e) in ECOSYSTEMS.items():
            found = sorted(r for m in markers for r in self.by_name.get(m, []))
            if name == "dotnet":
                found = sorted(self.match("*.csproj", "*.fsproj", "*.sln"))
            if found or counts[name]:
                result[name] = {"files": counts[name], "markers": found[:10]}
        return result

    def ci(self):
        files = {}

        def add(system, rels):
            rels = sorted(r for r in rels if r.endswith((".yml", ".yaml")) or system == "jenkins")
            if rels:
                files.setdefault(system, []).extend(rels)

        add("github-actions", [r for r in self.files if r.startswith(".github/workflows/") and r.count("/") == 2])
        add("gitlab", [r for r in self.files if r == ".gitlab-ci.yml" or r.startswith(".gitlab/ci/")])
        add("buildkite", [r for r in self.files if r.startswith(".buildkite/")])
        add("circleci", [r for r in self.files if r == ".circleci/config.yml"])
        add("jenkins", [r for r in self.files if posixpath.basename(r) == "Jenkinsfile"
                        or posixpath.basename(r).startswith("Jenkinsfile.") or r.endswith(".jenkinsfile")])
        add("azure-pipelines", [r for r in self.files if posixpath.basename(r) in ("azure-pipelines.yml",
                                                                                   "azure-pipelines.yaml")
                                or r.startswith((".azure-pipelines/", "azure-pipelines/"))])
        add("travis", [r for r in self.files if r == ".travis.yml"])
        add("bitbucket", [r for r in self.files if r == "bitbucket-pipelines.yml"])
        add("drone", [r for r in self.files if r in (".drone.yml", ".woodpecker.yml")
                      or r.startswith(".woodpecker/")])

        caps = {k: [] for k in CAPABILITY_MARKERS}
        merge = {"merge_queue": [], "codeowners": [], "protection_config": []}
        flow_hints = []
        workflows = []
        for system, rels in files.items():
            for rel in rels:
                text = self.text(rel)
                if text is None:
                    workflows.append({"file": rel, "system": system, "skipped": self.skip_reason(rel),
                                      "triggers": [], "jobs": []})
                    continue
                lines = text.splitlines()
                comment = "//" if system == "jenkins" else "#"
                self._capabilities(rel, system, lines, comment, caps)
                wf = {"file": rel, "system": system, "triggers": [], "jobs": []}
                if system == "github-actions":
                    wf["triggers"] = _gha_triggers(lines)
                    for i, line in enumerate(lines):
                        if line.strip().startswith("merge_group"):
                            merge["merge_queue"].append({"file": rel, "line": i + 1})
                for seg in _segments(system, lines):
                    wf["jobs"].append(self._job(rel, system, lines, seg, comment))
                for job in wf["jobs"]:
                    for c in job["checks"].get("flow_metrics", []):
                        flow_hints.append({"file": rel, "line": c["line"], "keyword": c["keyword"]})
                workflows.append(wf)
        for script, caller in sorted(self._called_scripts.items()):
            text = self.text(script)
            if text is not None:
                system = next(w["system"] for w in workflows if w["file"] == caller["file"])
                self._capabilities(script, system, text.splitlines()[:2000], "#", caps,
                                   only=SCRIPT_CAPABILITIES, called_from=caller)
        for rel in self.files:
            name = posixpath.basename(rel)
            if name == "CODEOWNERS":
                merge["codeowners"].append(rel)
            if rel in (".github/settings.yml", ".github/settings.yaml") or rel.startswith(".github/rulesets/"):
                merge["protection_config"].append(rel)
        for k in caps:
            caps[k] = caps[k][:LIST_CAP]
        return {"systems": {k: v for k, v in sorted(files.items())}, "workflows": workflows,
                "capabilities": caps, "merge_gating": merge}, flow_hints

    def _capabilities(self, rel, system, lines, comment, caps, only=None, called_from=None):
        for i, line in enumerate(lines):
            s = line.strip()
            if not s or s.startswith(comment):
                continue
            low = s.lower()
            for cap, markers in CAPABILITY_MARKERS.items():
                if only and cap not in only:
                    continue
                for marker in markers:
                    if marker in INDENTED_ONLY and _indent(line) == 0:
                        continue
                    if marker == "- wait" and low not in ("- wait", '- "wait"') and not low.startswith("- wait:"):
                        continue
                    if marker in low:
                        if cap == "soft_fail" and _soft_fail_disabled(low, marker):
                            continue
                        if len(caps[cap]) < LIST_CAP:
                            entry = {"file": rel, "line": i + 1, "marker": marker, "system": system}
                            if called_from:
                                entry["called_from"] = called_from
                            caps[cap].append(entry)
                        break

    def _job(self, rel, system, lines, seg, comment):
        name, start, end, extra = seg
        base = ""
        soft = None
        checks: dict[str, list] = {}
        seen = set()
        for i in range(start, end):
            s = lines[i].strip()
            if s.startswith("working-directory:") or s.startswith("- working-directory:"):
                base = self._join("", s.split(":", 1)[1].strip().strip("'\""))
        for i in range(start, end):
            line = lines[i]
            s = line.strip()
            if not s or s.startswith(comment):
                continue
            low = s.lower()
            if soft is None:
                for marker in CAPABILITY_MARKERS["soft_fail"]:
                    if marker in low and not _soft_fail_disabled(low, marker):
                        soft = {"line": i + 1, "marker": marker}
                        break
            touched = []
            for kind, kw, via in self.classify(s, base, touched=touched):
                key = (kind, kw, tuple((v.get("file"), v.get("line")) for v in via))
                if key in seen:
                    continue
                seen.add(key)
                bucket = checks.setdefault(kind, [])
                if len(bucket) < CHECK_CAP:
                    entry = {"keyword": kw, "line": i + 1, "via": [v for v in via if "file" in v]}
                    if any(v.get("unresolved") for v in via):
                        entry["unresolved"] = True
                    bucket.append(entry)
            for script in touched:
                self._called_scripts.setdefault(script, {"file": rel, "line": i + 1})
        job = {"name": name, "line": start + 1, "soft_fail": soft, "checks": checks}
        job.update(extra)
        return job

    def tools(self):
        out = []
        seen = set()

        def add(tool, kind, rel, line, how):
            key = (tool, kind, rel)
            if key not in seen:
                seen.add(key)
                out.append({"tool": tool, "kind": kind, "file": rel, "line": line, "how": how})

        for tool, kind, globs in FILE_TOOLS:
            for rel in sorted(self.match(*globs)):
                if tool in ("dependabot",) and not rel.startswith(".github/"):
                    continue
                add(tool, kind, rel, None, "config file")
        for rel in sorted(self.files):
            if rel.startswith(".husky/"):
                add("husky", "pre_commit", rel, None, "config file")
            if rel.startswith(".semgrep/"):
                add("semgrep", "sast", rel, None, "config file")
            if posixpath.basename(rel).endswith(".pact.json") or "/pacts/" in f"/{rel}":
                add("pact", "contract", rel, None, "pact file")
        manifests = [r for r in self.files
                     if posixpath.basename(r) in MANIFEST_NAMES
                     or any(fnmatch.fnmatchcase(posixpath.basename(r), g) for g in MANIFEST_GLOBS)]
        for rel in sorted(manifests):
            text = self.text(rel)
            if text is None:
                continue
            low = text.lower()
            name = posixpath.basename(rel)
            for tool, kind, rx, globs in _CONTENT_MARKERS:
                if globs and not any(fnmatch.fnmatchcase(name, g) for g in globs):
                    continue
                m = rx.search(low)
                if m:
                    add(tool, kind, rel, low.count("\n", 0, m.start()) + 1, f"mentions {m.group(0)!r}")
        # Go native fuzz targets.
        reads = 0
        for rel in sorted(self.files):
            if rel.endswith("_test.go") and reads < HEAD_READ_CAP:
                reads += 1
                text = self.text(rel, cache=False)
                if text and "func Fuzz" in text:
                    idx = text.find("func Fuzz")
                    add("go-fuzz", "fuzz", rel, text.count("\n", 0, idx) + 1, "func Fuzz")
        return out

    def tests(self):
        files = 0
        by_hint = {h: 0 for h in TEST_HINT_ORDER}
        by_hint["unclassified"] = 0
        samples: dict[str, list] = {}
        for rel in self.files:
            if not _is_test_file(rel):
                continue
            files += 1
            hint = _test_hint(rel)
            by_hint[hint] += 1
            bucket = samples.setdefault(hint, [])
            if len(bucket) < 5:
                bucket.append(rel)
        markers = []
        for rel in sorted(self.files):
            name = posixpath.basename(rel)
            if name not in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"):
                continue
            text = self.text(rel)
            if not text:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                low = line.lower()
                if "markers" in low or any(w in low for w in ("integration", "e2e", "smoke", "slow")):
                    if len(markers) < SAMPLE_CAP:
                        markers.append({"file": rel, "line": n, "text": line.strip()[:TEXT_CAP]})
        return {"files": files, "by_hint": by_hint, "samples": samples, "markers": markers}

    def specs_and_intent(self):
        specs = {"openapi": [], "asyncapi": [], "graphql": 0, "proto": 0}
        intent = {"ears_like": [], "acceptance_criteria": [], "gherkin": 0, "gherkin_samples": []}
        head_reads = md_reads = 0
        for rel in sorted(self.files):
            ext = posixpath.splitext(rel)[1].lower()
            if ext in (".graphql", ".gql"):
                specs["graphql"] += 1
            elif ext == ".proto":
                specs["proto"] += 1
            elif ext == ".feature":
                intent["gherkin"] += 1
                if len(intent["gherkin_samples"]) < 5:
                    intent["gherkin_samples"].append(rel)
            elif ext in (".yaml", ".yml", ".json") and head_reads < HEAD_READ_CAP:
                if rel.startswith((".github/", ".gitlab", ".circleci/", ".buildkite/")):
                    continue
                head_reads += 1
                head = self.head(rel)
                if not head:
                    continue
                m = SPEC_HEAD.search(head)
                if m:
                    kind = "asyncapi" if m.group(1) == "asyncapi" else "openapi"
                    if len(specs[kind]) < LIST_CAP:
                        specs[kind].append({"file": rel, "format": m.group(1)})
            elif ext in DOC_SUFFIXES and md_reads < MD_READ_CAP:
                md_reads += 1
                text = self.text(rel, cache=False)
                if not text:
                    continue
                count, first, ac_line = 0, None, None
                for n, line in enumerate(text.splitlines(), 1):
                    low = line.lower()
                    if " shall " in low:
                        count += 1
                        first = first or n
                    if ac_line is None and "acceptance criteria" in low:
                        ac_line = n
                if count and len(intent["ears_like"]) < LIST_CAP:
                    intent["ears_like"].append({"file": rel, "count": count, "first_line": first})
                if ac_line and len(intent["acceptance_criteria"]) < LIST_CAP:
                    intent["acceptance_criteria"].append({"file": rel, "line": ac_line})
        return specs, intent

    def dev_env(self):
        runners = []
        for rel in sorted(self.files):
            name = posixpath.basename(rel)
            kind = None
            if name in MAKEFILES:
                kind = "make"
            elif name in JUSTFILES:
                kind = "just"
            elif name in TASKFILES:
                kind = "task"
            elif name == "package.json":
                kind = "npm"
            if kind:
                parsed = self._parsed_runner(kind, rel)
                if kind == "npm" and not parsed:
                    continue
                runners.append({"file": rel, "kind": kind, "targets": list(parsed)[:50]})
            elif name == "tox.ini":
                text = self.text(rel) or ""
                envs = [line.strip()[9:-1] for line in text.splitlines() if line.strip().startswith("[testenv:")
                        and line.strip().endswith("]")]
                runners.append({"file": rel, "kind": "tox", "targets": envs[:50]})
            elif name == "noxfile.py":
                runners.append({"file": rel, "kind": "nox", "targets": []})
        return {
            "devcontainer": sorted(self.match(*DEVCONTAINER_GLOBS, basename=False)),
            "dockerfiles": sorted(r for r in self.files if _is_dockerfile(posixpath.basename(r)))[:LIST_CAP],
            "compose": sorted(self.match(*COMPOSE_GLOBS))[:LIST_CAP],
            "task_runners": runners[:LIST_CAP],
            "toolchain_pins": sorted(r for r in self.files if posixpath.basename(r) in TOOLCHAIN_PINS)[:LIST_CAP],
            "lockfiles": sorted(r for r in self.files if posixpath.basename(r) in LOCKFILES)[:LIST_CAP],
            "setup_scripts": sorted(r for r in self.files if _is_setup_script(r))[:LIST_CAP],
        }

    def context(self):
        docs = []
        for rel in sorted(self.files):
            name = posixpath.basename(rel)
            if name not in AGENT_DOCS:
                continue
            if name == "copilot-instructions.md" and rel != ".github/copilot-instructions.md":
                continue
            entry = {"file": rel}
            text = self.text(rel)
            if text is None:
                entry.update({"skipped": self.skip_reason(rel), "lines": None, "bytes": None, "commands": {}})
            else:
                entry.update({"lines": len(text.splitlines()), "bytes": len(text.encode()),
                              "commands": self._doc_commands(rel, text)})
            docs.append(entry)
        arch, adr, contributing, readme = [], set(), [], []
        for rel in sorted(self.files):
            name = posixpath.basename(rel)
            low = rel.lower()
            parts = low.split("/")
            if name.upper().startswith(("ARCHITECTURE", "DESIGN")) and name.lower().endswith(DOC_SUFFIXES):
                arch.append(rel)
            if any(p in ("adr", "adrs", "decisions", "decision-records") for p in parts[:-1]):
                adr.add(posixpath.dirname(rel))
            if name.upper().startswith("CONTRIBUTING"):
                contributing.append(rel)
            if name.upper().startswith("README") and rel.count("/") == 0:
                readme.append(rel)
        return {"agent_docs": docs[:LIST_CAP], "architecture_docs": arch[:LIST_CAP], "adr_dirs": sorted(adr)[:LIST_CAP],
                "contributing": contributing, "readme": readme}

    def _doc_commands(self, rel, text):
        commands: dict[str, list] = {}
        in_fence = False
        for n, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            pieces = [stripped] if in_fence else line.split("`")[1::2]
            for piece in pieces:
                if not piece.strip():
                    continue
                for kind, _kw, _via in self.classify(piece, posixpath.dirname(rel)):
                    bucket = commands.setdefault(kind, [])
                    if len(bucket) < CHECK_CAP and not any(b["line"] == n for b in bucket):
                        bucket.append({"line": n, "text": piece.strip()[:TEXT_CAP]})
        return commands

    def agent_config(self):
        settings, skills, commands, agents, mcp = [], [], [], [], []
        for rel in sorted(self.files):
            parts = rel.split("/")
            name = parts[-1]
            if len(parts) >= 2 and parts[-2] == ".claude" and name in ("settings.json", "settings.local.json"):
                settings.append(self._settings(rel))
            elif ".claude" in parts:
                i = parts.index(".claude")
                sub = parts[i + 1:]
                if len(sub) == 3 and sub[0] == "skills" and sub[2] == "SKILL.md":
                    skills.append({"name": sub[1], "file": rel, "verify": sub[1].lower().startswith("verify")})
                elif len(sub) >= 2 and sub[0] == "commands" and name.endswith(".md"):
                    commands.append(rel)
                elif len(sub) >= 2 and sub[0] == "agents" and name.endswith(".md"):
                    agents.append(rel)
            if name == ".mcp.json":
                text = self.text(rel)
                if text is None:
                    mcp.append({"file": rel, "error": self.skip_reason(rel)})
                    continue
                data, err = load_json(text)
                servers = data.get("mcpServers") if isinstance(data, dict) else None
                if err or not isinstance(servers, dict):
                    mcp.append({"file": rel, "error": err or "unexpected shape"})
                else:
                    mcp.append({"file": rel, "servers": sorted(str(k)[:TEXT_CAP] for k in servers)[:LIST_CAP]})
        return {"settings": settings, "skills": skills[:LIST_CAP], "commands": commands[:LIST_CAP],
                "agents": agents[:LIST_CAP], "mcp_servers": mcp}

    def _settings(self, rel):
        entry = {"file": rel}
        text = self.text(rel)
        if text is None:
            entry["error"] = self.skip_reason(rel)
            return entry
        data, err = load_json(text)
        if err or not isinstance(data, dict):
            entry["error"] = err or "not a JSON object"
            return entry
        perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
        p = {}
        for key in ("allow", "deny", "ask"):
            vals = perms.get(key)
            if isinstance(vals, list):
                p[key] = [str(v)[:TEXT_CAP] for v in vals][:LIST_CAP]
        if "defaultMode" in perms:
            p["defaultMode"] = str(perms["defaultMode"])[:TEXT_CAP]
        if isinstance(perms.get("additionalDirectories"), list):
            p["additionalDirectories"] = len(perms["additionalDirectories"])
        entry["permissions"] = p
        hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
        entry["hooks"] = {str(k)[:TEXT_CAP]: (len(v) if isinstance(v, list) else 0) for k, v in hooks.items()}
        return entry

    def codegen(self):
        samples, count = [], 0
        reads = 0
        go_generate = []
        attributes = []
        for rel in sorted(self.files):
            name = posixpath.basename(rel)
            ext = posixpath.splitext(rel)[1].lower()
            if name == ".gitattributes":
                for n, line in enumerate((self.text(rel) or "").splitlines(), 1):
                    if "linguist-generated" in line and len(attributes) < LIST_CAP:
                        attributes.append({"file": rel, "line": n, "text": line.strip()[:TEXT_CAP]})
                continue
            if name in LOCKFILES or ext in NOT_FOR_GENERATED:
                continue
            if ext not in SOURCE_HEAD_SUFFIXES and name not in ("docker-compose.yml",):
                continue
            if reads >= HEAD_READ_CAP:
                continue
            reads += 1
            head = self.head(rel)
            if not head:
                continue
            lines = head.splitlines()[:15]
            for n, line in enumerate(lines, 1):
                m = GENERATED_MARKERS.search(line.lower())
                if m:
                    count += 1
                    if len(samples) < SAMPLE_CAP:
                        samples.append({"file": rel, "line": n, "marker": m.group(0)})
                    break
            if ext == ".go":
                for n, line in enumerate(head.splitlines(), 1):
                    if line.startswith("//go:generate") and len(go_generate) < LIST_CAP:
                        go_generate.append({"file": rel, "line": n, "text": line[:TEXT_CAP]})
        targets = []
        for runner in self.dev_env()["task_runners"]:
            for t in runner["targets"]:
                low = t.lower()
                if "generate" in low or "codegen" in low or low == "gen" or low.startswith(("gen:", "gen-", "gen_")):
                    targets.append({"file": runner["file"], "name": t})
        return {
            "generated_files": {"count": count, "samples": samples},
            "generator_configs": sorted(self.match(*GENERATOR_CONFIGS))[:LIST_CAP],
            "go_generate": go_generate,
            "generate_targets": targets[:LIST_CAP],
            "gitattributes_generated": attributes,
        }

    def run(self):
        self.walk()
        return self.run_after_walk()

    def run_after_walk(self):
        ci, flow_hints = self.ci()
        specs, intent = self.specs_and_intent()
        result = {
            "schema": SCHEMA,
            "root": str(self.root),
            "ecosystems": self.ecosystems(),
            "ci": ci,
            "tools": self.tools(),
            "tests": self.tests(),
            "specs": specs,
            "intent": intent,
            "dev_env": self.dev_env(),
            "context": self.context(),
            "agent_config": self.agent_config(),
            "codegen": self.codegen(),
            "smoke": {"files": sorted(r for r in self.files if "smoke" in posixpath.basename(r).lower())[:LIST_CAP]},
            "flow": {"pr_templates": sorted(r for r in self.files if "pull_request_template" in r.lower())[:LIST_CAP],
                     "ci_hints": flow_hints[:LIST_CAP]},
        }
        result["scan"] = {
            "files_listed": len(self.files),
            "reads": self.reads,
            "truncated": self.truncated,
            "resolution_truncated": self.resolution_truncated,
            "limits": {"max_files": self.max_files, "max_bytes": self.max_bytes},
            "skipped": self.skipped,
        }
        return result


def _gha_triggers(lines):
    for i, line in enumerate(lines):
        k = yaml_key(line)
        if not k or k[0] != 0 or k[1] not in ("on", "true"):
            continue
        rest = k[2]
        if rest:
            return [t for t in (w.strip(" []'\"") for w in rest.split(",")) if t]
        end = next((j for j in range(i + 1, len(lines))
                    if not _is_blank_or_comment(lines[j]) and _indent(lines[j]) == 0), len(lines))
        ci = _child_indent(lines, i + 1, end, 0)
        if ci is None:
            return []
        out = [b[0] for b in yaml_blocks(lines, i + 1, end, ci)]
        out += [lines[j].strip()[2:].strip() for j in range(i + 1, end)
                if _indent(lines[j]) == ci and lines[j].strip().startswith("- ")]
        return out
    return []


def _strip_name(value):
    return value.strip().strip("'\"")[:TEXT_CAP]


def _segments(system, lines):
    """[(name, start, end, extra)] job segments of a pipeline file."""
    n = len(lines)
    mode = CI_SEGMENTATION.get(system)
    whole = [("(pipeline)", 0, n, {})]
    if mode == "jobs":
        for key, rest, s, e in yaml_blocks(lines, 0, n, 0):
            if key == "jobs" and not rest:
                ci = _child_indent(lines, s + 1, e, 0)
                if ci is None:
                    return []
                return [(k, js, je, {}) for k, _r, js, je in yaml_blocks(lines, s + 1, e, ci)]
        return whole
    if mode == "toplevel":
        segs = []
        for key, _rest, s, e in yaml_blocks(lines, 0, n, 0):
            if key in GITLAB_RESERVED:
                continue
            segs.append((key, s, e, {"template": True} if key.startswith(".") else {}))
        return segs
    if mode == "steps":
        for i, line in enumerate(lines):
            k = yaml_key(line)
            if not k or k[1] != "steps":
                continue
            end = next((j for j in range(i + 1, n)
                        if not _is_blank_or_comment(lines[j]) and _indent(lines[j]) <= k[0]
                        and not lines[j].strip().startswith("-")), n)
            items = [j for j in range(i + 1, end) if lines[j].strip().startswith("-")]
            if not items:
                return whole
            item_indent = _indent(lines[items[0]])
            starts = [j for j in items if _indent(lines[j]) == item_indent]
            segs = []
            for idx, s in enumerate(starts):
                e = starts[idx + 1] if idx + 1 < len(starts) else end
                segs.append((_step_name(lines, s, e), s, e, {}))
            return segs
        return whole
    if mode == "azure":
        starts = [i for i, line in enumerate(lines)
                  if line.strip().startswith(("- job:", "- deployment:"))]
        if not starts:
            return whole
        return [(_strip_name(lines[s].split(":", 1)[1]) or "(job)", s,
                 starts[idx + 1] if idx + 1 < len(starts) else n, {}) for idx, s in enumerate(starts)]
    if mode == "jenkins":
        starts = []
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("stage(") or s.startswith("stage ("):
                inner = s.split("(", 1)[1]
                starts.append((i, _strip_name(inner.split(")", 1)[0])))
        if not starts:
            return whole
        return [(name, s, starts[idx + 1][0] if idx + 1 < len(starts) else n, {})
                for idx, (s, name) in enumerate(starts)]
    return whole


def _step_name(lines, s, e):
    first = lines[s].strip()[1:].strip()
    for j in range(s, e):
        body = lines[j].strip()
        if body.startswith("- "):
            body = body[2:]
        k = yaml_key(" " + body)
        if k and k[1] in ("label", "name", "key") and k[2]:
            return _strip_name(k[2])
    if first and ":" not in first:
        return _strip_name(first)
    k = yaml_key(" " + first)
    if k and k[2]:
        return _strip_name(f"{k[1]} {k[2]}")
    return _strip_name(first) or "(step)"


def _is_test_file(rel):
    name = posixpath.basename(rel)
    parts = rel.split("/")
    ext = posixpath.splitext(name)[1]
    if ext == ".py":
        return name.startswith("test_") or name.endswith("_test.py")
    if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"):
        stem = name[: -len(ext)]
        return stem.endswith((".test", ".spec", ".e2e")) or "__tests__" in parts[:-1]
    if ext == ".go":
        return name.endswith("_test.go")
    if ext == ".rs":
        return "tests" in parts[:-1]
    if ext in (".java", ".kt"):
        stem = name[: -len(ext)]
        return stem.endswith(("Test", "Tests", "IT", "Spec"))
    if ext == ".rb":
        return name.endswith(("_spec.rb", "_test.rb"))
    if ext == ".php":
        return name.endswith("Test.php")
    if ext == ".cs":
        return name.endswith(("Test.cs", "Tests.cs"))
    if ext == ".exs":
        return name.endswith("_test.exs")
    return False


def _test_hint(rel):
    low = rel.lower()
    parts = low.split("/")
    name = parts[-1]
    stem_bits = set(re.split(r"[._\-]", name))
    for hint in TEST_HINT_ORDER:
        words = TEST_HINT_PARTS[hint]
        if any(p in words for p in parts[:-1]) or stem_bits & (words - {"it", "system"}):
            return hint
    if rel.endswith(("IT.java", "IT.kt")):
        return "integration"
    if rel.endswith(".rs"):
        return "integration"
    return "unclassified"


def _is_dockerfile(name):
    return (name in ("Dockerfile", "Containerfile") or name.startswith("Dockerfile.")
            or name.endswith((".Dockerfile", ".dockerfile")))


def _is_setup_script(rel):
    name = posixpath.basename(rel).lower()
    stem, ext = posixpath.splitext(name)
    if ext not in ("", ".sh", ".bash", ".ps1", ".bat"):
        return False
    return stem.startswith(("setup", "bootstrap", "dev-setup", "install-dev")) or rel in ("bin/setup", "script/setup")


def scan(root, max_files: int = DEFAULT_MAX_FILES, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """Scan a repository and return the facts as a dict."""
    return Scanner(Path(root), max_files, max_bytes).run()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect agent-readiness evidence from a repository (read-only).")
    ap.add_argument("path", help="repository root to scan")
    ap.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = ap.parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        print(f"agent_ready_scan: {args.path}: not a directory", file=sys.stderr)
        return 2
    json.dump(scan(root, args.max_files, args.max_bytes), sys.stdout, indent=1, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
