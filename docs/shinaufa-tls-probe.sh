#!/bin/bash
# TLS handshake probe + auto-heal for booking + avito on :443.
# Runs every 2 min via shinaufa-tls-probe.timer.
# Logs: /var/log/shinaufa-tls-probe/actions.log
#
# External clients hit the public :443 listener; hairpin (curl --resolve to
# PUBLIC_IP from this host) can succeed while the public queue is stuck — do NOT
# use hairpin as a pass signal. syn-recv / listen Recv-Q on :443 are the hard
# signals for that failure mode. Local openssl/curl on 127.0.0.1 only prove
# the app+TLS stack itself, not the public accept path.
set -uo pipefail

LOGDIR=/var/log/shinaufa-tls-probe
ACTION_LOG="$LOGDIR/actions.log"
STATE="$LOGDIR/fail_streak"
LAST_OK="$LOGDIR/last_ok"
LAST_RUN="$LOGDIR/last_run"
CONNECT_TIMEOUT=4
MAX_TIME=8
UA="shinaufa-tls-probe/2.1"
SYN_RECV_LIMIT=3
LISTEN_RECVQ_LIMIT=3
PUBLIC_IP="185.198.152.108"
TS=$(date -Is)

mkdir -p "$LOGDIR"

log_action() {
  echo "$TS $*" >> "$ACTION_LOG"
}

count_syn_recv_443() {
  ss -H -tan state syn-recv '( sport = :443 )' 2>/dev/null | wc -l | tr -d ' '
}

count_established_443() {
  ss -H -tan state established '( sport = :443 )' 2>/dev/null | wc -l | tr -d ' '
}

# Accept-queue depth on the public :443 listeners (external symptom).
count_listen_recvq_443() {
  local maxq=0
  local q
  while read -r q; do
    [[ "$q" =~ ^[0-9]+$ ]] || continue
    if [[ "$q" -gt "$maxq" ]]; then
      maxq=$q
    fi
  done < <(ss -H -ltn '( sport = :443 )' 2>/dev/null | awk '{print $2}')
  echo "$maxq"
}

count_nginx_workers() {
  local n
  n=$(ps -C nginx -o cmd --no-headers 2>/dev/null | grep -c '[w]orker process' || true)
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  echo "$n"
}

# Best-effort: workers look saturated if every worker has a large share of
# established+syn-recv sockets (no stub_status on this host).
nginx_workers_busy() {
  local workers est syn total
  workers=$(count_nginx_workers)
  [[ "$workers" =~ ^[0-9]+$ ]] || workers=0
  [[ "$workers" -gt 0 ]] || return 1
  est=$(count_established_443)
  syn=$(count_syn_recv_443)
  [[ "$est" =~ ^[0-9]+$ ]] || est=0
  [[ "$syn" =~ ^[0-9]+$ ]] || syn=0
  total=$((est + syn))
  # Soft ceiling: if syn backlog present and total sockets >> workers, treat busy.
  if [[ "$syn" -gt "$SYN_RECV_LIMIT" && "$total" -ge $((workers * 50)) ]]; then
    return 0
  fi
  return 1
}

# Optional non-loopback source IP (secondary addr / docker bridge) — never treat
# success as healthy (may still hairpin); failure while local OK is a symptom.
pick_alt_iface_ip() {
  # Only a second public address on eth*/ens*/enp* (skip docker/br-* hairpins).
  local iface cidr ip
  while read -r _ iface _ cidr _; do
    case "$iface" in
      eth*|ens*|enp*) ;;
      *) continue ;;
    esac
    ip="${cidr%%/*}"
    [[ -n "$ip" ]] || continue
    [[ "$ip" == "$PUBLIC_IP" ]] && continue
    [[ "$ip" == 127.* ]] && continue
    echo "$ip"
    return 0
  done < <(ip -4 -o addr show scope global 2>/dev/null)
  return 1
}

# TLS + HTTP via loopback (not hairpin to public IP).
probe_curl_local() {
  local name="$1"
  local host="$2"
  local path="$3"
  local out
  out=$(curl -sS -o /dev/null \
    -w '%{http_code} connect=%{time_connect} appconnect=%{time_appconnect} total=%{time_total}' \
    --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
    -A "$UA" --resolve "${host}:443:127.0.0.1" "https://${host}${path}" 2>/dev/null \
    || echo "000 connect=0 appconnect=0 total=${MAX_TIME}")
  local code="${out%% *}"
  local appconnect
  appconnect=$(echo "$out" | sed -n 's/.*appconnect=\([0-9.]*\).*/\1/p')
  if [[ ! "$code" =~ ^[0-9]+$ ]] || [[ "$code" == "000" ]]; then
    log_action "FAIL name=$name reason=curl code=$code detail=$out"
    return 1
  fi
  if awk -v t="$appconnect" -v lim="$CONNECT_TIMEOUT" 'BEGIN{exit !(t+0 > lim)}'; then
    log_action "FAIL name=$name reason=slow_tls appconnect=$appconnect detail=$out"
    return 1
  fi
  return 0
}

probe_openssl_local() {
  local name="$1"
  local host="$2"
  if timeout "$CONNECT_TIMEOUT" openssl s_client -connect 127.0.0.1:443 -servername "$host" \
      </dev/null >/dev/null 2>&1; then
    return 0
  fi
  log_action "FAIL name=$name reason=openssl_s_client host=$host ip=127.0.0.1"
  return 1
}

# Probe via alternate source address toward PUBLIC_IP (diagnostic only).
# Failure + healthy localhost => public-path symptom. Success is ignored.
probe_curl_alt_iface() {
  local alt_ip
  alt_ip=$(pick_alt_iface_ip) || return 0
  local out code
  out=$(curl -sS -o /dev/null \
    -w '%{http_code}' \
    --interface "$alt_ip" \
    --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
    -A "$UA" --resolve "booking.shinaufa.ru:443:${PUBLIC_IP}" \
    "https://booking.shinaufa.ru/ping" 2>/dev/null \
    || echo "000")
  code="${out%% *}"
  if [[ "$code" == "000" ]]; then
    log_action "WARN name=alt_iface_curl reason=fail code=$code iface=$alt_ip (not pass; public-path hint)"
    return 1
  fi
  # Success may be false-OK hairpin — do not clear fail.
  log_action "INFO name=alt_iface_curl code=$code iface=$alt_ip (ignored as pass)"
  return 0
}

verify_healthy() {
  local syn est recvq
  syn=$(count_syn_recv_443)
  est=$(count_established_443)
  recvq=$(count_listen_recvq_443)
  [[ "$syn" =~ ^[0-9]+$ ]] || syn=0
  [[ "$est" =~ ^[0-9]+$ ]] || est=0
  [[ "$recvq" =~ ^[0-9]+$ ]] || recvq=0
  [[ "$syn" -le "$SYN_RECV_LIMIT" ]] || return 1
  [[ "$recvq" -le "$LISTEN_RECVQ_LIMIT" ]] || return 1
  nginx_workers_busy && return 1
  probe_openssl_local booking_openssl booking.shinaufa.ru || return 1
  probe_openssl_local avito_openssl avito.shinaufa.ru || return 1
  probe_curl_local booking_curl booking.shinaufa.ru /ping || return 1
  probe_curl_local avito_curl avito.shinaufa.ru /healthz || return 1
  return 0
}

fail=0
heal_now=0
local_ok=1
syn_recv=$(count_syn_recv_443)
established=$(count_established_443)
listen_recvq=$(count_listen_recvq_443)
[[ "$syn_recv" =~ ^[0-9]+$ ]] || syn_recv=0
[[ "$established" =~ ^[0-9]+$ ]] || established=0
[[ "$listen_recvq" =~ ^[0-9]+$ ]] || listen_recvq=0

if [[ "$syn_recv" -gt "$SYN_RECV_LIMIT" ]]; then
  log_action "FAIL reason=syn_recv_stuck count=$syn_recv limit=$SYN_RECV_LIMIT established=$established (public :443 queue)"
  fail=1
  heal_now=1
fi

if [[ "$listen_recvq" -gt "$LISTEN_RECVQ_LIMIT" ]]; then
  log_action "FAIL reason=listen_recvq_stuck recvq=$listen_recvq limit=$LISTEN_RECVQ_LIMIT syn_recv=$syn_recv established=$established"
  fail=1
  heal_now=1
fi

if nginx_workers_busy; then
  log_action "FAIL reason=nginx_workers_busy syn_recv=$syn_recv established=$established workers=$(count_nginx_workers)"
  fail=1
  heal_now=1
fi

probe_openssl_local booking_openssl booking.shinaufa.ru || { fail=1; local_ok=0; }
probe_openssl_local avito_openssl avito.shinaufa.ru || { fail=1; local_ok=0; }
probe_curl_local booking_curl booking.shinaufa.ru /ping || { fail=1; local_ok=0; }
probe_curl_local avito_curl avito.shinaufa.ru /healthz || { fail=1; local_ok=0; }

# Local stack OK but public accept path looks stuck → immediate heal + clear log.
if [[ "$local_ok" -eq 1 && "$heal_now" -eq 1 ]]; then
  log_action "FAIL reason=local_ok_public_stuck syn_recv=$syn_recv listen_recvq=$listen_recvq established=$established"
fi

# Diagnostic alt-iface curl (only if a second public IP exists).
# Failure alone never heals; only reinforces when queue symptoms already present.
if [[ "$local_ok" -eq 1 ]]; then
  if ! probe_curl_alt_iface; then
    if [[ "$syn_recv" -gt "$SYN_RECV_LIMIT" || "$listen_recvq" -gt "$LISTEN_RECVQ_LIMIT" ]]; then
      log_action "FAIL reason=alt_iface_and_queue syn_recv=$syn_recv listen_recvq=$listen_recvq"
    fi
  fi
fi

echo "$TS fail=$fail syn_recv=$syn_recv established=$established listen_recvq=$listen_recvq heal_now=$heal_now local_ok=$local_ok" > "$LAST_RUN"

if [[ "$fail" -eq 0 ]]; then
  echo 0 > "$STATE"
  echo "$TS ok syn_recv=$syn_recv established=$established listen_recvq=$listen_recvq" > "$LAST_OK"
  exit 0
fi

streak=0
[[ -f "$STATE" ]] && streak=$(cat "$STATE" 2>/dev/null || echo 0)
[[ "$streak" =~ ^[0-9]+$ ]] || streak=0
streak=$((streak + 1))
echo "$streak" > "$STATE"

if [[ "$heal_now" -eq 1 ]]; then
  log_action "HEAL trigger=immediate reason=public_path_or_queue syn_recv=$syn_recv listen_recvq=$listen_recvq established=$established streak=$streak"
else
  log_action "streak=$streak (need 2 before heal for tls/curl-only fail)"
  if [[ "$streak" -lt 2 ]]; then
    exit 1
  fi
  log_action "HEAL trigger=streak reason=tls_or_curl_fail streak=$streak"
fi

log_action "HEAL action=reload nginx syn_recv=$syn_recv listen_recvq=$listen_recvq"
if systemctl reload nginx; then
  sleep 3
  syn_recv=$(count_syn_recv_443)
  listen_recvq=$(count_listen_recvq_443)
  if verify_healthy; then
    log_action "HEAL reload OK syn_recv=$syn_recv listen_recvq=$listen_recvq"
    echo 0 > "$STATE"
    echo "$TS ok after reload syn_recv=$syn_recv" > "$LAST_OK"
    exit 0
  fi
  log_action "HEAL reload insufficient syn_recv=$syn_recv listen_recvq=$listen_recvq"
else
  log_action "HEAL reload command_failed"
fi

log_action "HEAL action=restart nginx syn_recv=$syn_recv listen_recvq=$listen_recvq"
if systemctl restart nginx; then
  sleep 2
  syn_recv=$(count_syn_recv_443)
  listen_recvq=$(count_listen_recvq_443)
  if verify_healthy; then
    log_action "HEAL restart OK syn_recv=$syn_recv listen_recvq=$listen_recvq"
    echo 0 > "$STATE"
    echo "$TS ok after restart syn_recv=$syn_recv" > "$LAST_OK"
    exit 0
  fi
  log_action "HEAL restart FAILED still broken syn_recv=$syn_recv listen_recvq=$listen_recvq"
else
  log_action "HEAL restart command_failed"
fi

exit 1
