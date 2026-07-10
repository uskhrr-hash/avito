(function () {
  const stores = window.PHOTO_UPLOAD_STORES || [];
  const select = document.getElementById("store");
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("login-error");

  for (const store of stores) {
    const option = document.createElement("option");
    option.value = store.prefix;
    option.textContent = `${store.label} (${store.prefix})`;
    select.appendChild(option);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.classList.add("hidden");
    const payload = {
      store: select.value,
      password: document.getElementById("password").value,
    };
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      errorEl.textContent = "Неверный магазин или пароль";
      errorEl.classList.remove("hidden");
      return;
    }
    window.location.reload();
  });
})();
