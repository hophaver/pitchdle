// Admin: which companies are in the game, each one's profile and outside opinions, player submissions, exports
// and resets.
const { h, api, post, AXES, AXIS, fmt1 } = PD;
const $app = document.getElementById("app");

const TABS = [{ key: "companies", label: "Companies" }, { key: "data", label: "Data" }];
const S = { tab: Tool.hashTab(TABS.map((t) => t.key), "companies"), companies: [], submissions: [], mode: null, query: "",
  editing: null, fetching: null, report: null };

const link = (name, url) => (url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, name) : name);

// --- companies --------------------------------------------------------------------------------------

// The whole company is saved each time, so a quick change must carry everything else along, the profile too.
function companyBody(c, overrides = {}) {
  return {
    name: c.name, emoji: c.emoji || "", sector: c.sector || "", one_liner: c.one_liner || "", claim_ask: c.claim_ask || "",
    website: c.website || "", facts: c.facts || [], evidence: c.evidence || {}, evidence_note: c.evidence_note || "",
    active: !!c.active, vision: c.vision || "", stages: c.stages || [], raised_eur: c.raised_eur ?? null,
    investors: c.investors || [], ...overrides,
  };
}

async function setInGame(c, on, box) {
  box.disabled = true;
  try {
    await post(`/api/admin/companies/${c.id}`, companyBody(c, { active: on }), "PUT");
    c.active = on;
    fillCount();
  } catch (e) { PD.toast(e.message); box.checked = !on; }
  box.disabled = false;
}

function companyCard(c) {
  const box = h("input", { type: "checkbox", checked: !!c.active, onchange: () => setInGame(c, box.checked, box) });
  return h("article", { class: "ac" },
    h("div", { class: "name" }, link(c.name, c.website)),
    c.sector ? h("div", { class: "muted small" }, c.sector) : null,
    h("div", { class: "what" }, c.one_liner),
    c.claim_ask ? h("div", { class: "ask" }, c.claim_ask) : null,
    h("div", { class: "row foot" }, h("label", { class: "check" }, box, "In game"), h("span", { class: "spacer" }),
      h("button", { class: "btn link", onclick: () => openEditor(c.id) }, "Profile & opinions")));
}

// --- profile and outside opinions -------------------------------------------------------------------
// What an investor's game card and the dashboard show beside the pitch: the vision, stages, money raised and
// investors, and AI models' and social media's reads (fetched with the API keys in .env, or typed in here).
// A'Pelago's own evaluation is given on Moderation.

const VISION_WORDS = 400; // matches VISION_WORDS in app/main.py
const INVESTOR_HELP = "Investors, one per line: name | invested | amount (500000, 500k or 1.2M), or name | interested";
const OUTSIDE = { claude: "Claude", gpt: "GPT", grok: "Grok", x: "X", threads: "Threads", linkedin: "LinkedIn",
  reddit: "Reddit", bluesky: "Bluesky" };
const AI_SOURCES = ["claude", "gpt", "grok"];
const KEY_NAMES = { claude: "ANTHROPIC_API_KEY", gpt: "OPENAI_API_KEY", grok: "XAI_API_KEY" };

// Euros as typed: 500000, 500k, 1.2M and €1.2M all work. Blank is "not disclosed"; anything else is NaN.
function parseEuros(text) {
  const t = String(text || "").replace(/[€\s,]/g, "");
  if (!t) return null;
  const m = t.match(/^(\d+(?:\.\d+)?)([kKmM]?)$/);
  return m ? Math.round(parseFloat(m[1]) * ({ k: 1e3, m: 1e6 }[m[2].toLowerCase()] || 1)) : NaN;
}
const investorsToText = (list) => (list || []).map((i) => (i.status === "interested" ? `${i.name} | interested`
  : `${i.name} | invested${i.amount_eur ? ` | ${i.amount_eur}` : ""}`)).join("\n");
function textToInvestors(text) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const [name = "", status = "", amount = ""] = l.split("|").map((x) => x.trim());
    const interested = /^interest/i.test(status);
    const eur = interested ? null : parseEuros(amount);
    return { name, status: interested ? "interested" : "invested", amount_eur: Number.isNaN(eur) ? null : eur };
  });
}
const wordCount = (text) => (text.trim() ? text.trim().split(/\s+/).length : 0);
const day = (iso) => (iso ? iso.slice(0, 10) : "");
const safeLink = (url) => (/^https?:\/\//i.test(url || "") ? url : null);

function openEditor(id) {
  S.editing = id;
  S.report = null;
  renderEditor();
}

function closeEditor() {
  S.editing = null;
  renderEditor();
}

function profileForm(c) {
  const field = (label, el) => h("label", {}, label, el);
  const words = h("span", { class: "muted small" });
  const vision = h("textarea", { rows: 7, maxlength: 4000 });
  vision.value = c.vision || "";
  const countWords = () => {
    const n = wordCount(vision.value);
    words.textContent = `${n}/${VISION_WORDS} words`;
    words.classList.toggle("over", n > VISION_WORDS);
  };
  vision.addEventListener("input", countWords);
  countWords();
  const stages = h("textarea", { rows: 3 });
  stages.value = (c.stages || []).join("\n");
  const raised = h("input", { type: "text", placeholder: "650k" });
  raised.value = c.raised_eur ?? "";
  const investors = h("textarea", { rows: 3 });
  investors.value = investorsToText(c.investors);
  async function save() {
    const eur = parseEuros(raised.value);
    if (Number.isNaN(eur)) return PD.toast("Money raised: a number like 650000, 650k or 1.2M");
    if (wordCount(vision.value) > VISION_WORDS) return PD.toast(`The vision is over ${VISION_WORDS} words`);
    try {
      await post(`/api/admin/companies/${c.id}`, companyBody(c, {
        vision: vision.value, stages: stages.value.split("\n").map((l) => l.trim()).filter(Boolean),
        raised_eur: eur, investors: textToInvestors(investors.value),
      }), "PUT");
      PD.toast("Profile saved");
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  // Fills only the empty fields, from the website and news; also done by itself for every new real startup.
  async function fillWithAI(btn) {
    btn.disabled = true;
    btn.classList.add("busy");
    btn.textContent = "Reading its website and news…";
    try {
      const r = await post(`/api/admin/companies/${c.id}/profile/fill`, {});
      PD.toast(r.filled.length ? `Filled: ${r.filled.join(", ")}` : "The AI found nothing new to fill");
      await refresh();
    } catch (e) {
      PD.toast(e.message, 6000);
      btn.disabled = false;
      btn.classList.remove("busy");
      btn.textContent = "Fill with AI";
    }
  }
  return [
    h("h3", {}, "Profile"),
    c.profile_note ? h("p", { class: "muted small" }, c.profile_note) : null,
    h("div", { class: "form" },
      h("label", {}, h("span", { class: "row" }, "Vision (a blank line starts a new paragraph)", h("span", { class: "spacer" }), words), vision),
      field("Stages passed, one per line, oldest first (incubators, rounds)", stages),
      field("Money raised so far, € (blank: not disclosed)", raised),
      field(INVESTOR_HELP, investors),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: save }, "Save profile"),
        c.is_real ? h("button", { class: "btn", disabled: !S.mode.discover.ai.enabled, onclick: (e) => fillWithAI(e.currentTarget),
          title: "Fills only the empty fields, from its website and news headlines" }, "Fill with AI") : null)),
  ];
}

function reportView(report) {
  return h("ul", { class: "small report" }, Object.entries(report).map(([k, r]) => h("li", {}, h("b", {}, OUTSIDE[k]), ": ",
    r.done ? (r.posts === 0 ? "searched, found no posts about it" : r.posts ? `read ${r.posts} post${r.posts === 1 ? "" : "s"}` : "rated it")
      : r.error ? h("span", { class: "bad" }, r.error) : `skipped (${r.skipped})`)));
}

function opinionRow(c, key) {
  const label = OUTSIDE[key];
  const o = (c.opinions || {})[key];
  const social = !AI_SOURCES.includes(key);
  const nums = Object.fromEntries(AXES.map((a) => {
    const el = h("input", { type: "number", min: 0, max: 5, step: 0.5, "aria-label": `${label}: ${AXIS[a]}` });
    el.value = o && o.scores ? o.scores[a] : "";
    return [a, el];
  }));
  const note = h("input", { type: "text", maxlength: 600, placeholder: social ? "what people say" : "the model's reason" });
  note.value = o ? o.note : "";
  const links = social ? h("input", { type: "text", placeholder: "links to the posts, space-separated" }) : null;
  if (links) links.value = o && o.meta.links ? o.meta.links.join(" ") : "";
  async function save() {
    const scores = Object.fromEntries(AXES.map((a) => [a, parseFloat(nums[a].value)]));
    if (AXES.some((a) => !(scores[a] >= 0 && scores[a] <= 5))) return PD.toast(`${label}: give all four calls, 0–5`);
    try {
      await post(`/api/admin/companies/${c.id}/opinions/${key}`,
        { scores, note: note.value, links: links ? links.value.split(/\s+/).filter(Boolean) : [] }, "PUT");
      PD.toast(`${label} saved`);
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  async function clear() {
    try {
      await api(`/api/admin/companies/${c.id}/opinions/${key}`, { method: "DELETE" });
      PD.toast(`${label} cleared`);
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  const status = !o ? "none yet"
    : o.scores === null ? `found no posts · ${day(o.updated_at)}`
      : o.meta.by === "hand" ? `typed in · ${day(o.updated_at)}`
        : `${social ? `${o.meta.posts} post${o.meta.posts === 1 ? "" : "s"}, ${o.meta.via}` : o.meta.model} · ${day(o.updated_at)}`;
  const postLinks = social && o && o.meta.links ? o.meta.links.map(safeLink).filter(Boolean) : [];
  return h("tr", {},
    h("td", {}, h("b", {}, label), h("div", { class: "muted small" }, status)),
    AXES.map((a) => h("td", { class: "score-cell" }, nums[a])),
    h("td", { class: "wide" }, note, links,
      postLinks.length ? h("div", { class: "muted small" }, postLinks.map((u, i) => [i ? " · " : "",
        h("a", { href: u, target: "_blank", rel: "noopener noreferrer nofollow" }, `post ${i + 1} ↗`)])) : null),
    h("td", {}, h("div", { class: "row", style: { flexWrap: "nowrap" } },
      h("button", { class: "btn", onclick: save }, "Save"),
      o ? h("button", { class: "btn link", onclick: clear }, "Clear") : null)));
}

function opinionsForm(c) {
  const { ready, models, route } = S.mode.reads;
  async function fetchReads(kind) {
    S.fetching = kind;
    renderEditor();
    try {
      const out = await post(`/api/admin/companies/${c.id}/reads/${kind}`, {});
      S.report = out.report;
      const done = Object.values(out.report).filter((r) => r.done).length;
      PD.toast(`${done} of ${Object.keys(out.report).length} ${kind === "ai" ? "models" : "platforms"} read; details below`);
    } catch (e) { PD.toast(e.message); }
    S.fetching = null;
    await refresh();
  }
  const a = c.apelago;
  const busy = (kind) => S.fetching === kind;
  return [
    h("h3", {}, "Outside opinions"),
    h("p", { class: "muted small" }, "Fetch them, or type them in when there's no key or a search came up empty."),
    h("p", { class: "small" }, route === "openrouter" ? "All three through OpenRouter: " : null,
      AI_SOURCES.map((k, i) => [i ? " · " : "", h("b", {}, OUTSIDE[k]), " ", ready[k] ? h("span", { class: "muted" }, models[k])
        : h("span", { class: "bad" }, `not set up (${KEY_NAMES[k]} or OPENROUTER_API_KEY)`)])),
    h("div", { class: "row" },
      h("button", { class: `btn${busy("ai") ? " busy" : ""}`, disabled: !!S.fetching || !AI_SOURCES.some((k) => ready[k]),
        onclick: () => fetchReads("ai") }, busy("ai") ? "Asking the AIs… (up to a minute)" : "Ask the AIs"),
      h("button", { class: `btn${busy("social") ? " busy" : ""}`, disabled: !!S.fetching || !(ready.claude || ready.grok),
        onclick: () => fetchReads("social"), title: "Claude searches each platform's site; Grok searches X itself" },
      busy("social") ? "Reading social media… (a minute or two)" : "Read social media")),
    S.report ? reportView(S.report) : null,
    h("div", { class: "table-wrap" }, h("table", { class: "data opinions" },
      h("thead", {}, h("tr", {}, ["Source", ...AXES.map((x) => AXIS[x]), "Note", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, Object.keys(OUTSIDE).map((key) => opinionRow(c, key))))),
    h("p", { class: "small" }, h("b", {}, "A'Pelago: "),
      a ? `${a.n} reviewer${a.n === 1 ? "" : "s"} (${a.reps.join(", ")}) · ${AXES.map((x) => `${AXIS[x]} ${fmt1(a.means[x])}`).join(" · ")}`
        : "no evaluation yet. ",
      h("a", { href: "/moderate" }, "Evaluate on Moderation"), "."),
  ];
}

function renderEditor() {
  document.querySelectorAll(".drawer, .scrim").forEach((el) => el.remove());
  const c = S.editing && S.companies.find((x) => x.id === S.editing);
  if (!c) return;
  document.body.append(h("div", { class: "scrim", onclick: closeEditor }),
    h("aside", { class: "drawer wide", role: "dialog", "aria-label": c.name },
      h("button", { class: "btn link close", "aria-label": "Close", onclick: closeEditor }, "Close"),
      h("h2", {}, c.name),
      h("div", { class: "muted small" }, c.sector),
      profileForm(c),
      opinionsForm(c)));
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.editing) closeEditor(); });

// Built once; typing only refills the grid, so the search box keeps focus.
const grid = h("div", { class: "grid" });
const count = h("span", { class: "muted small" });
const search = h("input", { type: "search", placeholder: "Search", "aria-label": "Search companies",
  oninput: (e) => { S.query = e.target.value.trim().toLowerCase(); fillGrid(); } });

const shown = () => S.companies.filter((c) => !S.query || `${c.name} ${c.sector} ${c.one_liner}`.toLowerCase().includes(S.query));

function fillCount() {
  count.textContent = `${shown().length} of ${S.companies.length} · ${S.companies.filter((c) => c.active).length} in game`;
}

function fillGrid() {
  grid.replaceChildren(...shown().map(companyCard));
  fillCount();
}

function submissions() {
  if (!S.submissions.length) return null;
  async function approve(sub) {
    try {
      await post(`/api/admin/submissions/${sub.id}/approve`, {});
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  async function discard(sub) {
    if (!confirm(`Discard ${sub.name}?`)) return;
    await post(`/api/admin/submissions/${sub.id}`, undefined, "DELETE");
    await refresh();
  }
  return h("section", { class: "panel" },
    h("h2", {}, `Sent in by players (${S.submissions.length})`),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("tbody", {}, S.submissions.map((sub) => h("tr", {},
        h("td", {}, h("b", {}, link(sub.name, /^https?:\/\//i.test(sub.website) ? sub.website : ""))),
        h("td", { class: "muted" }, sub.sector),
        h("td", {}, sub.one_liner, h("div", { class: "muted small" }, sub.claim_ask)),
        h("td", { class: "num" }, h("div", { class: "row", style: { justifyContent: "flex-end" } },
          h("button", { class: "btn primary", onclick: () => approve(sub) }, "Approve"),
          h("button", { class: "btn link", onclick: () => discard(sub) }, "Discard")))))))));
}

function companiesTab() {
  fillGrid();
  return [submissions(), h("div", { class: "toolbar" }, search, count), grid];
}

// --- data -------------------------------------------------------------------------------------------

// Every card gets its AI ratings (and a real startup its social media read) by itself, when it's added and on
// startup. This shows the last run and starts one by hand.
function readsPanel() {
  const { ready, auto } = S.mode.reads;
  const errors = auto.errors || [];
  const any = Object.values(ready).some(Boolean);
  async function readMissing() {
    try {
      const r = await post("/api/admin/autoread", {});
      PD.toast(r.started ? "Reading cards that are missing something…" : "No model has a key: set OPENROUTER_API_KEY in .env");
    } catch (e) { PD.toast(e.message); }
    await refresh();
  }
  const tasks = S.mode.discover.ai.models;
  const { models } = S.mode.reads;
  return h("section", { class: "panel" }, h("h2", {}, "AI and social reads"),
    h("p", { class: "muted small" }, "Models, set per task in .env: ",
      `screening ${tasks.screen} · cards ${tasks.card} · profiles ${tasks.profile} · ratings ${models.claude}, ${models.gpt}, ${models.grok}.`),
    h("p", { class: "small" }, auto.running ? "Reading new cards…"
      : auto.finished_at ? `Last run ${auto.finished_at.slice(0, 16).replace("T", " ")}, ${auto.read.length} card${auto.read.length === 1 ? "" : "s"} read${errors.length ? `, ${errors.length} error${errors.length === 1 ? "" : "s"}` : ""}.`
        : any ? "Not run yet." : "Off until a key is set (OPENROUTER_API_KEY)."),
    errors.length ? h("p", { class: "small bad" }, errors.slice(-5).join(" · ")) : null,
    h("button", { class: `btn${auto.running ? " busy" : ""}`, disabled: auto.running || !any, onclick: readMissing,
      title: "Read every card still missing AI ratings or a social media read" }, "Read missing now"));
}

function dataTab() {
  const reset = (scope, label, question, danger) => h("button", { class: `btn${danger ? " danger" : ""}`, onclick: async () => {
    if (!confirm(question)) return;
    await post("/api/admin/reset", { scope });
    PD.toast("Done");
    await refresh();
  } }, label);
  return h("div", { class: "split" },
    h("div", {}, readsPanel(), h("section", { class: "panel" }, h("h2", {}, "Export"),
      h("div", { class: "row" },
        h("a", { class: "btn", href: "/api/admin/export.csv" }, "CSV"),
        h("a", { class: "btn", href: "/api/admin/export.json" }, "JSON")))),
    h("section", { class: "panel" }, h("h2", {}, "Reset"),
      h("div", { class: "row" },
        reset("seed", "Clear demo answers", "Remove the seeded players and their answers?"),
        reset("real", "Clear real answers", "Remove every real player's answers?", true),
        reset("everything", "Reset everything", "Delete all data and reload the sample companies and sets?", true))));
}

// --- page -------------------------------------------------------------------------------------------

function render() {
  const body = S.tab === "companies" ? companiesTab() : dataTab();
  $app.replaceChildren(...[
    h("div", { class: "head" }, h("h1", {}, "Admin"),
      Tool.tabs(TABS, S.tab, (k) => { S.tab = k; Tool.setHash(k); render(); })),
    ...[body].flat()].filter(Boolean));
}

async function refresh() {
  try {
    [S.companies, S.submissions, S.mode] = await Promise.all([
      api("/api/admin/companies?pool=current"), api("/api/admin/submissions"), api("/api/admin/mode")]);
    Tool.setInfo(S.mode);
    // Whatever comes back, only the current mode's pool is drawn.
    S.companies = S.companies.filter((c) => !!c.is_real === (S.mode.mode === "live"));
    render();
    renderEditor();
    // Keep polling while the automatic reads run in the background, so their results show up on their own.
    clearTimeout(S.poll);
    if (S.mode.reads.auto.running) S.poll = setTimeout(refresh, 3000);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(refresh);
refresh();
