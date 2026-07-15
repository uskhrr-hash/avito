# Развёртывание через Git (ПК + VPS)

Пошаговая инструкция для **не программиста**. Все команды копируйте целиком и вставляйте в терминал.

- **ПК** — Windows, проект в `C:\Users\Ruslan\Desktop\avito_tires_parser`
- **Сервер** — `root@185.198.152.108`, папка `/opt/avito_tires_parser`
- **Сайт** — `https://avito.shinaufa.ru`

---

## Что хранится в Git, а что нет

| В Git (код) | НЕ в Git (только на машине) |
|---|---|
| Все `.py` файлы, `config.yaml`, `stores.yaml` | `secrets.local.yaml` — пароли, API-ключи |
| Шаблоны в `input/` (выгрузка Avito) | `config.local.yaml` — настройки только для VPS |
| Скрипты `deploy/` | `input/goods.xlsx` — остатки (собираются на сервере) |
| | `data/avito_descriptions.db` — один раз копируется на сервер |
| | Фото в `/opt/avito_tires_photos/` |

> **Публичный репозиторий:** в Git **никогда** не попадают `secrets.local.yaml` и `config.local.yaml`. Перед каждым `git push` смотрите `git status` — там не должно быть файлов с паролями.

---

## ЧАСТЬ 1. Один раз: создать репозиторий на GitHub

### Шаг 1.1 — Зайти на GitHub

1. Откройте https://github.com и войдите в аккаунт.
2. Нажмите **+** → **New repository**.
3. Имя: `avito` (у вас уже создан: https://github.com/uskhrr-hash/avito)
4. Выберите **Public** (публичный) или **Private** — сейчас репозиторий публичный.
5. **Не** ставьте галочки README / .gitignore (у нас уже есть).
6. Нажмите **Create repository**.
7. Адрес репозитория: `https://github.com/uskhrr-hash/avito.git`

### Шаг 1.2 — На ПК: отправить код в GitHub

Откройте **PowerShell** (Win+X → Terminal) и выполните **по очереди**:

```powershell
cd C:\Users\Ruslan\Desktop\avito_tires_parser
```

```powershell
git add -A
```

```powershell
git status
```

(Проверьте: в списке **не должно** быть `secrets.local.yaml`)

```powershell
git commit -m "Avito autoload: stock pipeline, photo upload, API publish"
```

```powershell
git branch -M main
```

```powershell
git remote add origin https://github.com/uskhrr-hash/avito.git
```

Если `origin` уже был с другим адресом:

```powershell
git remote set-url origin https://github.com/uskhrr-hash/avito.git
```

```powershell
git push -u origin main
```

GitHub спросит логин/пароль. Для пароля используйте **Personal Access Token** (не пароль от аккаунта):

1. GitHub → Settings → Developer settings → Personal access tokens → Generate new token
2. Права: `repo`
3. Скопируйте токен и вставьте как пароль

---

## ЧАСТЬ 2. Один раз: установить проект на сервере

Подключитесь к серверу:

```powershell
ssh root@185.198.152.108
```

Дальше все команды — **на сервере** (приглашение `root@booking:...`).

### Шаг 2.1 — Удалить старую копию (если была через scp)

```bash
rm -rf /opt/avito_tires_parser
```

### Шаг 2.2 — Клонировать из GitHub

```bash
git clone https://github.com/uskhrr-hash/avito.git /opt/avito_tires_parser
```

Если спросит логин GitHub — введите логин и **токен** как пароль.

### Шаг 2.3 — Автоматическая первичная настройка

```bash
cd /opt/avito_tires_parser
bash deploy/first-install-on-server.sh https://github.com/uskhrr-hash/avito.git
```

### Шаг 2.4 — Настройки только для сервера

```bash
nano /opt/avito_tires_parser/config.local.yaml
```

Файл уже создан из примера. Обычно менять ничего не нужно.  
Сохранить: `Ctrl+O`, Enter, `Ctrl+X`.

### Шаг 2.5 — Секреты (пароли, API)

```bash
nano /opt/avito_tires_parser/secrets.local.yaml
```

Заполните (как на ПК, плюс блок `photo_upload`):

```yaml
photo_upload:
  session_secret: длинная-случайная-строка
  stores:
    md: пароль-для-магазина-md
    pg: пароль-для-магазина-pg
```

Сохранить: `Ctrl+O`, Enter, `Ctrl+X`.

### Шаг 2.6 — База описаний (один раз с ПК)

На **ПК** в PowerShell:

```powershell
scp C:\Users\Ruslan\Desktop\avito_tires_parser\data\avito_descriptions.db root@185.198.152.108:/opt/avito_tires_parser/data/
```

### Шаг 2.7 — nginx (если ещё не настроен)

На сервере:

```bash
cp /opt/avito_tires_parser/deploy/nginx-avito.shinaufa.ru.conf /etc/nginx/sites-available/avito.shinaufa.ru
ln -sf /etc/nginx/sites-available/avito.shinaufa.ru /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

### Шаг 2.8 — Проверка

```bash
systemctl status avito-photo-upload
curl -s https://avito.shinaufa.ru/health
```

В браузере на телефоне: **https://avito.shinaufa.ru/photo/**

---

## ЧАСТЬ 3. Каждый раз при изменениях (обычная работа)

### На ПК — после правок в коде

```powershell
cd C:\Users\Ruslan\Desktop\avito_tires_parser
```

```powershell
git add -A
```

```powershell
git status
```

```powershell
git commit -m "Кратко: что изменили"
```

```powershell
git push
```

### На сервере — подтянуть обновления

```powershell
ssh root@185.198.152.108
```

На сервере:

```bash
cd /opt/avito_tires_parser
bash deploy/update-on-server.sh
```

Скрипт сам сделает: `git pull`, `pip install`, перезапуск `avito-photo-upload`.

---

## ЧАСТЬ 4. Полный пайплайн на сервере (автомат)

Цикл: `build_stock` → `process_manager_inbox` → `compare_prices` → `build_autoload` → `publish_avito_feed` (+ sync API).

Таймер **каждые 3 часа** по Екатеринбургу: **06:00, 09:00, 12:00, 15:00, 18:00, 21:00**.

### Один раз: часовой пояс сервера

```bash
timedatectl set-timezone Asia/Yekaterinburg
timedatectl
```

(Иначе слоты таймера считаются в UTC / текущем TZ системы.)

### После `git pull` / `update-on-server.sh`

Таймер ставится автоматически. Первый раз перед автозапуском прогоните вручную:

```bash
cd /opt/avito_tires_parser
bash deploy/run-daily.sh
```

Логи: `logs/daily-YYYYMMDD.log`, краткий журнал — `logs/run.log`.

### Управление таймером

```bash
systemctl list-timers avito-daily.timer
systemctl status avito-daily.timer
systemctl start avito-daily.service   # ручной прогон сейчас
journalctl -u avito-daily -n 50 --no-pager
```

Отключить автозапуск:

```bash
systemctl disable --now avito-daily.timer
```

### Предпосылки

В `config.local.yaml`: `avito_publish.enabled: true`, `avito_sync.enabled: true`, `photos_local_dir`, `report_email`.  
В `secrets.local.yaml`: ERP, Google/CSV, Avito API (и Я.Диск, если нужен inbox).

---

## ЧАСТЬ 5. Фото

### Вариант А — через веб-страницу (рекомендуется)

Менеджер открывает https://avito.shinaufa.ru/photo/ → логин → артикул → снимок → «Отправить на сервер».

### Вариант Б — первичная копия старых фото с ПК

Один раз на ПК:

```powershell
scp -r "C:\Users\Ruslan\Yandex.Disk\Авито\*" root@185.198.152.108:/opt/avito_tires_photos/
```

---

## Частые проблемы

### `git push` просит пароль каждый раз

На ПК настройте сохранение учётных данных GitHub или используйте SSH-ключ (можно настроить позже).

### На сервере `git pull` — конфликт

Не правьте код вручную на сервере. Если правили:

```bash
cd /opt/avito_tires_parser
git checkout -- .
git pull
```

### Страница /photo/ не открывается

```bash
systemctl status avito-photo-upload
journalctl -u avito-photo-upload -n 30
```

### В build_autoload «папка фото не найдена»

Проверьте:

```bash
ls /opt/avito_tires_photos
cat /opt/avito_tires_parser/config.local.yaml
```

Должно быть `photos_local_dir: /opt/avito_tires_photos`.

---

## Краткая шпаргалка

| Действие | Где | Команда |
|---|---|---|
| Отправить код | ПК | `git add -A` → `git commit -m "..."` → `git push` |
| Обновить сервер | VPS | `bash deploy/update-on-server.sh` |
| Собрать фид / publish | VPS авто | `avito-daily.timer` → `deploy/run-daily.sh` |
| Ручной прогон сейчас | VPS | `systemctl start avito-daily.service` |
| Фото с телефона | Браузер | https://avito.shinaufa.ru/photo/ |
