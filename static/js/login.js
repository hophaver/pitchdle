// The sign-in page, served in place of a host or moderation page to anyone not allowed in yet. It sits on the
// page's own URL, so signing in just reloads it.
(() => {
  const PAGES = {
    "/host": ["Dashboard", "admin"], "/game": ["Game", "admin"], "/admin": ["Admin", "admin"],
    "/moderate": ["Moderation", "moderator"], "/review": ["Review", "moderator"],
  };
  const [name, need] = PAGES[location.pathname] || ["Pitchdle", "admin"];
  const form = document.getElementById("login");
  const error = document.getElementById("login-error");
  const submit = form.querySelector("button[type=submit]");

  document.title = `Sign in · ${name}`;
  document.getElementById("login-title").textContent = `Sign in to ${name}`;
  document.getElementById("login-sub").textContent = need === "admin"
    ? "With an admin account or the admin password."
    : "With a moderator or admin account, or the admin password.";

  // Already logged in on /play, but without the rights for this page: say so instead of a bare form.
  PD.api("/api/me").then((me) => {
    if (!me || !me.user) return;
    const note = document.getElementById("login-note");
    note.textContent = `You're logged in as ${me.user.username}, which can't open ${name}. Sign in with an account that can.`;
    note.hidden = false;
  }).catch(() => { /* no note */ });

  const show = (msg) => { error.textContent = msg; error.hidden = !msg; };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = form.username.value.trim();
    const password = form.password.value;
    if (!password) { show("Enter your password."); form.password.focus(); return; }
    show("");
    submit.disabled = true;
    submit.classList.add("busy");
    try {
      await PD.post("/api/staff/login", { username, password, need });
      location.reload();
    } catch (err) {
      show(err.message);
      form.password.select();
      submit.disabled = false;
      submit.classList.remove("busy");
    }
  });

  (form.username.value ? form.password : form.username).focus();
})();
