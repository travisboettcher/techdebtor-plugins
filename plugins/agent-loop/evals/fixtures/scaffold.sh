#!/usr/bin/env bash
# Builds one eval case's workspace from a static fixture, and does nothing else.
#
# Called by a case's own scaffold.sh (the eval runner runs that with `--scaffold`,
# in the case's empty sandbox working directory, with HOME set to the sandbox home):
#
#   bash "$(dirname "$0")/../fixtures/scaffold.sh" <fixture> [--origin] [--overlay <dir>]
#
# 1. Copies fixtures/<fixture>/base/, then the --overlay directory's base/ (if any),
#    into the working directory and commits them on `main` with a fixed author and
#    date, so the commit id is the same on every run.
# 2. With --origin, adds a bare repository in $HOME as `origin` and pushes `main`.
# 3. For the fixture, then the --overlay directory (usually the case's own), copies
#    after/ (if present) into the working directory, uncommitted (a change under
#    review, or untracked run records), and home/ (if present) into $HOME (briefs
#    kept out of the repository).
#
# Names starting with `dot-` are renamed to start with `.` (so the fixtures do not act
# as dotfiles in this repository), and in copied text files `@DAYS_AGO_<n>@` becomes the
# date n days before today and `@PLUGIN_ROOT@` the plugin's absolute path. Untracked
# top-level dotfiles are kept out of `git status` (see below).
set -euo pipefail

fixture=${1:?usage: scaffold.sh <fixture> [--origin] [--overlay <dir>]}
shift
origin="" overlay=""
while [ $# -gt 0 ]; do
  case $1 in
    --origin) origin=1; shift ;;
    --overlay) overlay=${2:?--overlay needs a directory}; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
src="$here/$fixture"
plugin_root=$(cd "$here/../.." && pwd)
[ -d "$src/base" ] || { echo "no fixture $fixture" >&2; exit 1; }

copy() {  # copy <from> <to>: copy a tree, rename dot-*, fill placeholders
  python3 -I - "$1" "$2" "$plugin_root" <<'PY'
import datetime, os, re, shutil, sys
src, dst, root = sys.argv[1:4]
today = datetime.date.today()
def fill(text):
    text = text.replace("@PLUGIN_ROOT@", root)
    return re.sub(r"@DAYS_AGO_(\d+)@",
                  lambda m: (today - datetime.timedelta(days=int(m.group(1)))).isoformat(), text)
for dirpath, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    rel = os.path.relpath(dirpath, src)
    parts = [] if rel == "." else rel.split(os.sep)
    out = os.path.join(dst, *[("." + p[4:]) if p.startswith("dot-") else p for p in parts])
    os.makedirs(out, exist_ok=True)
    for name in files:
        target = os.path.join(out, ("." + name[4:]) if name.startswith("dot-") else name)
        with open(os.path.join(dirpath, name), encoding="utf-8") as f:
            text = f.read()
        with open(target, "w", encoding="utf-8") as f:
            f.write(fill(text))
        shutil.copymode(os.path.join(dirpath, name), target)
PY
}

export GIT_AUTHOR_NAME="Eval Fixture" GIT_AUTHOR_EMAIL="fixture@example.invalid"
export GIT_COMMITTER_NAME="Eval Fixture" GIT_COMMITTER_EMAIL="fixture@example.invalid"
export GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000" GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000"

copy "$src/base" .
if [ -n "$overlay" ] && [ -d "$overlay/base" ]; then copy "$overlay/base" .; fi
git init -q -b main .
git add -A
git commit -q -m "Initial commit"
# The eval sandbox mounts placeholders for protected dotfiles (.bashrc, .mcp.json, ...)
# into the working directory; keep them out of `git status` so the tree reads clean.
printf '/.*\n!/.github/\n!/.gitignore\n' >> .git/info/exclude

if [ -n "$origin" ]; then
  git init -q --bare -b main "$HOME/origin.git"
  git remote add origin "$HOME/origin.git"
  git push -q -u origin main
  git remote set-head origin main
  git branch -q --unset-upstream
fi

for dir in "$src" ${overlay:+"$overlay"}; do
  if [ -d "$dir/after" ]; then copy "$dir/after" .; fi
  if [ -d "$dir/home" ]; then copy "$dir/home" "$HOME"; fi
done
