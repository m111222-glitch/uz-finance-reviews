const form = document.getElementById("loginForm");
const errorEl = document.getElementById("error");
const btn = document.getElementById("submitBtn");

async function alreadyIn() {
  try {
    const res = await fetch("/api/auth/status", { credentials: "include" });
    const data = await res.json();
    if (!data.auth_required || data.authenticated) {
      location.replace("/");
    }
  } catch {
    /* stay on login */
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    const password = document.getElementById("password").value;
    const res = await fetch("/api/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Invalid password");
    }
    location.replace("/");
  } catch (err) {
    errorEl.textContent = err.message || "Login failed";
    errorEl.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "Open dashboard";
  }
});

alreadyIn();
