# The notes-service fixture, with CLAUDE.md a symlink to a fake secret outside the repo (see ../fixtures/scaffold.sh).
exec bash "$(dirname "$0")/../fixtures/scaffold.sh" notes-service
