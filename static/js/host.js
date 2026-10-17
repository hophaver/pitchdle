// Dashboard: the opportunity radar. Every tracked company and every new discovery as a card with a call
// (back / watch / avoid), a lens on why (thesis, readiness, the game's crowd, the web), and its next move.
// Details opens the full read: readiness levels, thesis fit, ranked investors, grants, partners and clients.
const { h, api, post, fmt1 } = PD;
const $app = document.getElementById("app");

const LENSES = [["thesis", "Thesis"], ["readiness", "Readiness"], ["game", "Game"], ["web", "Web"]];
const FILTERS = [["all", "All"], ["back", "Back"], ["watch", "Watch"], ["avoid", "Avoid"], ["evidence", "Needs evidence"], ["new", "New"]];
const SORTS = [["redstone", "Redstone fit"], ["apelago", "A'Pelago fit"], ["readiness", "Readiness"], ["gap", "Crowd gap"]];
const KIND_LABEL = { investor: "Investors", grant: "Grants", partner: "Partners", client: "Clients" };
const LEVELS = [["ocean_impact", "Ocean impact"], ["business", "Business"], ["tech", "Technology"], ["investment", "Investment"]];
const DEFS = {
  readiness: "Ocean impact: how proven the ocean benefit is (Ocean Impact Navigator). Business: market, value proposition and "
    + "business model validation (KTH BRL). Technology: TRL 1–9 from evidence such as pilots and deployments, never a self-claim. "
    + "Investment: market, product, team, model, competition, distribution, financials, tech, deal, impact. Scores 0–5.",
  thesis: "Redstone: early-stage blue-economy venture lens (market, product, team, model, financials, deal). "
    + "A'Pelago: accelerator lens (ocean impact, business readiness, team). 0–5, from evidence alone.",
};

const state = {
  lens: localStorageGet("pd.lens") || "thesis", filter: "all", sort: "redstone", realOnly: false,
  open: null, busy: new Set(), searching: false,
};
let data = null;
let lastSig = null;

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// --- small pieces -----------------------------------------------------------------------------------

function nameLink(name, url) {
  return url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, name) : name;
}

function callChip(c) {
  return c.kind === "cand" ? h("span", { class: "call new" }, "New") : h("span", { class: `call ${c.call.key}` }, c.call.label);
}

function bar(label, score, extra = "") {
  const none = score === null || score === undefined;
  const cls = none ? "none" : score >= 3.5 ? "hi" : score < 2.5 ? "lo" : "";
  return h("div", { class: `bar ${cls}` }, h("span", { class: "k" }, label),
    h("span", { class: "t" }, h("i", { style: { width: none ? "0" : `${(score / 5) * 100}%` } })),
    h("span", { class: "v" }, none ? "–" : `${extra}${fmt1(score)}`));
}

function track(c) {
  const pct = (v) => `${(v / 5) * 100}%`;
  const crowd = c.crowd.n ? c.crowd.composite : null;
  const engine = c.engine.composite;
  const lo = crowd === null ? engine : Math.min(crowd, engine);
  const hi = crowd === null ? engine : Math.max(crowd, engine);
  return h("div", { class: "track", role: "img", "aria-label": `Crowd ${fmt1(crowd)}, engine ${fmt1(engine)}` },
    [0, 1, 2, 3, 4, 5].map((t) => h("i", { class: "tick", style: { left: pct(t) } })),
    h("i", { class: "span", style: { left: pct(lo), width: `${((hi - lo) / 5) * 100}%` } }),
    h("i", { class: "dot engine", style: { left: pct(engine) } }),
    crowd === null ? null : h("i", { class: "dot crowd", style: { left: pct(crowd) } }));
}

function lean(p) {
  return h("span", { class: `lean ${p.lean}` }, h("i"), `${p.lean} · ${plural(p.items_total, "hit")}`);
}

const short = (label) => label.replace(/\s*\(.*\)\s*/, "").toLowerCase();
const known = (c) => c.coverage && c.coverage.assessed > 0;
const extremes = (c) => {
  const f = [...(c.factors || [])].sort((a, b) => b.value - a.value);
  return f.length >= 2 ? [f[0], f[f.length - 1]] : [];
};

// --- the lens on a card -----------------------------------------------------------------------------

function lensBody(c) {
  if (c.kind === "cand") return h("span", { class: "muted" }, "Not assessed yet");
  if (state.lens === "thesis") {
    const [top, low] = extremes(c);
    return [bar("Redstone", c.theses.redstone.score), bar("A'Pelago", c.theses.apelago.score),
      top ? h("span", { class: "muted" }, `+ ${short(top.label)} ${fmt1(top.value)}   − ${short(low.label)} ${fmt1(low.value)}`) : null];
  }
  if (state.lens === "readiness") {
    return LEVELS.map(([k, label]) => {
      const lv = c.readiness[k];
      return k === "tech" && lv.trl ? bar(label, lv.score, `TRL ${lv.trl} · `) : bar(label, lv.score);
    });
  }
  if (state.lens === "game") {
    if (!c.crowd.n) return h("span", { class: "muted" }, "Not played yet");
    return [track(c), h("span", { class: "muted" },
      h("span", {}, h("i", { class: "key crowd" }), `crowd ${fmt1(c.crowd.composite)}`), "  ",
      h("span", {}, h("i", { class: "key engine" }), `engine ${known(c) ? fmt1(c.engine.composite) : "–"}`),
      ` · ${plural(c.crowd.n, "answer")}`),
    c.flags.length ? h("span", {}, c.flags.map((f) => f.label).join(" · ")) : null];
  }
  const p = c.pulse;
  if (!p) return h("span", { class: "muted" }, "Not checked");
  const top = p.top_hits[0];
  return [lean(p), top ? h("a", { href: top.link, target: "_blank", rel: "noopener noreferrer", class: "muted" }, top.title) : null];
}

// --- cards ------------------------------------------------------------------------------------------

function card(c) {
  if (c.kind === "cand") {
    const sc = c.screen || {};
    const where = sc.verdict === "kept" && (sc.based_in || c.country_tag) ? sc.based_in || c.country_tag : "";
    const busy = state.busy.has(`c${c.id}`);
    return h("article", { class: "rc new" },
      h("div", { class: "top" }, h("div", { class: "name" }, nameLink(c.name, c.url)), callChip(c)),
      h("div", { class: "meta" }, [c.card?.sector || c.sector_query, where].filter(Boolean).join(" · ") || " "),
      h("div", { class: "what" }, c.card?.one_liner || c.snippet),
      c.card?.claim_ask ? h("div", { class: "ask" }, c.card.claim_ask) : null,
      h("div", { class: "foot" },
        h("button", { class: `btn primary${busy ? " busy" : ""}`, disabled: busy, onclick: () => track_(c) }, busy ? "Tracking…" : "Track"),
        h("button", { class: "btn link", disabled: busy, onclick: () => dismiss(c) }, "Dismiss")));
  }
  const n = c.next;
  return h("article", { class: "rc" },
    h("div", { class: "top" }, h("div", { class: "name" }, nameLink(c.name, c.website)), callChip(c)),
    h("div", { class: "meta" }, [c.sector, c.country].filter(Boolean).join(" · ") || " "),
    h("div", { class: "what" }, c.one_liner),
    c.claim_ask ? h("div", { class: "ask" }, c.claim_ask) : null,
    h("div", { class: "lens" }, lensBody(c)),
    n && n.with ? h("div", { class: "next" }, h("b", {}, "Next: "), `${n.text} with `, nameLink(n.with, n.url)) : null,
    h("div", { class: "foot" }, h("button", { class: "btn", onclick: () => openDrawer(c.id) }, "Details")));
}

async function track_(c) {
  state.busy.add(`c${c.id}`);
  render();
  try {
    await post(`/api/admin/discover/${c.id}/approve`, {});
    PD.toast(`${c.name} tracked`);
  } catch (e) { PD.toast(e.message); }
  state.busy.delete(`c${c.id}`);
  refresh(true);
}

async function dismiss(c) {
  try { await post(`/api/admin/discover/${c.id}`, undefined, "DELETE"); } catch (e) { PD.toast(e.message); }
  refresh(true);
}

// --- details drawer ---------------------------------------------------------------------------------

// "#co-12" opens company 12's details, so a read can be linked to.
function openDrawer(id) {
  state.open = id;
  history.replaceState(null, "", `#co-${id}`);
  renderDrawer();
}

function closeDrawer() {
  state.open = null;
  history.replaceState(null, "", location.pathname);
  renderDrawer();
}

async function runPulse(c, btn) {
  btn.disabled = true;
  btn.classList.add("busy");
  try { await post(`/api/admin/pulse/run/${c.id}`, {}); } catch (e) { PD.toast(e.message); }
  await refresh(true);
}

function renderDrawer() {
  document.querySelectorAll(".drawer, .scrim").forEach((el) => el.remove());
  const c = state.open && data && data.companies.find((x) => x.id === state.open);
  if (!c) return;
  const groups = Object.keys(KIND_LABEL).map((k) => [k, c.actions.filter((a) => a.kind === k)]).filter(([, list]) => list.length);
  const n = c.next;
  const p = c.pulse;
  const drawer = h("aside", { class: "drawer", role: "dialog", "aria-label": c.name },
    h("button", { class: "btn link close", "aria-label": "Close", onclick: closeDrawer }, "Close"),
    h("h2", {}, nameLink(c.name, c.website)),
    h("div", { class: "muted small" }, [c.sector, c.country].filter(Boolean).join(" · ")),
    h("p", { class: "small", style: { margin: ".5rem 0 0" } }, c.one_liner, c.claim_ask ? h("span", { class: "muted" }, ` — ${c.claim_ask}`) : null),

    h("h3", {}, "Call"),
    h("div", { class: "row" }, callChip(c)),
    h("ul", { class: "small", style: { marginTop: ".4rem" } }, c.call.reasons.map((r) => h("li", {}, r))),
    n ? h("div", { class: "move small" }, h("b", {}, n.text), n.with ? [" with ", nameLink(n.with, n.url)] : null,
      h("div", { class: "muted" }, `Gap: ${n.gap_label} ${n.gap_score === null ? "unknown" : fmt1(n.gap_score)}`)) : null,

    h("h3", {}, "Readiness", Tool.tip(DEFS.readiness)),
    h("div", { style: { display: "grid", gap: ".3rem" } }, LEVELS.map(([k, label]) => {
      const lv = c.readiness[k];
      return h("div", {}, k === "tech" && lv.trl ? bar(label, lv.score, `TRL ${lv.trl} · `) : bar(label, lv.score),
        lv.coverage ? h("div", { class: "muted", style: { fontSize: ".7rem", marginLeft: "104px" } },
          `${lv.coverage.assessed}/${lv.coverage.total} factors known`) : null);
    })),

    h("h3", {}, "Thesis fit", Tool.tip(DEFS.thesis)),
    Object.values(c.theses).map((t) => h("div", { style: { marginBottom: ".45rem" } }, bar(t.label.split(" ")[0], t.score),
      t.why ? h("div", { class: "muted small" }, t.why) : null)),

    h("h3", {}, "Next steps, ranked"),
    groups.length ? groups.map(([k, list]) => [h("div", { class: "small", style: { fontWeight: 700, margin: ".5rem 0 .3rem" } }, KIND_LABEL[k]),
      h("div", { class: "steps" }, list.map((a, i) => h("div", { class: "step small" },
        h("span", { class: "n" }, nameLink(a.name, a.url)), h("span", { class: "fit" }, `#${i + 1}`),
        h("span", { class: "w" }, [a.why, ...(a.reasons || [])].filter(Boolean).join(" · ")))))])
      : h("p", { class: "muted small" }, "No matches."),

    h("h3", {}, "Crowd vs engine"),
    c.crowd.n ? [track(c), h("div", { class: "muted small", style: { marginTop: ".3rem" } },
      `Crowd ${fmt1(c.crowd.composite)} · engine ${fmt1(c.engine.composite)} · ${plural(c.crowd.n, "answer")}`),
    c.flags.map((f) => h("div", { class: "small" }, `${f.label}: ${f.detail}`))]
      : h("p", { class: "muted small" }, "Not played yet."),

    h("h3", {}, "Web"),
    p ? [lean(p), h("ul", { class: "small", style: { marginTop: ".35rem" } }, p.top_hits.slice(0, 5).map((t) =>
      h("li", {}, h("a", { href: t.link, target: "_blank", rel: "noopener noreferrer" }, t.title))))] : null,
    h("button", { class: "btn", style: { marginTop: ".5rem" }, onclick: (e) => runPulse(c, e.currentTarget) }, p ? "Refresh" : "Check the web"),

    c.evidence_note ? [h("h3", {}, "Sources"), h("p", { class: "muted small" }, c.evidence_note)] : null);
  document.body.append(h("div", { class: "scrim", onclick: closeDrawer }), drawer);
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.open) closeDrawer(); });

// --- page -------------------------------------------------------------------------------------------

function items() {
  const cos = data.companies.map((c) => ({ ...c, kind: "co" }));
  const cands = data.candidates.map((c) => ({ ...c, kind: "cand" }));
  return { cos, cands };
}

function readinessMean(c) {
  const s = Object.values(c.readiness).map((l) => l.score).filter((v) => v !== null);
  return s.length ? s.reduce((a, b) => a + b, 0) / s.length : -1;
}

const SORT = {
  redstone: (c) => c.theses.redstone.score ?? -1,
  apelago: (c) => c.theses.apelago.score ?? -1,
  readiness: readinessMean,
  gap: (c) => (c.gap === null ? -1 : Math.abs(c.gap)),
};

function searchRow() {
  const country = h("input", { type: "text", placeholder: "Country", maxlength: 40, "aria-label": "Country" });
  const field = h("input", { type: "text", placeholder: "Field (optional)", maxlength: 60, "aria-label": "Field" });
  async function find() {
    if (country.value.trim().length < 2 && field.value.trim().length < 2) return country.focus();
    state.searching = true;
    btn.disabled = true;
    btn.textContent = "Finding…";
    try {
      const found = await post("/api/admin/discover/search", { sector: field.value.trim(), country: country.value.trim(), limit: 8 });
      PD.toast(found.length ? `${plural(found.length, "startup")} found` : "Nothing found");
      state.filter = "new";
    } catch (e) { PD.toast(e.message); }
    state.searching = false;
    refresh(true);
  }
  const btn = h("button", { class: "btn primary", disabled: state.searching, onclick: find }, state.searching ? "Finding…" : "Find startups");
  [country, field].forEach((el) => el.addEventListener("keydown", (e) => { if (e.key === "Enter") find(); }));
  return data.mode === "live" ? h("div", { class: "row" }, country, field, btn) : null;
}

function render() {
  if (!data) return;
  const { cos, cands } = items();
  const count = { all: cos.length + cands.length, new: cands.length };
  for (const c of cos) count[c.call.key] = (count[c.call.key] || 0) + 1;
  const sorted = (arr) => [...arr].sort((a, b) => SORT[state.sort](b) - SORT[state.sort](a) || a.name.localeCompare(b.name));
  const list = state.filter === "new" ? cands
    : state.filter === "all" ? [...sorted(cos), ...cands]
      : sorted(cos.filter((c) => c.call.key === state.filter));

  const seg = (opts, cur, pick) => h("div", { class: "seg", role: "group" }, opts.map(([k, label]) =>
    h("button", { type: "button", "aria-pressed": String(cur === k), onclick: () => pick(k) }, label)));

  $app.replaceChildren(...[
    h("div", { class: "head" }, h("h1", {}, "Dashboard"), h("span", { class: "spacer" }), searchRow()),
    h("div", { class: "toolbar" },
      h("div", { class: "chips", role: "group", "aria-label": "Show" }, FILTERS.filter(([k]) => k === "all" || count[k]).map(([k, label]) =>
        h("button", { "aria-pressed": String(state.filter === k), onclick: () => { state.filter = k; render(); } }, label, h("b", {}, count[k] || 0)))),
      h("span", { class: "spacer" }),
      seg(LENSES, state.lens, (k) => { state.lens = k; localStorageSet("pd.lens", k); render(); }),
      h("select", { "aria-label": "Sort", onchange: (e) => { state.sort = e.target.value; render(); } },
        SORTS.map(([k, label]) => h("option", { value: k, selected: state.sort === k }, label))),
      state.lens === "game" ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: state.realOnly,
        onchange: (e) => { state.realOnly = e.target.checked; refresh(true); } }), "Real answers only") : null),
    list.length ? h("div", { class: "grid" }, list.map(card))
      : h("p", { class: "empty" }, data.mode === "live" ? "No startups yet. Find some above." : "No companies."),
  ].filter(Boolean));
}

async function refresh(force = false) {
  let fresh;
  try {
    fresh = await api(`/api/host/radar?real_only=${state.realOnly}`);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
    return;
  }
  const sig = JSON.stringify(fresh);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  // Whatever comes back, only the current mode's pool is drawn.
  fresh.companies = fresh.companies.filter((c) => c.is_real === (fresh.mode === "live"));
  data = fresh;
  render();
  if (state.open) renderDrawer();
}

state.open = Number((location.hash.match(/^#co-(\d+)$/) || [])[1]) || null;
Tool.onMode(() => { state.open = null; state.filter = "all"; renderDrawer(); refresh(true); });
refresh(true);
// Quietly pick up autofill finds and new answers, never while the host is reading details or typing.
setInterval(() => {
  const typing = document.activeElement && ["INPUT", "SELECT"].includes(document.activeElement.tagName);
  if (!document.hidden && !state.open && !typing && !state.searching) refresh();
}, 15000);
