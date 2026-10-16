// Admin: companies (with evidence → engine score on save), opportunities, dives, session controls.
const { h, api, post, AXES, AXIS, fmt1 } = PD;
const $app = document.getElementById("app");
let companies = [];
let dives = [];
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
  [companies, dives, factors] = await Promise.all([
    api("/api/admin/companies"), api("/api/host/dives"), factors ? factors : api("/api/admin/factors")]);
}

function companyTable() {
  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, "Companies"), h("span", { class: "spacer" }),
      h("button", { class: "btn small", onclick: () => hideReal(true) }, "Hide real companies"),
      h("button", { class: "btn small", onclick: () => hideReal(false) }, "Show real companies"),
      h("button", { class: "btn small primary", onclick: () => { editing = {}; render(); } }, "+ Add company")),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Name", "Sector", "Active", "Real", ...AXES.map((a) => AXIS[a].name), "Composite", "Coverage", "Reads", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, companies.map((c) => h("tr", {},
        h("td", {}, h("b", {}, c.name)),
        h("td", {}, c.sector),
        h("td", {}, h("input", { type: "checkbox", checked: !!c.active, onchange: (e) => quickSave(c, { active: e.target.checked }) })),
        h("td", {}, h("input", { type: "checkbox", checked: !!c.is_real, onchange: (e) => quickSave(c, { is_real: e.target.checked }) })),
        AXES.map((a) => h("td", { class: "num" }, fmt1(c.engine_axes[a]))),
        h("td", { class: "num", style: { color: "var(--accent)" } }, fmt1(c.engine_composite)),
        h("td", { class: "num" }, `${c.engine_coverage.assessed}/${c.engine_coverage.total}`),
        h("td", { class: "num" }, c.votes),
        h("td", {}, h("div", { class: "row" },
          h("button", { class: "btn small", onclick: () => { editing = c; render(); window.scrollTo({ top: 0 }); } }, "Edit"),
          h("button", { class: "btn small danger", onclick: () => remove(c) }, "Delete")))))))));
}

function companyBody(c, overrides = {}) {
  return {
    name: c.name, sector: c.sector || "", one_liner: c.one_liner || "", claim_ask: c.claim_ask || "",
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

async function hideReal(hide) {
  await post("/api/admin/hide-real", { hide });
  PD.toast(hide ? "Real companies hidden from new dives" : "Real companies active again");
  await refresh();
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
      name: f.name.value.trim(), sector: f.sector.value, one_liner: f.one_liner.value, claim_ask: f.claim_ask.value,
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

  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, c.id ? `Edit ${c.name}` : "Add company"), h("span", { class: "spacer" }),
      c.id ? h("span", { class: "chip" }, `Engine ${fmt1(c.engine_composite)} · ${AXES.map((a) => `${AXIS[a].name[0]} ${fmt1(c.engine_axes[a])}`).join(" ")}`) : null,
      h("button", { class: "btn small", onclick: () => { editing = null; render(); } }, "Close")),
    h("div", { class: "form-grid", style: { marginTop: "1rem" } },
      input("name", "Name", c.name),
      input("sector", "Sector", c.sector),
      input("website", "Website (optional, for recrawl)", c.website),
      h("label", { class: "row" }, isReal, "Real startup"),
      h("label", { class: "row" }, active, "Active (in rotation)")),
    h("div", { class: "form-grid", style: { marginTop: ".8rem" } },
      input("one_liner", "What the company does (one line)", c.one_liner),
      input("claim_ask", "Claim / ask (one line)", c.claim_ask)),
    h("div", { class: "form-grid", style: { marginTop: ".8rem" } },
      input("facts", "Second-look facts, one per line as “Label: value” (1–2)", factsToText(c.facts), { textarea: true }),
      input("note", "Evidence note (sources)", c.evidence_note, { textarea: true })),
    h("h3", { style: { marginTop: "1.2rem" } }, "Evidence (0–5, blank = unknown)"),
    h("p", { class: "muted small" }, "The engine scores only what's known and reports coverage. TRL comes from evidence, never a self-claim."),
    h("div", { class: "form-grid" }, h("label", {}, "Tech stage (evidence-derived TRL)", trl), h("label", {}, "Patents granted", patents)),
    groups,
    h("h3", { style: { marginTop: "1.2rem" } }, "Opportunities (ranked next actions)"),
    h("p", { class: "muted small" }, OPP_HELP), opps,
    h("div", { class: "btns" },
      h("button", { class: "btn primary", onclick: save }, "Save and score"),
      h("button", { class: "btn", onclick: recrawl }, "Recrawl website (optional)")),
    crawlOut);
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
  const picks = Array.from({ length: 5 }, () => h("select", {}, h("option", { value: "" }, "—"),
    companies.map((c) => h("option", { value: c.id }, c.name))));
  async function create() {
    const ids = picks.map((p) => Number(p.value)).filter(Boolean);
    if (!label.value.trim() || !ids.length) return PD.toast("Give it a label and at least one company");
    try {
      await post("/api/admin/dives", { label: label.value.trim(), company_ids: ids, mode: mode.value, date: date.value.trim() || null });
      PD.toast("Dive created");
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  async function demo(d) {
    const r = await post("/api/admin/demo-votes", { dive_id: d.id, players: 30 });
    PD.toast(`Added ${r.inserted} demo votes to ${d.label}`);
    await refresh();
  }
  async function del(d) {
    if (!confirm(`Delete dive ${d.label} and its votes?`)) return;
    await post(`/api/admin/dives/${d.id}`, undefined, "DELETE");
    await refresh();
  }
  return h("section", { class: "panel" },
    h("h2", {}, "Dives"),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Label", "Mode", "Date", "Cards", "Players", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, dives.map((d) => h("tr", {},
        h("td", {}, h("b", {}, d.label)), h("td", {}, d.mode), h("td", {}, d.date || "–"),
        h("td", {}, d.company_ids.map((i) => byId[i] || `#${i}`).join(", ")),
        h("td", { class: "num" }, d.players),
        h("td", {}, h("div", { class: "row" },
          d.mode === "daily" ? h("a", { class: "btn small", href: `/play?dive=${d.id}`, target: "_blank" }, "Play") : null,
          h("button", { class: "btn small", onclick: () => demo(d), title: "30 fake players, flagged as seed votes" }, "Load demo votes"),
          h("button", { class: "btn small danger", onclick: () => del(d) }, "Delete")))))))),
    h("h3", { style: { marginTop: "1rem" } }, "New dive"),
    h("div", { class: "form-grid" }, h("label", {}, "Label", label), h("label", {}, "Mode", mode), h("label", {}, "Date", date)),
    h("div", { class: "form-grid", style: { marginTop: ".6rem" } }, picks.map((p, i) => h("label", {}, `Card ${i + 1}`, p))),
    h("div", { class: "btns" }, h("button", { class: "btn primary", onclick: create }, "Create dive")));
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
      reset("real", "Clear real votes? Removes every real player's answers and leaderboard entries."),
      reset("all", "Clear all votes? Wipes every answer, real and demo."),
      reset("everything", "Reset everything? Deletes all data and reloads the seed companies and dives.")),
    h("h3", { style: { marginTop: "1rem" } }, "Export host insights (real votes only)"),
    h("div", { class: "row" },
      h("a", { class: "btn", href: "/api/admin/export.csv" }, "Download CSV"),
      h("a", { class: "btn", href: "/api/admin/export.json" }, "Download JSON")));
}

function render() {
  $app.replaceChildren(
    h("h1", {}, "Admin"),
    editing ? editor() : null,
    companyTable(),
    diveSection(),
    sessionSection());
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
