(function () {
  const articleInput = document.getElementById("article");
  const articleHint = document.getElementById("article-hint");
  const searchResults = document.getElementById("search-results");
  const pendingList = document.getElementById("pending-list");
  const pendingCount = document.getElementById("pending-count");
  const cameraInput = document.getElementById("camera");
  const uploadBtn = document.getElementById("upload");
  const queueList = document.getElementById("queue-list");
  const refreshQueueBtn = document.getElementById("refresh-queue");
  const toast = document.getElementById("toast");

  /** @type {{id:string,index:number,filename:string,relativePath:string,blob:Blob,url:string}[]} */
  let pending = [];
  let lookupTimer = null;
  let searchTimer = null;

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    window.setTimeout(() => toast.classList.remove("show"), 2200);
  }

  function currentArticle() {
    return articleInput.value.trim();
  }

  function renderPending() {
    pendingList.innerHTML = "";
    pendingCount.textContent = String(pending.length);
    uploadBtn.disabled = pending.length === 0 || !currentArticle();

    for (const item of pending) {
      const card = document.createElement("div");
      card.className = "pending-item";
      card.innerHTML = `
        <img alt="Превью" src="${item.url}">
        <div class="pending-meta">
          <strong>Фото ${item.index}</strong>
          <code>${item.relativePath}</code>
          <div class="pending-actions">
            <button type="button" class="btn btn-danger" data-id="${item.id}">Удалить</button>
          </div>
        </div>
      `;
      pendingList.appendChild(card);
    }

    pendingList.querySelectorAll("button[data-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.getAttribute("data-id");
        const found = pending.find((item) => item.id === id);
        if (found) {
          URL.revokeObjectURL(found.url);
          pending = pending.filter((item) => item.id !== id);
          renderPending();
        }
      });
    });
  }

  async function lookupArticle() {
    const article = currentArticle();
    if (!article) {
      articleHint.textContent = "Введите артикул шины";
      articleHint.className = "hint";
      return;
    }
    const response = await fetch(`api/stock/lookup?article=${encodeURIComponent(article)}`);
    if (!response.ok) return;
    const data = await response.json();
    if (data.found) {
      articleHint.textContent = `${data.nomenclature} · на складе: ${data.quantity}`;
      articleHint.className = "hint ok";
    } else {
      articleHint.textContent = "Артикул не найден в остатках — можно снять, но проверьте номер";
      articleHint.className = "hint warn";
    }
  }

  async function searchArticles() {
    const q = currentArticle();
    if (q.length < 2) {
      searchResults.classList.add("hidden");
      searchResults.innerHTML = "";
      return;
    }
    const response = await fetch(`api/stock/search?q=${encodeURIComponent(q)}`);
    if (!response.ok) return;
    const rows = await response.json();
    if (!rows.length) {
      searchResults.classList.add("hidden");
      searchResults.innerHTML = "";
      return;
    }
    searchResults.innerHTML = "";
    for (const row of rows.slice(0, 8)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pick-item";
      button.innerHTML = `<strong>${row.article}</strong><span>${row.nomenclature}</span>`;
      button.addEventListener("click", () => {
        articleInput.value = row.article;
        searchResults.classList.add("hidden");
        lookupArticle();
        renderPending();
      });
      searchResults.appendChild(button);
    }
    searchResults.classList.remove("hidden");
  }

  async function nextIndexForArticle(article) {
    const response = await fetch(`api/next-index?article=${encodeURIComponent(article)}`);
    if (!response.ok) {
      throw new Error("Не удалось получить номер фото");
    }
    return response.json();
  }

  cameraInput.addEventListener("change", async () => {
    const file = cameraInput.files && cameraInput.files[0];
    cameraInput.value = "";
    if (!file) return;

    const article = currentArticle();
    if (!/^\d{4,}$/.test(article)) {
      showToast("Сначала введите артикул");
      return;
    }

    const used = new Set(pending.map((item) => item.index));
    let meta;
    try {
      meta = await nextIndexForArticle(article);
      while (used.has(meta.index)) {
        meta.index += 1;
        meta.filename = meta.index === 1 ? `${article}.jpg` : `${article}-${meta.index}.jpg`;
        meta.relative_path = `${window.PHOTO_UPLOAD_SESSION.prefix}/${meta.filename}`;
      }
    } catch (error) {
      showToast(String(error.message || error));
      return;
    }

    const id = `${Date.now()}-${meta.index}`;
    const url = URL.createObjectURL(file);
    pending.push({
      id,
      index: meta.index,
      filename: meta.filename,
      relativePath: meta.relative_path,
      blob: file,
      url,
    });
    renderPending();
    showToast(`Добавлено: ${meta.relative_path}`);
  });

  uploadBtn.addEventListener("click", async () => {
    const article = currentArticle();
    if (!article || pending.length === 0) return;

    uploadBtn.disabled = true;
    const formData = new FormData();
    formData.append("article", article);
    formData.append("indices", pending.map((item) => item.index).join(","));
    for (const item of pending) {
      formData.append("files", item.blob, item.filename);
    }

    try {
      const response = await fetch("api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Ошибка загрузки");
      }
      for (const item of pending) {
        URL.revokeObjectURL(item.url);
      }
      pending = [];
      renderPending();
      showToast(`Сохранено: ${data.saved.length} фото`);
      await loadQueue();
    } catch (error) {
      showToast(String(error.message || error));
      uploadBtn.disabled = false;
    }
  });

  articleInput.addEventListener("input", () => {
    window.clearTimeout(lookupTimer);
    window.clearTimeout(searchTimer);
    lookupTimer = window.setTimeout(lookupArticle, 250);
    searchTimer = window.setTimeout(searchArticles, 250);
    renderPending();
  });

  async function loadQueue() {
    queueList.innerHTML = "<p class='muted'>Загрузка…</p>";
    const response = await fetch("api/no-photos?limit=80");
    if (!response.ok) {
      queueList.innerHTML = "<p class='muted'>Не удалось загрузить список</p>";
      return;
    }
    const rows = await response.json();
    if (!rows.length) {
      queueList.innerHTML = "<p class='muted'>Список пуст или файл ещё не собран</p>";
      return;
    }
    queueList.innerHTML = "";
    for (const row of rows) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "queue-item";
      button.innerHTML = `<strong>${row.article}</strong><span>${row.nomenclature}</span>`;
      button.addEventListener("click", () => {
        articleInput.value = row.article;
        searchResults.classList.add("hidden");
        lookupArticle();
        renderPending();
        document.querySelector(".card-camera")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      queueList.appendChild(button);
    }
  }

  document.getElementById("logout").addEventListener("click", async () => {
    await fetch("api/logout", { method: "POST" });
    window.location.reload();
  });

  refreshQueueBtn.addEventListener("click", loadQueue);

  renderPending();
  loadQueue();
})();
