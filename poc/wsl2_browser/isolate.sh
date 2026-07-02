#!/usr/bin/env bash
# Throwaway spike copy of the isolation mechanism in src/artemis/capabilities/sandbox_wsl2.py
# (_ISOLATE_SCRIPT), adapted to a standalone file so it can be invoked directly for the
# headless-Chromium feasibility spike. Same security shape: netns + nginx SNI-allowlist
# proxy (stream{} ssl_preread for HTTPS, http{} Host-map for HTTP) + in-ns dnsmasq DNS stub +
# de-privileged setpriv exec inside a private mount+pid namespace, cgroup+ulimit caps.
# DO NOT edit src/ — this file is a disposable copy for the spike only.
set -euo pipefail
SKILL_WSL="$1"; EGRESS_CSV="$2"; RUN_ID="$3"; shift 3   # remaining "$@" = command tokens
NS="artemis-$RUN_ID"; WORK="/tmp/artemis-$RUN_ID"; CG="/sys/fs/cgroup/artemis-$RUN_ID"
NGXDIR="/run/artemis-ngx-$RUN_ID"
NGX_HTTPS=8443; NGX_HTTP=8080; UNTRUSTED_UID=4000; NGINX_UID=33
DNS_STUB=127.0.0.1
SID="${RUN_ID:0:8}"; VETH_HOST="vh$SID"; VETH_PEER="vc$SID"; HOST_IF=""
: "${MEM_MAX:=1610612736}"   # default 1.5GiB for this spike (chromium is memory-hungry)
: "${CPU_MAX:=400000 100000}"   # 4 cores — a 1-core CFS quota (100000/100000) was observed to cause
                                 # severe latency amplification for chromium's multi-threaded startup
                                 # (a trivial about:blank render exceeded 60s vs ~10-20s unconstrained)
: "${PIDS_MAX:=256}"
: "${ULIMIT_T:=60}"
: "${ULIMIT_V:=unlimited}"   # per-process VSZ ulimit is useless for chromium's mmap-heavy address space; rely on cgroup memory.max instead
abort() { echo "isolate-setup-failed: $1" >&2; exit 1; }
cleanup() {
  if [ -n "${DEBUG_KEEP:-}" ]; then echo "DEBUG_KEEP set, skipping cleanup for $RUN_ID" >&2; return 0; fi
  ip netns pids "$NS" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  ip netns del "$NS" 2>/dev/null || true
  if [ -n "${HOST_IF:-}" ]; then
    iptables -t nat -D POSTROUTING -s "$VETH_NET" -o "$HOST_IF" -j MASQUERADE 2>/dev/null || true
    iptables -D FORWARD -i "$VETH_HOST" -o "$HOST_IF" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -i "$HOST_IF" -o "$VETH_HOST" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
  fi
  ip link del "$VETH_HOST" 2>/dev/null || true
  rmdir "$CG" 2>/dev/null || true
  rm -rf "$WORK" "$NGXDIR" 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$WORK" || abort workdir; cp -r "$SKILL_WSL/." "$WORK/" || abort copy
mkdir -p "$CG" || abort cgroup
echo "$MEM_MAX"  > "$CG/memory.max" || abort memory.max
echo 0 > "$CG/memory.swap.max" || true
echo "$CPU_MAX"  > "$CG/cpu.max"    || abort cpu.max
echo "$PIDS_MAX" > "$CG/pids.max"   || abort pids.max
chown -R "$UNTRUSTED_UID:$UNTRUSTED_UID" "$WORK" || abort chown
ip netns add "$NS" || abort netns
ip -n "$NS" link set lo up || abort lo
ip netns exec "$NS" sysctl -qw net.ipv6.conf.all.disable_ipv6=1 || abort ipv6
ip netns exec "$NS" sysctl -qw net.ipv6.conf.default.disable_ipv6=1 || true
if [ -n "$EGRESS_CSV" ]; then
  O1=$((16#${RUN_ID:0:2} % 254 + 1)); O2=$((16#${RUN_ID:2:2} & 252))
  VETH_NET="10.201.$O1.$O2/30"; VETH_HOST_IP="10.201.$O1.$((O2 + 1))"; VETH_PEER_IP="10.201.$O1.$((O2 + 2))"
  ip link del "$VETH_HOST" 2>/dev/null || true
  ip link add "$VETH_HOST" type veth peer name "$VETH_PEER" || abort veth-add
  ip link set "$VETH_PEER" netns "$NS" || abort veth-netns
  ip addr add "$VETH_HOST_IP/30" dev "$VETH_HOST" || abort veth-host-addr
  ip link set "$VETH_HOST" up || abort veth-host-up
  ip -n "$NS" addr add "$VETH_PEER_IP/30" dev "$VETH_PEER" || abort veth-peer-addr
  ip -n "$NS" link set "$VETH_PEER" up || abort veth-peer-up
  ip -n "$NS" route add default via "$VETH_HOST_IP" || abort veth-route
  HOST_IF=$(ip route show default | awk '/default/{print $5; exit}') || abort host-if
  [ -n "$HOST_IF" ] || abort host-if
  sysctl -qw net.ipv4.ip_forward=1 || abort ip-forward
  iptables -t nat -A POSTROUTING -s "$VETH_NET" -o "$HOST_IF" -j MASQUERADE || abort nat-masq
  iptables -A FORWARD -i "$VETH_HOST" -o "$HOST_IF" -j ACCEPT || abort fwd-out
  iptables -A FORWARD -i "$HOST_IF" -o "$VETH_HOST" -m state --state RELATED,ESTABLISHED -j ACCEPT || abort fwd-in
  mkdir -p "$NGXDIR" || abort ngxdir
  chmod 700 "$NGXDIR" || abort ngxdir-perm
  RE='^[a-zA-Z0-9]([a-zA-Z0-9-]{0,62}\.)+[a-zA-Z]{2,63}$'
  set -f
  IFS=',' read -ra _domains <<< "$EGRESS_CSV"
  set +f
  ALLOWED=()
  for d in "${_domains[@]}"; do
    [ -z "$d" ] && continue
    case "$d" in *$'\n'*|*$'\r'*) abort "newline-in-domain" ;; esac
    [[ "$d" =~ $RE ]] || abort "bad-domain:$d"
    ALLOWED+=("$d")
  done
  [ "${#ALLOWED[@]}" -gt 0 ] || abort no-valid-domains
  ip netns exec "$NS" dnsmasq --keep-in-foreground --conf-file=/dev/null --no-resolv --no-hosts \
    --listen-address="$DNS_STUB" --bind-interfaces --port=53 --address="/#/$DNS_STUB" &
  DNSPID=$!; disown; sleep 0.2; kill -0 "$DNSPID" 2>/dev/null || abort dnsmasq
  printf 'nameserver %s\n' "$DNS_STUB" > "$NGXDIR/resolv.conf" || abort resolvconf
  {
    printf 'load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n'
    printf 'user www-data;\nworker_processes 1;\npid %s/nginx.pid;\n' "$NGXDIR"
    printf 'events { worker_connections 128; }\n'
    printf 'stream {\n  resolver 8.8.8.8 valid=10s ipv6=off;\n  map $ssl_preread_server_name $ups {\n    default "";\n'
    for d in "${ALLOWED[@]}"; do printf '    "%s" "%s:443";\n' "$d" "$d"; done
    printf '  }\n  server {\n    listen %s;\n    ssl_preread on;\n    proxy_pass $ups;\n' "$NGX_HTTPS"
    printf '    proxy_connect_timeout 5s;\n  }\n}\n'
    printf 'http {\n  resolver 8.8.8.8 valid=10s ipv6=off;\n  map $host $ok {\n    default 0;\n'
    for d in "${ALLOWED[@]}"; do printf '    "%s" 1;\n' "$d"; done
    printf '  }\n  server {\n    listen %s;\n    location / {\n' "$NGX_HTTP"
    printf '      if ($ok = 0) { return 444; }\n      proxy_pass http://$host;\n    }\n  }\n}\n'
  } > "$NGXDIR/nginx.conf" || abort nginx-conf
  ip netns exec "$NS" nginx -c "$NGXDIR/nginx.conf" || abort nginx
  NSX="ip netns exec $NS iptables"
  $NSX -t nat -A OUTPUT -m owner --uid-owner "$NGINX_UID" -j RETURN || abort nat-nginx
  $NSX -t nat -A OUTPUT -p tcp --dport 443 -m owner --uid-owner "$UNTRUSTED_UID" -j REDIRECT --to-ports "$NGX_HTTPS" || abort nat-443
  $NSX -t nat -A OUTPUT -p tcp --dport 80  -m owner --uid-owner "$UNTRUSTED_UID" -j REDIRECT --to-ports "$NGX_HTTP" || abort nat-80
  $NSX -A OUTPUT -m owner --uid-owner "$NGINX_UID" -j ACCEPT || abort acc-nginx
  $NSX -A OUTPUT -o lo -j ACCEPT || abort acc-lo
  $NSX -A OUTPUT -p udp --dport 53 -d "$DNS_STUB" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort dns-udp-ok
  $NSX -A OUTPUT -p tcp --dport 53 -d "$DNS_STUB" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort dns-tcp-ok
  $NSX -A OUTPUT -p udp --dport 53 -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort dns-udp-drop
  $NSX -A OUTPUT -p tcp --dport 53 -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort dns-tcp-drop
  $NSX -A OUTPUT -p tcp -m multiport --dports "$NGX_HTTPS,$NGX_HTTP" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort acc-proxy
  $NSX -A OUTPUT -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort default-deny   # catches QUIC (443/udp) too — no explicit allow above
fi
set +e
# Peak memory is read from the cgroup's memory.peak (kernel >=6.5, aggregates ALL processes
# placed in this cgroup — the whole chromium process tree — unlike a single-process rusage).
ip netns exec "$NS" unshare --mount --pid --fork bash -c '
  set -euo pipefail
  mount --make-rprivate /
  mount -t tmpfs none /mnt
  mount -t proc proc /proc
  mount -t cgroup2 none /sys/fs/cgroup
  if [ -f "'"$NGXDIR"'/resolv.conf" ]; then
    rm -f /etc/resolv.conf 2>/dev/null || true
    cp "'"$NGXDIR"'/resolv.conf" /etc/resolv.conf
  fi
  echo $$ > "'"$CG"'/cgroup.procs"
  ulimit -t "'"$ULIMIT_T"'"
  mkdir -p /tmp/shm && mount -t tmpfs -o size=512m none /dev/shm 2>/dev/null || true
  cd "'"$WORK"'"
  exec setpriv --reuid="'"$UNTRUSTED_UID"'" --regid="'"$UNTRUSTED_UID"'" --clear-groups \
       --inh-caps=-all --bounding-set=-all -- "$@"' _ "$@" \
  > "$WORK/../artemis-$RUN_ID-stdout.log" 2> "$WORK/../artemis-$RUN_ID-stderr.log"
STATUS=$?
set -e
echo "=== PEAK MEMORY (cgroup, bytes) ==="
cat "$CG/memory.peak" 2>/dev/null || echo "memory.peak not available on this kernel"
echo "=== STDOUT ==="
cat "$WORK/../artemis-$RUN_ID-stdout.log" 2>/dev/null
echo "=== STDERR (tail) ==="
tail -c 4000 "$WORK/../artemis-$RUN_ID-stderr.log" 2>/dev/null
rm -f "$WORK/../artemis-$RUN_ID-stdout.log" "$WORK/../artemis-$RUN_ID-stderr.log" "$WORK/../artemis-$RUN_ID-time.log" 2>/dev/null
exit "$STATUS"
