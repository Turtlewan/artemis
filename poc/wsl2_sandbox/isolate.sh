#!/usr/bin/env bash
set -u

if [ "$#" -ne 3 ]; then
  echo "usage: isolate.sh <capability.py> <egress-allowlist> <run-id>" >&2
  exit 2
fi

CAP_SRC=$1
ALLOWLIST=$2
RUN_ID=$3
WORK=/tmp/artemis-$RUN_ID

rm -rf "$WORK"
mkdir -p "$WORK"
cp "$CAP_SRC" "$WORK/cap.py"
trap 'rm -rf "$WORK"' EXIT

read -r -d '' CHILD <<'EOF' || true
set -u

if [ -n "$ALLOWLIST" ]; then
  if command -v ip >/dev/null 2>&1; then
    ip link set lo up >/dev/null 2>&1 || true
  fi

  : >"$WORK/dnsmasq.conf"
  old_ifs=$IFS
  IFS=,
  for domain in $ALLOWLIST; do
    if [ -n "$domain" ]; then
      printf 'server=/%s/8.8.8.8\n' "$domain" >>"$WORK/dnsmasq.conf"
    fi
  done
  IFS=$old_ifs
  printf 'address=/#/0.0.0.0\n' >>"$WORK/dnsmasq.conf"

  dnsmasq \
    --no-daemon \
    --conf-file="$WORK/dnsmasq.conf" \
    --listen-address=127.0.0.1 \
    --bind-interfaces \
    --port=53 \
    >"$WORK/dnsmasq.log" 2>&1 &
  DNSMASQ_PID=$!
  trap 'kill "$DNSMASQ_PID" >/dev/null 2>&1 || true' EXIT

  printf 'nameserver 127.0.0.1\n' >"$WORK/resolv.conf"
  mount --bind "$WORK/resolv.conf" /etc/resolv.conf
else
  : >"$WORK/resolv.conf"
  mount --bind "$WORK/resolv.conf" /etc/resolv.conf
fi

cd "$WORK"
timeout 35 python3 cap.py
EOF

# Network model (see README): an empty allowlist = pure no-network (full --net
# isolation). A non-empty allowlist keeps host connectivity and gates egress via
# the private resolv.conf -> sinkhole dnsmasq (unshare --net would make even the
# allowed domain unreachable). --mount keeps the resolv.conf bind-mount private.
if [ -n "$ALLOWLIST" ]; then
  NET_NS=""
else
  NET_NS="--net"
fi

run_with_systemd() {
  systemd-run --scope -q -p MemoryMax=512M -p CPUQuota=100% \
    env WORK="$WORK" ALLOWLIST="$ALLOWLIST" CHILD="$CHILD" \
    unshare --mount $NET_NS --pid --fork --kill-child \
    bash -c 'ulimit -t 30; bash -c "$CHILD"'
}

run_with_ulimit() {
  env WORK="$WORK" ALLOWLIST="$ALLOWLIST" CHILD="$CHILD" \
    unshare --mount $NET_NS --pid --fork --kill-child \
    bash -c 'ulimit -t 30 -v 524288; bash -c "$CHILD"'
}

set +e
if command -v systemd-run >/dev/null 2>&1 \
  && systemd-run --scope -q -p MemoryMax=512M -p CPUQuota=100% true >/dev/null 2>&1; then
  OUTPUT=$(run_with_systemd 2>&1)
  STATUS=$?
else
  OUTPUT=$(run_with_ulimit 2>&1)
  STATUS=$?
fi
set -e

printf '%s' "${OUTPUT:0:4000}"
exit "$STATUS"
