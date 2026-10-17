// Player flow for /play (today's set, self-paced) and /live (host-paced room).
// Answer every card first; you vs the crowd is shown only at the end.
const { h, api, post, AXES, AXIS, colorFor, safeLink, hostOf, plural } = PD;

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
  $app.classList.remove("wide"); // only the card being rated takes the whole screen
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
// Everything there is to weigh, from the start: the pitch, the facts and the vision, and what A'Pelago, the AI models
// and social media make of it. On a wide screen the facts, vision and your four calls sit left and the opinions
// right; on a phone they stack in that order, opinions before the calls. The crowd's read waits for the results.

function cardFacts(c) {
  const invested = c.investors.filter((i) => i.status === "invested");
  const box = (label, value, cls = "") => h("div", { class: `fact-box ${cls}` }, h("small", { class: "caps" }, label),
    h("b", {}, value));
  return h("section", { class: "sect g-facts" },
    h("div", { class: "fact-grid" },
      box("Raised so far", c.raised_eur === null || c.raised_eur === undefined ? "Not disclosed" : PD.money(c.raised_eur)),
      box("Investors", invested.length ? String(invested.length) : "None yet"),
      box("Stage", c.stages.length ? c.stages[c.stages.length - 1] : "Not given", "wide")),
    c.stages.length ? [h("div", { class: "caps sect-title" }, "Stages passed"),
      h("ol", { class: "stage-list" }, c.stages.map((stage) => h("li", {}, stage)))] : null,
    c.investors.length ? [h("div", { class: "caps sect-title" }, "Investors"),
      h("ul", { class: "investor-list" }, c.investors.map((i) => h("li", {}, h("b", {}, i.name), " ",
        i.status === "interested" ? h("span", { class: "interested" }, "interested")
          : i.amount_eur ? PD.money(i.amount_eur) : "invested")))] : null);
}

function cardVision(c) {
  if (!c.vision) return null;
  return h("section", { class: "sect g-vision" }, h("div", { class: "caps sect-title" }, "Vision"),
    c.vision.split(/\n{2,}/).map((para) => h("p", { class: "vision" }, para)));
}

// One row per opinion: who, their four calls on the 0–5 scale, and why.
function opinionRow(t) {
  const count = t.count ? plural(t.count, COUNT_WORD[t.key] || "post") : null;
  return h("div", { class: "op-row" },
    h("div", { class: "op-who" }, h("b", {}, t.label), count ? h("small", {}, count) : null),
    PD.opinionChart(t.scores, { labelled: true }),
    t.note ? h("p", { class: "op-note" }, t.note) : null);
}

function cardOpinions(c) {
  const group = (g) => c.opinions.filter((t) => t.group === g);
  const empty = (text) => h("p", { class: "op-empty" }, text);
  const [apelago, ai, social] = [group("people"), group("ai"), group("social")];
  return h("section", { class: "sect g-opinions" },
    h("div", { class: "caps sect-title" }, "What others make of it"),
    apelago.length ? apelago.map(opinionRow) : empty("A'Pelago hasn't rated it yet."),
    h("div", { class: "caps sect-title" }, "AI models"),
    ai.length ? ai.map(opinionRow) : empty("No AI ratings yet."),
    h("div", { class: "caps sect-title" }, "Social media"),
    social.map(opinionRow),
    !c.is_real && !social.length ? empty("None: this startup is made up.")
      : c.quiet.length ? empty(`No posts found on ${c.quiet.join(", ")}.`)
        : social.length ? null : empty("Not read yet."));
}

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

  const site = safeLink(c.website);
  const el = card(colorFor(index),
    cardTop(index, total, live ? h("span", { class: "timer", dataset: { timer: "1" } }, "") : null),
    h("div", { class: "pitch-head" },
      h("div", {}, h("div", { class: "caps sector" }, c.sector),
        h("p", { class: "pitch-line" }, c.one_liner || (c.vision || "").split(/(?<=[.!?])\s/)[0])),
      c.emoji ? h("div", { class: "art", "aria-hidden": "true" }, c.emoji) : null),
    h("p", { class: "ask" }, c.claim_ask),
    h("div", { class: "who" }, `— ${c.name}`, site ? [" · ", h("a", { href: site, target: "_blank",
      rel: "noopener noreferrer nofollow" }, `${hostOf(site)} ↗`)] : null),
    h("div", { class: "card-grid" },
      cardFacts(c),
      cardVision(c),
      cardOpinions(c),
      // Leads into the four calls: "Is this… novel? useful? …"
      h("section", { class: "sect g-call" },
        h("div", { class: "is-this" }, "Is this…"),
        h("div", { class: "axes" }, rows),
        h("div", { class: "actions" }, lock))));
  el.classList.add("full");

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
  $app.classList.add("wide");
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

function companyLink(r) {
  const site = safeLink(r.card.website);
  if (site) {
    return h("a", { class: "company-link", href: site, target: "_blank", rel: "noopener noreferrer nofollow" }, `${hostOf(site)} ↗`);
  }
  if (r.card.is_real) {
    const q = encodeURIComponent(r.card.name);
    return h("a", { class: "company-link", href: `https://duckduckgo.com/?q=${q}`, target: "_blank", rel: "noopener noreferrer" },
      "Look them up ↗");
  }
  return h("span", { class: "company-link muted-link" }, "Made-up startup");
}

// Every opinion on a result card is the same little chart: four columns, Novel to Investable, on 0–5.
const OPINION_GROUPS = [["people", "People"], ["ai", "AI models"], ["social", "Social media"]];
const COUNT_WORD = { crowd: "answer", apelago: "reviewer" }; // social media counts posts

function opinionTile(t) {
  const you = t.key === "you";
  const count = t.count ? plural(t.count, COUNT_WORD[t.key] || "post") : null;
  // Your read is the one picked out; you and everyone else carry their numbers, the rest on hover or below.
  return h("figure", { class: `op${you ? " op-you" : ""}` },
    h("figcaption", {}, h("b", {}, t.label), count ? h("small", {}, count) : null),
    PD.opinionChart(t.scores, { labelled: you || t.key === "crowd" }));
}

// The same numbers as a table, with why each AI or platform thinks so: nothing is only on hover.
function opinionDetails(tiles) {
  const notes = tiles.filter((t) => t.note);
  return h("details", { class: "op-more" },
    h("summary", {}, notes.length ? "Numbers and reasons" : "Numbers"),
    h("table", { class: "op-table" },
      h("thead", {}, h("tr", {}, h("td"), AXES.map((a) => h("th", { scope: "col" }, AXIS[a])))),
      h("tbody", {}, tiles.map((t) => h("tr", {}, h("th", { scope: "row" }, t.label),
        AXES.map((a) => h("td", {}, fmtAvg(t.scores[a]))))))),
    notes.length ? h("ul", { class: "op-notes" }, notes.map((t) => h("li", {}, h("b", {}, `${t.label}: `), t.note))) : null);
}

function resultCard(r, i) {
  return card(colorFor(i),
    h("div", { class: "result-head" },
      r.card.emoji ? h("div", { class: "art small", "aria-hidden": "true" }, r.card.emoji) : null,
      h("div", {}, h("div", { class: "result-name" }, r.card.name), h("div", { class: "caps sector" }, r.card.sector),
        companyLink(r))),
    OPINION_GROUPS.map(([group, title]) => {
      const tiles = r.opinions.filter((t) => t.group === group);
      return tiles.length ? h("section", { class: "op-group" }, h("div", { class: "caps op-title" }, title),
        h("div", { class: "op-grid" }, tiles.map(opinionTile))) : null;
    }),
    opinionDetails(r.opinions));
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
// across devices, opens earlier sets, and counts for more in the crowd score. A moderator approves every
// sign-up before it can log in.

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
    // Moderators' login opens the moderation page too, so this needs no second sign-in.
    S.user.is_moderator ? item("Moderation ↗", () => { closeMenu(); window.open("/moderate", "_blank", "noopener"); }) : null,
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
  if (mode === "signup") return showSignup();
  closeMenu();
  S.overlay = true;
  const username = h("input", { name: "username", type: "text", required: true, minlength: 3, maxlength: 20,
    autocomplete: "username", autocapitalize: "none", spellcheck: "false", placeholder: "seaotter" });
  const password = h("input", { name: "password", type: "password", required: true, minlength: 4, maxlength: 200,
    autocomplete: "current-password" });
  const send = h("button", { class: "pill block", type: "submit" }, "Log in");
  // The right password on a sign-up that isn't approved (yet) is explained here, not in a passing toast.
  const note = h("p", { class: "auth-note hidden", role: "status" });
  const field = (label, el) => h("label", { class: "submit-field" }, h("span", { class: "caps" }, label), el);

  const form = h("form", { novalidate: true },
    field("Username", username),
    field("Password", password),
    note,
    h("div", { class: "actions" }, send));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (username.value.trim().length < 3) { username.focus(); return PD.toast("Username: at least 3 characters"); }
    if (password.value.length < 4) { password.focus(); return PD.toast("Password: at least 4 characters"); }
    send.disabled = true;
    note.classList.add("hidden");
    try {
      const r = await post("/api/account/login", { username: username.value.trim(), password: password.value });
      S.user = r.user;
      PD.toast(r.claimed ? `Hi ${r.user.username}! ${r.claimed} answer${r.claimed === 1 ? "" : "s"} saved` : `Hi ${r.user.username}!`);
      resume();
    } catch (err) {
      if (err.status === 403) {
        note.textContent = err.message;
        note.classList.remove("hidden");
      } else {
        PD.toast(err.message);
      }
      send.disabled = false;
    }
  });

  show(paperCard("Log in",
    h("h1", { class: "account-head" }, "Welcome ", h("span", { class: "hand" }, "back")),
    form,
    h("button", { class: "switch-link", type: "button", onclick: showSignup }, "New here? ", h("b", {}, "Sign up"))));
  setTimeout(() => username.focus(), 50);
}

// What a sign-up tells the moderators. Mirrors SignUp in app/main.py, which checks all of it again.
const LINK_KEYS = ["linkedin", "github", "portfolio", "cv", "other"];
const SIGNUP_SECTIONS = [
  { title: "Your account", fields: [
    { key: "username", label: "Username", min: 3, max: 20, autocomplete: "username", placeholder: "seaotter",
      attrs: { autocapitalize: "none", spellcheck: "false" } },
    { key: "password", label: "Password", type: "password", min: 4, max: 200, autocomplete: "new-password",
      placeholder: "at least 4 characters" },
  ] },
  { title: "About you", fields: [
    { key: "full_name", label: "Full name", min: 2, max: 80, autocomplete: "name", placeholder: "Maija Virtanen" },
    { key: "email", label: "Email", type: "email", max: 120, autocomplete: "email", placeholder: "maija@example.com" },
    { key: "role", label: "What do you do?", options: PD.ROLES },
    { key: "organisation", label: "Organisation", optional: true, max: 80, autocomplete: "organization",
      placeholder: "company, fund or university" },
    { key: "location", label: "Based in", optional: true, max: 80, placeholder: "Turku, Finland" },
    { key: "expertise", label: "What you know well", optional: true, max: 160,
      placeholder: "aquaculture, ship design, impact investing" },
  ] },
  { title: "Your links", note: "At least one, so a moderator can see who you are.", fields: [
    { key: "linkedin", label: "LinkedIn", type: "url", max: 200, placeholder: "linkedin.com/in/…" },
    { key: "github", label: "GitHub", type: "url", max: 200, placeholder: "github.com/…" },
    { key: "portfolio", label: "Portfolio or website", type: "url", max: 200, placeholder: "yourname.com" },
    { key: "cv", label: "CV", type: "url", max: 200, placeholder: "a link, e.g. Google Drive or Dropbox" },
    { key: "other", label: "Anything else", type: "url", max: 200, placeholder: "Google Scholar, X, Wellfound…" },
  ] },
  { title: "Why join?", fields: [
    { key: "motivation", label: "What would you bring?", short: "Why join", area: true, min: 20, max: 600,
      placeholder: "A sentence or two is plenty." },
  ] },
];
const SIGNUP_FIELDS = SIGNUP_SECTIONS.flatMap((sec) => sec.fields);

// [field, message] for the first thing to fix before sending, or null.
function signupProblem(body) {
  for (const f of SIGNUP_FIELDS) {
    const name = f.short || f.label;
    if (f.options && !body[f.key]) return [f.key, `${name} Pick one.`];
    if (f.min && body[f.key].length < f.min) return [f.key, `${name}: at least ${f.min} characters`];
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email)) return ["email", "Email: that doesn't look like an address"];
  if (!LINK_KEYS.some((k) => body[k])) return ["linkedin", "Add at least one link"];
  return null;
}

function showSignup() {
  closeMenu();
  S.overlay = true;
  const inputs = {};
  const clean = (v) => v.replace(/\s+/g, " ").trim();
  const send = h("button", { class: "pill block", type: "submit" }, "Send for review");

  const fieldRow = (f) => {
    const el = f.options
      ? h("select", { name: f.key, required: true },
        h("option", { value: "" }, "Choose one"), Object.entries(f.options).map(([v, t]) => h("option", { value: v }, t)))
      : h(f.area ? "textarea" : "input", {
        name: f.key, type: f.area ? null : (f.type || "text"), rows: f.area ? 4 : null,
        required: !f.optional && f.type !== "url", maxlength: f.max, placeholder: f.placeholder,
        autocomplete: f.autocomplete || "off", inputmode: f.type === "url" ? "url" : null, ...f.attrs });
    const count = f.area ? h("span", { class: "count" }) : null;
    if (count) {
      const tally = () => { count.textContent = `${el.value.trim().length}/${f.max}`; };
      el.addEventListener("input", tally);
      tally();
    }
    inputs[f.key] = el;
    return h("label", { class: "submit-field" },
      h("span", { class: "row" }, h("span", { class: "caps" }, f.label),
        f.optional ? h("span", { class: "optional" }, "optional") : null, h("span", { class: "spacer" }), count),
      el);
  };

  const form = h("form", { novalidate: true },
    SIGNUP_SECTIONS.map((sec) => h("fieldset", { class: "form-section" },
      h("legend", { class: "hand" }, sec.title),
      sec.note ? h("p", { class: "section-note" }, sec.note) : null,
      sec.fields.map(fieldRow))),
    h("p", { class: "section-note privacy" }, "Only moderators see these details. Deleting your account deletes them too."),
    h("div", { class: "actions" }, send));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    // The password as typed and the motivation with its line breaks; everything else as one tidy line.
    const body = Object.fromEntries(SIGNUP_FIELDS.map((f) => {
      const v = inputs[f.key].value;
      return [f.key, f.type === "password" ? v : f.area ? v.trim() : clean(v)];
    }));
    const problem = signupProblem(body);
    if (problem) {
      inputs[problem[0]].focus();
      return PD.toast(problem[1]);
    }
    send.disabled = true;
    try {
      await post("/api/account/register", body);
      showApplied(body.full_name);
    } catch (err) {
      PD.toast(err.message, 5000);
      send.disabled = false;
    }
  });

  show(paperCard("Sign up",
    h("h1", { class: "account-head" }, "Keep your ", h("span", { class: "hand" }, "streak")),
    h("p", { class: "submit-intro" },
      "A moderator reviews every sign-up. Once you're in, your answers and stats are saved, earlier sets open up, and your reads count for more in the crowd score. Whatever you play here as a guest comes with you."),
    form,
    h("button", { class: "switch-link", type: "button", onclick: () => showAuth("login") }, "Have an account? ", h("b", {}, "Log in"))));
  setTimeout(() => inputs.username.focus(), 50);
}

function showApplied(fullName) {
  document.querySelector(".toast")?.classList.add("hidden"); // an error fixed a moment ago shouldn't linger here
  show(paperCard("Sign up",
    h("div", { class: "big-mark" }, "✓"),
    h("div", { class: "wait-title" }, `Thanks, ${fullName.split(" ")[0]}!`),
    h("p", { class: "submit-intro applied" },
      "A moderator will look at your sign-up, and you can log in once it's approved. Until then, keep playing as a guest: what you play on this device comes with you the first time you log in here."),
    h("div", { class: "actions" }, pill("Back to the game →", resume))));
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
  if (!S.cards.length) {
    return show(waitCard(colorFor(0), -1, 0, "–", "No cards today", data.notice || "check back soon"));
  }
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
        st.notice ? h("p", { class: "wait-sub" }, st.notice) : null,
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
