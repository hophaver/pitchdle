// Dashboard: the opportunity radar. Every tracked company and every new discovery as a card with a call
// (back / watch / avoid), a lens on why (thesis, readiness, the game's crowd, the web), and its next move.
// Details opens the startup's full card: everything an investor's game card shows, and the radar's whole read.
const { h, api, post, fmt1, AXES, AXIS } = PD;
const $app = document.getElementById("app");

const LENSES = [["thesis", "Thesis"], ["readiness", "Readiness"], ["game", "Game"], ["opinions", "Opinions"], ["web", "Web"]];
const COUNT_WORD = { crowd: "answer", apelago: "reviewer" }; // social media counts posts
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

// --- the startup's profile and outside opinions (what an investor's game card shows) ----------------

// The average of an opinion's four calls, for one bar per source.
const meanOf = (scores) => AXES.reduce((sum, a) => sum + scores[a], 0) / AXES.length;
const groupMean = (tiles) => (tiles.length ? tiles.reduce((sum, t) => sum + meanOf(t.scores), 0) / tiles.length : null);

// "€650k raised · Seed round · 3 investors": the card's facts on one line.
function factLine(c) {
  const invested = c.investors.filter((i) => i.status === "invested").length;
  const facts = [
    c.raised_eur === null || c.raised_eur === undefined ? null : `${PD.money(c.raised_eur)} raised`,
    c.stages.length ? c.stages[c.stages.length - 1] : null,
    invested ? plural(invested, "investor") : null,
  ].filter(Boolean);
  return facts.length ? h("div", { class: "facts-line" }, facts.map((f) => h("span", {}, f))) : null;
}

// One bar each for A'Pelago, the AI models and social media: the average of their four calls.
function opinionBars(c) {
  const of = (g) => c.opinions.filter((t) => t.group === g);
  const ap = c.opinions.find((t) => t.key === "apelago");
  const ai = of("ai");
  const social = of("social");
  if (!ap && !ai.length && !social.length) return [h("span", { class: "muted" }, "No outside opinions yet")];
  return [
    bar("A'Pelago", ap ? meanOf(ap.scores) : null),
    bar("AI models", groupMean(ai)),
    bar("Social", groupMean(social)),
    h("span", { class: "muted" }, [ap ? plural(ap.count, "reviewer") : null, ai.length ? `${ai.map((t) => t.label).join(", ")}` : null,
      social.length ? social.map((t) => t.label).join(", ") : null].filter(Boolean).join(" · ")),
  ];
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
  if (state.lens === "opinions") return opinionBars(c);
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
    factLine(c),
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

// --- details: the startup's full card -------------------------------------------------------------
// The investor's game card made bigger and denser, sized to the window so it reads without scrolling: the pitch
// across the top with the call and next move beside it, then three columns. The startup (facts, stages, investors,
// vision, evidence); the radar's read (readiness, thesis fit, the ranked next steps); and what everyone makes of it (every
// read on the four calls in one table, crowd vs engine, the web). Long text is cut to fit and opens on a click.
// On a phone the columns stack and the card scrolls.

const money = (eur) => (eur === null || eur === undefined ? "Not disclosed" : PD.money(eur));
const sect = (title, ...kids) => h("section", { class: "sect" }, h("div", { class: "caps sect-title" }, title), ...kids);
const subTitle = (text) => h("div", { class: "caps sub-title" }, text);
const empty = (text) => h("p", { class: "op-empty" }, text);
// A paragraph cut to a few lines that opens in full on a click.
const clamp = (text, cls = "") => h("p", { class: `clamp ${cls}`, title: "Click to read it all", tabindex: "0",
  onclick: (e) => e.currentTarget.classList.toggle("open"),
  onkeydown: (e) => { if (e.key === "Enter") e.currentTarget.classList.toggle("open"); } }, text);

// The facts as the investor's game card shows them: raised so far, investors and stage, then every stage passed
// and every investor. A profile the AI filled says so.
function factsSect(c) {
  const invested = c.investors.filter((i) => i.status === "invested");
  const box = (label, value, cls = "") => h("div", { class: `fact-box ${cls}` }, h("small", { class: "caps" }, label), h("b", {}, value));
  const ai = c.profile && c.profile.status === "ai";
  return h("section", { class: "sect g-facts" },
    h("div", { class: "fact-grid" },
      box("Raised so far", money(c.raised_eur)),
      box("Investors", invested.length ? String(invested.length) : "None yet"),
      box("Stage", c.stages.length ? c.stages[c.stages.length - 1] : "Not given", "wide")),
    c.stages.length ? [subTitle("Stages passed"), h("ol", { class: "stage-list" }, c.stages.map((s) => h("li", {}, s)))] : null,
    c.investors.length ? [subTitle("Investors"),
      h("ul", { class: "investor-list" }, c.investors.map((i) => h("li", {}, h("b", {}, i.name), " ",
        i.status === "interested" ? h("span", { class: "interested" }, "interested")
          : i.amount_eur ? PD.money(i.amount_eur) : "invested")))] : null,
    ai ? h("p", { class: "note ai-note", title: c.profile.note }, "Filled by AI from its website and news. Check it.") : null,
    c.is_real && !ai && !c.stages.length && !c.investors.length && c.raised_eur == null
      ? h("p", { class: "note" }, "Not filled yet: the AI fills it in the background, or use Admin → Profile & opinions.") : null);
}

function startupCol(c) {
  return [
    factsSect(c),
    c.vision ? sect("Vision", h("div", { class: "clamp vision-text", title: "Click to read it all", tabindex: "0",
      onclick: (e) => e.currentTarget.classList.toggle("open"),
      onkeydown: (e) => { if (e.key === "Enter") e.currentTarget.classList.toggle("open"); } },
    c.vision.split(/\n{2,}/).map((p) => h("p", { class: "vision" }, p)))) : null,
    evidenceSect(c),
  ];
}

// Every evidence factor the engine scored, best first, with the sources.
function evidenceSect(c) {
  const f = [...(c.factors || [])].sort((a, b) => b.value - a.value);
  return f.length ? sect(`Evidence${c.coverage ? ` · ${c.coverage.assessed}/${c.coverage.total} factors` : ""}${c.review.pending ? " · to confirm" : " · reviewed"}`,
      f.length ? h("div", { class: "factor-grid" }, f.map((x) => h("div", { class: "factor", title: x.label },
        h("span", { class: "k" }, x.label.replace(/\s*\(.*\)\s*/, "")), h("span", { class: "t" }, h("i", { style: { width: `${(x.value / 5) * 100}%` } })),
        h("b", {}, fmt1(x.value))))) : null,
      c.evidence_note ? clamp(`Sources: ${c.evidence_note}`, "note sources") : null) : null;
}

// The call and the next move, beside the pitch in the header.
function callBox(c) {
  const n = c.next;
  return h("section", { class: "sect call-box" },
    h("div", { class: "caps sect-title" }, "The call ", callChip(c)),
    h("p", { class: "reasons" }, c.call.reasons.join(" · ")),
    n ? h("div", { class: "move" }, h("b", {}, n.text, n.with ? [" with ", nameLink(n.with, n.url)] : null),
      h("span", { class: "note" }, ` · weakest: ${n.gap_label.replace(/\s*\(.*\)/, "")} ${n.gap_score === null ? "unknown" : fmt1(n.gap_score)}`)) : null);
}

function readCol(c) {
  const factorList = (title, list) => (list && list.length
    ? h("div", { class: "note" }, `${title}: ${list.map((x) => `${short(x.label)} ${fmt1(x.value)}`).join(" · ")}`) : null);
  return [
    sect(["Readiness", Tool.tip(DEFS.readiness)],
      h("div", { class: "bars-list" }, LEVELS.map(([k, label]) => {
        const lv = c.readiness[k];
        const known_ = lv.coverage ? ` (${lv.coverage.assessed}/${lv.coverage.total})` : "";
        return h("div", { title: `${lv.label}: ${known_.trim() || "no"} factors known` },
          k === "tech" && lv.trl ? bar(label, lv.score, `TRL ${lv.trl} · `) : bar(label, lv.score));
      })),
      c.coverage && c.coverage.unknown && c.coverage.unknown.length
        ? clamp(`Unknown: ${c.coverage.unknown.join(", ")}`, "note") : null),
    sect(["Thesis fit", Tool.tip(DEFS.thesis)],
      Object.values(c.theses).map((t) => h("div", { class: "thesis" },
        bar(t.label.split(" ")[0], t.score),
        t.why ? clamp(t.why, "note") : null,
        factorList("Risks", t.risks)))),
    stepsSect(c),
  ];
}

// Every read of the startup on the same four calls: the engine's evidence, the crowd, A'Pelago, the AI models and
// social media. A row with a reason opens it on a click.
function readsTable(c) {
  const rows = [];
  if (known(c)) rows.push({ key: "engine", label: "Engine", scores: c.engine.axes, note: `From the evidence: ${c.coverage.assessed}/${c.coverage.total} factors known.` });
  rows.push(...c.opinions);
  const avg = (s) => AXES.reduce((sum, a) => sum + s[a], 0) / AXES.length;
  const cell = (v) => h("td", {}, h("span", { class: "v" }, fmt1(v)), h("i", { class: "mini", style: { "--v": v / 5 } }));
  const groupOf = (t) => (t.key === "engine" ? "engine" : t.group);
  const body = [];
  let last = null;
  for (const t of rows) {
    const g = groupOf(t);
    if (g !== last && g !== "engine") {
      body.push(h("tr", { class: "group" }, h("th", { colspan: 7 }, { people: "People", ai: "AI models", social: "Social media" }[g])));
    }
    last = g;
    const count = t.count ? plural(t.count, COUNT_WORD[t.key] || "post") : "";
    const tr = h("tr", { class: t.note ? "has-note" : "", title: t.note || "", onclick: t.note ? () => tr.classList.toggle("open") : null },
      h("th", {}, t.label, count ? h("small", {}, count) : null),
      AXES.map((a) => cell(t.scores[a])),
      h("td", { class: "avg" }, fmt1(avg(t.scores))),
      h("td", { class: "why" }, t.note ? h("span", {}, t.note) : null));
    body.push(tr);
  }
  const social = c.opinions.filter((t) => t.group === "social");
  const missing = [
    !c.crowd.n ? "nobody has played it yet" : null,
    !c.opinions.some((t) => t.key === "apelago") ? "A'Pelago hasn't rated it" : null,
    !c.opinions.some((t) => t.group === "ai") ? "no AI ratings yet" : null,
    !c.is_real && !social.length ? "no social media (made up)" : c.quiet.length ? `no posts on ${c.quiet.join(", ")}`
      : social.length ? null : "social media not read yet",
  ].filter(Boolean);
  return sect("What everyone makes of it",
    !rows.length ? null : h("table", { class: "reads" },
      h("colgroup", {}, h("col", { class: "c-who" }), AXES.map(() => h("col", { class: "c-num" })), h("col", { class: "c-num" }), h("col")),
      h("thead", {}, h("tr", {}, h("td"), AXES.map((a) => h("th", { title: AXIS[a] }, AXIS[a][0])), h("th", {}, "Avg"), h("th", { class: "why" }, "Why"))),
      h("tbody", {}, body)),
    missing.length ? h("p", { class: "note" }, `${missing.join(" · ")}.`.replace(/^./, (s) => s.toUpperCase())) : null);
}

function crowdSect(c) {
  if (!c.crowd.n) return null;
  return sect("Crowd vs engine",
    track(c),
    h("div", { class: "legend" }, h("span", {}, h("i", { class: "key crowd" }), `Crowd ${fmt1(c.crowd.composite)}`),
      h("span", {}, h("i", { class: "key engine" }), `Engine ${known(c) ? fmt1(c.engine.composite) : "–"}`),
      c.gap === null ? null : h("span", {}, `Gap ${c.gap > 0 ? "+" : ""}${fmt1(c.gap)}`),
      h("span", { class: "note" }, `${plural(c.crowd.n, "answer")} · ${c.crowd.signed_in} signed in · spread ${fmt1(c.crowd.consensus)}`)),
    c.flags.map((f) => h("div", { class: "note" }, h("b", {}, f.label), ` ${f.detail}`)));
}

function webSect(c) {
  const p = c.pulse;
  return sect("Web",
    h("div", { class: "row" }, p ? lean(p) : h("span", { class: "note" }, "Not checked yet."), h("span", { class: "spacer" }),
      h("button", { class: "pill ghost small", onclick: (e) => runPulse(c, e.currentTarget) }, p ? "Refresh" : "Check the web")),
    p && p.top_hits.length ? h("ul", { class: "hits" }, p.top_hits.slice(0, 3).map((t) =>
      h("li", {}, h("a", { href: t.link, target: "_blank", rel: "noopener noreferrer", title: t.title }, t.title)))) : null);
}

// The top matches of each kind on one line each; the rest open on a click.
function stepsSect(c) {
  const TOP = 2;
  const groups = Object.keys(KIND_LABEL).map((k) => [k, c.actions.filter((a) => a.kind === k)]).filter(([, l]) => l.length);
  const step = (a, i) => h("li", { title: [a.why, ...(a.reasons || []), ...(a.boosted || [])].filter(Boolean).join(" · ") },
    h("span", { class: "n" }, `${i + 1}`), h("b", {}, nameLink(a.name, a.url)),
    h("span", { class: "w" }, [a.stage_fit, a.why].filter(Boolean).join(" · ")));
  return sect("Next steps, ranked",
    groups.length ? h("div", { class: "steps" }, groups.map(([k, list]) => h("div", {},
      subTitle(KIND_LABEL[k]),
      h("ol", {}, list.slice(0, TOP).map(step)),
      list.length > TOP ? h("details", {}, h("summary", {}, `${list.length - TOP} more`),
        h("ol", { start: TOP + 1 }, list.slice(TOP).map((a, i) => step(a, i + TOP)))) : null)))
      : empty("No matches."));
}

function renderDrawer() {
  document.querySelectorAll(".dossier-wrap").forEach((el) => el.remove());
  document.body.classList.remove("dossier-open");
  const c = state.open && data && data.companies.find((x) => x.id === state.open);
  if (!c) return;
  const site = c.website && /^https?:\/\//i.test(c.website) ? c.website : null;
  const card = h("article", { class: "card dossier", style: { "--card": PD.colorFor(data.companies.indexOf(c)) },
    role: "dialog", "aria-modal": "true", "aria-label": c.name },
    h("header", { class: "dossier-head" },
      h("div", { class: "pitch" },
        h("div", { class: "name-row" }, c.emoji ? h("div", { class: "art small", "aria-hidden": "true" }, c.emoji) : null,
          h("div", {}, h("h2", {}, c.name),
            h("div", { class: "row meta" },
              h("span", { class: "caps sector" }, [c.sector, c.country, c.is_real ? "real startup" : "made-up startup"].filter(Boolean).join(" · ")),
              site ? h("a", { class: "site", href: site, target: "_blank", rel: "noopener noreferrer nofollow" },
                `${site.replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, "")} ↗`) : null))),
        h("p", { class: "pitch-line" }, c.one_liner || (c.vision || "").split(/(?<=[.!?])\s/)[0]),
        c.claim_ask ? h("p", { class: "ask" }, c.claim_ask) : null),
      callBox(c),
      h("button", { class: "close-x", "aria-label": "Close", title: "Close (Esc)", onclick: closeDrawer }, "✕")),
    h("div", { class: "dossier-grid" },
      h("div", { class: "col" }, startupCol(c)),
      h("div", { class: "col" }, readCol(c)),
      h("div", { class: "col" }, readsTable(c), crowdSect(c), webSect(c))));
  const wrap = h("div", { class: "dossier-wrap", onclick: (e) => { if (e.target === wrap) closeDrawer(); } }, card);
  document.body.append(wrap);
  document.body.classList.add("dossier-open");
  card.querySelector(".close-x").focus({ preventScroll: true });
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
