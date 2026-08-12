# Wheels (Avito) — deploy notes
#
# Restored on /opt/avito_tires_parser/ (2026-08-12):
#   stock + listings + photo UI tabs Шины/Диски
#   photos under /opt/avito_tires_photos/wheels/{md,pg}/
#   shinaufa hotlink: images/large/tyres + images/large/wheels
#   Backup: /opt/avito_tires_parser/_bak_wheels_restore_20260812_113840/
#
# Keep: wheels.include_in_publish: false
# Pilot: wheels.publish_ids: [md_…] — only those wheels enter live XML (tires full)
# Keep: avito_sync.photo_updates_diff_only: false (full XML feed)
# Secrets: port 5431, register_via: postgres
#
# Photo UI: https://avito.shinaufa.ru/photo/ → tabs Шины / Диски
# Leftover before full publish: clear publish_ids only when ready for all wheels,
# then flip include_in_publish. Never upload wheels-only / delta-only XML.
#
# 2026-08-12 pilot: md_105464, md_105462, md_10344, md_104331, md_105473
# merge fix: write_listing_feeds brand/model check accepts RimBrand/RimModel
