#!/bin/bash
# Обновление кода на VPS после git pull
set -euo pipefail

cd /opt/avito_tires_parser

echo "=== git pull ==="
git pull --ff-only

echo "=== Python зависимости ==="
source .venv/bin/activate
pip install -r requirements.txt -q

echo "=== Перезапуск веб-загрузки фото ==="
if systemctl is-enabled avito-photo-upload >/dev/null 2>&1; then
  systemctl restart avito-photo-upload
  systemctl status avito-photo-upload --no-pager
else
  echo "Сервис avito-photo-upload не установлен — пропуск"
fi

echo "=== Готово ==="
