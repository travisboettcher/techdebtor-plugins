# The textutil fixture plus this case's rules ledger and hooks (committed) and three
# run records dated 5 to 20 days ago (untracked) (see ../fixtures/scaffold.sh).
exec bash "$(dirname "$0")/../fixtures/scaffold.sh" textutil --origin --overlay "$(dirname "$0")"
