(function () {
  const grid = document.getElementById("store-grid");
  const storeInput = document.getElementById("store");
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("login-error");
  const passwordInput = document.getElementById("password");
  const loginInput = document.getElementById("login");
  const userPasswordInput = document.getElementById("user-password");

  if (!form) return;

  if (grid && storeInput) {
    grid.querySelectorAll(".store-card").forEach((card) => {
      card.addEventListener("click", () => {
        grid.querySelectorAll(".store-card").forEach((c) => c.classList.remove("selected"));
        card.classList.add("selected");
        storeInput.value = card.getAttribute("data-prefix") || "";
        if (loginInput) loginInput.value = "";
        errorEl.classList.add("hidden");
        passwordInput.focus();
      });
    });
  }

  if (loginInput) {
    loginInput.addEventListener("input", () => {
      if (loginInput.value.trim() && storeInput) {
        storeInput.value = "";
        if (grid) {
          grid.querySelectorAll(".store-card").forEach((c) => c.classList.remove("selected"));
        }
      }
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.classList.add("hidden");

    const login = loginInput ? loginInput.value.trim() : "";
    const store = storeInput ? storeInput.value.trim() : "";
    let payload;

    if (login) {
      payload = {
        login: login,
        password: userPasswordInput ? userPasswordInput.value : "",
      };
    } else if (store) {
      payload = {
        store: store,
        password: passwordInput ? passwordInput.value : "",
      };
    } else {
      errorEl.textContent = "Выберите магазин или введите логин";
      errorEl.classList.remove("hidden");
      return;
    }

    const response = await fetch("api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      errorEl.textContent = login
        ? "Неверный логин или пароль"
        : "Неверный пароль";
      errorEl.classList.remove("hidden");
      return;
    }

    const data = await response.json().catch(() => ({}));
    if (data.redirect) {
      window.location.href = data.redirect;
    } else {
      window.location.reload();
    }
  });
})();
