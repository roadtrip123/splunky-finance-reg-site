#!/bin/sh
# Take the portal off the box and, with --restore-splunky, hand the box back to Splunky Finance.
#
#   sudo ./scripts/uninstall.sh
#   sudo ./scripts/uninstall.sh --restore-splunky --host lab.example.com
#
# The roster is left in data/ unless --wipe is given, because an export after the event is usually
# wanted and a database is easier to keep than to recreate.
set -eu

say()  { printf '\n=== %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
die()  { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESTORE=0; WIPE=0; HOST=""

while [ $# -gt 0 ]; do
  case "$1" in
    --restore-splunky) RESTORE=1; shift ;;
    --wipe) WIPE=1; shift ;;
    --host) HOST="$2"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done
[ "$(id -u)" = "0" ] || die "Run this with sudo."

say "Portal"
systemctl disable --now lab-portal.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/lab-portal.service
systemctl daemon-reload
note "lab-portal.service removed"

if [ "$WIPE" = "1" ]; then
  rm -f "$ROOT"/data/lab.db "$ROOT"/data/lab.db-wal "$ROOT"/data/lab.db-shm
  note "roster deleted"
else
  note "roster left in $ROOT/data (pass --wipe to delete it)"
fi

if [ "$RESTORE" = "1" ]; then
  say "Splunky Finance"
  for UNIT in splunky-finance.service splunky-finance-egress.timer; do
    systemctl enable "$UNIT" >/dev/null 2>&1 && note "enabled $UNIT" || note "no $UNIT here"
  done
  systemctl start splunky-finance.service >/dev/null 2>&1 || true
  for DIR in /home/*/splunky-finance /opt/splunky-finance; do
    [ -f "$DIR/compose.yaml" ] || continue
    note "starting containers in $DIR"
    (cd "$DIR" && docker compose up -d >/dev/null 2>&1) || true
    if [ -n "$HOST" ] && [ -x "$DIR/scripts/install.sh" ]; then
      note "re-running its installer to take back the proxy"
      (cd "$DIR" && ./scripts/install.sh --host "$HOST") || \
        note "that reported a problem; its Caddyfile may need a look"
    else
      note "pass --host <name> to have its installer rewrite /etc/caddy/Caddyfile"
    fi
  done
else
  note "Caddy still points at the portal. Pass --restore-splunky to hand the box back."
fi

printf '\nDone.\n\n'
