#!/bin/bash
# Полный цикл на VPS: остатки → inbox → цены → autoload → publish+sync
# Запуск: bash /opt/avito_tires_parser/deploy/run-daily.sh
# Или: systemctl start avito-daily.service
set -euo pipefail

export TZ="${TZ:-Asia/Yekaterinburg}"

APP_DIR=/opt/avito_tires_parser
cd "$APP_DIR"

mkdir -p logs
LOCK_FILE=logs/daily.lock
DAY_LOG="logs/daily-$(date +%Y%m%d).log"
RUN_LOG=logs/run.log

PYTHON="${APP_DIR}/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Нет $PYTHON — сначала venv: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date '+%Y-%m-%d %H:%M:%S %Z') SKIP: предыдущий прогон ещё идёт (lock $LOCK_FILE)" | tee -a "$RUN_LOG"
  exit 0
fi

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*" | tee -a "$DAY_LOG" "$RUN_LOG"
}

run_step() {
  local title="$1"
  shift
  log "=== $title ==="
  "$@" >>"$DAY_LOG" 2>&1
  log "OK: $title"
}

log "START daily pipeline"
run_step "build_stock" "$PYTHON" build_stock.py
run_step "process_manager_inbox" "$PYTHON" process_manager_inbox.py
run_step "compare_prices" "$PYTHON" compare_prices.py
run_step "build_autoload" "$PYTHON" build_autoload.py
run_step "publish_avito_feed" "$PYTHON" scripts/publish_avito_feed.py
log "DONE daily pipeline"
