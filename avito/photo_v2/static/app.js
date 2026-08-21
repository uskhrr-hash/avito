/* Photo v2 S3.2 — login + upload + camera + picker + article check / Файлы + delete. */
(function () {
  const LOGIN_MS = 8000;
  const ME_MS = 5000;
  const LOGOUT_MS = 5000;
  const LOOKUP_MS = 10000;
  const ARTICLES_MS = 12000;
  const LISTINGS_MS = 15000;
  const PHOTOS_MS = 15000;
  const DELETE_MS = 15000;
  const UPLOAD_MS = 120000;
  const LOOKUP_DEBOUNCE_MS = 350;
  const SEARCH_DEBOUNCE_MS = 320;
  const SEARCH_MIN_CHARS = 2;
  const ARTICLES_LIMIT = 40;
  const LISTINGS_LIMIT = 10;
  const CHECK_THUMBS_LIMIT = 6;
  const PHOTOS_LIMIT = 40;
  const CACHE_TTL_MS = 50000;
  const THUMB_MAX = 3;
  const UPLOAD_LABEL = "Отправить на сервер";
  const KIND_KEY = "photo_v2_kind";

  const form = document.getElementById("login-form");
  const home = document.getElementById("home");
  const err = document.getElementById("err");
  const who = document.getElementById("who");
  const subtitle = document.getElementById("subtitle");
  const submit = document.getElementById("submit");
  const logoutBtn = document.getElementById("logout");
  const articleInput = document.getElementById("article");
  const lookupHint = document.getElementById("lookup-hint");
  const pickBtn = document.getElementById("pick-articles");
  const pickerEl = document.getElementById("article-picker");
  const articleList = document.getElementById("article-list");
  const articleMore = document.getElementById("article-more");
  const pickerHint = document.getElementById("article-picker-hint");
  const filesInput = document.getElementById("files");
  const filesGallery = document.getElementById("files-gallery");
  const pendingEl = document.getElementById("pending");
  const uploadBtn = document.getElementById("upload");
  const progressEl = document.getElementById("progress");
  const savedEl = document.getElementById("saved");
  const kindTire = document.getElementById("kind-tire");
  const kindWheel = document.getElementById("kind-wheel");

  const tabUpload = document.getElementById("tab-upload");
  const tabListings = document.getElementById("tab-listings");
  const tabPhotos = document.getElementById("tab-photos");
  const panelUpload = document.getElementById("panel-upload");
  const panelListings = document.getElementById("panel-listings");
  const panelPhotos = document.getElementById("panel-photos");
  const listingsArticle = document.getElementById("listings-article");
  const listingsCheck = document.getElementById("listings-check");
  const listingsCard = document.getElementById("listings-card");
  const listingsHint = document.getElementById("listings-hint");
  const photosList = document.getElementById("photos-list");
  const photosMore = document.getElementById("photos-more");
  const photosHint = document.getElementById("photos-hint");
  const photosArticle = document.getElementById("photos-article");
  const photosFolder = document.getElementById("photos-folder");
  const photosApply = document.getElementById("photos-apply");

  let kind = "tire";
  let lookup = null;
  let lookupTimer = null;
  let lookupSeq = 0;
  let pending = [];
  let nextId = 1;

  /** @type {Map<string, {expires:number, data:*, etag:string}>} */
  const jsonCache = new Map();
  /** @type {Map<string, Promise<*>>} */
  const jsonInFlight = new Map();
  /** @type {Map<string, AbortController>} */
  const abortByKey = new Map();

  let searchTimer = null;
  let pickerMode = null; // "search" | "need_photos" | null
  let pickerOffset = 0;
  let pickerHasMore = false;
  let pickerQuery = "";
  let pickerSeq = 0;
  let pickOpen = false;

  let activeTab = "upload";
  let listingsSeq = 0;
  let listingsBusy = false;

  let photosOffset = 0;
  let photosHasMore = false;
  let photosSeq = 0;
  let photosLoaded = false;
  let photosFilterArticle = "";
  let photosFilterFolder = "";
  let storePrefix = "";
  let deletingPath = "";

  try {
    const saved = localStorage.getItem(KIND_KEY);
    if (saved === "wheel" || saved === "tire") kind = saved;
  } catch (_) {}

  function showErr(msg) {
    err.hidden = !msg;
    err.textContent = msg || "";
  }

  function abortKey(key) {
    const prev = abortByKey.get(key);
    if (prev) {
      try {
        prev.abort();
      } catch (_) {}
    }
    const ctrl = new AbortController();
    abortByKey.set(key, ctrl);
    return ctrl;
  }

  function clearAbortKey(key) {
    abortByKey.delete(key);
  }

  function abortTabFetches() {
    ["listings", "photos"].forEach((key) => {
      const prev = abortByKey.get(key);
      if (prev) {
        try {
          prev.abort();
        } catch (_) {}
        abortByKey.delete(key);
      }
    });
  }

  async function api(path, opts, timeoutMs, abortKeyName) {
    const ctrl = abortKeyName
      ? abortKey(abortKeyName)
      : new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(path, {
        credentials: "same-origin",
        cache: "no-store",
        signal: ctrl.signal,
        ...opts,
      });
      let body = null;
      const text = await res.text();
      if (text) {
        try {
          body = JSON.parse(text);
        } catch (_) {
          body = { detail: text.slice(0, 200) };
        }
      }
      return { res, body };
    } finally {
      clearTimeout(t);
      if (abortKeyName) clearAbortKey(abortKeyName);
    }
  }

  function detail(body) {
    if (!body) return "Ошибка";
    if (typeof body.detail === "string") return body.detail;
    return "Ошибка запроса";
  }

  function shopLabel(me) {
    return (me && (me.label || me.store)) || "магазин";
  }

  function lockPhotosFolder(prefix) {
    storePrefix = String(prefix || "").trim();
    photosFilterFolder = storePrefix;
    if (!photosFolder) return;
    photosFolder.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = storePrefix;
    opt.textContent = storePrefix || "—";
    photosFolder.appendChild(opt);
    photosFolder.value = storePrefix;
    photosFolder.disabled = true;
  }

  function invalidatePhotosCache() {
    const keys = Array.from(jsonCache.keys());
    for (const key of keys) {
      if (String(key).indexOf("api/photos?") === 0) jsonCache.delete(key);
    }
  }

  function isMobileUploadClient() {
    const ua = String(navigator.userAgent || "");
    if (/iPhone|iPod|iPad|Android/i.test(ua)) return true;
    if (/Mobile/i.test(ua) && !/Windows NT/i.test(ua)) return true;
    return false;
  }

  function uploadConcurrency() {
    return isMobileUploadClient() ? 1 : 2;
  }

  function currentArticle() {
    return String(articleInput.value || "").trim();
  }

  function syncKindButtons() {
    kindTire.classList.toggle("active", kind === "tire");
    kindWheel.classList.toggle("active", kind === "wheel");
  }

  function setKind(next) {
    kind = next === "wheel" ? "wheel" : "tire";
    try {
      localStorage.setItem(KIND_KEY, kind);
    } catch (_) {}
    syncKindButtons();
    clearPending();
    closePicker();
    scheduleLookup();
  }

  function clearPending() {
    for (const item of pending) {
      if (item.url) URL.revokeObjectURL(item.url);
    }
    pending = [];
    renderPending();
    savedEl.innerHTML = "";
  }

  function setProgress(text) {
    if (!text) {
      progressEl.hidden = true;
      progressEl.textContent = "";
      return;
    }
    progressEl.hidden = false;
    progressEl.textContent = text;
  }

  let uploading = false;

  function updateUploadEnabled() {
    uploadBtn.disabled = uploading;
    const blocked = !uploading && !!uploadBlockedReason();
    uploadBtn.classList.toggle("is-blocked", blocked);
    uploadBtn.setAttribute("aria-disabled", blocked ? "true" : "false");
  }

  function uploadBlockedReason() {
    if (!currentArticle()) return "Сначала укажите артикул";
    if (!lookup) return "Дождитесь проверки артикула (или исправьте номер)";
    if (pending.length === 0) return "Сначала сделайте или выберите фото";
    return "";
  }

  function looksLikeImageFile(file) {
    if (!file) return false;
    const type = String(file.type || "").toLowerCase();
    if (type.indexOf("image/") === 0) return true;
    // Mobile Safari/Android sometimes omit MIME; accept by extension / empty type.
    const name = String(file.name || "").toLowerCase();
    if (/\.(jpe?g|png|gif|webp|heic|heif|bmp|tif{1,2})$/i.test(name)) return true;
    if (!type && file.size > 0) return true;
    return false;
  }

  function renderPending() {
    pendingEl.innerHTML = "";
    for (const item of pending) {
      const li = document.createElement("li");
      li.className = "pending-item";
      const thumb = document.createElement("img");
      thumb.src = item.url;
      thumb.alt = "";
      const meta = document.createElement("div");
      meta.className = "pending-meta";
      meta.innerHTML =
        "<strong>#" +
        item.index +
        "</strong> <span>" +
        item.filename +
        "</span>";
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "secondary pending-rm";
      rm.textContent = "×";
      rm.addEventListener("click", () => {
        pending = pending.filter((p) => p.id !== item.id);
        URL.revokeObjectURL(item.url);
        renderPending();
      });
      li.appendChild(thumb);
      li.appendChild(meta);
      li.appendChild(rm);
      pendingEl.appendChild(li);
    }
    updateUploadEnabled();
    if (!uploadBtn.disabled) {
      uploadBtn.textContent = UPLOAD_LABEL;
    }
  }

  function assignIndicesFromLookup() {
    if (!lookup) return;
    let idx = lookup.next_index;
    const used = new Set();
    for (const item of pending) {
      while (used.has(idx)) idx += 1;
      item.index = idx;
      item.filename =
        idx === 1
          ? lookup.article + ".jpg"
          : lookup.article + "-" + idx + ".jpg";
      used.add(idx);
      idx += 1;
    }
  }

  async function runLookup() {
    const article = currentArticle();
    const seq = ++lookupSeq;
    if (!article) {
      lookup = null;
      lookupHint.textContent = "Введите артикул или подберите без фото";
      lookupHint.className = "hint";
      updateUploadEnabled();
      return;
    }
    lookupHint.textContent = "Проверка…";
    lookupHint.className = "hint";
    try {
      const { res, body } = await api(
        "api/lookup?article=" +
          encodeURIComponent(article) +
          "&kind=" +
          encodeURIComponent(kind),
        { method: "GET" },
        LOOKUP_MS
      );
      if (seq !== lookupSeq) return;
      if (!res.ok) {
        lookup = null;
        lookupHint.textContent = detail(body);
        lookupHint.className = "hint warn";
        updateUploadEnabled();
        return;
      }
      lookup = body;
      if (body.found) {
        lookupHint.textContent =
          (body.nomenclature || body.article) +
          " · склад: " +
          (body.quantity || "—") +
          " · слот #" +
          body.next_index +
          (body.folder ? " · " + body.folder : "");
        lookupHint.className = "hint ok";
      } else {
        lookupHint.textContent =
          "Нет в остатках — можно грузить, проверьте номер · слот #" +
          body.next_index;
        lookupHint.className = "hint warn";
      }
      assignIndicesFromLookup();
      renderPending();
    } catch (ex) {
      if (seq !== lookupSeq) return;
      lookup = null;
      lookupHint.textContent =
        ex.name === "AbortError" ? "Таймаут проверки" : "Сеть недоступна";
      lookupHint.className = "hint warn";
      updateUploadEnabled();
    }
  }

  function scheduleLookup() {
    window.clearTimeout(lookupTimer);
    lookupTimer = window.setTimeout(runLookup, LOOKUP_DEBOUNCE_MS);
  }

  function articlesUrl(params) {
    const p = new URLSearchParams();
    p.set("kind", kind);
    p.set("limit", String(ARTICLES_LIMIT));
    p.set("offset", String(params.offset || 0));
    if (params.needPhotos) {
      p.set("need_photos", "1");
    } else if (params.q) {
      p.set("q", params.q);
    }
    return "api/articles?" + p.toString();
  }

  function readEtag(res) {
    return (
      (res && res.headers && (res.headers.get("ETag") || res.headers.get("etag"))) ||
      ""
    );
  }

  /**
   * Memory TTL 50s + single-flight + If-None-Match after expiry.
   * fetch cache:"no-store" so browser cache cannot hide 304.
   */
  async function fetchJsonCached(url, timeoutMs, abortKeyName) {
    const now = Date.now();
    const cached = jsonCache.get(url);
    if (cached && cached.expires > now && cached.data) {
      return cached.data;
    }
    const flying = jsonInFlight.get(url);
    if (flying) return flying;

    const job = (async () => {
      const headers = {};
      if (cached && cached.etag) {
        headers["If-None-Match"] = cached.etag;
      }
      const { res, body } = await api(
        url,
        { method: "GET", headers: headers },
        timeoutMs,
        abortKeyName
      );
      const etag = readEtag(res);
      if (res.status === 304 && cached && cached.data) {
        const fresh = {
          expires: now + CACHE_TTL_MS,
          data: cached.data,
          etag: etag || cached.etag || "",
        };
        jsonCache.set(url, fresh);
        return fresh.data;
      }
      if (!res.ok) {
        throw new Error(detail(body));
      }
      const data = body || { items: [], has_more: false };
      jsonCache.set(url, {
        expires: now + CACHE_TTL_MS,
        data: data,
        etag: etag,
      });
      return data;
    })();

    jsonInFlight.set(url, job);
    try {
      return await job;
    } finally {
      jsonInFlight.delete(url);
    }
  }

  function closePicker() {
    pickOpen = false;
    pickerMode = null;
    pickerOffset = 0;
    pickerHasMore = false;
    pickerQuery = "";
    pickerEl.hidden = true;
    articleMore.hidden = true;
    pickerHint.hidden = true;
    pickerHint.textContent = "";
    articleList.innerHTML = "";
  }

  function openPickerShell(mode) {
    pickOpen = true;
    pickerMode = mode;
    pickerEl.hidden = false;
    pickerHint.hidden = true;
    pickerHint.textContent = "";
  }

  function rowMeta(row) {
    const bits = [];
    if (row.nomenclature) bits.push(row.nomenclature);
    if (row.quantity) bits.push("склад " + row.quantity);
    if (row.photo_count === 0) bits.push("без фото");
    else if (row.photo_count != null) bits.push("фото " + row.photo_count);
    return bits.join(" · ");
  }

  function appendRows(items, replace) {
    if (replace) articleList.innerHTML = "";
    for (const row of items || []) {
      if (!row || !row.article) continue;
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "article-row-btn";
      btn.innerHTML =
        "<strong>" +
        row.article +
        "</strong><span>" +
        rowMeta(row) +
        "</span>";
      btn.addEventListener("click", () => {
        selectArticle(row.article);
      });
      li.appendChild(btn);
      articleList.appendChild(li);
    }
  }

  function selectArticle(article) {
    articleInput.value = String(article || "").trim();
    closePicker();
    clearPending();
    runLookup();
  }

  async function loadPickerPage(opts) {
    const replace = !!opts.replace;
    const seq = ++pickerSeq;
    const offset = replace ? 0 : pickerOffset;
    const needPhotos = pickerMode === "need_photos";
    const q = needPhotos ? "" : pickerQuery;
    if (!needPhotos && q.length < SEARCH_MIN_CHARS) {
      closePicker();
      return;
    }
    openPickerShell(pickerMode);
    if (replace) {
      articleList.innerHTML = "";
      pickerHint.hidden = false;
      pickerHint.textContent = "Загрузка…";
      pickerHint.className = "hint";
    }
    articleMore.hidden = true;
    try {
      const url = articlesUrl({
        offset: offset,
        needPhotos: needPhotos,
        q: q,
      });
      const data = await fetchJsonCached(url, ARTICLES_MS);
      if (seq !== pickerSeq) return;
      const items = (data && data.items) || [];
      appendRows(items, replace);
      pickerOffset = offset + items.length;
      pickerHasMore = !!(data && data.has_more);
      articleMore.hidden = !pickerHasMore;
      if (!items.length && replace) {
        pickerHint.hidden = false;
        pickerHint.textContent = needPhotos
          ? "Нет артикулов без фото"
          : "Ничего не найдено";
        pickerHint.className = "hint warn";
      } else {
        pickerHint.hidden = true;
      }
    } catch (ex) {
      if (seq !== pickerSeq) return;
      if (ex && ex.name === "AbortError") return;
      pickerHint.hidden = false;
      pickerHint.textContent =
        ex.name === "AbortError"
          ? "Таймаут списка"
          : String(ex.message || ex || "Ошибка списка");
      pickerHint.className = "hint warn";
      articleMore.hidden = true;
    }
  }

  function scheduleSearch() {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      const q = currentArticle();
      if (q.length < SEARCH_MIN_CHARS) {
        if (pickerMode === "search") closePicker();
        return;
      }
      pickerMode = "search";
      pickerQuery = q;
      pickerOffset = 0;
      loadPickerPage({ replace: true });
    }, SEARCH_DEBOUNCE_MS);
  }

  function attachLazyThumbs(container) {
    if (!container) return;
    const imgs = Array.from(container.querySelectorAll("img.lazy-thumb[data-src]"));
    if (!imgs.length) return;
    let loading = 0;
    let i = 0;

    function pump() {
      while (loading < THUMB_MAX && i < imgs.length) {
        const img = imgs[i];
        i += 1;
        if (!img || !img.dataset.src) continue;
        loading += 1;
        const src = img.dataset.src;
        img.removeAttribute("data-src");
        const done = () => {
          loading = Math.max(0, loading - 1);
          pump();
        };
        img.addEventListener("load", done, { once: true });
        img.addEventListener("error", done, { once: true });
        img.src = src;
      }
    }
    pump();
  }

  function setActiveTab(name) {
    const next = name === "listings" || name === "photos" ? name : "upload";
    if (next !== activeTab) {
      abortTabFetches();
    }
    activeTab = next;

    [tabUpload, tabListings, tabPhotos].forEach((btn) => {
      if (!btn) return;
      const on = btn.getAttribute("data-tab") === activeTab;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    panelUpload.hidden = activeTab !== "upload";
    panelListings.hidden = activeTab !== "listings";
    panelPhotos.hidden = activeTab !== "photos";

    // Avoid auto-focus on tab switch — iPhone soft keyboard causes layout jump.
    if (activeTab === "photos") {
      if (!photosLoaded) loadPhotosPage({ replace: true });
    }
  }

  function clearListingsCard() {
    if (listingsCard) {
      listingsCard.hidden = true;
      listingsCard.innerHTML = "";
    }
  }

  function checkPhotosUrl(article) {
    const p = new URLSearchParams();
    p.set("limit", String(CHECK_THUMBS_LIMIT));
    p.set("offset", "0");
    p.set("article", article);
    if (storePrefix) p.set("folder", storePrefix);
    return "api/photos?" + p.toString();
  }

  function pickExactListing(items, article) {
    const want = String(article || "").trim();
    const rows = items || [];
    for (const row of rows) {
      if (row && String(row.article || "").trim() === want) return row;
    }
    return null;
  }

  function formatPrice(row) {
    if (!row) return null;
    const price =
      row.manual_price != null
        ? row.manual_price
        : row.calculated_price != null
          ? row.calculated_price
          : row.incoming != null
            ? row.incoming
            : null;
    if (price == null || Number.isNaN(Number(price))) return null;
    return String(Math.round(Number(price))) + " ₽";
  }

  function detectProductKind(lookupBody, listingRow) {
    const fromListing = listingRow && listingRow.kind;
    const fromLookup = lookupBody && lookupBody.kind;
    const raw = String(fromListing || fromLookup || "").trim().toLowerCase();
    return raw === "wheel" ? "wheel" : "tire";
  }

  function renderCheckCard(lookupBody, listingRow, photoItems) {
    const art = (lookupBody && lookupBody.article) || "";
    const found = !!(lookupBody && lookupBody.found) || !!listingRow;
    const title =
      (listingRow && listingRow.nomenclature) ||
      (lookupBody && lookupBody.nomenclature) ||
      "";
    const qty = (lookupBody && lookupBody.quantity) || "";
    const photoCount =
      listingRow && listingRow.photo_count != null
        ? listingRow.photo_count
        : photoItems
          ? photoItems.length
          : null;
    const price = formatPrice(listingRow);
    const cardKind = detectProductKind(lookupBody, listingRow);

    const lines = [];
    lines.push(
      '<div class="check-card-head">' +
        "<strong>" +
        art +
        "</strong>" +
        '<span class="check-badge ' +
        (found ? "ok" : "warn") +
        '">' +
        (found ? "есть в остатках" : "нет в остатках") +
        "</span></div>"
    );
    if (title) lines.push('<p class="check-title">' + title + "</p>");
    if (price) {
      lines.push('<p class="check-price">' + price + "</p>");
    } else if (found) {
      lines.push('<p class="check-price missing">цена не найдена</p>');
    }
    const meta = [];
    if (qty) meta.push("склад " + qty);
    if (photoCount != null) {
      meta.push(photoCount === 0 ? "без фото" : "фото " + photoCount);
    }
    if (meta.length) {
      lines.push('<p class="check-meta">' + meta.join(" · ") + "</p>");
    }

    const thumbs = photoItems || [];
    if (thumbs.length) {
      lines.push('<div class="check-thumbs">');
      for (const ph of thumbs) {
        if (!ph || !ph.url) continue;
        lines.push(
          '<a href="' +
            ph.url +
            '" target="_blank" rel="noopener">' +
            '<img class="lazy-thumb" data-src="' +
            ph.url +
            '" alt="" loading="lazy">' +
            "</a>"
        );
      }
      lines.push("</div>");
    }

    lines.push(
      '<button type="button" class="secondary" id="listings-to-upload">В загрузку</button>'
    );

    listingsCard.innerHTML = lines.join("");
    listingsCard.hidden = false;
    attachLazyThumbs(listingsCard);
    const go = document.getElementById("listings-to-upload");
    if (go) {
      go.addEventListener("click", () => {
        setKind(cardKind);
        setActiveTab("upload");
        selectArticle(art);
      });
    }
  }

  async function checkListingArticle() {
    const article = String((listingsArticle && listingsArticle.value) || "").trim();
    const seq = ++listingsSeq;
    clearListingsCard();
    if (!article) {
      listingsHint.hidden = false;
      listingsHint.textContent = "Введите артикул и нажмите «Проверить»";
      listingsHint.className = "hint";
      return;
    }
    listingsBusy = true;
    if (listingsCheck) listingsCheck.disabled = true;
    listingsHint.hidden = false;
    listingsHint.textContent = "Проверка…";
    listingsHint.className = "hint";
    try {
      const wantArt = article;
      const lookupPath =
        "api/lookup?article=" + encodeURIComponent(wantArt);
      const listingsPath = (() => {
        const p = new URLSearchParams();
        p.set("limit", String(LISTINGS_LIMIT));
        p.set("offset", "0");
        p.set("q", wantArt);
        return "api/listings?" + p.toString();
      })();

      const [lookupResp, listingData, photoData] = await Promise.all([
        api(lookupPath, { method: "GET" }, LOOKUP_MS, "listings"),
        fetchJsonCached(listingsPath, LISTINGS_MS),
        fetchJsonCached(checkPhotosUrl(wantArt), PHOTOS_MS).catch(() => ({
          items: [],
        })),
      ]);
      if (seq !== listingsSeq || activeTab !== "listings") return;

      if (!lookupResp.res.ok) {
        listingsHint.hidden = false;
        listingsHint.textContent = detail(lookupResp.body);
        listingsHint.className = "hint warn";
        return;
      }

      const lookupBody = lookupResp.body || {};
      const listingRow = pickExactListing(
        (listingData && listingData.items) || [],
        lookupBody.article || wantArt
      );
      const photoItems = (photoData && photoData.items) || [];
      const found = !!(lookupBody && lookupBody.found) || !!listingRow;

      if (!found) {
        listingsHint.hidden = false;
        listingsHint.textContent =
          "Артикул " +
          (lookupBody.article || wantArt) +
          " не найден в остатках";
        listingsHint.className = "hint warn";
        renderCheckCard(lookupBody, null, photoItems);
        return;
      }

      listingsHint.hidden = false;
      listingsHint.textContent = lookupBody.found || listingRow
        ? "Найден в остатках"
        : "В каталоге фото есть, в остатках — нет";
      listingsHint.className =
        lookupBody.found || listingRow ? "hint ok" : "hint warn";
      renderCheckCard(lookupBody, listingRow, photoItems);
    } catch (ex) {
      if (seq !== listingsSeq || activeTab !== "listings") return;
      if (ex && ex.name === "AbortError") return;
      listingsHint.hidden = false;
      listingsHint.textContent = String(ex.message || ex || "Ошибка проверки");
      listingsHint.className = "hint warn";
    } finally {
      if (seq === listingsSeq) {
        listingsBusy = false;
        if (listingsCheck) listingsCheck.disabled = false;
      }
    }
  }

  function photosUrl(offset) {
    const p = new URLSearchParams();
    p.set("limit", String(PHOTOS_LIMIT));
    p.set("offset", String(offset || 0));
    if (photosFilterArticle) p.set("article", photosFilterArticle);
    const folder = photosFilterFolder || storePrefix;
    if (folder) p.set("folder", folder);
    return "api/photos?" + p.toString();
  }

  function confirmDeletePhoto(rel) {
    const path = String(rel || "");
    const name = path.split("/").pop() || path;
    return window.confirm("Удалить фото «" + name + "»?\n\nФайл будет удалён с сервера.");
  }

  async function deletePhoto(rel, li) {
    const path = String(rel || "").trim();
    if (!path || deletingPath) return;
    if (!confirmDeletePhoto(path)) return;
    deletingPath = path;
    if (li) li.classList.add("photo-deleting");
    photosHint.hidden = false;
    photosHint.textContent = "Удаление…";
    photosHint.className = "hint";
    try {
      const { res, body } = await api(
        "api/photos/delete",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ relative_path: path }),
        },
        DELETE_MS
      );
      if (!res.ok) {
        photosHint.hidden = false;
        photosHint.textContent = detail(body);
        photosHint.className = "hint warn";
        return;
      }
      invalidatePhotosCache();
      clearListingsCard();
      if (li && li.parentNode) li.parentNode.removeChild(li);
      photosHint.hidden = false;
      photosHint.textContent = body && body.missing ? "Уже удалено" : "Удалено";
      photosHint.className = "hint ok";
      if (!photosList.children.length) {
        photosLoaded = false;
        loadPhotosPage({ replace: true });
      }
    } catch (ex) {
      photosHint.hidden = false;
      photosHint.textContent =
        ex.name === "AbortError" ? "Таймаут удаления" : String(ex.message || ex);
      photosHint.className = "hint warn";
    } finally {
      deletingPath = "";
      if (li) li.classList.remove("photo-deleting");
    }
  }

  function appendPhotoRows(items, replace) {
    if (replace) photosList.innerHTML = "";
    for (const row of items || []) {
      if (!row || !row.url) continue;
      const li = document.createElement("li");
      li.className = "photo-card";
      const a = document.createElement("a");
      a.href = row.url;
      a.target = "_blank";
      a.rel = "noopener";
      const img = document.createElement("img");
      img.className = "lazy-thumb";
      img.alt = row.filename || "";
      img.dataset.src = row.url;
      const cap = document.createElement("span");
      cap.textContent =
        (row.folder ? row.folder + "/" : "") + (row.filename || row.relative_path || "");
      a.appendChild(img);
      a.appendChild(cap);
      const del = document.createElement("button");
      del.type = "button";
      del.className = "secondary photo-del";
      del.textContent = "Удалить";
      del.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        deletePhoto(row.relative_path, li);
      });
      li.appendChild(a);
      li.appendChild(del);
      photosList.appendChild(li);
    }
    attachLazyThumbs(photosList);
  }

  async function loadPhotosPage(opts) {
    const replace = !!opts.replace;
    const seq = ++photosSeq;
    const offset = replace ? 0 : photosOffset;
    if (replace) {
      photosHint.hidden = false;
      photosHint.textContent = "Загрузка…";
      photosHint.className = "hint";
    }
    photosMore.hidden = true;
    try {
      const data = await fetchJsonCached(photosUrl(offset), PHOTOS_MS, "photos");
      if (seq !== photosSeq || activeTab !== "photos") return;
      const items = (data && data.items) || [];
      appendPhotoRows(items, replace);
      photosOffset = offset + items.length;
      photosHasMore = !!(data && data.has_more);
      photosLoaded = true;
      photosMore.hidden = !photosHasMore;
      if (!items.length && replace) {
        photosHint.hidden = false;
        photosHint.textContent = "Нет файлов";
        photosHint.className = "hint warn";
      } else {
        photosHint.hidden = true;
      }
    } catch (ex) {
      if (seq !== photosSeq || activeTab !== "photos") return;
      if (ex && ex.name === "AbortError") return;
      photosHint.hidden = false;
      photosHint.textContent = String(ex.message || ex || "Ошибка списка");
      photosHint.className = "hint warn";
      photosMore.hidden = true;
    }
  }

  async function addFiles(fileList) {
    if (!lookup) {
      await runLookup();
    }
    if (!lookup || !currentArticle()) {
      const msg = "Сначала укажите корректный артикул — без него фото не загрузится";
      lookupHint.textContent = msg;
      lookupHint.className = "hint warn";
      setProgress(msg);
      return;
    }
    const files = Array.from(fileList || []);
    let added = 0;
    let skipped = 0;
    for (const file of files) {
      if (!looksLikeImageFile(file)) {
        skipped += 1;
        continue;
      }
      const url = URL.createObjectURL(file);
      pending.push({
        id: nextId++,
        blob: file,
        url: url,
        index: 0,
        filename: file.name || "photo.jpg",
      });
      added += 1;
    }
    assignIndicesFromLookup();
    renderPending();
    if (added === 0) {
      const msg =
        skipped > 0
          ? "Файл не похож на изображение — выберите фото ещё раз"
          : "В очереди нет фото — сделайте снимок или выберите из галереи";
      setProgress(msg);
      lookupHint.textContent = msg;
      lookupHint.className = "hint warn";
      return;
    }
    setProgress(
      "В очереди: " +
        pending.length +
        ". Нажмите «Отправить на сервер»"
    );
  }

  async function uploadOne(article, item) {
    const fd = new FormData();
    fd.append("article", article);
    fd.append("kind", kind);
    fd.append("indices", String(item.index));
    fd.append("files", item.blob, item.filename);
    const { res, body } = await api(
      "api/upload",
      { method: "POST", body: fd },
      UPLOAD_MS
    );
    if (!res.ok) {
      throw new Error(detail(body));
    }
    return body;
  }

  async function uploadQueue(article, items) {
    const total = items.length;
    const cap = Math.min(uploadConcurrency(), total);
    let next = 0;
    let started = 0;
    let done = 0;
    const okIds = {};
    const errors = [];
    const thumbs = [];

    function paint() {
      const n = Math.min(Math.max(started, done), total) || 1;
      const label = "Загрузка " + n + "/" + total + "…";
      uploadBtn.textContent = label;
      setProgress(label);
    }

    async function worker() {
      while (true) {
        const i = next;
        next += 1;
        if (i >= total) return;
        const item = items[i];
        started += 1;
        paint();
        try {
          const data = await uploadOne(article, item);
          okIds[item.id] = true;
          const urls = (data && data.photos_urls) || [];
          const saved = (data && data.saved) || [];
          for (let j = 0; j < urls.length; j += 1) {
            thumbs.push({ url: urls[j], path: saved[j] || urls[j] });
          }
        } catch (ex) {
          errors.push(String((ex && ex.message) || ex || "Ошибка"));
        } finally {
          done += 1;
          paint();
        }
      }
    }

    const workers = [];
    for (let w = 0; w < cap; w += 1) workers.push(worker());
    await Promise.all(workers);
    return {
      total: total,
      okIds: okIds,
      okCount: Object.keys(okIds).length,
      errors: errors,
      thumbs: thumbs,
    };
  }

  function showSavedThumbs(thumbs) {
    savedEl.innerHTML = "";
    for (const t of thumbs) {
      const a = document.createElement("a");
      a.href = t.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "saved-item";
      const img = document.createElement("img");
      img.src = t.url;
      img.alt = t.path || "";
      const cap = document.createElement("span");
      cap.textContent = t.path || t.url;
      a.appendChild(img);
      a.appendChild(cap);
      savedEl.appendChild(a);
    }
  }

  function showHome(me) {
    form.hidden = true;
    home.hidden = false;
    who.textContent = shopLabel(me);
    if (subtitle) subtitle.textContent = "Загрузка фото";
    document.title = "Photo v2 — " + shopLabel(me);
    showErr("");
    lockPhotosFolder((me && me.store) || "");
    syncKindButtons();
    setActiveTab("upload");
    // Do NOT preload catalogs on login — tabs stay idle until user acts.
  }

  function showLogin() {
    abortTabFetches();
    home.hidden = true;
    form.hidden = false;
    who.textContent = "";
    if (subtitle) subtitle.textContent = "Вход магазина";
    document.title = "Avito Photo v2 — вход";
    clearPending();
    closePicker();
    jsonCache.clear();
    jsonInFlight.clear();
    lookup = null;
    articleInput.value = "";
    lookupHint.textContent = "Введите артикул или подберите без фото";
    lookupHint.className = "hint";
    setProgress("");
    photosLoaded = false;
    clearListingsCard();
    if (listingsArticle) listingsArticle.value = "";
    if (listingsHint) {
      listingsHint.hidden = false;
      listingsHint.textContent = "Введите артикул и нажмите «Проверить»";
      listingsHint.className = "hint";
    }
    photosList.innerHTML = "";
    storePrefix = "";
    photosFilterFolder = "";
    deletingPath = "";
    if (photosFolder) {
      photosFolder.innerHTML = '<option value="">—</option>';
      photosFolder.value = "";
      photosFolder.disabled = true;
    }
    activeTab = "upload";
  }

  async function refreshMe() {
    const { res, body } = await api("api/me", { method: "GET" }, ME_MS);
    if (res.ok && body) {
      showHome(body);
      return true;
    }
    showLogin();
    return false;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showErr("");
    submit.disabled = true;
    try {
      const store = document.getElementById("store").value;
      const password = document.getElementById("password").value;
      const { res, body } = await api(
        "api/login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ store, password }),
        },
        LOGIN_MS
      );
      if (!res.ok) {
        showErr(detail(body));
        return;
      }
      document.getElementById("password").value = "";
      showHome(body || {});
    } catch (ex) {
      showErr(ex.name === "AbortError" ? "Таймаут входа" : "Сеть недоступна");
    } finally {
      submit.disabled = false;
    }
  });

  logoutBtn.addEventListener("click", async () => {
    logoutBtn.disabled = true;
    try {
      await api("api/logout", { method: "POST" }, LOGOUT_MS);
    } catch (_) {
      /* still clear UI */
    } finally {
      logoutBtn.disabled = false;
      showLogin();
    }
  });

  tabUpload.addEventListener("click", () => setActiveTab("upload"));
  tabListings.addEventListener("click", () => setActiveTab("listings"));
  tabPhotos.addEventListener("click", () => setActiveTab("photos"));

  if (listingsCheck) {
    listingsCheck.addEventListener("click", () => {
      if (listingsBusy) return;
      checkListingArticle();
    });
  }
  if (listingsArticle) {
    listingsArticle.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (!listingsBusy) checkListingArticle();
      }
    });
  }
  photosApply.addEventListener("click", () => {
    photosFilterArticle = String(photosArticle.value || "").trim();
    photosFilterFolder = storePrefix || String(photosFolder.value || "").trim();
    photosLoaded = false;
    loadPhotosPage({ replace: true });
  });
  photosMore.addEventListener("click", () => {
    if (!photosHasMore) return;
    loadPhotosPage({ replace: false });
  });

  kindTire.addEventListener("click", () => setKind("tire"));
  kindWheel.addEventListener("click", () => setKind("wheel"));

  articleInput.addEventListener("input", () => {
    clearPending();
    scheduleLookup();
    scheduleSearch();
  });

  pickBtn.addEventListener("click", () => {
    if (pickOpen && pickerMode === "need_photos") {
      closePicker();
      return;
    }
    pickerMode = "need_photos";
    pickerQuery = "";
    pickerOffset = 0;
    loadPickerPage({ replace: true });
  });

  articleMore.addEventListener("click", () => {
    if (!pickerHasMore) return;
    loadPickerPage({ replace: false });
  });

  async function onPickFiles(input) {
    // FileList is live: clearing input.value empties it. Snapshot first.
    const list = Array.from(input.files || []);
    input.value = "";
    if (list.length === 0) {
      const msg =
        "Камера/галерея не вернула файл — попробуйте ещё раз или «Из галереи»";
      setProgress(msg);
      lookupHint.textContent = msg;
      lookupHint.className = "hint warn";
      try {
        console.warn("[photo-v2] change event with 0 files");
      } catch (_e) {}
      return;
    }
    await addFiles(list);
  }

  filesInput.addEventListener("change", () => onPickFiles(filesInput));
  if (filesGallery) {
    filesGallery.addEventListener("change", () => onPickFiles(filesGallery));
  }

  uploadBtn.addEventListener("click", async () => {
    if (uploading) return;
    const blocked = uploadBlockedReason();
    if (blocked) {
      setProgress(blocked);
      lookupHint.textContent = blocked;
      lookupHint.className = "hint warn";
      return;
    }
    const article = currentArticle();
    const batch = pending.slice();
    uploading = true;
    updateUploadEnabled();
    setProgress("Загрузка 1/" + batch.length + "…");
    uploadBtn.textContent = "Загрузка 1/" + batch.length + "…";
    try {
      const result = await uploadQueue(article, batch);
      const still = [];
      for (const item of pending) {
        if (result.okIds[item.id]) {
          URL.revokeObjectURL(item.url);
        } else {
          still.push(item);
        }
      }
      pending = still;
      renderPending();
      if (result.thumbs.length) showSavedThumbs(result.thumbs);
      if (result.okCount > 0 && result.errors.length === 0) {
        setProgress("Сохранено: " + result.okCount);
        await runLookup();
        clearListingsCard();
        photosLoaded = false;
      } else if (result.okCount > 0) {
        setProgress(
          "Сохранено " +
            result.okCount +
            "/" +
            result.total +
            ". " +
            (result.errors[0] || "")
        );
        await runLookup();
        clearListingsCard();
        photosLoaded = false;
      } else {
        setProgress(result.errors[0] || "Ошибка загрузки");
      }
    } catch (ex) {
      setProgress(
        ex.name === "AbortError" ? "Таймаут загрузки" : String(ex.message || ex)
      );
    } finally {
      uploading = false;
      uploadBtn.textContent = UPLOAD_LABEL;
      updateUploadEnabled();
    }
  });

  syncKindButtons();
  updateUploadEnabled();
  showLogin();
  refreshMe().catch(() => showLogin());
})();
