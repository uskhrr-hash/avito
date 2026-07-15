"""HTML админки фото/баллов."""
from __future__ import annotations


def render_admin_html(*, base: str) -> str:
    base_href = base if base.endswith("/") else f"{base}/"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <base href="{base_href}">
  <title>Админка — фото Avito</title>
  <link rel="stylesheet" href="static/app.css">
  <link rel="stylesheet" href="static/admin.css?v=1">
</head>
<body class="page-admin">
  <header class="topbar">
    <div>
      <div class="topbar-title">Админка</div>
      <div class="topbar-sub" id="admin-sub">Сотрудники · баллы · фото</div>
    </div>
    <div class="topbar-actions">
      <a href="./" class="topbar-guide">Загрузка</a>
      <button type="button" id="logout" class="btn btn-ghost">Выйти</button>
    </div>
  </header>

  <nav class="admin-tabs" role="tablist">
    <button type="button" class="admin-tab active" data-tab="users">Сотрудники</button>
    <button type="button" class="admin-tab" data-tab="points">Баллы</button>
    <button type="button" class="admin-tab" data-tab="photos">Фото</button>
  </nav>

  <main class="shell">
    <section id="tab-users" class="admin-panel">
      <div class="card">
        <h2>Новый сотрудник</h2>
        <form id="create-user-form" class="admin-form">
          <label class="field"><span>Логин</span>
            <input name="login" required autocomplete="off" placeholder="ivan">
          </label>
          <label class="field"><span>Имя</span>
            <input name="display_name" placeholder="Иван">
          </label>
          <label class="field"><span>Пароль</span>
            <input name="password" type="password" required minlength="4">
          </label>
          <button type="submit" class="btn btn-primary">Создать</button>
        </form>
        <p id="create-user-msg" class="muted"></p>
      </div>
      <div class="card">
        <h2>Список</h2>
        <div id="users-list" class="admin-list"></div>
      </div>
    </section>

    <section id="tab-points" class="admin-panel hidden">
      <div class="card">
        <h2>Балансы</h2>
        <div id="balances-list" class="admin-list"></div>
      </div>
      <div class="card">
        <h2>Списать баллы</h2>
        <form id="deduct-form" class="admin-form">
          <label class="field"><span>Сотрудник (id)</span>
            <input name="user_id" type="number" required min="1">
          </label>
          <label class="field"><span>Сколько списать</span>
            <input name="amount" type="number" required min="1">
          </label>
          <label class="field"><span>Комментарий</span>
            <input name="reason" placeholder="Выплата / подарок">
          </label>
          <button type="submit" class="btn btn-primary">Списать</button>
        </form>
        <p id="deduct-msg" class="muted"></p>
      </div>
      <div class="card">
        <h2>История</h2>
        <div id="ledger-list" class="admin-list"></div>
      </div>
    </section>

    <section id="tab-photos" class="admin-panel hidden">
      <div class="card">
        <h2>Файлы на сервере</h2>
        <form id="photos-filter" class="admin-form row-form">
          <label class="field"><span>Папка</span>
            <select name="folder">
              <option value="">все</option>
              <option value="contributors">contributors</option>
              <option value="md">md</option>
              <option value="pg">pg</option>
            </select>
          </label>
          <label class="field"><span>Артикул</span>
            <input name="article" inputmode="numeric" placeholder="122062">
          </label>
          <button type="submit" class="btn btn-secondary">Найти</button>
        </form>
        <div id="photos-list" class="admin-list"></div>
      </div>
    </section>
  </main>
  <div id="toast" class="toast"></div>
  <script src="static/admin.js?v=1"></script>
</body>
</html>"""
