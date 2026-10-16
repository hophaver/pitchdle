// Admin: companies (with evidence → engine score on save), opportunities, dives, session controls.
const { h, api, post, AXES, AXIS, fmt1 } = PD;
const $app = document.getElementById("app");
let companies = [];
let dives = [];
let submissions = [];
let users = { users: [], guests: 0 };
let candidates = [];
let modeInfo = null;
let autofillPoll = null;
const discoverFilter = { status: "", sector: "", country: "" };
let searching = false;
let factors = null;
let editing = null; // company object being edited, or {} for new

const OPP_HELP = "One per line: kind | name | fit 0–1 | stage | why. Kinds: investor, grant, partner, customer.";

function factsToText(facts) { return (facts || []).map((f) => `${f.label}: ${f.value}`).join("\n"); }
function textToFacts(text) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const i = l.indexOf(":");
    return i === -1 ? { label: "Fact", value: l } : { label: l.slice(0, i).trim(), value: l.slice(i + 1).trim() };
  });
}
function oppsToText(opps) { return (opps || []).map((o) => [o.kind, o.name, o.fit, o.stage_fit, o.why].join(" | ")).join("\n"); }
function textToOpps(text) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const [kind = "partner", name = "", fit = "0.5", stage = "", ...why] = l.split("|").map((s) => s.trim());
    return { kind, name, fit: Math.max(0, Math.min(1, parseFloat(fit) || 0.5)), stage_fit: stage, why: why.join(" | ") };
  });
}

async function load() {
  const qs = new URLSearchParams(Object.entries(discoverFilter).filter(([, v]) => v)).toString();
  [companies, dives, factors, submissions, users, candidates, modeInfo] = await Promise.all([
    api("/api/admin/companies"), api("/api/host/dives"), factors ? factors : api("/api/admin/factors"),
    api("/api/admin/submissions"), api("/api/admin/users"), api(`/api/admin/discover${qs ? `?${qs}` : ""}`),
    api("/api/admin/mode")]);
  // Keep polling while a background discovery run is going, so its results show up on their own.
  clearTimeout(autofillPoll);
  if (modeInfo.autofill.running) autofillPoll = setTimeout(refresh, 3000);
}

const AUTOFILL_START = {
  started: "Looking for real startups…", running: "Discovery is already running",
  "cap-reached": "Already at the DISCOVER_MAX cap", "not-live": "Switch to Live first", "auto-off": "Auto discovery is off",
};

// Demo shows the seeded sample companies everywhere (game + dashboard); live shows real ones.
function modeSection() {
  const m = modeInfo;
  const live = m.mode === "live";
  const af = m.autofill;
  const d = m.discover;
  async function setMode(mode) {
    if (mode === m.mode) return;
    try {
      const r = await post("/api/admin/mode", { mode });
      PD.toast(mode === "demo" ? "Demo mode" : r.autofill_start === "started" ? "Live mode · looking for real startups…" : "Live mode");
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  async function findMore() {
    try {
      const r = await post("/api/admin/autofill", {});
      PD.toast(AUTOFILL_START[r.autofill_start] || r.autofill_start);
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  const seg = (value, text) => h("button", { class: `btn${m.mode === value ? " primary" : ""}`, "aria-pressed": String(m.mode === value),
    onclick: () => setMode(value) }, text);
  const c = m.counts;
  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, "Mode"), h("span", { class: "spacer" }),
      h("div", { class: "seg", role: "group", "aria-label": "Mode" }, seg("demo", "Demo"), seg("live", "Live"))),
    h("p", { class: "muted small" }, live
      ? `The game and dashboard show real startups. ${c.live_active} in the game, ${c.live_pending} waiting for you to add them.`
      : `The game and dashboard show the ${c.demo} sample companies.`),
    live && !c.live_active ? h("p", { class: "callout" },
      "No real startups are in the game yet, so players see a “check back soon” notice. Add found startups below with “Add to game”.") : null,
    live ? [
      h("div", { class: "row" },
        h("span", { class: "small" }, af.running ? h("b", {}, "Discovery running…")
          : af.finished_at ? `Last run ${af.finished_at.slice(0, 16).replace("T", " ")}: ${af.added.length} added${af.added.length ? ` (${af.added.join(", ")})` : ""}` : "Discovery hasn't run yet."),
        h("span", { class: "spacer" }),
        h("button", { class: `btn small${af.running ? " busy" : ""}`, disabled: af.running, onclick: findMore }, "Find more now")),
      af.errors && af.errors.length ? h("p", { class: "thin small" }, af.errors.join(" · ")) : null,
      h("p", { class: "muted small" },
        `Searching ${d.fields.join(", ") || "(no fields)"}${d.region ? ` in ${d.region}` : ""} · depth ${d.depth} per field · `,
        `${af.found}/${d.max} auto-found${d.exclude.length ? ` · skipping ${d.exclude.join(", ")}` : ""}`,
        `${d.auto ? "" : " · auto-run off"}. Edit DISCOVER_* in .env and restart.`)] : null);
}

const LEAN_SHORT = { positive: "pos", negative: "neg", mixed: "mixed", neutral: "neutral", silent: "silent" };
const leanBadge = (lean) => h("span", { class: `badge ${lean}` }, LEAN_SHORT[lean] || lean);
const pulseSummary = (p) => (p ? h("span", { class: "row", style: { gap: ".35rem", flexWrap: "nowrap" } },
  h("span", { class: "num" }, `${p.items_total} hits`), leanBadge(p.lean)) : h("span", { class: "muted" }, "–"));

// Startups found on the open web for a sector (and optional country). Nothing here is in the game until
// it's approved, and then it arrives inactive, like a submission.
function discoverSection() {
  const sector = h("input", { type: "text", placeholder: "e.g. ocean plastics", maxlength: 60 });
  const country = h("input", { type: "text", placeholder: "optional, e.g. Finland", maxlength: 40 });
  const limit = h("select", {}, [5, 8, 10].map((n) => h("option", { value: n, selected: n === 8 }, `${n} results`)));
  async function search() {
    if (sector.value.trim().length < 2) return PD.toast("Enter a sector keyword");
    searching = true;
    render();
    try {
      const found = await post("/api/admin/discover/search", { sector: sector.value.trim(), country: country.value.trim(), limit: Number(limit.value) });
      PD.toast(found.length ? `Found ${found.length} candidate${found.length === 1 ? "" : "s"}` : "Nothing found (or the feeds are unreachable)");
    } catch (e) { PD.toast(e.message); }
    searching = false;
    await refresh();
  }
  async function act(c, path, body, method = "POST") {
    try {
      const out = await post(`/api/admin/discover/${c.id}${path}`, body, method);
      if (path === "/approve") {
        editing = out;
        PD.toast(`${c.name} added (inactive). Check the evidence, then tick Active.`);
        window.scrollTo({ top: 0 });
      }
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  const filterSel = (key, label, options) => h("select", { "aria-label": label, onchange: (e) => { discoverFilter[key] = e.target.value; refresh(); } },
    options.map(([v, t]) => h("option", { value: v, selected: discoverFilter[key] === v }, t)));
  const uniq = (key) => [...new Set(candidates.map((c) => c[key]).filter(Boolean))].sort();
  const queued = candidates.filter((c) => c.status === "queued").length;
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Discover startups"), h("span", { class: "spacer" }),
      h("span", { class: "chip" }, `Queued for next game: ${queued}`)),
    h("p", { class: "muted small", style: { marginTop: 0 } },
      "Searches public news and Hacker News. Auto-estimates score only what a crawl can show, so coverage is low by design; approve to add as an inactive company and finish the evidence yourself."),
    h("div", { class: "form-grid" }, h("label", {}, "Sector keyword", sector), h("label", {}, "Country tag", country), h("label", {}, "Limit", limit)),
    h("div", { class: "btns", style: { marginTop: ".7rem" } },
      h("button", { class: `btn primary${searching ? " busy" : ""}`, disabled: searching, onclick: search }, searching ? "Searching… (can take a minute)" : "Search")),
    h("div", { class: "toolbar", style: { marginTop: "1rem" } },
      filterSel("status", "Status", [["", "Open (new + queued)"], ["queued", "Queued"], ["new", "New"], ["approved", "Approved"], ["dismissed", "Dismissed"]]),
      filterSel("sector", "Sector", [["", "All sectors"], ...uniq("sector_query").map((v) => [v, v])]),
      filterSel("country", "Country", [["", "All countries"], ...uniq("country_tag").map((v) => [v, v])])),
    candidates.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Name", "Source", "Query", "Auto-estimate", "Web pulse", "Status", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, candidates.map((c) => {
        const hint = c.engine_hint;
        return h("tr", {},
          h("td", {}, h("div", { class: "co-name" }, c.url ? h("a", { href: c.url, target: "_blank", rel: "noopener noreferrer" }, c.name) : c.name),
            h("div", { class: "co-meta" }, c.snippet)),
          h("td", {}, c.source),
          h("td", {}, [c.sector_query, c.country_tag].filter(Boolean).join(" · ")),
          // With nothing learned the engine only returns its unknown default, so don't show that as a score.
          h("td", {}, hint && hint.coverage.assessed ? [h("span", { class: "num" }, fmt1(hint.composite)),
            h("div", { class: "co-meta" }, `auto-estimate · ${hint.coverage.assessed}/${hint.coverage.total} factors${hint.flags.length ? ` · ${hint.flags.join(", ")} mentioned` : ""}`)]
            : [h("span", { class: "muted" }, "–"),
              h("div", { class: "co-meta" }, hint ? `not estimated${c.url ? "" : " (no site found)"}` : "")]),
          h("td", {}, pulseSummary(c.pulse)),
          h("td", {}, h("span", { class: `badge ${c.status === "queued" ? "mixed" : c.status === "approved" ? "convergent" : "unknown"}` }, c.status)),
          h("td", {}, c.status === "approved" || c.status === "dismissed" ? null : h("div", { class: "row", style: { flexWrap: "nowrap" } },
            h("button", { class: "btn small", onclick: () => act(c, "/queue", { queued: c.status !== "queued" }) }, c.status === "queued" ? "Unqueue" : "Queue for next game"),
            h("button", { class: "btn small primary", onclick: () => act(c, "/approve", {}) }, "Approve"),
            h("button", { class: "btn small danger", onclick: () => act(c, "", undefined, "DELETE") }, "Dismiss"))));
      }))))
      : h("p", { class: "muted small" }, "No candidates yet. Search a sector above."));
}

function pulseView(p) {
  return h("div", { style: { marginTop: "1rem" } },
    h("h3", {}, "Web pulse (a hint; never changes the score)"),
    h("p", { class: "small" }, pulseSummary(p), " ",
      h("span", { class: "muted" }, `${p.items_recent} in the last 30 days · ${p.good_count} positive / ${p.risk_count} risk · coverage ${p.coverage} · fetched ${p.fetched_at.slice(0, 10)}`)),
    p.errors && p.errors.length ? h("p", { class: "thin" }, p.errors.join(" · ")) : null,
    p.top_hits.length ? h("ul", { class: "small" }, p.top_hits.map((t) => h("li", {},
      h("a", { href: t.link, target: "_blank", rel: "noopener noreferrer" }, t.title),
      h("span", { class: "muted" }, ` · ${t.source}${t.published ? ` · ${t.published}` : ""}${t.lean ? ` · ${t.lean}` : ""}`)))) : null);
}

// Startups sent in from the player page. Approving adds them as real but inactive, then opens the editor
// so evidence and an emoji can go in before they're put in rotation.
function submissionSection() {
  if (!submissions.length) return null;
  async function approve(sub) {
    try {
      editing = await post(`/api/admin/submissions/${sub.id}/approve`, {});
      PD.toast(`${sub.name} added (inactive). Add evidence, then tick Active.`);
      await refresh();
      window.scrollTo({ top: 0 });
    } catch (e) { PD.toast(e.message); }
  }
  async function reject(sub) {
    if (!confirm(`Discard the submission from ${sub.name}?`)) return;
    await post(`/api/admin/submissions/${sub.id}`, undefined, "DELETE");
    await refresh();
  }
  return h("section", { class: "panel" },
    h("h2", {}, `Submitted startups (${submissions.length})`),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Name", "Field", "Pitch", "Ask", "Link", "Sent", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, submissions.map((sub) => h("tr", {},
        h("td", {}, h("b", {}, sub.name)), h("td", {}, sub.sector), h("td", {}, sub.one_liner), h("td", {}, sub.claim_ask),
        h("td", {}, /^https?:\/\//i.test(sub.website) ? h("a", { href: sub.website, target: "_blank", rel: "noopener noreferrer" }, sub.website) : sub.website),
        h("td", {}, sub.created_at.slice(0, 10)),
        h("td", {}, h("div", { class: "row" },
          h("button", { class: "btn small primary", onclick: () => approve(sub) }, "Approve"),
          h("button", { class: "btn small danger", onclick: () => reject(sub) }, "Discard")))))))));
}

function companyTable() {
  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, "Companies"), h("span", { class: "spacer" }),
      h("button", { class: "btn small primary", onclick: () => { editing = {}; render(); } }, "+ Add company")),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Name", "Sector", "Active", "Real", ...AXES.map((a) => AXIS[a]), "Composite", "Coverage", "Answers", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, companies.map((c) => h("tr", {},
        h("td", {}, h("b", {}, c.name), c.origin === "discovery-auto" ? h("span", { class: "chip", style: { marginLeft: ".4rem" } }, "auto-found") : null),
        h("td", {}, c.sector),
        h("td", {}, h("input", { type: "checkbox", checked: !!c.active, onchange: (e) => quickSave(c, { active: e.target.checked }) })),
        h("td", {}, h("input", { type: "checkbox", checked: !!c.is_real, onchange: (e) => quickSave(c, { is_real: e.target.checked }) })),
        AXES.map((a) => h("td", { class: "num" }, fmt1(c.engine_axes[a]))),
        h("td", { class: "num", style: { color: "var(--accent)" } }, fmt1(c.engine_composite)),
        h("td", { class: "num" }, `${c.engine_coverage.assessed}/${c.engine_coverage.total}`),
        h("td", { class: "num" }, c.votes),
        h("td", {}, h("div", { class: "row" },
          c.is_real && !c.active ? h("button", { class: "btn small primary", onclick: () => quickSave(c, { active: true }),
            title: "Put it in the live game's rotation" }, "Add to game") : null,
          h("button", { class: "btn small", onclick: () => { editing = c; render(); window.scrollTo({ top: 0 }); } }, "Edit"),
          h("button", { class: "btn small danger", onclick: () => remove(c) }, "Delete")))))))));
}

function companyBody(c, overrides = {}) {
  return {
    name: c.name, emoji: c.emoji || "", sector: c.sector || "", one_liner: c.one_liner || "", claim_ask: c.claim_ask || "",
    website: c.website || "", facts: c.facts || [], evidence: c.evidence || {}, evidence_note: c.evidence_note || "",
    is_real: !!c.is_real, active: c.active === undefined ? true : !!c.active, ...overrides,
  };
}

async function quickSave(c, overrides) {
  try {
    await post(`/api/admin/companies/${c.id}`, companyBody(c, overrides), "PUT");
    await refresh();
  } catch (e) { PD.toast(e.message); }
}

async function remove(c) {
  if (!confirm(`Delete ${c.name} and all its votes? This can't be undone.`)) return;
  await post(`/api/admin/companies/${c.id}`, undefined, "DELETE");
  if (editing && editing.id === c.id) editing = null;
  await refresh();
}

function editor() {
  const c = editing;
  const ev = c.evidence || {};
  const f = {};
  const input = (key, label, value, attrs = {}) => {
    f[key] = h(attrs.textarea ? "textarea" : "input", { type: "text", rows: attrs.rows || 3, ...attrs, textarea: null });
    f[key].value = value ?? "";
    return h("label", {}, label, f[key]);
  };
  const factorInputs = {};
  const groups = Object.entries(factors.groups).map(([group, names]) => h("div", {},
    h("h4", { style: { margin: ".8rem 0 .4rem" } }, factors.group_labels[group]),
    h("div", { class: "factor-grid" }, names.map((name) => {
      const el = h("input", { type: "number", min: 0, max: 5, step: 0.5, placeholder: "unknown" });
      const v = (ev[group] || {})[name];
      el.value = v === undefined || v === null ? "" : v;
      factorInputs[`${group}.${name}`] = el;
      return h("label", {}, name.replace(/_/g, " "), el);
    }))));
  const trl = h("select", {}, h("option", { value: "" }, "unknown"),
    Object.entries(factors.trl_stages).map(([stage, n]) => h("option", { value: stage, selected: ev.trl_stage === stage }, `${stage} (TRL ${n})`)));
  const patents = h("input", { type: "number", min: 0, step: 1, placeholder: "unknown" });
  patents.value = ev.patents ?? "";
  const isReal = h("input", { type: "checkbox", checked: !!c.is_real });
  const active = h("input", { type: "checkbox", checked: c.active === undefined ? true : !!c.active });
  const opps = h("textarea", { rows: 4 });
  opps.value = oppsToText(c.opportunities);
  const crawlOut = h("div", {}, c.crawl ? crawlView(c.crawl) : null);
  const pulseOut = h("div", {}, c.pulse ? pulseView(c.pulse) : null);

  function collectEvidence() {
    const out = {};
    for (const [key, el] of Object.entries(factorInputs)) {
      if (el.value === "") continue;
      const [group, name] = key.split(".");
      (out[group] ||= {})[name] = Math.max(0, Math.min(5, parseFloat(el.value)));
    }
    if (trl.value) out.trl_stage = trl.value;
    if (patents.value !== "") out.patents = parseInt(patents.value, 10);
    return out;
  }

  async function save() {
    const body = {
      name: f.name.value.trim(), emoji: f.emoji.value.trim(), sector: f.sector.value, one_liner: f.one_liner.value, claim_ask: f.claim_ask.value,
      website: f.website.value.trim(), facts: textToFacts(f.facts.value), evidence: collectEvidence(),
      evidence_note: f.note.value, is_real: isReal.checked, active: active.checked,
    };
    if (!body.name) return PD.toast("Name is required");
    try {
      let saved = c.id ? await post(`/api/admin/companies/${c.id}`, body, "PUT") : await post("/api/admin/companies", body);
      saved = await post(`/api/admin/companies/${saved.id}/opportunities`, textToOpps(opps.value), "PUT");
      editing = saved;
      PD.toast(`Saved. Engine read ${fmt1(saved.engine_composite)} (${saved.engine_coverage.assessed}/${saved.engine_coverage.total} factors)`);
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }

  async function recrawl() {
    if (!c.id) return PD.toast("Save the company first");
    crawlOut.replaceChildren(h("p", { class: "muted" }, "Crawling… (needs internet; the game never waits for this)"));
    try {
      crawlOut.replaceChildren(crawlView(await post(`/api/admin/companies/${c.id}/recrawl`, {})));
    } catch (e) { crawlOut.replaceChildren(h("p", { class: "callout" }, e.message)); }
  }

  async function runPulse() {
    if (!c.id) return PD.toast("Save the company first");
    pulseOut.replaceChildren(h("p", { class: "muted" }, "Fetching web coverage… (needs internet; the game never waits for this)"));
    try {
      pulseOut.replaceChildren(pulseView(await post(`/api/admin/pulse/run/${c.id}`, {})));
    } catch (e) { pulseOut.replaceChildren(h("p", { class: "callout" }, e.message)); }
  }

  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, c.id ? `Edit ${c.name}` : "Add company"), h("span", { class: "spacer" }),
      c.id ? h("span", { class: "chip" }, `Engine ${fmt1(c.engine_composite)} · ${AXES.map((a) => `${AXIS[a][0]} ${fmt1(c.engine_axes[a])}`).join(" ")}`) : null,
      h("button", { class: "btn small", onclick: () => { editing = null; render(); } }, "Close")),
    h("div", { class: "form-grid", style: { marginTop: "1rem" } },
      input("name", "Name", c.name),
      input("emoji", "Picture (one emoji)", c.emoji),
      input("sector", "Sector", c.sector),
      input("website", "Website (optional, for recrawl)", c.website),
      h("label", { class: "row" }, isReal, "Real startup"),
      h("label", { class: "row" }, active, "Active (in rotation)")),
    h("div", { class: "form-grid", style: { marginTop: ".8rem" } },
      input("one_liner", "The pitch: one concrete line (show, don't tell)", c.one_liner),
      input("claim_ask", "The ask, e.g. “€500k to build ten more rafts”", c.claim_ask)),
    h("div", { class: "form-grid", style: { marginTop: ".8rem" } },
      input("facts", "Facts for the wall reveal, one per line as “Label: value” (1–2)", factsToText(c.facts), { textarea: true }),
      input("note", "Evidence note (sources)", c.evidence_note, { textarea: true })),
    h("h3", { style: { marginTop: "1.2rem" } }, "Evidence (0–5, blank = unknown)"),
    h("p", { class: "muted small" }, "The engine scores only what's known and reports coverage. TRL comes from evidence, never a self-claim."),
    h("div", { class: "form-grid" }, h("label", {}, "Tech stage (evidence-derived TRL)", trl), h("label", {}, "Patents granted", patents)),
    groups,
    h("h3", { style: { marginTop: "1.2rem" } }, "Opportunities (ranked next actions)"),
    h("p", { class: "muted small" }, OPP_HELP), opps,
    h("div", { class: "btns" },
      h("button", { class: "btn primary", onclick: save }, "Save and score"),
      h("button", { class: "btn", onclick: recrawl }, "Recrawl website (optional)"),
      h("button", { class: "btn", onclick: runPulse }, "Run web pulse")),
    crawlOut, pulseOut);
}

function crawlView(cr) {
  return h("div", { style: { marginTop: "1rem" } },
    h("h3", {}, "Crawl hints (review, then update the evidence yourself)"),
    cr.errors && cr.errors.length ? h("p", { class: "thin" }, cr.errors.join(" · ")) : null,
    Object.keys(cr.signals || {}).length ? h("ul", {}, Object.entries(cr.signals).map(([k, v]) =>
      h("li", {}, h("b", {}, `${k} ×${v.count}: `), h("span", { class: "muted" }, `…${v.snippet}…`)))) : null,
    cr.news && cr.news.length ? h("div", {}, h("b", {}, "News"), h("ul", {}, cr.news.map((n) => h("li", {}, h("a", { href: n.link, target: "_blank", rel: "noopener" }, n.title))))) : null,
    cr.website ? h("details", {}, h("summary", {}, `Page text (${cr.website.cached ? "cached" : "fresh"})`), h("pre", { class: "crawl" }, cr.website.text)) : null);
}

function diveSection() {
  const byId = Object.fromEntries(companies.map((c) => [c.id, c.name]));
  const label = h("input", { type: "text", placeholder: "e.g. JunctionX final" });
  const mode = h("select", {}, h("option", { value: "live" }, "live (host-paced)"), h("option", { value: "daily" }, "daily (solo)"));
  const date = h("input", { type: "text", placeholder: "YYYY-MM-DD (daily only)" });
  // A set draws on the current mode's companies: sample ones in demo, real ones in live.
  const pool = companies.filter((c) => !!c.is_real === (modeInfo.mode === "live"));
  const picks = Array.from({ length: 5 }, () => h("select", {}, h("option", { value: "" }, "—"),
    pool.map((c) => h("option", { value: c.id }, c.name))));
  async function create() {
    const ids = picks.map((p) => Number(p.value)).filter(Boolean);
    if (!label.value.trim() || !ids.length) return PD.toast("Give it a label and at least one company");
    try {
      await post("/api/admin/dives", { label: label.value.trim(), company_ids: ids, mode: mode.value, date: date.value.trim() || null });
      PD.toast("Set created");
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  async function demo(d) {
    const r = await post("/api/admin/demo-votes", { dive_id: d.id, players: 30 });
    PD.toast(`Added ${r.inserted} demo votes to ${d.label}`);
    await refresh();
  }
  async function del(d) {
    if (!confirm(`Delete set ${d.label} and its votes?`)) return;
    await post(`/api/admin/dives/${d.id}`, undefined, "DELETE");
    await refresh();
  }
  return h("section", { class: "panel" },
    h("h2", {}, `Sets (${modeInfo.mode} companies)`),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Label", "Mode", "Date", "Cards", "Players", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, dives.map((d) => h("tr", {},
        h("td", {}, h("b", {}, d.label)), h("td", {}, d.mode), h("td", {}, d.date || "–"),
        h("td", {}, d.company_ids.map((i) => byId[i] || `#${i}`).join(", ")),
        h("td", { class: "num" }, d.players),
        h("td", {}, h("div", { class: "row" },
          d.mode === "daily" ? h("a", { class: "btn small", href: `/play?dive=${d.id}`, target: "_blank" }, "Play") : null,
          h("button", { class: "btn small", onclick: () => demo(d), title: "30 fake players, flagged as demo votes" }, "Load demo votes"),
          h("button", { class: "btn small danger", onclick: () => del(d) }, "Delete")))))))),
    h("h3", { style: { marginTop: "1rem" } }, "New set"),
    h("div", { class: "form-grid" }, h("label", {}, "Label", label), h("label", {}, "Mode", mode), h("label", {}, "Date", date)),
    h("div", { class: "form-grid", style: { marginTop: ".6rem" } }, picks.map((p, i) => h("label", {}, `Card ${i + 1}`, p))),
    h("div", { class: "btns" }, h("button", { class: "btn primary", onclick: create }, "Create set")));
}

// Player accounts. Deleting one removes its answers from every crowd score.
function userSection() {
  async function del(u) {
    if (!confirm(`Delete ${u.username} and all ${u.answers} of their answers? This can't be undone.`)) return;
    try {
      await post(`/api/admin/users/${u.id}`, undefined, "DELETE");
      PD.toast(`${u.username} deleted`);
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  const list = users.users;
  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, `Users (${list.length})`), h("span", { class: "spacer" }),
      h("span", { class: "chip" }, `${users.guests} guest device${users.guests === 1 ? "" : "s"}`)),
    h("p", { class: "muted small" }, "Signed-in answers count fully in crowd scores; guest answers count for less and are capped as a group."),
    list.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Username", "Joined", "Sets", "Answers", "Last played", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, list.map((u) => h("tr", {},
        h("td", {}, h("b", {}, u.username)),
        h("td", {}, (u.created_at || "").slice(0, 10)),
        h("td", {}, u.sets),
        h("td", {}, u.answers),
        h("td", {}, u.last_played ? u.last_played.slice(0, 10) : "–"),
        h("td", {}, h("button", { class: "btn small danger", onclick: () => del(u) }, "Delete")))))))
      : h("p", { class: "muted" }, "No accounts yet."));
}

function sessionSection() {
  const reset = (scope, text) => h("button", { class: `btn${scope === "everything" ? " danger" : ""}`, onclick: async () => {
    if (!confirm(text)) return;
    await post("/api/admin/reset", { scope });
    PD.toast("Done");
    editing = null;
    await refresh();
  } }, text.split("?")[0]);
  return h("section", { class: "panel" },
    h("h2", {}, "Session"),
    h("div", { class: "ctl-buttons" },
      reset("seed", "Clear demo votes? Removes all seed players and their votes."),
      reset("real", "Clear real votes? Removes every real player's answers."),
      reset("all", "Clear all votes? Wipes every answer, real and demo."),
      reset("everything", "Reset everything? Deletes all data and reloads the seed companies and dives.")),
    h("h3", { style: { marginTop: "1rem" } }, "Export host insights (real votes only)"),
    h("div", { class: "row" },
      h("a", { class: "btn", href: "/api/admin/export.csv" }, "Download CSV"),
      h("a", { class: "btn", href: "/api/admin/export.json" }, "Download JSON")));
}

function render() {
  // replaceChildren (unlike h) would print a skipped section as the text "null".
  $app.replaceChildren(...[
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Admin"),
      h("p", {}, "Companies and evidence, discovery, sets, players and session controls."))),
    modeSection(),
    editing ? editor() : null,
    discoverSection(),
    submissionSection(),
    companyTable(),
    diveSection(),
    userSection(),
    sessionSection()].filter(Boolean));
}

async function refresh() {
  try {
    await load();
    if (editing && editing.id) editing = companies.find((c) => c.id === editing.id) || null;
    render();
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

refresh();
