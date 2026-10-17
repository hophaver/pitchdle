// Dashboard: the opportunity radar. Every tracked company and every new discovery as a card with a call
// (back / watch / avoid), its reviews' average on the four calls, and its next move. Sorted by those reviews.
// Details opens the startup's full card: everything an investor's game card shows, and the radar's whole read.
const { h, api, post, fmt1, AXES, AXIS } = PD;
const $app = document.getElementById("app");

const COUNT_WORD = { crowd: "answer", apelago: "reviewer" }; // social media counts posts
const FILTERS = [["all", "All"], ["back", "Back"], ["watch", "Watch"], ["avoid", "Avoid"], ["evidence", "Needs evidence"], ["new", "New"]];
// Sorting is by the reviews' average (the game, AI models and social media): one of the four calls, or all four.
const SORTS = [["avg", "Average"], ["novel", "Novel"], ["useful", "Useful"], ["plausible", "Plausible"], ["investable", "Investable"]];
const KIND_LABEL = { investor: "Investors", grant: "Grants", partner: "Partners", client: "Clients" };
const LEVELS = [["ocean_impact", "Ocean impact"], ["business", "Business"], ["tech", "Technology"], ["investment", "Investment"]];
const DEFS = {
  readiness: "Ocean impact: how proven the ocean benefit is (Ocean Impact Navigator). Business: market, value proposition and "
    + "business model validation (KTH BRL). Technology: TRL 1–9 from evidence such as pilots and deployments, never a self-claim. "
    + "Investment: market, product, team, model, competition, distribution, financials, tech, deal, impact. Scores 0–5.",
  thesis: "Redstone: early-stage blue-economy venture lens (market, product, team, model, financials, deal). "
    + "A'Pelago: accelerator lens (ocean impact, business readiness, team). 0–5, from evidence alone.",
};

const saved = (localStorageGet("pd.sort") || "avg:desc").split(":");
const state = {
  filter: "all", sort: SORTS.some(([k]) => k === saved[0]) ? saved[0] : "avg", dir: saved[1] === "asc" ? "asc" : "desc",
  open: null, busy: new Set(), searching: false,
};
const remember = () => localStorageSet("pd.sort", `${state.sort}:${state.dir}`);
let data = null;
let lastSig = null;

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// --- small pieces -----------------------------------------------------------------------------------

function nameLink(name, url) {
  return url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, name) : name;
}

// A real startup joins the daily game by itself once its card is filled and passes the automatic check.
function gameTag(c) {
  const g = c.game || {};
  if (g.status === "in") return h("span", { class: "tag in" }, "In game");
  if (g.status === "out") return h("span", { class: "tag out", title: g.note }, "Not in game");
  return h("span", { class: "tag" }, c.profile && c.profile.status ? "Checking for the game" : "Not in game yet");
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

// The reviews' average: the game (everyone who played), the AI models and social media, each counting once, on each
// of the four calls. null until any of them is in. The card, the sort and the details table all use it.
function reviewAverage(c) {
  const groups = [c.opinions.filter((t) => t.key === "crowd"), c.opinions.filter((t) => t.group === "ai"),
    c.opinions.filter((t) => t.group === "social")].filter((g) => g.length);
  if (!groups.length) return null;
  const means = groups.map((g) => Object.fromEntries(AXES.map((a) => [a, g.reduce((s, t) => s + t.scores[a], 0) / g.length])));
  const scores = Object.fromEntries(AXES.map((a) => [a, means.reduce((s, m) => s + m[a], 0) / means.length]));
  return { scores, avg: AXES.reduce((s, a) => s + scores[a], 0) / AXES.length, groups: groups.length };
}

const AXIS_LETTER = { novel: "N", useful: "U", plausible: "P", investable: "I" };

// The card's scores: N U P I and their average, each on a small 0-5 bar.
function reviewScores(c) {
  const r = reviewAverage(c);
  if (!r) return h("div", { class: "nupi empty" }, h("span", { class: "muted" }, "No reviews yet"));
  const cell = (label, v, title, cls = "") => h("div", { class: `nupi-cell ${cls}`, title: `${title} ${fmt1(v)}` },
    h("small", {}, label), h("b", {}, fmt1(v)), h("i", { style: { "--v": v / 5 } }));
  return h("div", { class: "nupi", title: `Average of the game, AI models and social media (${r.groups} of 3 in)` },
    AXES.map((a) => cell(AXIS_LETTER[a], r.scores[a], AXIS[a], state.sort === a ? "on" : "")),
    cell("Avg", r.avg, "Average", `avg${state.sort === "avg" ? " on" : ""}`));
}

const short = (label) => label.replace(/\s*\(.*\)\s*/, "").toLowerCase();
const known = (c) => c.coverage && c.coverage.assessed > 0;

// --- cards ------------------------------------------------------------------------------------------

function card(c) {
  if (c.kind === "sub") {
    const busy = state.busy.has(`s${c.id}`);
    return h("article", { class: "rc new" },
      h("div", { class: "top" }, h("div", { class: "name" }, nameLink(c.name, /^https?:\/\//i.test(c.website) ? c.website : "")),
        h("span", { class: "call new" }, "New")),
      h("div", { class: "meta" }, h("span", { class: "tag player" }, "Sent in by a player"), c.sector ? ` · ${c.sector}` : ""),
      h("div", { class: "what" }, c.one_liner),
      c.claim_ask ? h("div", { class: "ask" }, c.claim_ask) : null,
      h("div", { class: "foot" },
        h("button", { class: `btn primary${busy ? " busy" : ""}`, disabled: busy, onclick: () => trackSub(c) }, busy ? "Tracking…" : "Track"),
        h("button", { class: "btn link", disabled: busy, onclick: () => dismissSub(c) }, "Dismiss")));
  }
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
    h("div", { class: "meta" }, c.is_real ? gameTag(c) : null, [c.sector, c.country].filter(Boolean).join(" · ") || " "),
    h("div", { class: "what" }, c.one_liner),
    c.claim_ask ? h("div", { class: "ask" }, c.claim_ask) : null,
    factLine(c),
    reviewScores(c),
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

// A player's suggestion becomes a real startup like a discovery find: filled, checked for the game and reviewed by
// itself once tracked.
async function trackSub(c) {
  state.busy.add(`s${c.id}`);
  render();
  try {
    await post(`/api/admin/submissions/${c.id}/approve`, {});
    PD.toast(`${c.name} tracked`);
  } catch (e) { PD.toast(e.message, 6000); }
  state.busy.delete(`s${c.id}`);
  refresh(true);
}

async function dismissSub(c) {
  try { await post(`/api/admin/submissions/${c.id}`, undefined, "DELETE"); } catch (e) { PD.toast(e.message); }
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

// Where a real startup's automatic fill (profile and evidence, from its website and news) stands, or null once
// it's done. A failed fill shows its error; the next background run tries again.
function fillState(c) {
  if (!c.is_real || (c.profile && c.profile.status)) return null;
  const r = data.reads || {};
  if (!r.fill) return "Fills automatically once OPENROUTER_API_KEY is set in .env.";
  const err = (r.auto.errors || []).find((e) => e.startsWith(`${c.name}, profile:`));
  if (r.auto.running) return "Filling from its website and news…";
  return err ? `Couldn't fill it: ${err.slice(c.name.length + 11)}` : "Waiting to be filled from its website and news.";
}

// The facts as the investor's game card shows them: raised so far, investors and stage, then every stage passed
// and every investor.
function factsSect(c) {
  const invested = c.investors.filter((i) => i.status === "invested");
  const box = (label, value, cls = "") => h("div", { class: `fact-box ${cls}` }, h("small", { class: "caps" }, label), h("b", {}, value));
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
    fillState(c) ? h("p", { class: "note fill-state" }, fillState(c)) : null);
}

function startupCol(c) {
  return [
    factsSect(c),
    // Always in full: a long vision sets a size smaller rather than being cut.
    c.vision ? sect("Vision", h("div", { class: `vision-text${c.vision.split(/\s+/).length > 110 ? " long" : ""}` },
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
    h("p", { class: "reasons" }, c.call.key === "evidence" && fillState(c) ? fillState(c) : c.call.reasons.join(" · ")),
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

// One click gets every review: the AI models' ratings and, for a real startup, a social media read (a made-up one
// would only turn up namesakes). Each overwrites that source's last read.
async function refreshReviews(c) {
  const key = `reviews${c.id}`;
  state.busy.add(key);
  renderDrawer();
  const kinds = c.is_real && (data.reads.ready.claude || data.reads.ready.grok) ? ["ai", "social"] : ["ai"];
  const outs = await Promise.allSettled(kinds.map((kind) => post(`/api/admin/companies/${c.id}/reads/${kind}`, {})));
  const report = outs.flatMap((o) => (o.status === "fulfilled" ? Object.values(o.value.report) : []));
  const failed = report.find((r) => r.error) || outs.find((o) => o.status === "rejected");
  const done = report.filter((r) => r.done).length;
  PD.toast(`${done} of ${report.length || kinds.length} reviews in${failed ? ` · ${failed.error || failed.reason.message}` : ""}`,
    failed ? 8000 : 3000);
  state.busy.delete(key);
  await refresh(true);
}

function reviewButton(c) {
  const { ready, models } = data.reads;
  const ok = Object.values(ready).some(Boolean);
  const busy = state.busy.has(`reviews${c.id}`);
  const has = c.opinions.some((t) => t.group === "ai" || t.group === "social") || c.quiet.length;
  return h("div", { class: "row review-btns" },
    h("button", { class: `pill ghost small${busy ? " busy" : ""}`, disabled: busy || !ok,
      title: `${models.claude}, ${models.gpt} and ${models.grok} rate it${c.is_real ? ", and social media is read" : ""} (a minute or two)`,
      onclick: () => refreshReviews(c) }, busy ? "Getting reviews…" : has ? "Refresh reviews" : "Get reviews"),
    ok ? null : h("span", { class: "note" }, "Set OPENROUTER_API_KEY in .env to get reviews."));
}

// Every read of the startup on the same four calls: the engine's evidence, the crowd, A'Pelago, the AI models and
// social media. A row with a reason opens it on a click.
function readsTable(c) {
  const rows = [];
  if (known(c)) rows.push({ key: "engine", label: "Engine", scores: c.engine.axes, note: `From the evidence: ${c.coverage.assessed}/${c.coverage.total} factors known.` });
  rows.push(...c.opinions);
  const r = reviewAverage(c);
  const overall = r ? { label: "Average", scores: r.scores,
    note: `The game, AI models and social media, each counting once (${r.groups} of 3 in).` } : null;
  const avg = (s) => AXES.reduce((sum, a) => sum + s[a], 0) / AXES.length;
  const cell = (v) => h("td", {}, h("span", { class: "v" }, fmt1(v)), h("i", { class: "mini", style: { "--v": v / 5 } }));
  const groupOf = (t) => (t.key === "engine" || t.key === "overall" ? t.key : t.group);
  const body = [];
  let last = null;
  for (const t of rows) {
    const g = groupOf(t);
    if (g !== last && g !== "engine" && g !== "overall") {
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
  if (overall) {
    body.unshift(h("tr", { class: "overall", title: overall.note },
      h("th", {}, overall.label, h("small", {}, "game · AI · social")),
      AXES.map((a) => cell(overall.scores[a])), h("td", { class: "avg" }, fmt1(avg(overall.scores))),
      h("td", { class: "why" }, h("span", {}, overall.note))));
  }
  return sect("What everyone makes of it",
    !rows.length ? null : h("table", { class: "reads" },
      h("colgroup", {}, h("col", { class: "c-who" }), AXES.map(() => h("col", { class: "c-num" })), h("col", { class: "c-num" }), h("col")),
      h("thead", {}, h("tr", {}, h("td"), AXES.map((a) => h("th", { title: AXIS[a] }, AXIS[a][0])), h("th", {}, "Avg"), h("th", { class: "why" }, "Why"))),
      h("tbody", {}, body)),
    missing.length ? h("p", { class: "note" }, `${missing.join(" · ")}.`.replace(/^./, (s) => s.toUpperCase())) : null,
    reviewButton(c));
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
  const was = document.querySelector(".dossier-wrap");
  const scroll = was ? was.scrollTop : 0;
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
              c.is_real ? gameTag(c) : null,
              h("span", { class: "caps sector" }, [c.sector, c.country, c.is_real ? null : "made-up startup"].filter(Boolean).join(" · ")),
              c.game && c.game.status === "out" ? h("span", { class: "game-note" }, `Kept out: ${c.game.note}`) : null,
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
  wrap.scrollTop = scroll;
  if (!was) card.querySelector(".close-x").focus({ preventScroll: true });
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.open) closeDrawer(); });

// --- page -------------------------------------------------------------------------------------------

function items() {
  const cos = data.companies.map((c) => ({ ...c, kind: "co" }));
  // Players' suggestions first, then discovery's finds: both wait for Track or Dismiss.
  const cands = [...(data.submissions || []).map((c) => ({ ...c, kind: "sub" })), ...data.candidates.map((c) => ({ ...c, kind: "cand" }))];
  return { cos, cands };
}

// The review score a card sorts by, or null when it has no reviews yet.
function sortValue(c) {
  const r = reviewAverage(c);
  return !r ? null : state.sort === "avg" ? r.avg : r.scores[state.sort];
}

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
  const sorted = (arr) => [...arr].sort((a, b) => {
    const x = sortValue(a), y = sortValue(b);
    if (x === null || y === null) return (x === null) - (y === null) || a.name.localeCompare(b.name);
    return (state.dir === "desc" ? y - x : x - y) || a.name.localeCompare(b.name);
  });
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
      h("label", { class: "sort" }, "Sort by",
        h("select", { "aria-label": "Sort by", onchange: (e) => { state.sort = e.target.value; remember(); render(); } },
          SORTS.map(([k, label]) => h("option", { value: k, selected: state.sort === k }, label)))),
      seg([["desc", "High → low"], ["asc", "Low → high"]], state.dir, (k) => { state.dir = k; remember(); render(); })),
    list.length ? h("div", { class: "grid" }, list.map(card))
      : h("p", { class: "empty" }, data.mode === "live" ? "No startups yet. Find some above." : "No companies."),
  ].filter(Boolean));
}

async function refresh(force = false) {
  let fresh;
  try {
    fresh = await api("/api/host/radar");
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
  // The open card is redrawn only when something on it changed (a fill or a read landing), so it never jumps.
  const open = state.open && data.companies.find((c) => c.id === state.open);
  const openSig = open ? JSON.stringify(open) + JSON.stringify(data.reads.auto.running) : null;
  if (state.open && (force || openSig !== state.openSig)) renderDrawer();
  state.openSig = openSig;
}

state.open = Number((location.hash.match(/^#co-(\d+)$/) || [])[1]) || null;
Tool.onMode(() => { state.open = null; state.filter = "all"; renderDrawer(); refresh(true); });
refresh(true);
// Quietly pick up autofill finds and new answers, never while the host is reading details or typing.
setInterval(() => {
  const typing = document.activeElement && ["INPUT", "SELECT"].includes(document.activeElement.tagName);
  if (!document.hidden && !state.open && !typing && !state.searching) refresh();
}, 15000);
// While cards are being filled or read in the background, check often, so profiles, evidence and ratings appear
// on their own, on an open card too.
setInterval(() => {
  if (!document.hidden && data && data.reads && data.reads.auto.running && !state.searching) refresh();
}, 4000);
