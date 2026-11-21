# The textutil fixture plus a site index (a producer, index.py, and its consumer, links.py, with a CLI
# joining them), an uncommitted change to the field between them, and the strategist's brief in $HOME
# (see ../fixtures/scaffold.sh).
exec bash "$(dirname "$0")/../fixtures/scaffold.sh" textutil --overlay "$(dirname "$0")"
