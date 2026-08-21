#!/usr/bin/env bash
# Бэкап Photo v2 (run_photo_v2.py) + shared photo helpers + nginx.
set -euo pipefail

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/backups}"
DEST="${BACKUP_ROOT}/avito-photo-${STAMP}"
PROJECT="${PROJECT:-/opt/avito_tires_parser}"

mkdir -p "${DEST}"

echo "→ ${DEST}"

cp -a "${PROJECT}/avito/photo_v2" "${DEST}/"
cp -a "${PROJECT}/avito/photo_upload" "${DEST}/" 2>/dev/null || true
cp -a "${PROJECT}/run_photo_v2.py" "${DEST}/"
cp -a /etc/nginx/sites-available/avito.shinaufa.ru.conf "${DEST}/" 2>/dev/null || true
cp -a /etc/systemd/system/avito-photo-v2.service "${DEST}/" 2>/dev/null || true

tar -czf "${DEST}.tar.gz" -C "${BACKUP_ROOT}" "$(basename "${DEST}")"
echo "Готово: ${DEST}.tar.gz"
ls -lh "${DEST}.tar.gz"
