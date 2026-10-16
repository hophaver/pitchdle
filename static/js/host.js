// Host dashboard: crowd vs engine vs web pulse per company, what needs attention, ranked next actions.
const { h, api, post, AXES, AXIS, fmt1 } = PD;
const $app = document.getElementById("app");
const state = { realOnly: false, open: new Set(), sort: { key: "name", dir: 1 }, verdict: "", pulsing: new Set(), runningAll: false };
let data = null;
let lastSig = null;

// Kept across renders so typing and choosing aren't interrupted by the background refresh.
const search = h("input", { type: "search", placeholder: "Filter by name or sector", "aria-label": "Filter companies", oninput: () => render() });
const verdictSel = h("select", { "aria-label": "Filter by verdict", onchange: (e) => { state.verdict = e.target.value; render(); } },
  h("option", { value: "" }, "All verdicts"), h("option", { value: "divergent" }, "Divergent"),
  h("option", { value: "convergent" }, "Convergent"), h("option", { value: "unknown" }, "Unknown"));

const VERDICT = {
  convergent: { icon: "✓", label: "Convergent" },
  divergent: { icon: "⚠", label: "Divergent" },
  unknown: { icon: "?", label: "Unknown" },
};
const VERDICT_ORDER = { divergent: 0, unknown: 1, convergent: 2 };
const LEAN_SHORT = { positive: "pos", negative: "neg", mixed: "mixed", neutral: "neutral", silent: "silent" };

const gapClass = (g) => (g === null ? "" : Math.abs(g) >= 1 ? "gap-hi" : Math.abs(g) >= 0.5 ? "gap-mid" : "");
const signed = (n) => (n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${Number(n).toFixed(1)}`);
const unevidenced = (v) => v === null || v === undefined;
const fitClass = (score) => (unevidenced(score) ? "muted" : score >= 3.5 ? "fit-hi" : score <= 2.0 ? "fit-lo" : "");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function verdictBadge(c) {
  const v = VERDICT[c.verdict] || VERDICT.unknown;
  return h("span", { class: `badge ${c.verdict}`, title: c.verdict_reason }, h("span", { "aria-hidden": "true" }, v.icon), v.label);
}

function leanBadge(lean) {
  return h("span", { class: `badge ${lean}` }, LEAN_SHORT[lean] || lean);
}

// Crowd and engine composites on one 0–5 line, so the gap reads at a glance.
function track(c) {
  const pct = (v) => `${(v / 5) * 100}%`;
  const crowd = c.crowd.n ? c.crowd.composite : null;
  const engine = c.engine.composite;
  const lo = crowd === null ? engine : Math.min(crowd, engine);
  const hi = crowd === null ? engine : Math.max(crowd, engine);
  const title = `Crowd ${crowd === null ? "no answers yet" : fmt1(crowd)} · Engine ${fmt1(engine)}`;
  return h("div", { class: "row", style: { gap: ".6rem", flexWrap: "nowrap" }, title },
    h("div", { class: "track", role: "img", "aria-label": title },
      [0, 1, 2, 3, 4, 5].map((t) => h("i", { class: "tick", style: { left: pct(t) } })),
      h("i", { class: "span", style: { left: pct(lo), width: `${((hi - lo) / 5) * 100}%` } }),
      h("i", { class: "dot engine", style: { left: pct(engine) } }),
      crowd === null ? null : h("i", { class: "dot crowd", style: { left: pct(crowd) } })),
    h("span", { class: "num small" }, `${fmt1(crowd)} / ${fmt1(engine)}`));
}

async function runPulse(c, ev) {
  ev.stopPropagation();
  if (state.pulsing.has(c.id)) return;
  state.pulsing.add(c.id);
  render();
  try {
    const p = await post(`/api/admin/pulse/run/${c.id}`, {});
    PD.toast(`${c.name}: ${plural(p.items_total, "web hit")}${p.errors.length ? ` (${p.errors.length} feed${p.errors.length === 1 ? "" : "s"} failed)` : ""}`);
  } catch (e) { PD.toast(e.message); }
  state.pulsing.delete(c.id);
  refresh();
}

async function runAll() {
  if (state.runningAll) return;
  state.runningAll = true;
  render();
  try {
    const r = await post("/api/admin/pulse/run-all", { active_only: true });
    PD.toast(`Web pulse ran for ${plural(r.ran, "company")}${r.errors.length ? ` · ${r.errors.length} with feed errors` : ""}`, 4500);
  } catch (e) { PD.toast(e.message); }
  state.runningAll = false;
  refresh();
}

function pulseCell(c) {
  if (state.pulsing.has(c.id) || state.runningAll && c.active) return h("span", { class: "muted small" }, "Running…");
  const p = c.pulse;
  return h("button", { class: "pulse-cell", type: "button", onclick: (e) => runPulse(c, e),
    title: p ? `Fetched ${p.fetched_at.slice(0, 16).replace("T", " ")} · click to refresh` : "Click to run web pulse" },
  p ? [h("span", { class: "n" }, `${p.items_total} hits`), leanBadge(p.lean)] : h("span", { class: "n muted" }, "Run"));
}

// --- expanded row ----------------------------------------------------------------------------------

function crowdRead(c) {
  const m = c.crowd.means || {};
  return h("div", { class: "read crowd" },
    h("h4", {}, h("span", {}, h("i", { class: "key crowd" }), "Crowd"), h("b", {}, fmt1(c.crowd.n ? c.crowd.composite : null))),
    h("dl", {}, AXES.map((a) => [h("dt", {}, AXIS[a]), h("dd", {}, fmt1(m[a]))]),
      h("dt", {}, "Answers"), h("dd", {}, `${c.crowd.n}${c.crowd.signed_in ? ` (${c.crowd.signed_in} signed in)` : ""}`),
      h("dt", {}, "Split (std-dev)"), h("dd", {}, c.crowd.consensus === null ? "–" : fmt1(c.crowd.consensus))));
}

function engineRead(c) {
  const unknown = c.coverage.unknown || [];
  return h("div", { class: "read engine" },
    h("h4", {}, h("span", {}, h("i", { class: "key engine" }), "Engine"), h("b", {}, fmt1(c.engine.composite))),
    h("dl", {}, AXES.map((a) => [h("dt", {}, AXIS[a]), h("dd", {}, fmt1(c.engine.axes[a]))]),
      h("dt", {}, "Evidence coverage"), h("dd", {}, `${c.coverage.assessed}/${c.coverage.total} factors`)),
    unknown.length ? h("p", { class: "note" }, `Unknown: ${unknown.slice(0, 6).join(", ")}${unknown.length > 6 ? ` +${unknown.length - 6} more` : ""}`) : null);
}

function webRead(c) {
  const p = c.pulse;
  if (!p) {
    return h("div", { class: "read web" },
      h("h4", {}, "Web pulse"),
      h("p", { class: "note" }, "Not run yet. Pulls public news and Hacker News coverage; a hint for you, never part of the score."),
      h("button", { class: "btn small", onclick: (e) => runPulse(c, e) }, "Run web pulse"));
  }
  return h("div", { class: "read web" },
    h("h4", {}, "Web pulse", leanBadge(p.lean)),
    h("dl", {},
      h("dt", {}, "Items found"), h("dd", {}, p.items_total),
      h("dt", {}, "Last 30 days"), h("dd", {}, p.items_recent),
      h("dt", {}, "Positive / risk"), h("dd", {}, `${p.good_count} / ${p.risk_count}`),
      h("dt", {}, "Coverage"), h("dd", {}, p.coverage)),
    p.top_hits.length ? h("ul", {}, p.top_hits.slice(0, 5).map((t) => h("li", {},
      h("a", { href: t.link, target: "_blank", rel: "noopener noreferrer" }, t.title),
      h("span", { class: "muted" }, ` · ${t.source}${t.published ? ` · ${t.published}` : ""}`)))) : null,
    h("p", { class: "note" }, `Fetched ${p.fetched_at.slice(0, 10)} from ${p.sources.join(", ") || "no sources"}.`,
      p.errors.length ? h("span", { class: "thin" }, ` ${p.errors.join(" · ")}`) : null, " ",
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); runPulse(c, e); } }, "Refresh")));
}

function detailRow(c, colspan) {
  const rd = c.readiness || {};
  const levels = ["ocean_impact", "business", "tech", "investment"].filter((k) => rd[k]).map((k) => {
    const l = rd[k];
    return [h("dt", {}, l.label || k),
      h("dd", {}, unevidenced(l.score) ? h("span", { class: "muted" }, "unevidenced") : `${fmt1(l.score)}${l.trl ? ` · TRL ${l.trl}` : ""}`,
        l.coverage ? h("span", { class: "muted" }, ` (${l.coverage.assessed}/${l.coverage.total})`) : null)];
  });
  const theses = Object.values(c.theses || {});
  return h("tr", { class: "detail" }, h("td", { colspan },
    h("div", { class: "verdict-bar" }, verdictBadge(c), h("span", {}, c.verdict_reason)),
    h("div", { class: "reads" }, crowdRead(c), engineRead(c), webRead(c)),
    h("div", { class: "detail-grid" },
      h("div", {},
        h("h3", {}, "Ranked next actions"),
        c.actions.length ? h("ol", {}, c.actions.map((a) => h("li", {},
          h("b", {}, a.name), h("span", { class: "muted small" }, ` · ${a.kind}${a.stage_fit ? ` · ${a.stage_fit}` : ""} · score ${a.score}`),
          h("div", { class: "small" }, a.why),
          a.boosted.length ? h("div", { class: "boost" }, `↑ ${a.boosted.join("; ")}`) : null)))
          : h("p", { class: "muted small" }, "No opportunities yet. Add them in Admin."),
        h("h3", {}, "Flags"),
        c.flags.length ? c.flags.map((f) => h("p", { class: "small", style: { margin: ".2rem 0" } }, h("span", { class: `flag ${f.key}` }, f.label), " ", f.detail))
          : h("p", { class: "muted small" }, c.crowd.n < 5 ? "Flags need 5+ answers." : "Crowd and engine broadly agree.")),
      h("div", {},
        levels.length ? [h("h3", {}, "Readiness levels"), h("div", { class: "read" }, h("dl", {}, levels))] : null,
        theses.length ? [h("h3", {}, "Thesis fit"), theses.map((t) => h("p", { class: "small", style: { margin: "0 0 .5rem" } },
          h("b", {}, t.label), " · ", h("span", { class: fitClass(t.score) }, unevidenced(t.score) ? "unevidenced" : `fit ${fmt1(t.score)}`),
          h("div", { class: "muted" }, t.why || t.description || "")))] : null)),
    c.factors && c.factors.length ? [h("h3", {}, "Evidence behind these numbers"),
      h("div", { class: "factor-trail" }, c.factors.map((f) => h("span", { class: "chip" }, `${f.label}: ${fmt1(f.value)}`)))] : null));
}

// --- table ----------------------------------------------------------------------------------------

const COLUMNS = [
  { label: "Company", sort: "name" },
  { label: "Answers", sort: "answers", num: true },
  { label: "Crowd / engine", sort: "crowd" },
  { label: "Gap", sort: "gap", num: true },
  { label: "Split", num: true },
  { label: "Coverage", num: true },
  { label: "Web pulse", sort: "web" },
  { label: "Verdict", sort: "verdict" },
  { label: "Flags" },
];

const SORTERS = {
  name: (c) => c.name.toLowerCase(),
  answers: (c) => c.crowd.n,
  crowd: (c) => (c.crowd.n ? c.crowd.composite : -1),
  gap: (c) => (c.gap === null ? -99 : c.gap),
  web: (c) => (c.pulse ? c.pulse.items_total : -1),
  verdict: (c) => VERDICT_ORDER[c.verdict] ?? 9,
};

function sorted(list) {
  const key = SORTERS[state.sort.key];
  return [...list].sort((a, b) => {
    const x = key(a), y = key(b);
    return (x < y ? -1 : x > y ? 1 : 0) * state.sort.dir || a.name.localeCompare(b.name);
  });
}

function header() {
  return h("tr", {}, COLUMNS.map((col) => {
    if (!col.sort) return h("th", { class: col.num ? "num" : "" }, col.label);
    const on = state.sort.key === col.sort;
    return h("th", { class: `sortable${col.num ? " num" : ""}`, "aria-sort": on ? (state.sort.dir > 0 ? "ascending" : "descending") : "none",
      onclick: () => { state.sort = { key: col.sort, dir: on ? -state.sort.dir : (col.sort === "name" || col.sort === "verdict" ? 1 : -1) }; render(); } },
    col.label, h("span", { class: "dir" }, on ? (state.sort.dir > 0 ? "↑" : "↓") : ""));
  }));
}

function companyRows(c) {
  const open = state.open.has(c.id);
  const row = h("tr", { class: `clickable${open ? " open" : ""}`, "aria-expanded": String(open), onclick: () => {
    open ? state.open.delete(c.id) : state.open.add(c.id);
    render();
  } },
  h("td", {}, h("div", { class: "row", style: { gap: ".3rem", flexWrap: "nowrap", alignItems: "flex-start" } },
    h("span", { class: "caret", "aria-hidden": "true" }, "›"),
    h("div", {}, h("div", { class: "co-name" }, c.name),
      h("div", { class: "co-meta" }, [c.sector, c.is_real ? "real" : null, c.active ? null : "inactive"].filter(Boolean).join(" · "))))),
  h("td", { class: "num" }, c.crowd.n),
  h("td", {}, track(c)),
  h("td", { class: `num ${gapClass(c.gap)}` }, signed(c.gap)),
  h("td", { class: "num" }, c.crowd.consensus === null ? "–" : fmt1(c.crowd.consensus)),
  h("td", { class: "num" }, `${c.coverage.assessed}/${c.coverage.total}`),
  h("td", {}, pulseCell(c)),
  h("td", {}, verdictBadge(c)),
  h("td", {}, c.flags.map((f) => h("span", { class: `flag ${f.key}`, title: f.detail }, f.label))));
  return open ? [row, detailRow(c, COLUMNS.length)] : row;
}

// --- page -----------------------------------------------------------------------------------------

function kpi(label, value, sub) {
  return h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}

function needsAttention(list) {
  const items = list.filter((c) => c.verdict === "divergent" || c.flags.length)
    .sort((a, b) => (VERDICT_ORDER[a.verdict] - VERDICT_ORDER[b.verdict]) || Math.abs(b.gap || 0) - Math.abs(a.gap || 0));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Needs attention"), h("span", { class: "muted small" }, "Divergent or flagged, biggest gap first")),
    items.length ? h("ul", { class: "attention" }, items.map((c) => h("li", {},
      h("div", {}, h("div", { class: "co-name" }, c.name), h("div", { class: "row", style: { gap: ".3rem", marginTop: ".25rem" } },
        verdictBadge(c), c.flags.map((f) => h("span", { class: `flag ${f.key}`, title: f.detail }, f.label)))),
      h("div", {}, h("div", { class: "why" }, c.verdict_reason),
        c.actions[0] ? h("div", { class: "next" }, `Next: ${c.actions[0].name}. ${c.actions[0].why}`) : null))))
      : h("p", { class: "muted small", style: { margin: 0 } },
        "Nothing yet. Verdicts and flags need 5+ answers on a company; Admin → “Load demo votes” fills a set for rehearsal."));
}

function thesisPanel(list) {
  const ranked = [...list].filter((c) => c.theses).sort((x, y) => (y.theses?.redstone?.score ?? -1) - (x.theses?.redstone?.score ?? -1));
  if (!ranked.length) return null;
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Thesis fit"), h("span", { class: "muted small" }, "From the evidence alone, no crowd needed")),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, h("th", {}, "Company"), Object.values(ranked[0].theses).map((t) => h("th", { class: "num" }, t.label)), h("th", {}, "Why"))),
      h("tbody", {}, ranked.slice(0, 5).map((c) => h("tr", {},
        h("td", {}, h("div", { class: "co-name" }, c.name), h("div", { class: "co-meta" }, c.sector)),
        Object.values(c.theses).map((t) => h("td", { class: `num ${fitClass(t.score)}` }, unevidenced(t.score) ? "–" : fmt1(t.score))),
        h("td", { class: "small muted wide" }, c.theses?.redstone?.why || "")))))));
}

function render() {
  if (!data) return;
  const all = data.companies;
  const q = search.value.trim().toLowerCase();
  const shown = sorted(all.filter((c) => (!q || `${c.name} ${c.sector}`.toLowerCase().includes(q))
    && (!state.verdict || c.verdict === state.verdict)));
  const active = all.filter((c) => c.active);
  const answers = all.reduce((s, c) => s + (c.crowd.n || 0), 0);
  const signedIn = all.reduce((s, c) => s + (c.crowd.signed_in || 0), 0);
  const pulsed = active.filter((c) => c.pulse).length;
  const scroll = window.scrollY;

  $app.replaceChildren(
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Perception vs reality"),
        h("p", {}, "How the room reads each startup, what the evidence says, and what the open web shows.")),
      h("span", { class: "spacer" }),
      h("label", { class: "check" },
        h("input", { type: "checkbox", checked: state.realOnly, onchange: (e) => { state.realOnly = e.target.checked; refresh(); } }),
        "Real answers only"),
      h("button", { class: `btn${state.runningAll ? " busy" : ""}`, disabled: state.runningAll, onclick: runAll,
        title: "Fetch public coverage for every active company. Never changes scores." },
      state.runningAll ? "Running web pulse…" : "Run web pulse for all"),
      h("a", { class: "btn", href: "/api/admin/export.csv" }, "Export CSV"),
      h("a", { class: "btn", href: "/api/admin/export.json" }, "JSON")),
    h("div", { class: "kpis" },
      kpi("Active companies", active.length, `${all.length} in total`),
      kpi(state.realOnly ? "Real answers" : "Answers", answers, `${signedIn} from signed-in players`),
      kpi("Flagged", all.filter((c) => c.flags.length).length, "story, substance or split"),
      kpi("Divergent", all.filter((c) => c.verdict === "divergent").length,
        `${all.filter((c) => c.verdict === "convergent").length} convergent`),
      kpi("Web pulse", h("span", {}, pulsed, h("small", {}, ` / ${active.length}`)), "active companies checked")),
    needsAttention(all),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", {}, "Companies"), h("span", { class: "spacer" }),
        h("div", { class: "legend" },
          h("span", {}, h("i", { class: "key crowd" }), "Crowd"), h("span", {}, h("i", { class: "key engine" }), "Engine"),
          h("span", {}, "Gap = crowd − engine"))),
      h("div", { class: "toolbar" }, search, verdictSel,
        h("span", { class: "muted small" }, `${shown.length} of ${all.length}`)),
      h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, header()),
        h("tbody", {}, shown.length ? shown.map(companyRows)
          : h("tr", {}, h("td", { colspan: COLUMNS.length, class: "muted" }, "No companies match."))))),
      h("p", { class: "muted small", style: { margin: ".7rem 0 0" } },
        "Split is how much the crowd disagrees with itself. Coverage is how many evidence factors the engine knows. Click a row for the full triangulation.")),
    thesisPanel(all));
  window.scrollTo({ top: scroll });
}

async function refresh(force = true) {
  let fresh;
  try {
    fresh = await api(`/api/host/overview?real_only=${state.realOnly}`);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
    return;
  }
  // Background refreshes skip the rebuild when nothing changed (keeps scroll and open rows steady).
  const sig = JSON.stringify(fresh);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  data = fresh;
  render();
}

refresh();
setInterval(() => { if (!document.hidden && !state.runningAll) refresh(false); }, 5000);
