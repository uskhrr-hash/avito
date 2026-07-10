# Avito — автозагрузка шин (остатки → фид → API)

**Развёртывание на сервер через Git:** см. [deploy/DEPLOY.md](deploy/DEPLOY.md) — пошаговые команды для ПК и VPS.

---

# Avito — мониторинг цен на шины (Уфа)

Сырой ежедневный дамп объявлений: новые легковые шины, цена за 1 шт. (с пометкой `price_confidence`).

## Установка

```bat
cd %USERPROFILE%\Desktop\avito_tires_parser
pip install -r requirements.txt
python -m playwright install chromium
```

## Настройка URL

1. Откройте [Авито — шины в Уфе](https://www.avito.ru/ufa/zapchasti_i_aksessuary/shiny_diski_i_kolesa/shiny-ASgBAgICAkQKJooLgJ0B) в обычном браузере.
2. Выставьте фильтры: **легковые**, **новые**, **Сначала из Уфы** (и при необходимости сезонность).
3. Скопируйте адресную строку целиком в `config.yaml` → `search_url`.

## Первый запуск (капча)

С дата-центровых IP Авито часто показывает «Доступ ограничен». С домашнего ПК обычно проще.

```bat
python scrape.py --headed --max-pages 1
```

1. Откроется окно Chromium — **не закрывайте его сами**.
2. В консоли появится: «Решите капчу…» — скрипт **ждёт до 5 минут**, пока не появятся объявления.
3. После сбора (или ошибки) нажмите **Enter в консоли**, чтобы закрыть браузер.

Куки сохранятся в `.browser_profile/`. Дальше можно без `--headed`.

## Обычный сбор

```bat
python scrape.py
```

Собираются **все страницы** выдачи (`?p=2`, `?p=3`, …), пока не кончатся объявления.
В `config.yaml` стоит `max_pages: 0` (без лимита). Ограничить: `python scrape.py --max-pages 5`.

Между страницами умная пауза (`config.yaml`):
- база **7 ± 3 с**, с 5-й страницы чуть растёт (`page_delay_step_sec`)
- каждые **8** страниц длинный отдых **30 ± 15 с** (`page_rest_every`)

После капчи на стр. 16: дамп сохранится частично, продолжение:
`python scrape.py --headed --start-page 17`

Результат: `output/avito_tires_YYYY-MM-DD.csv` и `.jsonl`.

## Нормализация title и сравнение с остатками

1. Остатки — **только** из двух источников (ручной `goods.xlsx` не используется):
   - Google Sheets (столбец **G** / `avito_price` — фиксированная цена Avito; **пусто** = расчётная)
   - БД `erp.shinaufa.ru` (SQL в `build_stock.py`)

   `input/goods.xlsx` — служебный кэш, перезаписывается при `build_stock.py` и перед `compare_prices.py`.

Цены выкладки округляются до **десятков** рублей.
2. Заполните `secrets.local.yaml` по примеру `secrets.local.yaml.example`.
3. После парсинга прогоните title через API словарей (`config.yaml` → `nomenclature_api`):

```bat
python normalize_avito.py
```

4. Сравнение (остатки подтянутся из Google/БД автоматически): **номенклатура** = **`name_canonical`** (1:1).

```bat
python compare_prices.py
```

Или вместе: `run_daily.bat` (scrape → normalize → build_stock → compare → autoload).

Результат: `output/posting_YYYY-MM-DD.xlsx` — листы «к выкладке», **«сопоставление»** (goods ↔ Avito), «проблемы», «свои на avito».

**Цены:** нет на Avito → входящая × 1.15; есть → min чужих − 1/2/3% (случайно), но не ниже входящая × 1.10. Свои объявления (`Шинный Центр №1`) в min не входят.

## Автозагрузка Avito (шаблон Excel)

**Старт:** скачанный с Авито xlsx в `autoload.template_file` — там уже ваши объявления.  
**Дальше:** накопленный `input/autoload_working.xlsx` (обновляется после каждого прогона).

- Номенклатура в файле = **номенклатура из goods** (наш формат).
- Поиск строки: **сначала артикул**, потом название.
- **Id** и **AvitoId** в существующих строках не перезаписываются (AvitoId — только если ячейка пустая).
- Позиций **нет в goods** → строка **удаляется** из файла (на Авито уйдёт в архив). Список: `output/autoload_removed_ДАТА.csv`.

```bat
python build_autoload.py
```

Результат: `output/autoload_YYYY-MM-DD.xlsx` и копия в `input/autoload_working.xlsx` → загрузить в ЛК → Автозагрузка.

**Фото:** папка [«Авито» на Диске](https://disk.yandex.ru/client/disk/%D0%90%D0%B2%D0%B8%D1%82%D0%BE). Перед автозагрузкой скрипт **смотрит файлы на диске** (`photos_local_dir`). **Без фото объявление не попадает.** Магазины и префиксы — **`stores.yaml`** (пример: `md103926-1.jpg` → Владислав, Менделеева). Список без фото: **`no_photos.xlsx`** на Диске. Проверка:

```bat
python check_photos.py 165935
```

Шпаргалка для телефона:

```bat
python prepare_photos.py
```

Откройте на телефоне `output/photo_upload_ДАТА.html` (поиск, кнопка «Скопировать имя»). Тот же Диск привязать в ЛК Avito → Автозагрузка.

**AvitoId:** `input/avito_ids.csv` (`артикул;avito_id`) — чтобы не создавать дубли при обновлении.

**Описания моделей:** отдельная PostgreSQL (`secrets.local.yaml` → `descriptions_db`), не ERP `alpha`.

```bat
docker compose up -d
python init_descriptions_db.py
python generate_descriptions.py --only-missing
python export_descriptions_db.py
python build_autoload.py
```

ERP (`db` в secrets) — только остатки. DeepSeek: `deepseek.api_key`. См. `secrets.local.yaml.example`.

Контакты, адрес, HTML-шаблон — в `config.yaml` → `autoload.defaults`, `autoload.description_html`.

### Поля

| Поле | Описание |
|------|----------|
| `price_per_tire` | Цена за 1 шину |
| `price_confidence` | `exact` / `inferred` / `needs_review` |
| `price_note` | Почему сомнительно |

Строки с `needs_review` оставляем для ручной проверки; на следующем этапе можно отфильтровать.

## Ежедневный запуск (Планировщик заданий Windows)

1. Планировщик заданий → Создать задачу → ежедневно, удобное время.
2. Действие: запуск программы `run_daily.bat` из этой папки.
3. Условие: только при питании от сети (по желанию).

Лог: `logs/run.log`.

## Тесты

```bat
python -m unittest discover -s tests -v
```

## Дальше

- Сопоставление с прайсами поставщиков (`csv_tool_git`)
- Фильтрация `needs_review`
- Карточка объявления для спорных цен
