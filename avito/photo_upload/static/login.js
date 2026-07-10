(function () {
  const grid = document.getElementById("store-grid");
  const storeInput = document.getElementById("store");
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("login-error");
  const passwordInput = document.getElementById("password");

  if (!grid || !storeInput) return;

  grid.querySelectorAll(".store-card").forEach((card) => {
    card.addEventListener("click", () => {
      grid.querySelectorAll(".store-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      storeInput.value = card.getAttribute("data-prefix") || "";
      errorEl.classList.add("hidden");
      passwordInput.focus();
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.classList.add("hidden");

    if (!storeInput.value) {
      errorEl.textContent = "Нажмите на карточку магазина";
      errorEl.classList.remove("hidden");
      return;
    }

    const payload = {
      store: storeInput.value,
      password: passwordInput.value,
    };

    const response = await fetch("api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      errorEl.textContent = "Неверный пароль";
      errorEl.classList.remove("hidden");
      return;
    }

    window.location.reload();
  });
})();
