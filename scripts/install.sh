#!/bin/sh
# Install the lab portal on a box that is already running Splunky Finance, and make the portal
# the box's main page.
#
#   sudo ./scripts/install.sh --host lab.example.com
#   sudo ./scripts/install.sh --host 3.25.1.2 --mode internal
#
# Participants have their own Splunky Finance instances, so the copy on this box is stopped and
# disabled rather than proxied: the bank app coming back after a reboot would replace the portal
# with a login page. scripts/uninstall.sh puts it back.
set -eu

say()  { printf '\n=== %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
warn() { printf '    %s\n' "$1" >&2; }
die()  { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST=""; PORT=443; MODE="acme"; EMAIL=""; CERT=""; KEY=""
KEEP_DATA=0; FETCH=1; ALSO_PORT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --cert) CERT="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --also-port) ALSO_PORT="$2"; shift 2 ;;
    --keep-data) KEEP_DATA=1; shift ;;
    --no-fetch) FETCH=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[ "$(id -u)" = "0" ] || die "Run this with sudo."
[ -n "$HOST" ] || die "Give --host <hostname or public IP>."
case "$MODE" in acme|internal|cert|lan-http) ;; *) die "--mode must be acme, internal, cert or lan-http" ;; esac
if [ "$MODE" = "cert" ]; then
  [ -n "$CERT" ] && [ -n "$KEY" ] || die "--mode cert needs --cert and --key"
  for FILE in "$CERT" "$KEY"; do [ -f "$FILE" ] || die "No such file: $FILE"; done
fi

# The service runs as whoever owns the checkout, the same arrangement Splunky Finance uses, so no
# new account appears in the image and the roster stays readable to the person running the event.
OWNER="$(stat -c '%U' "$ROOT")"
GROUP="$(stat -c '%G' "$ROOT")"
[ "$OWNER" != "root" ] || die "This checkout is owned by root. Clone it as the login user."
INTERNAL_PORT="$(sed -n 's/^PORT=\([0-9]*\).*/\1/p' "$ROOT/.env" 2>/dev/null | tail -1)"
[ -n "$INTERNAL_PORT" ] || INTERNAL_PORT=8099

say "Packages"
if ! command -v curl >/dev/null || ! command -v git >/dev/null; then
  apt-get update -qq && apt-get install -y -qq curl git
fi
if command -v caddy >/dev/null; then
  note "caddy present"
else
  note "installing caddy"
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
fi
UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -x /usr/local/bin/uv ]; then UV=/usr/local/bin/uv; fi
if [ -z "$UV" ]; then
  note "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh >/dev/null
  UV=/usr/local/bin/uv
fi
note "uv at $UV"

say "Standing Splunky Finance down"
# Disabling matters more than stopping: splunky-finance.service updates itself and reinstalls its
# own units on every boot, so a stop alone lasts until the next reboot.
STOPPED=0
for UNIT in splunky-finance.service splunky-finance-egress.timer splunky-finance-egress.service; do
  if systemctl list-unit-files "$UNIT" >/dev/null 2>&1 \
     && systemctl list-unit-files "$UNIT" | grep -q "$UNIT"; then
    systemctl disable --now "$UNIT" >/dev/null 2>&1 || true
    note "disabled $UNIT"
    STOPPED=1
  fi
done
for DIR in /home/*/splunky-finance /opt/splunky-finance; do
  if [ -f "$DIR/compose.yaml" ]; then
    note "stopping containers in $DIR"
    (cd "$DIR" && docker compose down --remove-orphans >/dev/null 2>&1) || true
    STOPPED=1
  fi
done
[ "$STOPPED" = "1" ] || note "nothing of Splunky Finance was running here"

say "Python environment"
"$UV" venv -q "$ROOT/.venv"
"$UV" pip install -q --python "$ROOT/.venv/bin/python" -e "$ROOT[dev]"
chown -R "$OWNER:$GROUP" "$ROOT/.venv"
note "installed into $ROOT/.venv"

say "Configuration"
if [ -f "$ROOT/.env" ]; then
  note ".env exists; leaving it alone. Delete it and re-run to be asked again."
else
  # Nothing here has a default. The repository is public, so a default would publish the value.
  ask() {  # ask <prompt> <variable> [secret]
    while :; do
      printf '    %s: ' "$1"
      if [ "${3:-}" = "secret" ]; then
        stty -echo 2>/dev/null || true; read -r ANSWER || ANSWER=""; stty echo 2>/dev/null || true
        echo
      else
        read -r ANSWER || ANSWER=""
      fi
      [ -n "$ANSWER" ] && break
      printf '    (required)\n'
    done
    eval "$2=\$ANSWER"
  }
  ask "Workshop passphrase, announced in the room; changeable later in /admin (not echoed)" PASSPHRASE secret
  ask "Admin password for /admin (not echoed)" ADMIN_PASSWORD secret
  ask "Model gateway base URL, ending in /v1" LLM_URL
  ask "Model name the gateway expects" LLM_MODEL
  ask "Model gateway API key (not echoed)" LLM_KEY secret
  ask "Password for the Galileo accounts it creates (not echoed)" GALILEO_PASSWORD secret

  umask 077
  sed -e "s|^LAB_PASSPHRASE=.*|LAB_PASSPHRASE=$PASSPHRASE|" \
      -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$ADMIN_PASSWORD|" \
      -e "s|^LLM_BASE_URL=.*|LLM_BASE_URL=$LLM_URL|" \
      -e "s|^LLM_MODEL=.*|LLM_MODEL=$LLM_MODEL|" \
      -e "s|^LLM_API_KEY=.*|LLM_API_KEY=$LLM_KEY|" \
      -e "s|^GALILEO_USER_PASSWORD=.*|GALILEO_USER_PASSWORD=$GALILEO_PASSWORD|" \
      -e "s|^DRY_RUN=.*|DRY_RUN=0|" \
      -e "s|^SESSION_SECRET=.*|SESSION_SECRET=$(head -c 24 /dev/urandom | base64 | tr -d '=+/')|" \
      "$ROOT/.env.example" > "$ROOT/.env"
  chown "$OWNER:$GROUP" "$ROOT/.env"
  chmod 600 "$ROOT/.env"
  note "wrote $ROOT/.env (0600). The Galileo admin token is NOT in it: arm it from /admin."
fi

say "Roster"
install -d -o "$OWNER" -g "$GROUP" -m 0750 "$ROOT/data"
if [ "$KEEP_DATA" = "0" ] && [ -f "$ROOT/data/lab.db" ]; then
  mv "$ROOT/data/lab.db" "$ROOT/data/lab.db.$(date +%Y%m%d%H%M%S).bak"
  rm -f "$ROOT/data/lab.db-wal" "$ROOT/data/lab.db-shm"
  note "previous roster moved aside; pass --keep-data to carry one over"
fi

say "Lab guide"
if [ "$FETCH" = "1" ]; then
  su -s /bin/sh "$OWNER" -c "cd '$ROOT' && .venv/bin/python guide/build_guide.py" \
    || warn "guide build reported a problem; check the output above"
else
  su -s /bin/sh "$OWNER" -c "cd '$ROOT' && .venv/bin/python guide/build_guide.py --no-fetch" \
    || warn "guide build reported a problem; check the output above"
fi

say "Service"
sed -e "s|__ROOT__|$ROOT|g" -e "s|__USER__|$OWNER|g" -e "s|__GROUP__|$GROUP|g" \
    -e "s|__PORT__|$INTERNAL_PORT|g" \
    "$ROOT/scripts/lab-portal.service" > /etc/systemd/system/lab-portal.service
systemctl daemon-reload
systemctl enable lab-portal.service >/dev/null 2>&1 || true
systemctl restart lab-portal.service
note "lab-portal.service on 127.0.0.1:$INTERNAL_PORT"

say "Proxy"
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  if ss -ltnp "sport = :$PORT" 2>/dev/null | grep -q '"caddy"'; then
    note "caddy already holds $PORT; its configuration will be replaced"
  else
    die "Something other than caddy listens on $PORT. Stop it, or pass --port <n>."
  fi
fi
# A lab platform that redirects 443 to 8443 does it in PREROUTING, and the rule is restored on
# every boot, so the destination port is served as well. Both the live table and the saved file are
# read: a box whose boot-time unit has already removed the live copy still carries it in the file.
ALSO_PORTS="$ALSO_PORT"
if [ -z "$ALSO_PORTS" ] && [ "$PORT" = "443" ]; then ALSO_PORTS="8443"; fi
if [ "$ALSO_PORT" = "off" ]; then ALSO_PORTS=""; fi
REDIRECTED="$( { iptables-save -t nat 2>/dev/null || true
                 cat /etc/iptables/rules.v4 2>/dev/null || true; } \
  | sed -n "s/.*--dport $PORT[^0-9].*-j REDIRECT.*--to-ports \([0-9][0-9]*\).*/\1/p" | sort -u)"
for FOUND in $REDIRECTED; do
  note "port $PORT is redirected to $FOUND here"
  case " $ALSO_PORTS " in *" $FOUND "*) ;; *) ALSO_PORTS="$ALSO_PORTS $FOUND" ;; esac
done
KEPT=""
for CANDIDATE in $ALSO_PORTS; do
  [ "$CANDIDATE" = "$PORT" ] && continue
  if ss -ltn "sport = :$CANDIDATE" | grep -q LISTEN \
     && ! ss -ltnp "sport = :$CANDIDATE" 2>/dev/null | grep -q '"caddy"'; then
    warn "something other than caddy listens on $CANDIDATE; not serving that port"
    continue
  fi
  KEPT="${KEPT:+$KEPT }$CANDIDATE"
done
ALSO_PORTS="$KEPT"
[ -z "$ALSO_PORTS" ] || note "also serving:$(printf ' %s' $ALSO_PORTS)"

is_ip() { printf '%s' "$1" | grep -Eq '^[0-9]+(\.[0-9]+){3}$'; }
if [ "$PORT" = "443" ] || { [ "$MODE" = "lan-http" ] && [ "$PORT" = "80" ]; }; then
  SITE="$HOST"
else
  SITE="$HOST:$PORT"
fi
[ "$MODE" != "lan-http" ] || SITE="http://$SITE"
for EXTRA in ${ALSO_PORTS:-}; do
  if [ "$MODE" = "lan-http" ]; then SITE="$SITE, http://$HOST:$EXTRA"
  else SITE="$SITE, $HOST:$EXTRA"; fi
done
{
  case "$MODE" in
    cert)
      install -o caddy -g caddy -m 0600 "$CERT" /etc/caddy/portal.crt
      install -o caddy -g caddy -m 0600 "$KEY" /etc/caddy/portal.key
      is_ip "$HOST" && printf '{\n\tdefault_sni %s\n}\n' "$HOST"
      printf '%s {\n\ttls /etc/caddy/portal.crt /etc/caddy/portal.key\n\treverse_proxy 127.0.0.1:%s\n}\n' "$SITE" "$INTERNAL_PORT"
      ;;
    acme)
      [ -z "$EMAIL" ] || printf '{\n\temail %s\n}\n' "$EMAIL"
      printf '%s {\n\treverse_proxy 127.0.0.1:%s\n}\n' "$SITE" "$INTERNAL_PORT"
      ;;
    lan-http)
      printf '{\n\tauto_https off\n}\n%s {\n\treverse_proxy 127.0.0.1:%s\n}\n' "$SITE" "$INTERNAL_PORT"
      ;;
    internal)
      printf '{\n\tauto_https disable_redirects\n\tskip_install_trust\n'
      is_ip "$HOST" && printf '\tdefault_sni %s\n' "$HOST"
      printf '}\n%s {\n\ttls internal\n\treverse_proxy 127.0.0.1:%s\n}\n' "$SITE" "$INTERNAL_PORT"
      ;;
  esac
} > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
  || die "Caddy rejected the generated config. Inspect /etc/caddy/Caddyfile."
systemctl restart caddy
note "caddy serving $SITE"

say "Checking"
OK=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$INTERNAL_PORT/healthz" >/dev/null 2>&1; then OK=1; break; fi
  sleep 1
done
[ "$OK" = "1" ] || die "The portal did not answer. Run: journalctl -u lab-portal -n 40"
note "portal answering on 127.0.0.1:$INTERNAL_PORT"

case "$MODE" in lan-http) SCHEME=http ;; *) SCHEME=https ;; esac
if [ "$PORT" = "443" ] || { [ "$MODE" = "lan-http" ] && [ "$PORT" = "80" ]; }; then
  URL="$SCHEME://$HOST"
else
  URL="$SCHEME://$HOST:$PORT"
fi
cat <<DONE

Done. The portal is this box's main page.

  Participants   $URL
  Instructor     $URL/admin

Before the room fills up:
  1. Sign in at $URL/admin
  2. Upload the Splunk Show instance URLs. Do not include this box's own URL.
  3. Upload the fallback account list, if you have one.
  4. Arm account creation with a Galileo admin API key. It is held in memory only, so it is
     never in a snapshot of this box, and it has to be armed again after a reboot.

DONE
