#!/bin/bash
# Первичная установка на VPS (запускать один раз от root)
set -euo pipefail

REPO_URL="${1:-}"
if [ -z "$REPO_URL" ]; then
  echo "Использование: bash first-install-on-server.sh https://github.com/uskhrr-hash/avito.git"
  exit 1
fi

APP_DIR=/opt/avito_tires_parser
PHOTOS_DIR=/opt/avito_tires_photos
FEED_DIR=/var/www/avito-feed/feeds

echo "=== Клонирование репозитория ==="
if [ -d "$APP_DIR/.git" ]; then
  echo "Уже есть $APP_DIR — пропуск clone"
else
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

echo "=== Папки ==="
mkdir -p "$PHOTOS_DIR" "$FEED_DIR" output logs input
chmod 755 "$PHOTOS_DIR"

echo "=== config.local.yaml ==="
if [ ! -f config.local.yaml ]; then
  cp deploy/config.local.vps.example.yaml config.local.yaml
  echo "Создан config.local.yaml — при необходимости отредактируйте: nano config.local.yaml"
fi

echo "=== secrets.local.yaml ==="
if [ ! -f secrets.local.yaml ]; then
  cp secrets.local.yaml.example secrets.local.yaml
  echo "ВАЖНО: заполните secrets.local.yaml: nano secrets.local.yaml"
fi

echo "=== Python venv ==="
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

echo "=== systemd: веб-загрузка фото ==="
cp deploy/avito-photo-upload.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable avito-photo-upload
systemctl restart avito-photo-upload

echo "=== systemd: ежедневный пайплайн (таймер) ==="
chmod +x deploy/run-daily.sh
cp deploy/avito-daily.service deploy/avito-daily.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable avito-daily.timer
systemctl start avito-daily.timer
echo "Перед первым автозапуском проверьте вручную: bash deploy/run-daily.sh"

echo "=== nginx ==="
echo "Скопируйте deploy/nginx-avito.shinaufa.ru.conf в /etc/nginx/sites-available/"
echo "и сделайте symlink в sites-enabled, затем: nginx -t && systemctl reload nginx"

echo "=== База описаний (один раз с ПК) ==="
echo "scp data/avito_descriptions.db root@SERVER:$APP_DIR/data/"

echo "=== Готово. Проверка: ==="
echo "  systemctl status avito-photo-upload"
echo "  systemctl list-timers avito-daily.timer"
echo "  curl -s https://avito.shinaufa.ru/health"
echo "  https://avito.shinaufa.ru/photo/"
echo "Рекомендуется: timedatectl set-timezone Asia/Yekaterinburg"
