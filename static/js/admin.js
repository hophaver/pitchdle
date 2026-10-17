// Admin: the background AI work, exports and resets. Companies need no hand-keeping: real startups fill, check and
// join the game by themselves, and their reviews are a click on their Dashboard details card.
const { h, api, post } = PD;
const $app = document.getElementById("app");
const S = { mode: null, poll: null, theses: null };

// Every real startup is filled, checked for the game and reviewed by itself, when it's added and on startup.
// This shows the last run and starts one by hand.
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
  return h("section", { class: "panel" }, h("h2", {}, "AI work in the background"),
    h("p", { class: "muted small" }, `Filling profiles and evidence, the game check, screening and card writing: ${S.mode.discover.ai.model} `,
      `(OPENROUTER_MODEL). Reviews: ${models.claude}, ${models.gpt}, ${models.grok}. Set them in .env.`),
    h("p", { class: "small" }, auto.running ? "Working on new cards…"
      : auto.finished_at ? `Last run ${auto.finished_at.slice(0, 16).replace("T", " ")}, ${auto.read.length} card${auto.read.length === 1 ? "" : "s"} done${errors.length ? `, ${errors.length} error${errors.length === 1 ? "" : "s"}` : ""}.`
        : any ? "Not run yet." : "Off until a key is set (OPENROUTER_API_KEY)."),
    errors.length ? h("p", { class: "small bad" }, errors.slice(-5).join(" · ")) : null,
    h("button", { class: `btn${auto.running ? " busy" : ""}`, disabled: auto.running || !any, onclick: readMissing,
      title: "Fill, check and review every card still missing something" }, "Run missing now"));
}

// The thesis criteria the dashboard's fit is judged by (rubric.json): gates, the stage window and where they came from.
// Defaults until A'Pelago and Redstone give their real ones; saving rewrites rubric.json and every fit follows.
function thesisPanel() {
  if (!S.theses) return null;
  const forms = Object.entries(S.theses).filter(([k]) => !k.startsWith("_")).map(([key, t]) => {
    const g = t.gates || {};
    const list = (v) => (v === "*" || !v ? "*" : v.join(", "));
    const inp = (value, attrs = {}) => h("input", { type: "text", value: value ?? "", ...attrs });
    const f = {
      sectors: inp(list(g.sectors), { "aria-label": "Sectors" }),
      countries: inp(list(g.countries), { "aria-label": "Countries", placeholder: "* or Finland, Nordic, EU, Baltic" }),
      tmin: inp(g.ticket_eur ? g.ticket_eur[0] : "", { type: "number", min: 0, step: 10000, placeholder: "min €", "aria-label": "Minimum ticket" }),
      tmax: inp(g.ticket_eur ? g.ticket_eur[1] : "", { type: "number", min: 0, step: 10000, placeholder: "max €", "aria-label": "Maximum ticket" }),
      scale: h("select", { "aria-label": "Stage scale" }, ["trl", "brl"].map((s) => h("option", { value: s, selected: t.window.scale === s }, s.toUpperCase()))),
      lo: inp(t.window.peak[0], { type: "number", min: 1, max: 9, "aria-label": "Band from" }),
      hi: inp(t.window.peak[1], { type: "number", min: 1, max: 9, "aria-label": "Band to" }),
      falloff: inp(t.window.falloff, { type: "number", min: 1, max: 9, step: 0.5, "aria-label": "Falloff" }),
      note: inp(t.criteria_note, { "aria-label": "Where these criteria come from", maxlength: 400 }),
    };
    const num = (el) => (el.value === "" ? null : Number(el.value));
    const split = (el) => el.value.split(",").map((s) => s.trim()).filter(Boolean);
    const read = () => ({ sectors: split(f.sectors), countries: split(f.countries),
      ticket_eur: num(f.tmin) === null && num(f.tmax) === null ? null : [num(f.tmin), num(f.tmax)],
      window: { scale: f.scale.value, peak: [num(f.lo), num(f.hi)], falloff: num(f.falloff) }, criteria_note: f.note.value });
    const row = (label, ...kids) => h("label", {}, label, h("div", { class: "row" }, kids));
    return { key, read, el: h("div", { class: "form thesis-form" }, h("h3", {}, t.label),
      row("Sectors (words in the sector or pitch; * = any)", f.sectors),
      row("Countries or regions", f.countries),
      row("Ticket size, €", f.tmin, "–", f.tmax),
      row("Stage band where fit peaks", f.scale, f.lo, "–", f.hi, "falls to 0 over", f.falloff, "levels"),
      row("Source of these criteria", f.note)) };
  });
  async function save(btn) {
    btn.disabled = true;
    try {
      S.theses = await post("/api/admin/rubric/theses", Object.fromEntries(forms.map((x) => [x.key, x.read()])), "PUT");
      PD.toast("Thesis criteria saved: every fit on the Dashboard follows");
    } catch (e) { PD.toast(e.message, 6000); }
    render();
  }
  return h("section", { class: "panel" }, h("h2", {}, "Thesis criteria"),
    h("p", { class: "muted small" }, "Out-of-scope gates, then the stage band where each holder fits best. These are editable defaults, not ",
      "A'Pelago's or Redstone's real thesis: enter theirs here and note where they came from. Unknowns (no country, no ask) never count against a startup."),
    forms.map((x) => x.el),
    h("button", { class: "btn primary", onclick: (e) => save(e.currentTarget) }, "Save criteria"));
}

function render() {
  const reset = (scope, label, question, danger) => h("button", { class: `btn${danger ? " danger" : ""}`, onclick: async () => {
    if (!confirm(question)) return;
    await post("/api/admin/reset", { scope });
    PD.toast("Done");
    await refresh();
  } }, label);
  $app.replaceChildren(
    h("div", { class: "head" }, h("h1", {}, "Admin")),
    h("div", { class: "split" },
      h("div", {}, readsPanel(), thesisPanel(), h("section", { class: "panel" }, h("h2", {}, "Export"),
        h("div", { class: "row" },
          h("a", { class: "btn", href: "/api/admin/export.csv" }, "CSV"),
          h("a", { class: "btn", href: "/api/admin/export.json" }, "JSON")))),
      h("section", { class: "panel" }, h("h2", {}, "Reset"),
        h("div", { class: "row" },
          reset("seed", "Clear demo answers", "Remove the seeded players and their answers?"),
          reset("real", "Clear real answers", "Remove every real player's answers?", true),
          reset("everything", "Reset everything", "Delete all data and reload the sample companies and sets?", true)))));
}

async function refresh() {
  try {
    S.mode = await api("/api/admin/mode");
    if (!S.theses) S.theses = (await api("/api/admin/rubric")).theses;
    Tool.setInfo(S.mode);
    render();
    // Keep polling while the background work runs, so its progress shows up on its own.
    clearTimeout(S.poll);
    if (S.mode.reads.auto.running) S.poll = setTimeout(refresh, 3000);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(refresh);
refresh();
