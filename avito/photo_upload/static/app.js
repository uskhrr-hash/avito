(function () {
  "use strict";

  const STATIC_VERSION = "3";

  const articleInput = document.getElementById("article");
  const articleHint = document.getElementById("article-hint");
  const searchResults = document.getElementById("search-results");
  const pendingList = document.getElementById("pending-list");
  const pendingCount = document.getElementById("pending-count");
  const cameraFallback = document.getElementById("camera-fallback");
  const openCameraBtn = document.getElementById("open-camera");
  const nextShotHint = document.getElementById("next-shot-hint");
  const uploadBtn = document.getElementById("upload");
  const queueList = document.getElementById("queue-list");
  const refreshQueueBtn = document.getElementById("refresh-queue");
  const inStoreOnly = document.getElementById("in-store-only");
  const toast = document.getElementById("toast");
  const loadingEl = document.getElementById("loading");
  const loadingText = document.getElementById("loading-text");
  const cameraModal = document.getElementById("camera-modal");
  const cameraVideo = document.getElementById("camera-video");
  const cameraOverlay = document.getElementById("camera-overlay");
  const cameraTitle = document.getElementById("camera-title");
  const cameraHint = document.getElementById("camera-hint");
  const cameraExample = document.getElementById("camera-example");
  const cameraClose = document.getElementById("camera-close");
  const cameraCapture = document.getElementById("camera-capture");
  const cameraSystemBtn = document.getElementById("camera-system");
  const logoutBtn = document.getElementById("logout");
  const UPLOAD_LABEL = "Отправить на сервер";

  if (!articleInput || !uploadBtn || !queueList || !refreshQueueBtn) {
    console.error("photo upload: missing required DOM nodes");
    return;
  }

  /** @type {{id:string,index:number,filename:string,relativePath:string,blob:Blob,url:string}[]} */
  let pending = [];
  let lookupTimer = null;
  let searchTimer = null;
  let hintTimer = null;
  /** @type {MediaStream | null} */
  let cameraStream = null;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    window.setTimeout(function () {
      toast.classList.remove("show");
    }, 2800);
  }

  function setLoading(active, text) {
    if (!loadingEl) return;
    loadingEl.classList.toggle("hidden", !active);
    loadingEl.setAttribute("aria-busy", active ? "true" : "false");
    document.body.classList.toggle("is-loading", active);
    if (loadingText && text) {
      loadingText.textContent = text;
    }
  }

  function currentArticle() {
    return articleInput.value.trim();
  }

  function validArticle(article) {
    return /^\d{4,}$/.test(article);
  }

  function storePrefix() {
    const session = window.PHOTO_UPLOAD_SESSION || {};
    return session.prefix || "md";
  }

  function scheduleNextShotHint() {
    if (!nextShotHint) return;
    window.clearTimeout(hintTimer);
    hintTimer = window.setTimeout(updateNextShotHint, 200);
  }

  function renderPending() {
    if (pendingList) pendingList.innerHTML = "";
    if (pendingCount) pendingCount.textContent = String(pending.length);
    uploadBtn.disabled = pending.length === 0 || !currentArticle();
    uploadBtn.textContent = UPLOAD_LABEL;

    for (const item of pending) {
      const card = document.createElement("div");
      card.className = "pending-item";
      card.innerHTML =
        '<img alt="Превью" src="' +
        item.url +
        '"><div class="pending-meta"><strong>Фото ' +
        item.index +
        '</strong><code>' +
        item.relativePath +
        '</code><div class="pending-actions"><button type="button" class="btn btn-danger" data-id="' +
        item.id +
        '">Удалить</button></div></div>';
      pendingList.appendChild(card);
    }

    const removeButtons = pendingList.querySelectorAll("button[data-id]");
    for (let i = 0; i < removeButtons.length; i += 1) {
      removeButtons[i].addEventListener("click", function () {
        const id = removeButtons[i].getAttribute("data-id");
        const found = pending.find(function (item) {
          return item.id === id;
        });
        if (found) {
          URL.revokeObjectURL(found.url);
          pending = pending.filter(function (item) {
            return item.id !== id;
          });
          renderPending();
        }
      });
    }
    scheduleNextShotHint();
  }

  async function lookupArticle() {
    const article = currentArticle();
    if (!articleHint) return;
    if (!article) {
      articleHint.textContent = "Введите артикул шины";
      articleHint.className = "hint";
      return;
    }
    try {
      const response = await fetch(
        "api/stock/lookup?article=" + encodeURIComponent(article)
      );
      if (!response.ok) return;
      const data = await response.json();
      if (data.found) {
        articleHint.textContent =
          data.nomenclature + " · на складе: " + data.quantity;
        articleHint.className = "hint ok";
      } else {
        articleHint.textContent =
          "Артикул не найден в остатках — можно снять, но проверьте номер";
        articleHint.className = "hint warn";
      }
    } catch (_err) {
      /* ignore lookup errors */
    }
  }

  async function searchArticles() {
    if (!searchResults) return;
    const q = currentArticle();
    if (q.length < 2) {
      searchResults.classList.add("hidden");
      searchResults.innerHTML = "";
      return;
    }
    try {
      const response = await fetch("api/stock/search?q=" + encodeURIComponent(q));
      if (!response.ok) return;
      const rows = await response.json();
      if (!rows.length) {
        searchResults.classList.add("hidden");
        searchResults.innerHTML = "";
        return;
      }
      searchResults.innerHTML = "";
      for (let i = 0; i < Math.min(rows.length, 8); i += 1) {
        const row = rows[i];
        const button = document.createElement("button");
        button.type = "button";
        button.className = "pick-item";
        button.innerHTML =
          "<strong>" + row.article + "</strong><span>" + row.nomenclature + "</span>";
        button.addEventListener("click", function () {
          articleInput.value = row.article;
          searchResults.classList.add("hidden");
          lookupArticle();
          renderPending();
        });
        searchResults.appendChild(button);
      }
      searchResults.classList.remove("hidden");
    } catch (_err) {
      /* ignore search errors */
    }
  }

  async function nextIndexForArticle(article) {
    const response = await fetch(
      "api/next-index?article=" + encodeURIComponent(article)
    );
    if (!response.ok) {
      throw new Error("Не удалось получить номер фото");
    }
    return response.json();
  }

  async function resolveNextMeta(article) {
    const used = new Set(
      pending.map(function (item) {
        return item.index;
      })
    );
    let meta = await nextIndexForArticle(article);
    while (used.has(meta.index)) {
      meta.index += 1;
      meta.filename =
        meta.index === 1 ? article + ".jpg" : article + "-" + meta.index + ".jpg";
      meta.relative_path = storePrefix() + "/" + meta.filename;
    }
    return meta;
  }

  async function fetchShotGuide(index) {
    const response = await fetch(
      "api/shot-guide?index=" + encodeURIComponent(String(index))
    );
    if (!response.ok) {
      throw new Error("Не удалось загрузить подсказку кадра");
    }
    return response.json();
  }

  async function updateNextShotHint() {
    if (!nextShotHint) return;
    const article = currentArticle();
    if (!validArticle(article)) {
      nextShotHint.textContent = "Введите артикул — подскажем следующий кадр";
      return;
    }
    try {
      const meta = await resolveNextMeta(article);
      const guide = await fetchShotGuide(meta.index);
      nextShotHint.innerHTML =
        "Следующий кадр: <strong>фото " +
        meta.index +
        " — " +
        guide.title +
        "</strong>";
    } catch (_error) {
      nextShotHint.textContent = "Введите артикул и снимайте по порядку 1 → 4";
    }
  }

  async function addCapturedFile(file) {
    const article = currentArticle();
    if (!validArticle(article)) {
      showToast("Сначала введите артикул");
      return;
    }

    setLoading(true, "Подготовка снимка…");
    let meta;
    try {
      meta = await resolveNextMeta(article);
    } catch (error) {
      setLoading(false);
      showToast(String(error.message || error));
      return;
    }

    const id = String(Date.now()) + "-" + String(meta.index);
    const url = URL.createObjectURL(file);
    pending.push({
      id: id,
      index: meta.index,
      filename: meta.filename,
      relativePath: meta.relative_path,
      blob: file,
      url: url,
    });
    setLoading(false);
    renderPending();
    showToast("Добавлено: " + meta.relative_path);
  }

  function stopCameraStream() {
    if (cameraStream) {
      const tracks = cameraStream.getTracks();
      for (let i = 0; i < tracks.length; i += 1) {
        tracks[i].stop();
      }
      cameraStream = null;
    }
    if (cameraVideo) {
      cameraVideo.srcObject = null;
    }
  }

  function closeCameraModal() {
    if (!cameraModal) return;
    cameraModal.classList.add("hidden");
    cameraModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("camera-open");
    stopCameraStream();
  }

  function openSystemCamera() {
    if (cameraFallback) {
      cameraFallback.click();
      return;
    }
    showToast("Камера недоступна в этом браузере");
  }

  async function applyShotGuideToModal(index) {
    if (!cameraTitle || !cameraHint || !cameraOverlay) return;
    let guide = null;
    try {
      guide = await fetchShotGuide(index);
    } catch (_err) {
      guide = {
        title: "Фото " + index,
        hint: "Снимайте по стандарту",
        overlay_svg: "",
        example_url: "",
      };
    }
    cameraTitle.textContent = "Фото " + index;
    cameraHint.textContent = guide.hint || guide.title;
    cameraOverlay.innerHTML = guide.overlay_svg || "";
    if (cameraExample) {
      const ghost = guide.ghost_url || "";
      if (ghost) {
        cameraExample.src = ghost + (ghost.indexOf("?") >= 0 ? "&" : "?") + "v=3";
        cameraExample.classList.remove("hidden");
        cameraExample.classList.add("camera-ghost");
        if (cameraHint) {
          cameraHint.textContent = "Совместите кадр с полупрозрачным эталоном";
        }
      } else if (guide.example_url) {
        cameraExample.src = guide.example_url;
        cameraExample.classList.remove("hidden", "camera-ghost");
      } else {
        cameraExample.classList.add("hidden");
        cameraExample.classList.remove("camera-ghost");
      }
    }
  }

  async function startCameraStream() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return false;
    }
    try {
      stopCameraStream();
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
        },
        audio: false,
      });
      if (cameraVideo) {
        cameraVideo.srcObject = cameraStream;
        await cameraVideo.play();
      }
      return true;
    } catch (_error) {
      return false;
    }
  }

  async function openCameraModal() {
    const article = currentArticle();
    if (!validArticle(article)) {
      showToast("Сначала введите артикул");
      return;
    }
    if (!cameraModal) {
      openSystemCamera();
      return;
    }

    let meta;
    try {
      meta = await resolveNextMeta(article);
    } catch (error) {
      showToast(String(error.message || error));
      return;
    }

    await applyShotGuideToModal(meta.index);
    cameraModal.classList.remove("hidden");
    cameraModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("camera-open");

    const started = await startCameraStream();
    if (!started) {
      showToast("Откройте системную камеру кнопкой ниже");
    }
  }

  async function captureFromCamera() {
    if (!cameraVideo || !cameraStream) {
      openSystemCamera();
      return;
    }
    const width = cameraVideo.videoWidth || 1280;
    const height = cameraVideo.videoHeight || 720;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      showToast("Не удалось снять кадр");
      return;
    }
    ctx.drawImage(cameraVideo, 0, 0, width, height);
    const blob = await new Promise(function (resolve) {
      canvas.toBlob(resolve, "image/jpeg", 0.9);
    });
    if (!blob) {
      showToast("Не удалось сохранить кадр");
      return;
    }
    closeCameraModal();
    await addCapturedFile(blob);
  }

  if (openCameraBtn) {
    openCameraBtn.addEventListener("click", function () {
      openCameraModal();
    });
  }

  if (cameraClose) {
    cameraClose.addEventListener("click", closeCameraModal);
  }

  if (cameraCapture) {
    cameraCapture.addEventListener("click", function () {
      captureFromCamera();
    });
  }

  if (cameraSystemBtn) {
    cameraSystemBtn.addEventListener("click", function () {
      closeCameraModal();
      openSystemCamera();
    });
  }

  if (cameraFallback) {
    cameraFallback.addEventListener("change", async function () {
      const file = cameraFallback.files && cameraFallback.files[0];
      cameraFallback.value = "";
      if (!file) return;
      await addCapturedFile(file);
    });
  }

  uploadBtn.addEventListener("click", async function () {
    const article = currentArticle();
    if (!article || pending.length === 0) return;

    const count = pending.length;
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Загрузка " + count + " фото…";
    setLoading(true, "Отправка " + count + " фото на сервер…");

    const formData = new FormData();
    formData.append("article", article);
    formData.append(
      "indices",
      pending
        .map(function (item) {
          return item.index;
        })
        .join(",")
    );
    for (let i = 0; i < pending.length; i += 1) {
      formData.append("files", pending[i].blob, pending[i].filename);
    }

    try {
      const response = await fetch("api/upload", {
        method: "POST",
        body: formData,
      });
      let data = {};
      try {
        data = await response.json();
      } catch (_err) {
        data = {};
      }
      if (!response.ok) {
        throw new Error(data.detail || "Ошибка загрузки");
      }
      for (let i = 0; i < pending.length; i += 1) {
        URL.revokeObjectURL(pending[i].url);
      }
      pending = [];
      renderPending();
      uploadBtn.classList.add("upload-success");
      window.setTimeout(function () {
        uploadBtn.classList.remove("upload-success");
      }, 400);
      const savedCount =
        data.saved && data.saved.length ? data.saved.length : count;
      showToast("✓ Сохранено: " + savedCount + " фото");
      await loadQueue();
    } catch (error) {
      showToast(String(error.message || error));
      uploadBtn.disabled = false;
      uploadBtn.textContent = UPLOAD_LABEL;
    } finally {
      setLoading(false);
    }
  });

  articleInput.addEventListener("input", function () {
    window.clearTimeout(lookupTimer);
    window.clearTimeout(searchTimer);
    lookupTimer = window.setTimeout(lookupArticle, 250);
    searchTimer = window.setTimeout(searchArticles, 250);
    renderPending();
  });

  async function loadQueue() {
    queueList.innerHTML = "<p class='muted'>Загрузка списка…</p>";
    const params = new URLSearchParams({ limit: "80" });
    if (inStoreOnly && inStoreOnly.checked) {
      params.set("in_store", "1");
    }
    try {
      const response = await fetch("api/no-photos?" + params.toString());
      if (response.status === 401) {
        queueList.innerHTML =
          "<p class='muted'>Сессия истекла — обновите страницу и войдите снова</p>";
        return;
      }
      if (!response.ok) {
        queueList.innerHTML =
          "<p class='muted'>Не удалось загрузить список (ошибка " +
          response.status +
          ")</p>";
        return;
      }
      const payload = await response.json();
      const rows = Array.isArray(payload) ? payload : payload.items || [];
      const hint = payload.hint || "";

      if (!rows.length) {
        queueList.innerHTML =
          "<p class='muted'>" + (hint || "Список пуст") + "</p>";
        return;
      }

      queueList.innerHTML = "";
      if (payload.source_file) {
        const meta = document.createElement("p");
        meta.className = "queue-meta";
        let label = rows.length + " позиций · " + payload.source_file;
        if (payload.in_store_only && payload.ushk_supplier) {
          label += " · только " + payload.ushk_supplier;
        }
        meta.textContent = label;
        queueList.appendChild(meta);
      }

      for (let i = 0; i < rows.length; i += 1) {
        const row = rows[i];
        const button = document.createElement("button");
        button.type = "button";
        button.className = "queue-item";
        button.innerHTML =
          "<strong>" + row.article + "</strong><span>" + row.nomenclature + "</span>";
        button.addEventListener("click", function () {
          articleInput.value = row.article;
          if (searchResults) searchResults.classList.add("hidden");
          lookupArticle();
          renderPending();
          const cameraCard = document.querySelector(".card-camera");
          if (cameraCard && cameraCard.scrollIntoView) {
            cameraCard.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
        queueList.appendChild(button);
      }
    } catch (error) {
      queueList.innerHTML =
        "<p class='muted'>Ошибка загрузки списка: " +
        String(error.message || error) +
        "</p>";
    }
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async function () {
      closeCameraModal();
      await fetch("api/logout", { method: "POST" });
      window.location.reload();
    });
  }

  refreshQueueBtn.addEventListener("click", loadQueue);
  if (inStoreOnly) {
    inStoreOnly.addEventListener("change", loadQueue);
  }

  renderPending();
  loadQueue();
})();
