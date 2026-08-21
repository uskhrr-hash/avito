#!/bin/bash
# Обновление кода на VPS после git pull
set -euo pipefail

cd /opt/avito_tires_parser

echo "=== git pull ==="
git pull --ff-only

echo "=== Python зависимости ==="
source .venv/bin/activate
pip install -r requirements.txt -q

echo "=== Перезапуск Photo v2 ==="
if systemctl is-enabled avito-photo-v2 >/dev/null 2>&1; then
  systemctl restart avito-photo-v2
  systemctl status avito-photo-v2 --no-pager
else
  echo "Сервис avito-photo-v2 не установлен — пропуск"
fi

# Legacy v1 must stay dead if somehow re-enabled
if systemctl list-unit-files avito-photo-upload.service >/dev/null 2>&1; then
  systemctl disable --now avito-photo-upload 2>/dev/null || true
fi

echo "=== systemd: ежедневный пайплайн (таймер) ==="
chmod +x deploy/run-daily.sh
cp deploy/avito-daily.service deploy/avito-daily.timer /etc/systemd/system/
systemctl daemon-reload
if systemctl is-enabled avito-daily.timer >/dev/null 2>&1; then
  systemctl restart avito-daily.timer
else
  systemctl enable --now avito-daily.timer
fi
systemctl list-timers avito-daily.timer --no-pager || true

echo "=== Готово ==="
