Файл остатков: goods.xlsx

Без строки заголовков, порядок колонок:
  0 — артикул
  1 — номенклатура (1 в 1 как title на Avito)
  2 — количество
  3 — цена (входящая)

Настройки в config.yaml → compare.

Запуск: python compare_prices.py

Шаблон автозагрузки Avito:
  432801655_2026-05-29T09_58_00Z.xlsx
  (вкладка 1 — инструкция, вкладка 2 — шаблон, вкладка 3 — справочник)

Фото на Яндекс.Диске:
  https://disk.yandex.ru/client/disk/Авито

  С телефона — в одну папку «Авито», без подпапок:
    165935.jpeg
    165935-2.jpeg   (см. image_ext в config.yaml)

  Расширение: webp (или как в config.yaml → image_ext). HEIC лучше не использовать.

  Шпаргалка: python prepare_photos.py
  → output/photo_upload_ДАТА.html (открыть в браузере телефона)

Опционально: avito_ids.csv — артикул;avito_id для обновления без дублей

python build_autoload.py  →  output/autoload_YYYY-MM-DD.xlsx
