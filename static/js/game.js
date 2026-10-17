// Game: who plays, the sets already played (with the crowd's read next to the engine's), and what's queued.
const { h, api, post, fmt1 } = PD;
const $app = document.getElementById("app");

const TABS = [{ key: "players", label: "Players" }, { key: "past", label: "Past games" }, { key: "next", label: "Next games" }];
const S = { tab: Tool.hashTab(TABS.map((t) => t.key), "next"), users: { users: [] }, dives: [], companies: [], open: new Map() };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

function names(d) {
  const byId = Object.fromEntries(S.companies.map((c) => [c.id, c.name]));
  return d.company_ids.map((id) => byId[id]).filter(Boolean).join(", ");
}

async function demoAnswers(d) {
  const r = await post("/api/admin/demo-votes", { dive_id: d.id, players: 30 });
  PD.toast(`${r.inserted} demo answers added`);
  S.open.delete(d.id);
  await refresh();
}

async function del(d) {
  if (!confirm(`Delete ${d.label} and its answers?`)) return;
  await post(`/api/admin/dives/${d.id}`, undefined, "DELETE");
  await refresh();
}

// --- players ----------------------------------------------------------------------------------------

function playersTab() {
  async function remove(u) {
    if (!confirm(`Delete ${u.username} and their ${u.answers} answers?`)) return;
    try {
      await post(`/api/admin/users/${u.id}`, undefined, "DELETE");
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  const { users, guests } = S.users;
  return h("section", { class: "panel" },
    h("div", { class: "row", style: { marginBottom: ".6rem" } }, h("h2", { style: { margin: 0 } }, plural(users.length, "account")),
      h("span", { class: "muted small" }, `+ ${plural(guests, "guest device")}`)),
    users.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Username", "Joined", "Sets", "Answers", "Last played", ""].map((t, i) =>
        h("th", { class: i >= 2 && i <= 3 ? "num" : "" }, t)))),
      h("tbody", {}, users.map((u) => h("tr", {},
        h("td", {}, h("b", {}, u.username)),
        h("td", {}, (u.created_at || "").slice(0, 10)),
        h("td", { class: "num" }, u.sets),
        h("td", { class: "num" }, u.answers),
        h("td", {}, u.last_played ? u.last_played.slice(0, 10) : "–"),
        h("td", { class: "num" }, h("button", { class: "btn link", onclick: () => remove(u) }, "Delete")))))))
      : h("p", { class: "empty" }, "No accounts yet."));
}

// --- past games -------------------------------------------------------------------------------------

async function toggle(d) {
  if (S.open.has(d.id)) S.open.delete(d.id);
  else S.open.set(d.id, await api(`/api/host/dives/${d.id}`));
  render();
}

function detailRows(d) {
  const detail = S.open.get(d.id);
  if (!detail) return null;
  return h("tr", { class: "sub" }, h("td", { colspan: 6 }, h("table", { class: "data" },
    h("thead", {}, h("tr", {}, ["Company", "Answers", "Crowd", "Engine", "Gap"].map((t, i) => h("th", { class: i ? "num" : "" }, t)))),
    h("tbody", {}, detail.cards.map((c) => {
      const gap = c.crowd.n && c.engine !== null ? c.crowd.composite - c.engine : null;
      return h("tr", {}, h("td", {}, c.name), h("td", { class: "num" }, c.crowd.n),
        h("td", { class: "num" }, c.crowd.n ? fmt1(c.crowd.composite) : "–"), h("td", { class: "num" }, fmt1(c.engine)),
        h("td", { class: "num" }, gap === null ? "–" : `${gap > 0 ? "+" : ""}${gap.toFixed(1)}`));
    })))));
}

function pastTab() {
  const past = S.dives.filter((d) => d.when === "past");
  if (!past.length) return h("p", { class: "empty" }, "No past games.");
  return h("section", { class: "panel" }, h("div", { class: "table-wrap" }, h("table", { class: "data" },
    h("thead", {}, h("tr", {}, ["Date", "Set", "Companies", "Players", "Answers", ""].map((t, i) =>
      h("th", { class: i === 3 || i === 4 ? "num" : "" }, t)))),
    h("tbody", {}, past.map((d) => [h("tr", {},
      h("td", {}, d.date), h("td", {}, h("b", {}, d.label)), h("td", { class: "muted" }, names(d)),
      h("td", { class: "num" }, d.players), h("td", { class: "num" }, d.answers),
      h("td", { class: "num" }, h("button", { class: "btn link", onclick: () => toggle(d) }, S.open.has(d.id) ? "Hide" : "Crowd vs engine"))),
    detailRows(d)])))));
}

// --- next games -------------------------------------------------------------------------------------

function builder() {
  const label = h("input", { type: "text", placeholder: "Label" });
  const date = h("input", { type: "text", placeholder: "YYYY-MM-DD (blank = any day)" });
  const pool = [...S.companies].sort((a, b) => b.active - a.active || a.name.localeCompare(b.name));
  const picks = Array.from({ length: 5 }, (_, i) => h("select", { "aria-label": `Card ${i + 1}` }, h("option", { value: "" }, `Card ${i + 1}`),
    pool.map((c) => h("option", { value: c.id }, `${c.name}${c.active ? "" : " (not in game)"}`))));
  async function create() {
    const ids = picks.map((p) => Number(p.value)).filter(Boolean);
    if (!label.value.trim() || !ids.length) return PD.toast("Add a label and at least one company");
    try {
      await post("/api/admin/dives", { label: label.value.trim(), company_ids: ids, date: date.value.trim() || null });
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  return h("section", { class: "panel" }, h("h2", {}, "Queue a game"),
    h("div", { class: "form" }, label, date, picks, h("button", { class: "btn primary", onclick: create }, "Add to queue")));
}

function nextTab() {
  const next = S.dives.filter((d) => d.when !== "past").sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999"));
  return h("div", { class: "split" },
    next.length ? h("section", { class: "panel" }, h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["When", "Set", "Companies", "Answers", ""].map((t, i) => h("th", { class: i === 3 ? "num" : "" }, t)))),
      h("tbody", {}, next.map((d) => h("tr", {},
        h("td", {}, d.when === "today" ? h("b", {}, "Today") : d.date || "Any day"),
        h("td", {}, h("b", {}, d.label)), h("td", { class: "muted" }, names(d)), h("td", { class: "num" }, d.answers),
        h("td", { class: "num" }, h("div", { class: "row", style: { justifyContent: "flex-end", flexWrap: "nowrap" } },
          h("a", { class: "btn link", href: `/play?dive=${d.id}`, target: "_blank" }, "Open"),
          h("button", { class: "btn link", onclick: () => demoAnswers(d) }, "Demo answers"),
          h("button", { class: "btn link", onclick: () => del(d) }, "Delete")))))))))
      : h("p", { class: "empty" }, "Nothing queued."),
    builder());
}

// --- page -------------------------------------------------------------------------------------------

function render() {
  const counts = { players: S.users.users.length, past: S.dives.filter((d) => d.when === "past").length,
    next: S.dives.filter((d) => d.when !== "past").length };
  const body = { players: playersTab, past: pastTab, next: nextTab }[S.tab]();
  $app.replaceChildren(
    h("div", { class: "head" }, h("h1", {}, "Game"),
      Tool.tabs(TABS.map((t) => ({ ...t, count: counts[t.key] })), S.tab, (k) => { S.tab = k; Tool.setHash(k); render(); })),
    body);
}

async function refresh() {
  try {
    [S.users, S.dives, S.companies] = await Promise.all([
      api("/api/admin/users"), api("/api/host/dives"), api("/api/admin/companies?pool=current")]);
    render();
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(() => { S.open.clear(); refresh(); });
refresh();
