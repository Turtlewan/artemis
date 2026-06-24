#!/usr/bin/env bash
set -euo pipefail

# Artemis keeps the brain process bound to loopback. This is the only remote
# ingress: Tailscale terminates HTTPS and restricts access to the tailnet.

BRAIN_PORT="${BRAIN_PORT:-8030}"
if [[ ! "${BRAIN_PORT}" =~ ^[0-9]{1,5}$ ]]; then
  echo "Invalid BRAIN_PORT" >&2
  exit 1
fi

if (( BRAIN_PORT < 1 || BRAIN_PORT > 65535 )); then
  echo "Invalid BRAIN_PORT" >&2
  exit 1
fi

tailscale serve --bg --https=443 "http://127.0.0.1:${BRAIN_PORT}"
tailscale status --self --json | python -c 'import json,sys; data=json.load(sys.stdin); dns=data.get("Self", {}).get("DNSName", ""); print("https://" + dns.rstrip(".") if dns else "tailscale serve configured")'
