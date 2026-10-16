// Player flow for /play (today's set, self-paced) and /live (host-paced room).
// Answer every card first; you vs the crowd is shown only at the end.
const { h, api, post, AXES, AXIS, colorFor } = PD;

const $app = document.getElementById("app");
const S = {
  mode: location.pathname.startsWith("/live") ? "live" : "solo",
  set: null,
  cards: [],
  answered: new Set(),
  liveKey: null,
  deadline: null,
  user: null,      // { username } when signed in
  overlay: false,  // an account screen is up; live polling holds off re-rendering
};

function show(...nodes) {
  $app.replaceChildren(...nodes.flat().filter(Boolean));
  window.scrollTo({ top: 0 });
}

function card(color, ...kids) {
  return h("section", { class: "card", style: { "--card": color } }, ...kids);
}

function cardTop(index, total, right) {
  return h("div", { class: "card-top" },
    accountTag(),
    total ? h("span", { class: "pips", "aria-label": `Card ${index + 1} of ${total}` },
      Array.from({ length: total }, (_, i) => h("i", { class: i <= index ? "on" : "" }))) : null,
    h("span", {}, right ?? setLabel()));
}

// "#3" reads as "No. 3"; named sets (like the live one) keep their name.
const setLabel = () => (!S.set ? "" : S.set.label.startsWith("#") ? `No. ${S.set.label.slice(1)}` : S.set.label);

const pill = (label, onclick, attrs = {}) => h("button", { class: "pill", onclick, ...attrs }, label);

// --- start ----------------------------------------------------------------------------------------

function showStart() {
  const started = S.answered.size > 0;
  const today = S.set.mode !== "daily" || S.set.today || !S.set.date;
  show(card(colorFor(0),
    cardTop(-1, 0),
    h("div", { class: "hero" },
      h("h1", {}, "Would you"),
      h("span", { class: "hand" }, "back"),
      h("h1", {}, "this?"),
      h("p", { class: "caps" }, today ? `${S.cards.length} startups · 4 calls each` : `${dayLabel(S.set.date)} · ${S.cards.length} startups`)),
    h("div", { class: "actions" },
      pill(started ? "Continue →" : today ? "Play today's →" : "Play it →", () => nextCard()))),
  submitSection());
}

// --- one card -------------------------------------------------------------------------------------

function showCard(c, index, total, { live = false } = {}) {
  const values = {};
  const lock = pill("Lock it in ↵", null, { disabled: true, class: "pill ghost block" });
  const rows = AXES.map((axis) => {
    const buttons = [0, 1, 2, 3, 4, 5].map((n) => h("button", {
      type: "button", "aria-label": `${AXIS[axis]} ${n}`, "aria-pressed": "false",
      onclick: () => {
        values[axis] = n;
        buttons.forEach((b, i) => { b.classList.toggle("on", i === n); b.setAttribute("aria-pressed", i === n); });
        const ready = AXES.every((a) => values[a] !== undefined);
        lock.disabled = !ready;
        lock.classList.toggle("ghost", !ready);
      },
    }, n));
    return h("div", {}, h("div", { class: "caps axis-label" }, AXIS[axis]), h("div", { class: "taps" }, buttons));
  });

  const el = card(colorFor(index),
    cardTop(index, total, live ? h("span", { class: "timer", dataset: { timer: "1" } }, "") : null),
    h("div", { class: "pitch-head" },
      h("div", {}, h("div", { class: "caps sector" }, c.sector), h("p", { class: "pitch-line" }, c.one_liner)),
      c.emoji ? h("div", { class: "art", "aria-hidden": "true" }, c.emoji) : null),
    h("p", { class: "ask" }, c.claim_ask),
    h("div", { class: "who" }, `— ${c.name}`),
    // Leads into the four calls: "Is this… novel? useful? …"
    h("div", { class: "is-this" }, "Is this…"),
    h("div", { class: "axes" }, rows),
    h("div", { class: "actions" }, lock));

  lock.addEventListener("click", async () => {
    lock.disabled = true;
    try {
      await post("/api/vote", { dive_id: S.set.id, company_id: c.id, scores: values });
      S.answered.add(c.id);
      el.classList.add("out");
      setTimeout(() => (live ? showLocked(index, total) : nextCard()), 230);
    } catch (e) {
      PD.toast(e.message);
      lock.disabled = false;
    }
  });
  show(el);
  tickTimers();
}

function nextCard() {
  const i = S.cards.findIndex((c) => !S.answered.has(c.id));
  if (i === -1) return showResults();
  return showCard(S.cards[i], i, S.cards.length);
}

// --- live waiting states ----------------------------------------------------------------------------

const dots = () => h("div", { class: "dots" }, h("i"), h("i"), h("i"));

function waitCard(color, index, total, mark, title, sub, ...extra) {
  return card(color, cardTop(index, total), h("div", { class: "big-mark" }, mark),
    h("div", { class: "wait-title" }, title), sub ? h("div", { class: "wait-sub" }, sub) : null, ...extra);
}

function showLocked(index, total) {
  show(waitCard(colorFor(index), index, total, "✓", "Locked in", "next one soon", dots()));
}

function tickTimers() {
  if (!S.deadline) return;
  const left = Math.max(0, Math.round((S.deadline - Date.now()) / 1000));
  document.querySelectorAll("[data-timer]").forEach((el) => {
    el.textContent = `${left}s`;
    el.classList.toggle("low", left <= 5);
  });
}
setInterval(tickTimers, 250);

// --- results ----------------------------------------------------------------------------------------

function headline(leans) {
  const [most, count] = Object.entries(leans).sort((a, b) => b[1] - a[1])[0];
  if (!count) return ["You're", "first", "— no one else has answered yet"];
  if (most === "higher") return ["You're more", "bullish", "than the crowd"];
  if (most === "lower") return ["You're", "tougher", "than the crowd"];
  return ["You're in", "sync", "with the crowd"];
}

// Averages to one decimal, dropping a trailing ".0": 4.2 → "4.2", 3.02 → "3".
const fmtAvg = (n) => (n === null || n === undefined ? "–" : String(Math.round(n * 10) / 10));

// Links come from the server already checked, but never render anything that isn't plain http(s).
const safeLink = (url) => (/^https?:\/\//i.test(url || "") ? url : null);

function companyLink(r) {
  const site = safeLink(r.website);
  if (site) {
    const host = new URL(site).hostname.replace(/^www\./, "");
    return h("a", { class: "company-link", href: site, target: "_blank", rel: "noopener noreferrer nofollow" }, `${host} ↗`);
  }
  if (r.card.is_real) {
    const q = encodeURIComponent(r.card.name);
    return h("a", { class: "company-link", href: `https://duckduckgo.com/?q=${q}`, target: "_blank", rel: "noopener noreferrer" },
      "Look them up ↗");
  }
  return h("span", { class: "company-link muted-link" }, "Made-up startup");
}

function resultCard(r, i) {
  const nums = (scores, fmt) => h("div", { class: "nums" },
    AXES.map((a) => h("div", {}, h("b", {}, fmt(scores && scores[a])), h("small", {}, AXIS[a]))));
  return card(colorFor(i),
    h("div", { class: "result-head" },
      r.card.emoji ? h("div", { class: "art small", "aria-hidden": "true" }, r.card.emoji) : null,
      h("div", {}, h("div", { class: "result-name" }, r.card.name), h("div", { class: "caps sector" }, r.card.sector),
        companyLink(r))),
    h("div", { class: "block you" }, h("div", { class: "caps" }, "You said"), nums(r.you.scores, (v) => v)),
    // Average of every other player's answer.
    h("div", { class: "block crowd" }, h("div", { class: "caps" }, `Everyone · ${r.crowd.n}`),
      nums(r.crowd.means, fmtAvg)));
}

async function showResults() {
  let r;
  try {
    r = await api(`/api/dive/${S.set.id}/results`);
  } catch (e) {
    show(waitCard(colorFor(0), -1, 0, "…", "Not yet", e.message));
    return;
  }
  if (!r.cards.length) {
    show(waitCard(colorFor(0), -1, 0, "–", "No answers", "you didn't answer any cards"));
    return;
  }
  const [a, b, c] = headline(r.summary.leans);
  const { leans } = r.summary;
  show(
    h("section", { class: "card summary" },
      cardTop(-1, 0),
      h("h1", {}, a, " ", h("span", { class: "hand" }, b), " ", c),
      h("div", { class: "tally" },
        h("div", {}, h("b", {}, `${leans.higher}`), h("span", {}, "Higher ↑")),
        h("div", {}, h("b", {}, `${leans.with}`), h("span", {}, "With =")),
        h("div", {}, h("b", {}, `${leans.lower}`), h("span", {}, "Lower ↓"))),
      r.next_set_in === null ? null : nextSetTimer(r.next_set_in)),
    r.dive.mode === "daily" ? moreSetsCard() : null,
    r.cards.map(resultCard),
    submitSection(),
  );
}

// --- next set countdown -----------------------------------------------------------------------------
// Counts down from the server's figure (not the device clock) in hours and minutes. Each digit slides in
// when it changes and the colon blinks, so it visibly ticks even though it only changes once a minute.

let countdownTimer;

function nextSetTimer(seconds) {
  const endsAt = Date.now() + seconds * 1000;
  const digits = Array.from({ length: 4 }, () => h("span", { class: "digit" }));
  const shown = ["", "", "", ""];
  const face = h("div", { class: "clock", role: "timer", "aria-live": "off" },
    h("div", { class: "clock-digits" }, digits[0], digits[1]),
    h("div", { class: "colon", "aria-hidden": "true" }, ":"),
    h("div", { class: "clock-digits" }, digits[2], digits[3]));
  const el = h("div", { class: "next-set" }, h("div", { class: "caps" }, "Next in"), face);

  function tick() {
    const left = Math.max(0, endsAt - Date.now());
    if (!left) {
      clearInterval(countdownTimer);
      el.replaceChildren(h("div", { class: "caps" }, "A new set is ready"),
        h("div", { class: "actions" }, pill("Play it →", () => location.reload())));
      return;
    }
    // Round up so "00:00" never shows while time is still left.
    const mins = Math.ceil(left / 60000);
    const text = `${String(Math.floor(mins / 60)).padStart(2, "0")}${String(mins % 60).padStart(2, "0")}`;
    face.setAttribute("aria-label", `${Math.floor(mins / 60)} hours ${mins % 60} minutes until the next set`);
    [...text].forEach((ch, i) => {
      if (ch === shown[i]) return;
      const first = shown[i] === "";
      shown[i] = ch;
      const next = h("span", { class: first ? "digit" : "digit flip" }, ch);
      digits[i].replaceWith(next);
      digits[i] = next;
    });
  }

  clearInterval(countdownTimer);
  countdownTimer = setInterval(tick, 1000);
  tick();
  return el;
}

// --- add your startup -------------------------------------------------------------------------------
// Shown under the welcome card and the results. Submissions go to the host's review queue in /admin.
// Limits mirror SUBMIT_LIMITS in app/main.py so whatever is typed fits on a card.

const SUBMIT_FIELDS = [
  { key: "name", label: "Company name", min: 2, max: 30, placeholder: "BrineWorks" },
  { key: "sector", label: "Field", min: 2, max: 24, placeholder: "desalination" },
  { key: "one_liner", label: "Short pitch", min: 20, max: 90, area: true,
    placeholder: "A solar raft that turns seawater into drinking water for island villages." },
  { key: "claim_ask", label: "What you're asking for, and why", min: 10, max: 60,
    placeholder: "€500k to build ten more rafts" },
  { key: "website", label: "Link", min: 4, max: 200, type: "url", placeholder: "https://example.com" },
];

function submitSection() {
  const wrap = h("section", { class: "submit" });
  const opener = h("button", { class: "submit-open", type: "button" },
    h("span", { class: "caps" }, "Got a startup?"), h("span", { class: "hand" }, "Put it in the game →"));
  opener.addEventListener("click", () => wrap.replaceChildren(...submitForm(wrap)));
  wrap.append(opener);
  return wrap;
}

function submitForm(wrap) {
  const inputs = {};
  // Live preview in the real card style, so people see exactly what players will see.
  const pv = { sector: h("div", { class: "caps sector" }), pitch: h("p", { class: "pitch-line" }),
    ask: h("p", { class: "ask" }), who: h("div", { class: "who" }) };
  const preview = card(colorFor(1), h("div", { class: "caps preview-tag" }, "Preview"),
    pv.sector, pv.pitch, pv.ask, pv.who);
  const send = h("button", { class: "pill block", type: "submit" }, "Send for review");

  const clean = (v) => v.replace(/\s+/g, " ").trim();
  function update() {
    const v = Object.fromEntries(SUBMIT_FIELDS.map((f) => [f.key, clean(inputs[f.key].el.value)]));
    pv.sector.textContent = v.sector || "your field";
    pv.pitch.textContent = v.one_liner || "Your pitch in one concrete line.";
    pv.ask.textContent = v.claim_ask || "What you're asking for";
    pv.who.textContent = `— ${v.name || "Your company"}`;
    for (const f of SUBMIT_FIELDS) inputs[f.key].count.textContent = `${v[f.key].length}/${f.max}`;
  }

  const rows = SUBMIT_FIELDS.map((f) => {
    const el = h(f.area ? "textarea" : "input", {
      name: f.key, type: f.area ? null : (f.type || "text"), rows: f.area ? 2 : null, required: true,
      minlength: f.min, maxlength: f.max, placeholder: f.placeholder, autocomplete: "off",
      inputmode: f.type === "url" ? "url" : null,
    });
    // One line only: Enter in the pitch box shouldn't add a line break.
    if (f.area) el.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    el.addEventListener("input", update);
    const count = h("span", { class: "count" });
    inputs[f.key] = { el, count };
    return h("label", { class: "submit-field" }, h("span", { class: "row" }, h("span", { class: "caps" }, f.label), h("span", { class: "spacer" }), count), el);
  });

  const form = h("form", { class: "card submit-card", style: { "--card": "var(--paper)" }, novalidate: true },
    h("div", { class: "card-top" }, h("span", {}, "Add your startup")),
    h("p", { class: "submit-intro" }, "Keep it plain and concrete. We review every pitch before it goes in the game."),
    rows,
    h("div", { class: "actions" }, send));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(SUBMIT_FIELDS.map((f) => [f.key, clean(inputs[f.key].el.value)]));
    for (const f of SUBMIT_FIELDS) {
      if (body[f.key].length < f.min) {
        inputs[f.key].el.focus();
        return PD.toast(`${f.label}: at least ${f.min} characters`);
      }
    }
    send.disabled = true;
    try {
      await post("/api/submit", body);
      wrap.replaceChildren(h("section", { class: "card submit-card", style: { "--card": "var(--paper)" } }, h("div", { class: "big-mark" }, "✓"),
        h("div", { class: "wait-title" }, "Thanks!"), h("div", { class: "wait-sub" }, "we'll review it soon")));
    } catch (err) {
      PD.toast(err.message);
      send.disabled = false;
    }
  });

  update();
  setTimeout(() => inputs.name.el.focus(), 50);
  return [preview, form];
}

// --- account ----------------------------------------------------------------------------------------
// Everyone plays as a guest until they log in. Guests get today's set; an account keeps history and stats
// across devices, opens earlier sets, and counts for more in the crowd score.

// Back to whatever the player was doing, after an account screen.
function resume() {
  S.overlay = false;
  if (S.mode === "live") {
    S.liveKey = null;
    return livePoll();
  }
  return startSolo();
}

let openMenu = null;
function closeMenu() {
  if (!openMenu) return;
  const wrap = openMenu.parentElement;
  wrap.closest(".card")?.classList.remove("lifted");
  wrap.querySelector(".me-btn")?.setAttribute("aria-expanded", "false");
  openMenu.remove();
  openMenu = null;
}
document.addEventListener("click", (e) => { if (openMenu && !openMenu.parentElement.contains(e.target)) closeMenu(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

// Top-left of every main card: the username (opens the account menu), or a way in for guests.
function accountTag() {
  if (!S.user) {
    return h("span", { class: "me" }, h("button", { class: "me-btn", type: "button", onclick: () => showAuth("login") }, "Log in"));
  }
  const wrap = h("span", { class: "me" });
  const btn = h("button", { class: "me-btn", type: "button", "aria-haspopup": "menu", "aria-expanded": "false" },
    S.user.username, h("span", { class: "caret", "aria-hidden": "true" }, "▾"));
  btn.addEventListener("click", () => {
    const wasOpen = openMenu && wrap.contains(openMenu);
    closeMenu();
    if (wasOpen) return;
    btn.setAttribute("aria-expanded", "true");
    openMenu = accountMenu();
    wrap.append(openMenu);
    wrap.closest(".card")?.classList.add("lifted");
  });
  wrap.append(btn);
  return wrap;
}

function accountMenu() {
  const menu = h("div", { class: "me-menu", role: "menu" });
  // Clicks inside the menu swap its contents; stopPropagation keeps the outside-click handler from closing it.
  const item = (label, onclick, cls = "") => h("button", { type: "button", role: "menuitem", class: cls,
    onclick: (e) => { e.stopPropagation(); onclick(); } }, label);

  async function deleteAccount() {
    try {
      await api("/api/account", { method: "DELETE" });
      closeMenu();
      S.user = null;
      PD.toast("Account deleted");
      resume();
    } catch (e) { PD.toast(e.message); }
  }
  async function logout() {
    closeMenu();
    await post("/api/account/logout", {});
    S.user = null;
    PD.toast("Logged out");
    resume();
  }
  async function resetData() {
    try {
      const r = await post("/api/account/reset", {});
      closeMenu();
      PD.toast(`Reset: ${r.removed} answer${r.removed === 1 ? "" : "s"} cleared`);
      resume();
    } catch (e) { PD.toast(e.message); }
  }
  const items = () => [
    item("Your history", () => { closeMenu(); showHistory(); }),
    // Test account only (TEST_USERNAME in .env): start the game over without making a new account.
    S.user.is_test ? item("Reset my data", resetData) : null,
    item("Log out", logout),
    h("hr"),
    item("Delete account", () => menu.replaceChildren(h("div", { class: "me-confirm" },
      h("b", {}, "Are you sure?"),
      h("p", {}, "Your account, history and every answer you've given go for good."),
      h("div", { class: "me-confirm-btns" },
        item("Cancel", () => menu.replaceChildren(...items().filter(Boolean))),
        item("Delete", deleteAccount, "danger solid")))), "danger"),
  ];
  menu.append(...items().filter(Boolean));
  return menu;
}

// Paper card with a back button, used by the account screens.
function paperCard(title, ...kids) {
  return h("section", { class: "card submit-card account-card", style: { "--card": "var(--paper)" } },
    h("div", { class: "card-top" },
      h("button", { class: "me-btn", type: "button", onclick: resume }, "← Back"),
      h("span", {}, title)),
    ...kids);
}

function showAuth(mode = "login") {
  closeMenu();
  S.overlay = true;
  const signup = mode === "signup";
  const username = h("input", { name: "username", type: "text", required: true, minlength: 3, maxlength: 20,
    autocomplete: "username", autocapitalize: "none", spellcheck: "false", placeholder: "seaotter" });
  const password = h("input", { name: "password", type: "password", required: true, minlength: 4, maxlength: 200,
    autocomplete: signup ? "new-password" : "current-password", placeholder: signup ? "at least 4 characters" : "" });
  const send = h("button", { class: "pill block", type: "submit" }, signup ? "Create account" : "Log in");
  const field = (label, el) => h("label", { class: "submit-field" }, h("span", { class: "caps" }, label), el);

  const form = h("form", { novalidate: true },
    field("Username", username),
    field("Password", password),
    h("div", { class: "actions" }, send));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (username.value.trim().length < 3) { username.focus(); return PD.toast("Username: at least 3 characters"); }
    if (password.value.length < 4) { password.focus(); return PD.toast("Password: at least 4 characters"); }
    send.disabled = true;
    try {
      const r = await post(signup ? "/api/account/register" : "/api/account/login",
        { username: username.value.trim(), password: password.value });
      S.user = r.user;
      PD.toast(r.claimed ? `Hi ${r.user.username}! ${r.claimed} answer${r.claimed === 1 ? "" : "s"} saved` : `Hi ${r.user.username}!`);
      resume();
    } catch (err) {
      PD.toast(err.message);
      send.disabled = false;
    }
  });

  show(paperCard(signup ? "Sign up" : "Log in",
    h("h1", { class: "account-head" }, signup ? "Keep your " : "Welcome ", h("span", { class: "hand" }, signup ? "streak" : "back")),
    signup ? h("p", { class: "submit-intro" },
      "Save your answers and stats, play earlier sets, and count for more in the crowd score. Whatever you played here as a guest comes with you.") : null,
    form,
    h("button", { class: "switch-link", type: "button", onclick: () => showAuth(signup ? "login" : "signup") },
      signup ? "Have an account? " : "New here? ", h("b", {}, signup ? "Log in" : "Create one"))));
  setTimeout(() => username.focus(), 50);
}

const dayLabel = (iso) => (iso ? new Date(`${iso}T00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "");

async function showHistory() {
  closeMenu();
  S.overlay = true;
  let r;
  try {
    r = await api("/api/account/history");
  } catch (e) {
    PD.toast(e.message);
    return resume();
  }
  const { stats } = r;
  const stat = (n, label) => h("div", {}, h("b", {}, `${n}`), h("span", {}, label));
  const row = (set) => {
    const status = set.done ? "Done ✓" : set.answered ? `${set.answered} of ${set.total}` : "Not played";
    const name = set.label.startsWith("#") ? `No. ${set.label.slice(1)}` : set.label;
    return h("li", { class: `set-row${set.done ? " done" : ""}` },
      h("div", {}, h("div", { class: "set-name" }, name, set.today ? h("span", { class: "today-tag" }, "Today") : null),
        h("div", { class: "caps set-date" }, `${dayLabel(set.date)} · ${status}`)),
      h("a", { class: "pill small", href: set.today ? "/play" : `/play?dive=${set.id}` },
        set.done ? "Results" : set.answered ? "Continue" : "Play"));
  };
  show(
    paperCard(S.user ? S.user.username : "History",
      h("h1", { class: "account-head" }, "Your ", h("span", { class: "hand" }, "track record")),
      h("div", { class: "tally" }, stat(stats.sets, "Sets"), stat(stats.streak, "Streak"), stat(stats.best_streak, "Best")),
      h("div", { class: "tally" },
        stat(stats.leans.higher, "Higher ↑"), stat(stats.leans.with, "With ="), stat(stats.leans.lower, "Lower ↓")),
      h("p", { class: "submit-intro history-note" },
        `${stats.cards} card${stats.cards === 1 ? "" : "s"} answered. Higher, with and lower is where your reads sat next to everyone else's.`)),
    h("section", { class: "card submit-card", style: { "--card": "var(--paper)" } },
      h("div", { class: "card-top" }, h("span", {}, "Every daily set")),
      r.sets.length ? h("ul", { class: "set-list" }, r.sets.map(row)) : h("p", { class: "submit-intro" }, "No sets yet.")));
}

// Under a daily set's results: guests are offered an account, signed-in players get their history.
function moreSetsCard() {
  if (S.user) {
    return h("section", { class: "card more-sets" },
      h("div", { class: "caps" }, "Want more?"),
      h("div", { class: "hand" }, "Play earlier sets"),
      h("div", { class: "actions" }, pill("Your history →", showHistory)));
  }
  return h("section", { class: "card more-sets" },
    h("div", { class: "caps" }, "Can't wait for tomorrow?"),
    h("div", { class: "hand" }, "Play earlier sets"),
    h("p", {}, "Make a free account to keep today's answers, track your streak and play every set you missed."),
    h("div", { class: "actions stack" },
      pill("Sign up →", () => showAuth("signup")),
      h("button", { class: "switch-link", type: "button", onclick: () => showAuth("login") }, "Have an account? ", h("b", {}, "Log in"))));
}

// --- solo -------------------------------------------------------------------------------------------

async function startSolo() {
  const q = new URLSearchParams(location.search).get("dive");
  let data;
  try {
    data = await api(q ? `/api/dive/${encodeURIComponent(q)}` : "/api/dive/today");
  } catch (e) {
    if (e.status !== 401) throw e;
    return show(waitCard(colorFor(0), -1, 0, "🔒", "Earlier set", "log in to play it",
      h("div", { class: "actions stack" },
        pill("Log in →", () => showAuth("login")),
        h("a", { class: "pill ghost", href: "/play" }, "Play today's"))));
  }
  S.set = data.dive;
  S.cards = data.cards;
  S.answered = new Set(data.answered);
  if (!S.cards.length) return show(waitCard(colorFor(0), -1, 0, "–", "No cards today", "check back soon"));
  if (S.answered.size === S.cards.length) return showResults();
  return showStart();
}

// --- live -------------------------------------------------------------------------------------------

async function livePoll() {
  let st;
  try {
    st = await api("/api/live/state");
  } catch {
    return; // keep showing the last screen; the next poll retries
  }
  if (st.dive) S.set = st.dive;
  S.deadline = st.remaining !== null ? Date.now() + st.remaining * 1000 : null;
  document.querySelectorAll("[data-joined]").forEach((el) => { el.textContent = st.joined; });
  if (S.overlay) return;
  const key = `${st.key}:${st.voted ? "v" : ""}`;
  if (key === S.liveKey) return;
  S.liveKey = key;
  renderLive(st);
}

function renderLive(st) {
  const total = st.dive ? st.dive.total : 0;
  const i = st.card_index;
  switch (st.phase) {
    case "idle":
      return show(card(colorFor(0), cardTop(-1, 0, ""),
        h("div", { class: "hero" }, h("h1", {}, "No live"), h("span", { class: "hand" }, "game"), h("h1", {}, "right now")),
        h("div", { class: "actions" }, h("a", { class: "pill", href: "/play" }, "Play today's →"))));
    case "lobby":
      return show(card(colorFor(0), cardTop(-1, 0, ""),
        h("div", { class: "hero" }, h("h1", {}, "You're"), h("span", { class: "hand" }, "in"),
          h("p", { class: "caps" }, h("span", { dataset: { joined: "1" } }, st.joined), " here")),
        dots()));
    case "open":
      return st.voted ? showLocked(i, total) : showCard(st.card, i, total, { live: true });
    case "locked":
      return st.voted ? showLocked(i, total) : show(waitCard(colorFor(i), i, total, "✕", "Missed it", "next one soon", dots()));
    case "revealed":
      return show(waitCard(colorFor(i), i, total, "👀", "Eyes up", "on the big screen", dots()));
    case "final":
      return showResults();
    default:
      return null;
  }
}

// --- boot -------------------------------------------------------------------------------------------

(async function boot() {
  try {
    S.user = (await api("/api/me")).user; // also sets the device cookie before anything else
    if (S.mode === "live") {
      await livePoll();
      setInterval(livePoll, 2000);
    } else {
      await startSolo();
    }
  } catch (e) {
    show(waitCard(colorFor(0), -1, 0, "!", "Something broke", e.message));
  }
})();
