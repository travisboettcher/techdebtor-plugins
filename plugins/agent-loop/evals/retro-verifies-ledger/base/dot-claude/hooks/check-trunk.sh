#!/usr/bin/env bash
# PreToolUse hook (Bash): refuse new branches started from a local main.
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
case $cmd in
  *"switch -c"*" main"|*"checkout -b"*" main") echo "branch from origin/main, not a local main" >&2; exit 2 ;;
esac
