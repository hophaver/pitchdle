// Admin: which companies are in the game, player submissions, exports and resets.
const { h, api, post } = PD;
const $app = document.getElementById("app");

const TABS = [{ key: "companies", label: "Companies" }, { key: "data", label: "Data" }];
const S = { tab: Tool.hashTab(TABS.map((t) => t.key), "companies"), companies: [], submissions: [], mode: null, query: "" };

const link = (name, url) => (url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, name) : name);

// --- companies --------------------------------------------------------------------------------------

async function setInGame(c, on, box) {
  box.disabled = true;
  try {
    await post(`/api/admin/companies/${c.id}`, {
      name: c.name, emoji: c.emoji || "", sector: c.sector || "", one_liner: c.one_liner || "", claim_ask: c.claim_ask || "",
      website: c.website || "", facts: c.facts || [], evidence: c.evidence || {}, evidence_note: c.evidence_note || "", active: on,
    }, "PUT");
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
    h("label", { class: "check" }, box, "In game"));
}

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

function dataTab() {
  const reset = (scope, label, question, danger) => h("button", { class: `btn${danger ? " danger" : ""}`, onclick: async () => {
    if (!confirm(question)) return;
    await post("/api/admin/reset", { scope });
    PD.toast("Done");
    await refresh();
  } }, label);
  return h("div", { class: "split" },
    h("section", { class: "panel" }, h("h2", {}, "Export"),
      h("div", { class: "row" },
        h("a", { class: "btn", href: "/api/admin/export.csv" }, "CSV"),
        h("a", { class: "btn", href: "/api/admin/export.json" }, "JSON"))),
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
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(refresh);
refresh();
