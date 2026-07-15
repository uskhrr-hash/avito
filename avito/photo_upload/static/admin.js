(function () {
  "use strict";

  const toast = document.getElementById("toast");
  const usersList = document.getElementById("users-list");
  const balancesList = document.getElementById("balances-list");
  const ledgerList = document.getElementById("ledger-list");
  const photosList = document.getElementById("photos-list");
  const createForm = document.getElementById("create-user-form");
  const createMsg = document.getElementById("create-user-msg");
  const deductForm = document.getElementById("deduct-form");
  const deductMsg = document.getElementById("deduct-msg");
  const photosFilter = document.getElementById("photos-filter");
  const logoutBtn = document.getElementById("logout");
  const createShopSelect = document.getElementById("create-shop-select");
  const editShopSelect = document.getElementById("edit-shop-select");
  const shopDialog = document.getElementById("shop-dialog");
  const shopDialogForm = document.getElementById("shop-dialog-form");
  const shopDialogTitle = document.getElementById("shop-dialog-title");

  let knownShops = [];
  let editShopUserId = null;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    window.setTimeout(function () {
      toast.classList.remove("show");
    }, 2200);
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      throw new Error(data.detail || data.message || "Ошибка " + response.status);
    }
    return data;
  }

  function fillShopSelect(select, selected, placeholder) {
    if (!select) return;
    const current = selected || "";
    select.innerHTML = "";
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder || "Выберите магазин";
    select.appendChild(empty);
    knownShops.forEach(function (name) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === current) opt.selected = true;
      select.appendChild(opt);
    });
    if (current && knownShops.indexOf(current) === -1) {
      const opt = document.createElement("option");
      opt.value = current;
      opt.textContent = current + " (текущий)";
      opt.selected = true;
      select.appendChild(opt);
    }
  }

  document.querySelectorAll(".admin-tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      const id = tab.getAttribute("data-tab");
      document.querySelectorAll(".admin-tab").forEach(function (t) {
        t.classList.toggle("active", t === tab);
      });
      document.querySelectorAll(".admin-panel").forEach(function (panel) {
        panel.classList.toggle("hidden", panel.id !== "tab-" + id);
      });
      if (id === "users") loadUsers();
      if (id === "points") {
        loadBalances();
        loadLedger();
      }
      if (id === "photos") loadPhotos();
    });
  });

  async function loadShops() {
    if (createShopSelect) {
      createShopSelect.innerHTML = "";
      const loading = document.createElement("option");
      loading.value = "";
      loading.textContent = "Загрузка списка…";
      createShopSelect.appendChild(loading);
      createShopSelect.disabled = true;
    }
    try {
      const data = await api("api/admin/shops");
      knownShops = data.shops || [];
      fillShopSelect(createShopSelect, "", "Выберите магазин");
      if (createShopSelect) createShopSelect.disabled = knownShops.length === 0;
      if (!knownShops.length && createShopSelect) {
        createShopSelect.options[0].textContent = "Список складов пуст";
      }
    } catch (err) {
      knownShops = [];
      if (createShopSelect) {
        createShopSelect.disabled = true;
        createShopSelect.innerHTML = "";
        const fail = document.createElement("option");
        fail.value = "";
        fail.textContent = "Не удалось загрузить магазины";
        createShopSelect.appendChild(fail);
      }
      showToast(String(err.message || err));
    }
  }

  async function loadUsers() {
    if (!usersList) return;
    usersList.textContent = "Загрузка…";
    try {
      const data = await api("api/admin/users");
      usersList.innerHTML = "";
      if (!data.users || !data.users.length) {
        usersList.textContent = "Пока нет сотрудников";
        return;
      }
      data.users.forEach(function (u) {
        const row = document.createElement("div");
        row.className = "admin-row" + (u.active ? "" : " inactive");
        const shopLabel =
          u.role === "contributor"
            ? u.ushk_supplier || "магазин не назначен"
            : "—";
        row.innerHTML =
          "<div><strong>" +
          u.login +
          "</strong> · " +
          (u.display_name || "—") +
          '<div class="meta">id ' +
          u.id +
          " · " +
          u.role +
          " · " +
          shopLabel +
          (u.active ? "" : " · выкл") +
          "</div></div>";
        const actions = document.createElement("div");
        actions.className = "actions";
        if (u.role === "contributor") {
          const shopBtn = document.createElement("button");
          shopBtn.type = "button";
          shopBtn.className = "btn btn-secondary";
          shopBtn.textContent = "Магазин";
          shopBtn.addEventListener("click", function () {
            if (!shopDialog || !editShopSelect) return;
            if (!knownShops.length) {
              showToast("Список магазинов ещё не загружен");
              return;
            }
            editShopUserId = u.id;
            if (shopDialogTitle) {
              shopDialogTitle.textContent =
                "Магазин: " + (u.display_name || u.login);
            }
            fillShopSelect(editShopSelect, u.ushk_supplier || "", "Выберите магазин");
            shopDialog.showModal();
          });
          actions.appendChild(shopBtn);
          const toggle = document.createElement("button");
          toggle.type = "button";
          toggle.className = "btn btn-ghost";
          toggle.textContent = u.active ? "Выкл" : "Вкл";
          toggle.addEventListener("click", async function () {
            try {
              await api("api/admin/users/" + u.id + "/active", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ active: !u.active }),
              });
              showToast(u.active ? "Отключён" : "Включён");
              loadUsers();
            } catch (err) {
              showToast(String(err.message || err));
            }
          });
          actions.appendChild(toggle);
          const reset = document.createElement("button");
          reset.type = "button";
          reset.className = "btn btn-secondary";
          reset.textContent = "Пароль";
          reset.addEventListener("click", async function () {
            const pwd = window.prompt("Новый пароль для " + u.login);
            if (!pwd) return;
            try {
              await api("api/admin/users/" + u.id + "/password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password: pwd }),
              });
              showToast("Пароль обновлён");
            } catch (err) {
              showToast(String(err.message || err));
            }
          });
          actions.appendChild(reset);
        }
        row.appendChild(actions);
        usersList.appendChild(row);
      });
    } catch (err) {
      usersList.textContent = String(err.message || err);
    }
  }

  if (shopDialogForm) {
    shopDialogForm.addEventListener("submit", async function (event) {
      const submitter = event.submitter;
      const value = submitter ? submitter.value : "cancel";
      if (value !== "ok") {
        editShopUserId = null;
        return;
      }
      event.preventDefault();
      if (!editShopUserId || !editShopSelect) return;
      const shop = String(editShopSelect.value || "").trim();
      if (!shop) {
        showToast("Выберите магазин");
        return;
      }
      try {
        await api("api/admin/users/" + editShopUserId + "/shop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ushk_supplier: shop }),
        });
        if (shopDialog) shopDialog.close();
        editShopUserId = null;
        showToast("Магазин обновлён");
        loadUsers();
      } catch (err) {
        showToast(String(err.message || err));
      }
    });
  }

  if (createForm) {
    createForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (createMsg) createMsg.textContent = "";
      const fd = new FormData(createForm);
      const shop = String(fd.get("ushk_supplier") || "").trim();
      if (!shop) {
        if (createMsg) createMsg.textContent = "Выберите магазин из списка";
        return;
      }
      try {
        await api("api/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            login: fd.get("login"),
            password: fd.get("password"),
            display_name: fd.get("display_name") || "",
            ushk_supplier: shop,
            role: "contributor",
          }),
        });
        createForm.reset();
        fillShopSelect(createShopSelect, "", "Выберите магазин");
        if (createMsg) createMsg.textContent = "Создан";
        showToast("Сотрудник создан");
        loadUsers();
      } catch (err) {
        if (createMsg) createMsg.textContent = String(err.message || err);
      }
    });
  }

  async function loadBalances() {
    if (!balancesList) return;
    balancesList.textContent = "Загрузка…";
    try {
      const data = await api("api/admin/balances");
      balancesList.innerHTML = "";
      (data.items || []).forEach(function (u) {
        const row = document.createElement("div");
        row.className = "admin-row";
        row.innerHTML =
          "<div><strong>" +
          u.login +
          "</strong> · id " +
          u.id +
          '<div class="meta">' +
          (u.display_name || "") +
          (u.ushk_supplier ? " · " + u.ushk_supplier : "") +
          "</div></div>" +
          "<div><strong>" +
          u.balance +
          "</strong> б.</div>";
        balancesList.appendChild(row);
      });
      if (!data.items || !data.items.length) {
        balancesList.textContent = "Нет сотрудников";
      }
    } catch (err) {
      balancesList.textContent = String(err.message || err);
    }
  }

  async function loadLedger() {
    if (!ledgerList) return;
    ledgerList.textContent = "Загрузка…";
    try {
      const data = await api("api/admin/ledger?limit=50");
      ledgerList.innerHTML = "";
      (data.items || []).forEach(function (e) {
        const row = document.createElement("div");
        row.className = "admin-row";
        const cls = e.delta >= 0 ? "points-pos" : "points-neg";
        row.innerHTML =
          "<div><strong>" +
          e.login +
          "</strong>" +
          '<div class="meta">' +
          e.created_at +
          " · " +
          (e.reason || "") +
          (e.article ? " · арт. " + e.article : "") +
          "</div></div>" +
          '<div class="' +
          cls +
          '">' +
          (e.delta > 0 ? "+" : "") +
          e.delta +
          "</div>";
        ledgerList.appendChild(row);
      });
    } catch (err) {
      ledgerList.textContent = String(err.message || err);
    }
  }

  if (deductForm) {
    deductForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (deductMsg) deductMsg.textContent = "";
      const fd = new FormData(deductForm);
      try {
        const data = await api("api/admin/points/deduct", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: Number(fd.get("user_id")),
            amount: Number(fd.get("amount")),
            reason: fd.get("reason") || "",
          }),
        });
        if (deductMsg) {
          deductMsg.textContent = "Баланс теперь: " + data.balance;
        }
        showToast("Списано");
        loadBalances();
        loadLedger();
      } catch (err) {
        if (deductMsg) deductMsg.textContent = String(err.message || err);
      }
    });
  }

  async function loadPhotos() {
    if (!photosList || !photosFilter) return;
    photosList.textContent = "Загрузка…";
    const fd = new FormData(photosFilter);
    const q =
      "folder=" +
      encodeURIComponent(String(fd.get("folder") || "")) +
      "&article=" +
      encodeURIComponent(String(fd.get("article") || ""));
    try {
      const data = await api("api/admin/photos?" + q);
      photosList.innerHTML = "";
      if (!data.items || !data.items.length) {
        photosList.textContent = "Ничего не найдено";
        return;
      }
      data.items.forEach(function (f) {
        const row = document.createElement("div");
        row.className = "admin-row";
        const left = document.createElement("div");
        left.style.display = "flex";
        left.style.gap = "10px";
        left.style.alignItems = "center";
        const img = document.createElement("img");
        img.className = "admin-thumb";
        img.src = "/photos/" + f.relative_path;
        img.alt = f.filename;
        left.appendChild(img);
        const text = document.createElement("div");
        text.innerHTML =
          "<strong>" +
          f.relative_path +
          "</strong>" +
          '<div class="meta">' +
          Math.round(f.size / 1024) +
          " КБ</div>";
        left.appendChild(text);
        row.appendChild(left);
        const del = document.createElement("button");
        del.type = "button";
        del.className = "btn btn-ghost";
        del.textContent = "Удалить";
        del.addEventListener("click", async function () {
          if (!window.confirm("Удалить " + f.relative_path + "?")) return;
          try {
            await api("api/admin/photos/delete", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ relative_path: f.relative_path }),
            });
            showToast("Удалено");
            loadPhotos();
          } catch (err) {
            showToast(String(err.message || err));
          }
        });
        row.appendChild(del);
        photosList.appendChild(row);
      });
    } catch (err) {
      photosList.textContent = String(err.message || err);
    }
  }

  if (photosFilter) {
    photosFilter.addEventListener("submit", function (event) {
      event.preventDefault();
      loadPhotos();
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async function () {
      await fetch("api/logout", { method: "POST" });
      window.location.href = "./";
    });
  }

  loadShops();
  loadUsers();
})();
