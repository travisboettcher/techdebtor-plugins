# The textutil fixture with a project selection override (committed), an uncommitted
# change to review, and the reviewer's brief in $HOME (see ../fixtures/scaffold.sh).
exec bash "$(dirname "$0")/../fixtures/scaffold.sh" textutil --overlay "$(dirname "$0")"
