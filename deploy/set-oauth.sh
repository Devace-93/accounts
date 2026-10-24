#!/usr/bin/env bash
# Interactive helper: asks for each OAuth provider's client id + secret, writes
# them into /opt/accounts/.env ON THE SERVER (over SSH, values travel on stdin,
# never on a command line) and restarts the API so the buttons appear.
#
#   bash deploy/set-oauth.sh                 # asks for all four providers
#   bash deploy/set-oauth.sh google github   # only these
#
# Press Enter on an empty client id to skip a provider. Secrets are read
# without echo. Callback URL to register at every provider:
#   https://accounts.3m4.net/api/auth/oauth/<provider>/callback
set -euo pipefail

HOST="${ACCOUNTS_SSH_HOST:-root@46.225.62.18}"
ENV_FILE="${ACCOUNTS_ENV_FILE:-/opt/accounts/.env}"
PROVIDERS=("$@")
[ ${#PROVIDERS[@]} -eq 0 ] && PROVIDERS=(google github microsoft discord)

lines=""
for p in "${PROVIDERS[@]}"; do
  P=$(printf '%s' "$p" | tr '[:lower:]' '[:upper:]')
  echo
  echo "── $p  (callback: https://accounts.3m4.net/api/auth/oauth/$p/callback)"
  read -rp "   client id (Enter to skip): " id
  [ -z "$id" ] && { echo "   skipped"; continue; }
  read -rsp "   client secret: " secret; echo
  [ -z "$secret" ] && { echo "   no secret given, skipped"; continue; }
  lines+="OAUTH_${P}_CLIENT_ID=$id"$'\n'
  lines+="OAUTH_${P}_CLIENT_SECRET=$secret"$'\n'
done

[ -z "$lines" ] && { echo "nothing to set"; exit 0; }

echo
echo "▶ writing to $HOST:$ENV_FILE and restarting the api"
# The remote side reads KEY=VALUE lines from stdin and replaces (or appends)
# them in .env with Python, so no value is ever interpolated into a shell.
printf '%s' "$lines" | ssh "$HOST" "python3 - '$ENV_FILE'" <<'PY'
import sys, pathlib
env = pathlib.Path(sys.argv[1])
pairs = dict(l.rstrip("\n").split("=", 1) for l in sys.stdin if "=" in l)
out, seen = [], set()
for line in env.read_text().splitlines():
    key = line.split("=", 1)[0]
    if key in pairs:
        out.append(f"{key}={pairs[key]}"); seen.add(key)
    else:
        out.append(line)
for key, value in pairs.items():
    if key not in seen:
        out.append(f"{key}={value}")
env.write_text("\n".join(out) + "\n")
print("  updated:", ", ".join(k for k in pairs if k.endswith("_ID")))
PY

ssh "$HOST" 'cd /opt/accounts/deploy && docker compose --env-file ../.env -f docker-compose.yml -f docker-compose.prod.yml up -d api >/dev/null 2>&1 && sleep 4 && echo "  providers now enabled: $(curl -sS https://accounts.3m4.net/api/auth/providers)"'
