// Admin: the background AI work, exports, vote weights, thesis criteria and resets. Companies need no hand-keeping: real
// startups fill, check and join the game by themselves, and their reviews are a click on their Dashboard details card.
const { h, api, post } = PD;
const $app = document.getElementById("app");
const S = { mode: null, poll: null, theses: null,
  weights: null, // { weights, defaults } as saved
  weightDraft: null }; // the weights being changed, until saved

// Every real startup is filled, checked for the game and reviewed by itself, when it's added and on startup.
// This shows the last run, what went wrong (each problem once, with what it hit), and starts one by hand.
const when = (iso) => new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// "CageEye, X: Out of credit: …" → one problem ("Out of credit: …") with the startups and steps it hit.
function groupErrors(errors) {
  const groups = new Map();
  for (const e of errors) {
    const m = /^(.+?)(?:, ([^:,]+))?: (.+)$/.exec(e) || [null, "", "", e];
    const [, who, step, message] = m;
    const g = groups.get(message) || { message, hits: new Map() };
    const steps = g.hits.get(who) || [];
    if (step) steps.push(step);
    g.hits.set(who, steps);
    groups.set(message, g);
  }
  return [...groups.values()];
}

function readsPanel() {
  const { ready, auto, models } = S.mode.reads;
  const errors = auto.errors || [];
  const any = Object.values(ready).some(Boolean);
  async function readMissing() {
    try {
      const r = await post("/api/admin/autoread", {});
      PD.toast(r.started ? "Working through cards that are missing something…" : "No model has a key: set OPENROUTER_API_KEY in .env");
    } catch (e) { PD.toast(e.message); }
    await refresh();
  }
  async function clearErrors() {
    try {
      await api("/api/admin/autoread/errors", { method: "DELETE" });
      PD.toast("Errors cleared");
    } catch (e) { PD.toast(e.message); }
    await refresh();
  }
  const status = auto.running ? ["busy", "Working on new cards…"] : !any ? ["off", "Off until a key is set (OPENROUTER_API_KEY in .env)"]
    : errors.length ? ["bad", "Last run had problems"] : auto.finished_at ? ["ok", "All caught up"] : ["off", "Not run yet"];
  const stat = (label, value) => h("div", { class: "ai-stat" }, h("span", {}, label), h("b", {}, value));
  return h("section", { class: "panel ai-panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "AI work in the background"), h("span", { class: "spacer" }),
      h("button", { class: `btn${auto.running ? " busy" : ""}`, disabled: auto.running || !any, onclick: readMissing,
        title: "Fill, check and review every card still missing something" }, auto.running ? "Running…" : "Run missing now"),
      errors.length ? h("button", { class: "btn", disabled: auto.running, onclick: clearErrors,
        title: auto.running ? "Wait for the run to finish" : "Empty the problems list. Failed cards are tried again on the next run." },
        "Clear errors") : null),
    h("div", { class: `ai-status ${status[0]}` }, h("i", { "aria-hidden": "true" }), status[1]),
    auto.finished_at || auto.running ? h("div", { class: "ai-stats" },
      stat("Last run", auto.finished_at ? when(auto.finished_at) : "now"),
      stat("Cards done", String((auto.read || []).length)),
      stat("Problems", errors.length ? String(errors.length) : "None")) : null,
    errors.length ? h("div", { class: "ai-errors" }, groupErrors(errors).map((g) => {
      const [title, ...more] = g.message.split(/(?<=[.:])\s+/);
      return h("div", { class: "ai-error" },
        h("b", {}, title.replace(/:$/, "")),
        more.length ? h("p", {}, more.join(" ")) : null,
        h("ul", {}, [...g.hits].map(([who, steps]) => h("li", {}, h("span", {}, who), steps.length ? ` · ${steps.join(", ")}` : null))));
    })) : null,
    h("dl", { class: "ai-models" },
      h("dt", {}, "Cards, profiles, game check"), h("dd", {}, S.mode.discover.ai.model, h("small", {}, " OPENROUTER_MODEL")),
      h("dt", {}, "Reviews"), h("dd", {}, [models.claude, models.gpt, models.grok].join(" · "))));
}

// How much one answer counts in a card's crowd score, by who gave it (scoring.vote_weights). Moderation shows what each
// member's answer counts; it's set here. The share is shown and typed as a percentage.
const WEIGHTS = [
  { key: "player", label: "Player", help: "One answer from a player account." },
  { key: "investor", label: "Investor", help: "One answer from an approved investor." },
  { key: "guest", label: "Guest", help: "One answer from someone playing without an account." },
  { key: "guest_max_share", label: "Guests' max share", help: "The most all guests together make up of a card's crowd score.", pct: true },
];
const sameWeights = (a, b) => WEIGHTS.every(({ key }) => Number(a[key]) === Number(b[key]));

function weightsSection() {
  if (!S.weights) return null;
  const { weights: saved, defaults } = S.weights;
  const w = S.weightDraft || saved;
  const field = ({ key, label, help, pct }) => {
    const input = h("input", { type: "number", min: 0, max: pct ? 95 : 10, step: pct ? 5 : 0.1,
      "aria-label": label, value: pct ? Math.round(w[key] * 100) : w[key],
      oninput: (e) => {
        const v = e.target.valueAsNumber;
        S.weightDraft = { ...(S.weightDraft || saved), [key]: Number.isFinite(v) ? (pct ? v / 100 : v) : NaN };
        paint();
      } });
    return h("label", { class: "w-field" },
      h("span", { class: "w-label" }, label),
      h("span", { class: "w-input" }, pct ? null : h("span", { class: "w-unit" }, "×"), input, pct ? h("span", { class: "w-unit" }, "%") : null),
      h("span", { class: "w-help" }, help));
  };
  const note = h("span", { class: "muted small" }, "Not saved yet.");
  const save = h("button", { class: "btn primary", onclick: saveWeights }, "Save weights");
  const undo = h("button", { class: "btn", onclick: () => { S.weightDraft = null; render(); } }, "Undo");
  const back = h("button", { class: "btn link", onclick: () => { S.weightDraft = { ...defaults }; render(); } }, "Back to defaults");
  function paint() {
    const changed = !!S.weightDraft && !sameWeights(S.weightDraft, saved);
    save.disabled = !changed;
    undo.classList.toggle("hidden", !changed);
    note.classList.toggle("hidden", !changed);
    back.classList.toggle("hidden", sameWeights(S.weightDraft || saved, defaults));
  }
  paint();
  return h("section", { class: "a-section" },
    h("div", { class: "a-section-head" }, h("h2", {}, "Vote weights"),
      h("p", { class: "muted small" }, "How much one answer counts in a card's crowd score, by who gave it. Saved weights count at once, ",
        "for every card. The defaults come from .env.")),
    h("div", { class: "panel" },
      h("div", { class: "w-grid" }, WEIGHTS.map(field)),
      h("div", { class: "row w-actions" }, note, h("span", { class: "spacer" }), back, undo, save)));
}

async function saveWeights() {
  const w = S.weightDraft;
  if (!w || WEIGHTS.some(({ key }) => !Number.isFinite(w[key]))) { PD.toast("Fill in all four weights"); return; }
  try {
    S.weights = await post("/api/admin/weights", w, "PUT");
    S.weightDraft = null;
    PD.toast("Weights saved: every crowd score uses them now");
  } catch (e) { PD.toast(e.message, 6000); }
  render();
}

// The thesis criteria the dashboard's fit is judged by (rubric.json): gates, the stage window and where they came from.
// Defaults until A'Pelago and Redstone give their real ones; saving rewrites rubric.json and every fit follows.
// One card per holder, each saved on its own.
function thesisCard(key, t) {
  const g = t.gates || {};
  const list = (v) => (v === "*" || !v ? "*" : v.join(", "));
  const inp = (value, attrs = {}) => h("input", { type: "text", value: value ?? "", ...attrs });
  let scale = t.window.scale;
  const f = {
    sectors: inp(list(g.sectors), { "aria-label": "Sectors", placeholder: "* = any" }),
    countries: inp(list(g.countries), { "aria-label": "Countries", placeholder: "* or Finland, Nordic, EU, Baltic" }),
    tmin: inp(g.ticket_eur ? g.ticket_eur[0] : "", { type: "number", min: 0, step: 10000, placeholder: "Open", "aria-label": "Minimum ticket" }),
    tmax: inp(g.ticket_eur ? g.ticket_eur[1] : "", { type: "number", min: 0, step: 10000, placeholder: "Open", "aria-label": "Maximum ticket" }),
    scale: Tool.dropdown({ label: "Stage scale", options: [["trl", "TRL (technology)"], ["brl", "BRL (business)"]], value: scale,
      onChange: (v) => { scale = v; } }),
    lo: inp(t.window.peak[0], { type: "number", min: 1, max: 9, "aria-label": "Band from" }),
    hi: inp(t.window.peak[1], { type: "number", min: 1, max: 9, "aria-label": "Band to" }),
    falloff: inp(t.window.falloff, { type: "number", min: 1, max: 9, step: 0.5, "aria-label": "Falloff" }),
    note: h("textarea", { rows: 2, "aria-label": "Where these criteria come from", maxlength: 400 }, t.criteria_note || ""),
  };
  const num = (el) => (el.value === "" ? null : Number(el.value));
  const split = (el) => el.value.split(",").map((s) => s.trim()).filter(Boolean);
  const read = () => ({ sectors: split(f.sectors), countries: split(f.countries),
    ticket_eur: num(f.tmin) === null && num(f.tmax) === null ? null : [num(f.tmin), num(f.tmax)],
    window: { scale, peak: [num(f.lo), num(f.hi)], falloff: num(f.falloff) }, criteria_note: f.note.value });
  async function save(btn) {
    btn.disabled = true;
    try {
      S.theses = await post("/api/admin/rubric/theses", { [key]: read() }, "PUT");
      PD.toast(`${t.label} saved: every fit on the Dashboard follows`);
    } catch (e) { PD.toast(e.message, 6000); }
    render();
  }
  const field = (label, hint, ...kids) => h("div", { class: "t-field" }, h("div", { class: "t-label" }, label, hint ? h("span", {}, hint) : null),
    h("div", { class: "t-inputs" }, kids));
  const group = (title, ...kids) => h("fieldset", { class: "t-group" }, h("legend", {}, title), kids);
  return h("section", { class: "panel t-card" },
    h("div", { class: "panel-head" }, h("h2", {}, t.label), h("span", { class: "spacer" }),
      h("button", { class: "btn primary", onclick: (e) => save(e.currentTarget) }, "Save")),
    t.description ? h("p", { class: "muted small" }, t.description) : null,
    group("Scope",
      field("Sectors", "words in the sector or pitch", f.sectors),
      field("Countries or regions", null, f.countries)),
    group("Ticket size",
      field("Range, €", "blank = open", f.tmin, h("span", { class: "t-dash" }, "–"), f.tmax)),
    group("Stage window",
      field("Scale", null, f.scale),
      field("Fit peaks at", "levels 1–9", f.lo, h("span", { class: "t-dash" }, "–"), f.hi),
      field("Falls to 0 over", "levels", f.falloff)),
    group("Source", field("Where these criteria come from", null, f.note)));
}

function thesisSection() {
  if (!S.theses) return null;
  return h("section", { class: "a-section" },
    h("div", { class: "a-section-head" }, h("h2", {}, "Thesis criteria"),
      h("p", { class: "muted small" }, "Out-of-scope gates first, then the stage band where each holder fits best. These are editable defaults, ",
        "not A'Pelago's or Redstone's real thesis: enter theirs here and note where they came from. Unknowns (no country, no ask) never count against a startup.")),
    h("div", { class: "t-grid" }, Object.entries(S.theses).filter(([k]) => !k.startsWith("_")).map(([k, t]) => thesisCard(k, t))));
}

function render() {
  const reset = (scope, label, question, sub, danger) => h("div", { class: "a-reset" },
    h("div", {}, h("b", {}, label), h("div", { class: "muted small" }, sub)),
    h("button", { class: `btn${danger ? " danger" : ""}`, onclick: async () => {
      if (!confirm(question)) return;
      await post("/api/admin/reset", { scope });
      PD.toast("Done");
      await refresh();
    } }, label));
  $app.replaceChildren(
    h("div", { class: "head" }, h("h1", {}, "Admin")),
    h("div", { class: "a-top" }, readsPanel(),
      h("section", { class: "panel" }, h("h2", {}, "Export"),
        h("p", { class: "muted small" }, "Every company with its scores, reads and answers."),
        h("div", { class: "row" },
          h("a", { class: "btn", href: "/api/admin/export.csv" }, "Download CSV"),
          h("a", { class: "btn", href: "/api/admin/export.json" }, "Download JSON")))),
    weightsSection(),
    thesisSection(),
    h("section", { class: "a-section" }, h("div", { class: "a-section-head" }, h("h2", {}, "Danger zone")),
      h("div", { class: "panel a-danger" },
        reset("seed", "Clear demo answers", "Remove the seeded players and their answers?", "Removes the seeded demo players and their answers."),
        reset("real", "Clear real answers", "Remove every real player's answers?", "Removes every real player's answers. Accounts stay.", true),
        reset("everything", "Reset everything", "Delete all data and reload the sample companies and sets?", "Deletes all data and reloads the sample companies and sets.", true))));
}

async function refresh(opts = {}) {
  try {
    S.mode = await api("/api/admin/mode");
    if (!S.theses) S.theses = (await api("/api/admin/rubric")).theses;
    if (!S.weights) S.weights = await api("/api/admin/weights");
    Tool.setInfo(S.mode);
    // A poll never redraws under someone typing in a field.
    const typing = $app.contains(document.activeElement) && document.activeElement.matches("input, textarea, select");
    if (!(opts.poll && typing)) render();
    // Keep polling while the background work runs, so its progress shows up on its own.
    clearTimeout(S.poll);
    if (S.mode.reads.auto.running) S.poll = setTimeout(() => refresh({ poll: true }), 3000);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(refresh);
refresh();
