# The textutil fixture with an origin remote, plus this case's brief in $HOME (see ../fixtures/scaffold.sh).
exec bash "$(dirname "$0")/../fixtures/scaffold.sh" textutil --origin --overlay "$(dirname "$0")"
