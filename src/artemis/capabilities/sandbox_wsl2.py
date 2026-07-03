"""Hardened WSL2 sandbox runner for untrusted capability verification.

Provisioning runbook for the WSL2 distro:
1. Install the required guest tools:
   `wsl.exe -d Ubuntu -- sudo apt-get update`
   `wsl.exe -d Ubuntu -- sudo apt-get install -y iptables nginx libnginx-mod-stream dnsmasq util-linux python3-pytest python3-requests python3-httpx`
   (`python3-pytest` is REQUIRED — capability verification runs `python3 -m pytest tests -q` in the
   isolate; without it every build fails with "No module named pytest". `python3-requests` and
   `python3-httpx` are the capability base set: the ONLY third-party runtime libraries the forge may
   author against — anything else must be stdlib. Keep this list in sync with AUTHOR_SYSTEM in
   forge.py and the sandbox-hint in run_tests below.)
2. Verify nginx has transparent TLS SNI support:
   `wsl.exe -d Ubuntu -- bash -lc 'nginx -V 2>&1 | grep -q ssl_preread'`
3. Create the de-privileged capability user once:
   `wsl.exe -d Ubuntu -- sudo useradd -r -u 4000 artemis-cap`
4. Enable systemd in `/etc/wsl.conf`, set `.wslconfig` networkingMode=nat, then run
   `wsl.exe --shutdown`.
5. Artemis probes with passwordless `wsl.exe -u root`; if the probe fails, it falls back to the
   non-hardened development subprocess sandbox.

See docs/technical/adr/ADR-036-hardened-wsl2-sandbox.md for the security boundary.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from artemis.capabilities.sandbox import SandboxRunner, SubprocessSandbox, VerifyResult

OUTPUT_LIMIT_DEFAULT = 4000
OUTPUT_LIMIT_MAX = 1_000_000
_CGROUP_PERIOD_US = 100_000
_SAFE_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RESERVED_ENV_NAMES = frozenset(
    {
        "PATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "GLIBC_TUNABLES",
        "IFS",
        "BASH_ENV",
        "ENV",
        "SHELL",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "MEM_MAX",
        "CPU_MAX",
        "PIDS_MAX",
        "ULIMIT_T",
        "ULIMIT_V",
        "OUTPUT_LIMIT",
        "WSLENV",
        "ARTEMIS_SECRETS_B64",
        "_",
    }
)
_PROBE_COMMAND = (
    "command -v ip iptables nginx dnsmasq setpriv unshare >/dev/null && "
    "nginx -V 2>&1 | grep -q ssl_preread && "
    "id -u artemis-cap >/dev/null && "
    "test -w /sys/fs/cgroup/cgroup.procs"
)

_ISOLATE_SCRIPT = r'''set -euo pipefail    # BLOCK 2: -e so any setup failure ABORTS before the untrusted command runs (fail CLOSED)
abort() { echo "isolate-setup-failed: $1" >&2; exit 1; }   # BLOCK 2: explicit guard on each security-critical step
# WSL's interop reconstructs the post-`--` argv into a single command line and re-parses it via `/bin/bash -c`
# semantics before invoking guest `bash -s`; that shell-reinterpretation is inside `wsl.exe`, invisible to the
# Python call site, so run_isolated shlex.quote()s every positional. The quotes arrive here literally, so unquote
# each back to its raw value. FAIL CLOSED (the BLOCK-2 invariant): the decode is a plain pipeline (NOT a process
# substitution, whose exit status set -e ignores) so a python3 crash/non-zero exit ABORTS; surrogateescape so a
# non-UTF8 argv byte can never crash the decode; and an explicit count check rejects any truncated decode.
_ARGC_IN=$#
_ARGV_FILE="$(mktemp)" || abort argv-mktemp
{ python3 - "$@" <<'PY'
import shlex
import sys

out = sys.stdout.buffer
for arg in sys.argv[1:]:
    parts = shlex.split(arg, posix=True)   # ValueError (malformed) => non-zero exit => abort (fail closed)
    if len(parts) == 0:
        decoded = ""                       # empty positional (e.g. empty egress CSV = no-network) — legitimate
    elif len(parts) == 1:
        decoded = parts[0]
    else:
        sys.exit(3)                        # ambiguous token: do NOT guess, fail closed
    out.write(decoded.encode("utf-8", "surrogateescape") + b"\0")
PY
} > "$_ARGV_FILE" || { rm -f "$_ARGV_FILE"; abort argv-decode; }   # no temp-file leak on the abort path
_DECODED_ARGV=()
while IFS= read -r -d '' _arg; do _DECODED_ARGV+=("$_arg"); done < "$_ARGV_FILE"
rm -f "$_ARGV_FILE"
[ "${#_DECODED_ARGV[@]}" -eq "$_ARGC_IN" ] || abort argv-count-mismatch   # truncated decode => fail closed
set -- "${_DECODED_ARGV[@]}"
unset _DECODED_ARGV _arg _ARGV_FILE _ARGC_IN
SKILL_WSL="$1"; EGRESS_CSV="$2"; RUN_ID="$3"; shift 3   # remaining "$@" = command tokens
NS="artemis-$RUN_ID"; WORK="/tmp/artemis-$RUN_ID"; CG="/sys/fs/cgroup/artemis-$RUN_ID"
NGXDIR="/run/artemis-ngx-$RUN_ID"                       # BLOCK 4: ROOT-OWNED firewall-config dir, NEVER chowned
NGX_HTTPS=8443; NGX_HTTP=8080; UNTRUSTED_UID=4000; NGINX_UID=33   # nginx=www-data; capability de-privileged
DNS_STUB=127.0.0.1                                      # BLOCK 3: the only resolver the capability may reach
SID="${RUN_ID:0:8}"; VETH_HOST="vh$SID"; VETH_PEER="vc$SID"; HOST_IF=""
OUTPUT_LIMIT="${OUTPUT_LIMIT:-4000}"
[[ "$OUTPUT_LIMIT" =~ ^[0-9]+$ ]] || abort bad-output-limit
cleanup() {
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
# 1. tmpfs copy in (D2 — no /mnt/c access from the guest process)
mkdir -p "$WORK" || abort workdir; cp -r "$SKILL_WSL/." "$WORK/" || abort copy
# 2. cgroups v2 caps as root (the enforced boundary the spike lacked). Values via WSLENV env.
mkdir -p "$CG" || abort cgroup
echo "$MEM_MAX"  > "$CG/memory.max" || abort memory.max   # bytes = memory_mb*1024*1024
echo 0 > "$CG/memory.swap.max" || true
echo "$CPU_MAX"  > "$CG/cpu.max"    || abort cpu.max       # "<quota> <period>", e.g. "100000 100000" = 100%
echo "$PIDS_MAX" > "$CG/pids.max"   || abort pids.max
# 3. de-privilege ONLY the tmpfs (capability code). The nginx-config dir stays root-owned (BLOCK 4) so the
#    capability can never unlink/replace its own firewall config.
chown -R "$UNTRUSTED_UID:$UNTRUSTED_UID" "$WORK" || abort chown
# 4. netns: empty allowlist => pure no-network (lo only); non-empty => nginx SNI/Host allowlist
#    (nginx stream ssl_preread for HTTPS-by-SNI + http $host map for HTTP; REDIRECT, not TPROXY —
#     xt_TPROXY is often absent in the WSL2 kernel and proxy_pass re-resolves by name so CDN IP
#     rotation is moot. tinyproxy CANNOT SNI-filter transparent HTTPS — see ADR-036.)
ip netns add "$NS" || abort netns
ip -n "$NS" link set lo up || abort lo
ip netns exec "$NS" sysctl -qw net.ipv6.conf.all.disable_ipv6=1 || abort ipv6      # FLAG 5: no unfiltered v6 egress
ip netns exec "$NS" sysctl -qw net.ipv6.conf.default.disable_ipv6=1 || true
if [ -n "$EGRESS_CSV" ]; then
  O1=$((16#${RUN_ID:0:2} % 254 + 1)); O2=$((16#${RUN_ID:2:2} & 252))
  VETH_NET="10.200.$O1.$O2/30"; VETH_HOST_IP="10.200.$O1.$((O2 + 1))"; VETH_PEER_IP="10.200.$O1.$((O2 + 2))"
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
  chmod 700 "$NGXDIR" || abort ngxdir-perm   # note: explicit, not umask-dependent
  # BLOCK (reopened FLAG 7): re-validate each domain BEFORE templating into nginx.conf (the egress-control
  # artifact). Split on comma with noglob so a `*`/`?`/`[` token cannot glob-expand to filenames; match the
  # WHOLE string with bash `=~` (NOT per-line `grep`, which would pass "ok.com\n<injected-directive>"); and
  # explicitly reject any embedded newline/CR as defense-in-depth. policy-wiring also pre-validates.
  RE='^[a-zA-Z0-9]([a-zA-Z0-9-]{0,62}\.)+[a-zA-Z]{2,63}$'
  set -f                                        # noglob for the split
  IFS=',' read -ra _domains <<< "$EGRESS_CSV"
  set +f
  ALLOWED=()
  for d in "${_domains[@]}"; do
    [ -z "$d" ] && continue
    case "$d" in *$'\n'*|*$'\r'*) abort "newline-in-domain" ;; esac   # reject multi-line values
    [[ "$d" =~ $RE ]] || abort "bad-domain:$d"                        # whole-string match
    ALLOWED+=("$d")
  done
  [ "${#ALLOWED[@]}" -gt 0 ] || abort no-valid-domains
  # BLOCK 3: local resolver in-ns so the capability's DNS has ONE legal destination. It resolves every name
  # to a dummy IP — content is irrelevant because REDIRECT catches the TCP connect by SNI/Host, not by the
  # resolved IP; nginx re-resolves the real name upstream. resolv.conf (nameserver $DNS_STUB) is bind-mounted
  # into the capability's private mount ns in step 5. --conf-file=/dev/null ignores any ambient dnsmasq.conf;
  # the startup is VERIFIED (backgrounding always returns success, so `& disown || abort` was dead code).
  ip netns exec "$NS" dnsmasq --keep-in-foreground --conf-file=/dev/null --no-resolv --no-hosts \
    --listen-address="$DNS_STUB" --bind-interfaces --port=53 --address="/#/$DNS_STUB" &
  DNSPID=$!; disown; sleep 0.2; kill -0 "$DNSPID" 2>/dev/null || abort dnsmasq   # verify it actually came up
  printf 'nameserver %s\n' "$DNS_STUB" > "$NGXDIR/resolv.conf" || abort resolvconf
  # Generate "$NGXDIR/nginx.conf" (root-owned) as LITERAL CODE — one map entry per validated domain. The
  # stream{} block SNI-allowlists HTTPS; the http{} block Host-allowlists plain HTTP; both default-deny.
  {
    printf 'load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n'   # stream+ssl_preread (dynamic on Ubuntu)
    printf 'user www-data;\nworker_processes 1;\npid %s/nginx.pid;\n' "$NGXDIR"
    printf 'events { worker_connections 128; }\n'
    printf 'stream {\n  resolver 8.8.8.8 valid=10s ipv6=off;\n  map $ssl_preread_server_name $ups {\n    default "";\n'
    for d in "${ALLOWED[@]}"; do printf '    "%s" "%s:443";\n' "$d" "$d"; done   # $d already regex-validated
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
  $NSX -A OUTPUT -m owner --uid-owner "$NGINX_UID" -j ACCEPT || abort acc-nginx      # nginx reaches the internet
  $NSX -A OUTPUT -o lo -j ACCEPT || abort acc-lo
  # BLOCK 3: DNS allowed ONLY to the pinned local stub; all other DNS (any other nameserver, TXT-exfil) DROPPED.
  $NSX -A OUTPUT -p udp --dport 53 -d "$DNS_STUB" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort dns-udp-ok
  $NSX -A OUTPUT -p tcp --dport 53 -d "$DNS_STUB" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort dns-tcp-ok
  $NSX -A OUTPUT -p udp --dport 53 -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort dns-udp-drop
  $NSX -A OUTPUT -p tcp --dport 53 -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort dns-tcp-drop
  $NSX -A OUTPUT -p tcp -m multiport --dports "$NGX_HTTPS,$NGX_HTTP" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort acc-proxy
  $NSX -A OUTPUT -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort default-deny   # default-deny (any proto/port)
fi
# 5. run command in netns + a PRIVATE mount+pid ns (BLOCK 1), DE-PRIVILEGED (non-root UID, all caps dropped),
#    cgroup + ulimit backstop, cwd=tmpfs. As root inside the mount ns: make mounts private, MASK the Windows
#    drives (tmpfs over /mnt — no /mnt/c host-filesystem access), bind the pinned resolv.conf, join the cgroup,
#    set ulimit; THEN setpriv drops to the untrusted UID for exec (so the capability never holds CAP_NET_ADMIN
#    /root and cannot `iptables -F` its way out or reach /mnt/c).
# The untrusted command is ALLOWED to exit non-zero (a blocked fetch / failing test is a normal,
# expected outcome we capture deliberately). Disable -e for JUST this capture so a non-zero child
# does not abort the outer script before we emit the length-prefixed output run_isolated parses.
# NOTE the inner `set -euo pipefail` (mount/proc/cgroup setup) still fails closed INSIDE the ns —
# any setup failure there makes the inner bash exit non-zero, which surfaces as STATUS!=0 here.
set +e
# Decode secrets only after nginx/dnsmasq/firewall setup so only the final capability chain
# inherits them via admin-only /proc environ, not already-running sandbox services.
ARTEMIS_SECRETS_B64='__ARTEMIS_SECRETS_B64__'
if [ -n "$ARTEMIS_SECRETS_B64" ]; then
  eval "$(printf '%s' "$ARTEMIS_SECRETS_B64" | base64 -d 2>/dev/null | python3 -c '
import json, shlex, sys
for k, v in json.load(sys.stdin).items():
    print("export " + k + "=" + shlex.quote(v))
' 2>/dev/null)" || abort secrets-decode
fi
unset ARTEMIS_SECRETS_B64
OUT=$(ip netns exec "$NS" unshare --mount --pid --fork bash -c '
  set -euo pipefail
  mount --make-rprivate /                                     # fail-closed: if this fails, abort (set -e) —
                                                              # never let the /mnt tmpfs propagate host-wide
  mount -t tmpfs none /mnt                                    # BLOCK 1: Windows drives gone inside the ns
  mount -t proc proc /proc                                    # FLAG: fresh /proc for the new pid ns (no host PIDs)
  mount -t cgroup2 none /sys/fs/cgroup                        # ip netns exec remounts /sys and shadows the cgroup
                                                              # tree; re-expose it so the cgroup-join below works
  if [ -f "'"$NGXDIR"'/resolv.conf" ]; then
    rm -f /etc/resolv.conf 2>/dev/null || true               # WSL /etc/resolv.conf is a dangling symlink → bind
    cp "'"$NGXDIR"'/resolv.conf" /etc/resolv.conf            # fails; replace it (private to this mount ns) so the
  fi                                                          # capability resolves only via the in-ns stub
  echo $$ > "'"$CG"'/cgroup.procs"
  ulimit -t "'"$ULIMIT_T"'"
  ulimit -v "'"$ULIMIT_V"'"
  cd "'"$WORK"'"
  exec setpriv --reuid="'"$UNTRUSTED_UID"'" --regid="'"$UNTRUSTED_UID"'" --clear-groups \
       --inh-caps=-all --bounding-set=-all -- "$@"' _ "$@" 2>&1)
STATUS=$?
set -e
printf '%s\n%s' "${#OUT}" "${OUT:0:$OUTPUT_LIMIT}"   # first line = original length; run_isolated derives `truncated`
exit "$STATUS"
'''


class SandboxCaps(BaseModel):
    """Resource caps enforced by the WSL2 guest cgroup and ulimit setup."""

    memory_mb: int = 512
    cpu_pct: int = 100
    pids_max: int = 128
    timeout_s: float = 60.0
    # When True, the guest `ulimit -v` (RLIMIT_AS / virtual address space) is set to `unlimited`
    # instead of `memory_mb*1024` KB. RLIMIT_AS is not a usable control for Chrome/V8, whose mmap-heavy
    # address-space reservation dwarfs its RSS; the enforced RAM ceiling stays the cgroup `memory.max`
    # (from `memory_mb`), which this flag does NOT touch. See ADR-041.
    unlimited_vsz: bool = False


# Spike-confirmed chrome-headless-shell profile (1.5GB RAM / 4 CPU / 256 pids / unlimited VSZ). Opt-in only;
# the default `SandboxCaps()` is unchanged. RENDER_CAPS deliberately relies SOLELY on cgroup `memory.max`
# for RAM containment — the `ulimit -v` backstop is disabled here because it is incompatible with Chrome/V8's
# virtual-memory reservation behavior (ADR-041 decision 2, apex-security-reviewed trade-off).
RENDER_CAPS = SandboxCaps(memory_mb=1536, cpu_pct=400, pids_max=256, unlimited_vsz=True)


@dataclass(frozen=True)
class _SandboxPolicy:
    egress_domains: list[str]
    caps: SandboxCaps


def _completed_policy() -> _SandboxPolicy:
    return _SandboxPolicy(egress_domains=[], caps=SandboxCaps())


def _policy_for(skill_dir: Path) -> _SandboxPolicy:
    policy_path = skill_dir / "sandbox_policy.json"
    if not policy_path.is_file():
        return _completed_policy()

    try:
        raw: object = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _completed_policy()

    if not isinstance(raw, dict):
        return _completed_policy()

    egress_raw = raw.get("egress_domains", [])
    egress_domains = [item for item in egress_raw if isinstance(item, str)] if isinstance(
        egress_raw, list
    ) else []

    default_caps = SandboxCaps()
    caps = SandboxCaps(
        memory_mb=_int_from_policy(raw.get("memory_mb"), default_caps.memory_mb),
        cpu_pct=_int_from_policy(raw.get("cpu_pct"), default_caps.cpu_pct),
        pids_max=_int_from_policy(raw.get("pids_max"), default_caps.pids_max),
        timeout_s=_float_from_policy(raw.get("timeout_s"), default_caps.timeout_s),
    )
    return _SandboxPolicy(egress_domains=egress_domains, caps=caps)


def _int_from_policy(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _float_from_policy(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _to_wsl_path(path: Path) -> str:
    """Convert a Windows path to its ``/mnt/<drive>`` WSL form (pure Python).

    ``wsl.exe -- wslpath`` mangles backslashes at the interop arg layer (proven live
    2026-07-01: ``C:\\Users\\...`` arrives as ``C:Users...`` and wslpath returns rc=1),
    so we convert directly instead of shelling out. Mirrors the spike's converter.
    """
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"cannot convert a driveless path to a WSL path: {resolved}")
    return "/mnt/" + drive + "/" + "/".join(resolved.parts[1:])


def _caps_env(caps: SandboxCaps) -> dict[str, str]:
    cpu_quota = max(1, math.ceil(_CGROUP_PERIOD_US * caps.cpu_pct / 100))
    return {
        "MEM_MAX": str(max(1, caps.memory_mb) * 1024 * 1024),
        "CPU_MAX": f"{cpu_quota} {_CGROUP_PERIOD_US}",
        "PIDS_MAX": str(max(1, caps.pids_max)),
        "ULIMIT_T": str(max(1, math.ceil(caps.timeout_s))),
        "ULIMIT_V": "unlimited" if caps.unlimited_vsz else str(max(1, caps.memory_mb) * 1024),
    }


def _wsl_env(existing: str | None) -> str:
    cap_names = "MEM_MAX:CPU_MAX:PIDS_MAX:ULIMIT_T:ULIMIT_V:OUTPUT_LIMIT"
    return f"{existing}:{cap_names}" if existing else cap_names


def _validate_secret_name(name: str) -> None:
    if _SAFE_ENV_NAME_RE.fullmatch(name) is None or name in _RESERVED_ENV_NAMES:
        raise ValueError(f"unsafe secret environment variable name: {name!r}")


def _secrets_b64(secrets: dict[str, str] | None) -> str:
    if not secrets:
        return ""
    for name in secrets:
        _validate_secret_name(name)
    return base64.b64encode(json.dumps(secrets, separators=(",", ":")).encode()).decode()


def _parse_isolate_output(
    stdout: bytes | str, stderr: bytes | str, output_limit: int = OUTPUT_LIMIT_DEFAULT
) -> tuple[str, bool]:
    stdout_text = stdout if isinstance(stdout, str) else stdout.decode(errors="replace")
    stderr_text = stderr if isinstance(stderr, str) else stderr.decode(errors="replace")
    first_line, separator, rest = stdout_text.partition("\n")
    if separator and first_line.isdecimal():
        original_len = int(first_line)
        output = rest + stderr_text
        return output, original_len > output_limit
    return stdout_text + stderr_text, False


async def run_isolated(
    skill_dir: Path,
    *,
    egress_domains: list[str],
    caps: SandboxCaps,
    command: list[str],
    timeout_s: float,
    secrets: dict[str, str] | None = None,
    output_limit: int = OUTPUT_LIMIT_DEFAULT,
) -> tuple[int, str, bool]:
    """Run a command in the hardened WSL2 guest sandbox.

    Returns `(exit_code, output, truncated)`. `truncated` is derived from the guest's
    length-prefixed output, not from the returned output length. `output_limit` controls
    how many output characters the isolate returns, clamped to `[1, OUTPUT_LIMIT_MAX]`.
    """

    run_id = uuid.uuid4().hex
    clamped_output_limit = min(max(1, output_limit), OUTPUT_LIMIT_MAX)
    skill_wsl_path = _to_wsl_path(skill_dir)
    blob = _secrets_b64(secrets)
    script = _ISOLATE_SCRIPT.replace("__ARTEMIS_SECRETS_B64__", blob)
    env = os.environ.copy()
    env.update(_caps_env(caps))
    env["OUTPUT_LIMIT"] = str(clamped_output_limit)
    env["WSLENV"] = _wsl_env(env.get("WSLENV"))
    # WSL's own interop layer reconstructs the post-`--` argv into a single command line and re-parses it via `/bin/bash -c` semantics before invoking guest `bash -s`; that shell-reinterpretation step is inside `wsl.exe`, not visible in this Python call site, so quoting here is not a no-op despite create_subprocess_exec having no shell.  # noqa: E501
    quoted_skill_wsl_path = shlex.quote(skill_wsl_path)
    quoted_egress_domains = shlex.quote(",".join(egress_domains))
    quoted_run_id = shlex.quote(run_id)
    quoted_command = [shlex.quote(arg) for arg in command]

    proc = await asyncio.create_subprocess_exec(
        "wsl.exe",
        "-u",
        "root",
        "--",
        "bash",
        "-s",
        "--",
        quoted_skill_wsl_path,
        quoted_egress_domains,
        quoted_run_id,
        *quoted_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(script.encode()), timeout=timeout_s
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "sandbox timeout exceeded", False

    output, truncated = _parse_isolate_output(stdout, stderr, clamped_output_limit)
    return proc.returncode or 0, output, truncated


class Wsl2SandboxRunner:
    """Hardened SandboxRunner backed by a root-provisioned WSL2 guest."""

    hardened = True

    async def run_tests(self, skill_dir: Path) -> VerifyResult:
        policy = _policy_for(skill_dir)
        code, output, _truncated = await run_isolated(
            skill_dir,
            egress_domains=policy.egress_domains,
            caps=policy.caps,
            command=["python3", "-m", "pytest", "tests", "-q"],
            timeout_s=policy.caps.timeout_s,
        )
        if code != 0:
            output = _with_missing_module_hint(output)
        return VerifyResult(passed=code == 0, output=output)


_MISSING_MODULE_RE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")

# Third-party libraries provisioned in the guest (see the runbook in the module docstring).
# Keep in sync with AUTHOR_SYSTEM in forge.py.
GUEST_BASE_LIBRARIES = ("requests", "httpx")


def _with_missing_module_hint(output: str) -> str:
    """Append a clear hint when a verify failure is a module missing from the sandbox guest.

    The raw ModuleNotFoundError is buried in a pytest traceback; the hint makes the cause
    obvious to the owner in the result card AND steers the forge's self-correction retry
    toward the provisioned base set / stdlib instead of another unavailable library.
    """
    missing = sorted(set(_MISSING_MODULE_RE.findall(output)))
    if not missing:
        return output
    names = ", ".join(missing)
    available = ", ".join(GUEST_BASE_LIBRARIES)
    return (
        f"{output}\n"
        f"sandbox-hint: module(s) not installed in the sandbox guest: {names}. "
        f"The only third-party libraries available are: {available} "
        "(pytest runs the tests). Use those or the Python standard library."
    )


def default_sandbox() -> SandboxRunner:
    """Return the WSL2 sandbox when provisioned, otherwise the subprocess development fallback."""

    try:
        completed = subprocess.run(
            ["wsl.exe", "-u", "root", "--", "bash", "-c", _PROBE_COMMAND],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return SubprocessSandbox()

    if completed.returncode == 0:
        return Wsl2SandboxRunner()
    return SubprocessSandbox()
