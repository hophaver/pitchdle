// Moderation: every sign-up waits here until a moderator lets it in. Members carry a badge that sets how much
// their answers count in crowd scores: high or low priority, or muted (not at all). Moderators sign in with their
// own account; admins (the admin password) also make and remove moderators and change moderators' accounts.
const { h, api, post, fmt1, ROLES } = PD;
const $app = document.getElementById("app");
const state = { tab: null, open: new Set(), sort: { key: "joined", dir: -1 }, badge: "all", picks: {} };
let data = null;
let lastSig = null;

const LINKS = { linkedin: "LinkedIn", github: "GitHub", portfolio: "Portfolio", cv: "CV", other: "Other link" };
const BADGE = { "": "No badge", high: "High priority", low: "Low priority", muted: "Muted" };
const BADGE_ORDER = { high: 0, "": 1, low: 2, muted: 3 };

// Kept across renders so typing and choosing aren't interrupted.
const search = h("input", { type: "search", placeholder: "Filter by name, email or organisation", "aria-label": "Filter members",
  oninput: () => render() });
const badgeFilter = h("select", { "aria-label": "Filter by badge", onchange: (e) => { state.badge = e.target.value; render(); } },
  h("option", { value: "all" }, "All badges"), ["high", "", "low", "muted"].map((b) => h("option", { value: b }, BADGE[b])),
  h("option", { value: "mods" }, "Moderators"));

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const day = (iso) => (iso ? iso.slice(0, 10) : "–");
// Links are checked on the server; still, never render anything but plain http(s) as a link.
const safeLink = (url) => (/^https?:\/\//i.test(url || "") ? url : null);
const weight = (badge) => ({ "": 1, high: data.weights.high, low: data.weights.low, muted: 0 })[badge];
const times = (w) => `×${Number(w)}`;
// Moderator accounts, the viewer's own included, are changed by admins only (the server checks this too).
const locked = (u) => u.is_moderator && !data.viewer.admin;

function badgeSelect(selected, label, onchange) {
  const sel = h("select", { class: `badge-select badge-${selected || "none"}`, "aria-label": label },
    ["", "high", "low", "muted"].map((b) => h("option", { value: b, selected: b === selected }, `${BADGE[b]} ${times(weight(b))}`)));
  sel.addEventListener("change", () => {
    sel.className = `badge-select badge-${sel.value || "none"}`;
    onchange(sel.value);
  });
  return sel;
}

function who(u) {
  const p = u.profile;
  const meta = [ROLES[p.role], p.organisation, p.location].filter(Boolean).join(" · ");
  return h("div", {},
    h("div", { class: "co-name" }, p.full_name || u.username, " ", h("span", { class: "handle" }, `@${u.username}`),
      u.is_moderator ? h("span", { class: "chip" }, "moderator") : null, u.is_test ? h("span", { class: "chip" }, "test account") : null),
    meta ? h("div", { class: "co-meta" }, meta) : null);
}

function profileBody(u) {
  const p = u.profile;
  if (!p.full_name) return h("p", { class: "muted small" }, "No sign-up details: this account didn't come through the sign-up form.");
  const links = Object.entries(p.links || {}).filter(([, url]) => safeLink(url));
  return h("div", { class: "profile" },
    links.length ? h("div", { class: "links" }, links.map(([key, url]) => h("a", { class: "chip", href: url, title: url,
      target: "_blank", rel: "noopener noreferrer nofollow" }, `${LINKS[key] || key} ↗`))) : null,
    h("dl", { class: "facts" },
      h("dt", {}, "Email"), h("dd", {}, p.email),
      p.expertise ? [h("dt", {}, "Knows"), h("dd", {}, p.expertise)] : null),
    h("blockquote", { class: "motivation" }, p.motivation));
}

// --- waiting and rejected sign-ups -------------------------------------------------------------------

function signupCard(u) {
  const pending = u.status === "pending";
  // The badge a new member starts with, picked before approving (e.g. muted for a founder in the game).
  const pick = pending ? badgeSelect(state.picks[u.id] || "", `Badge for ${u.username}`, (b) => { state.picks[u.id] = b; }) : null;
  return h("article", { class: "signup" },
    h("div", { class: "signup-head" }, who(u), h("span", { class: "spacer" }),
      h("span", { class: "co-meta" }, pending ? `Signed up ${day(u.created_at)}`
        : `Rejected by ${u.reviewed_by || "a moderator"} · ${day(u.reviewed_at)}`)),
    profileBody(u),
    h("div", { class: "signup-actions" },
      pending ? h("label", { class: "check" }, "Start with", pick) : null,
      h("span", { class: "spacer" }),
      pending ? h("button", { class: "btn danger", onclick: () => review(u, "rejected") }, "Reject")
        : h("button", { class: "btn danger", onclick: () => remove(u) }, "Delete"),
      h("button", { class: "btn primary", onclick: () => review(u, "approved", pending ? pick.value : "") }, "Approve")));
}

// --- members ------------------------------------------------------------------------------------------

const COLUMNS = [
  { label: "Member", sort: "name" },
  { label: "Badge", sort: "badge" },
  { label: "Answers", sort: "answers", num: true },
  { label: "Sets", sort: "sets", num: true },
  { label: "Vs engine", sort: "engine", num: true,
    title: "Average distance between their overall read of a card and the engine's evidence-based one, 0–5. Lower is closer to the evidence." },
  { label: "Flat", sort: "flat", num: true,
    title: "Share of their answers that gave all four calls one number, like 3-3-3-3. A high share can mean clicking through." },
  { label: "Last played", sort: "last" },
  { label: "Joined", sort: "joined" },
  { label: "" },
];

const SORTERS = {
  name: (u) => (u.profile.full_name || u.username).toLowerCase(),
  badge: (u) => BADGE_ORDER[u.badge],
  answers: (u) => u.answers,
  sets: (u) => u.sets,
  engine: (u) => (u.engine_gap === null ? -1 : u.engine_gap),
  flat: (u) => (u.flat_share === null ? -1 : u.flat_share),
  last: (u) => u.last_played || "",
  joined: (u) => u.created_at || "",
};

function sorted(list) {
  const key = SORTERS[state.sort.key];
  return [...list].sort((a, b) => {
    const x = key(a), y = key(b);
    return (x < y ? -1 : x > y ? 1 : 0) * state.sort.dir || a.username.localeCompare(b.username);
  });
}

function header() {
  return h("tr", {}, COLUMNS.map((col) => {
    if (!col.sort) return h("th", { class: col.num ? "num" : "", title: col.title }, col.label);
    const on = state.sort.key === col.sort;
    return h("th", { class: `sortable${col.num ? " num" : ""}`, title: col.title,
      "aria-sort": on ? (state.sort.dir > 0 ? "ascending" : "descending") : "none",
      onclick: () => { state.sort = { key: col.sort, dir: on ? -state.sort.dir : (col.sort === "name" || col.sort === "badge" ? 1 : -1) }; render(); } },
    col.label, h("span", { class: "dir" }, on ? (state.sort.dir > 0 ? "↑" : "↓") : ""));
  }));
}

function memberRows(u) {
  const open = state.open.has(u.id);
  const sel = badgeSelect(u.badge, `Badge for ${u.username}`, (b) => setBadge(u, b));
  sel.addEventListener("click", (e) => e.stopPropagation());
  if (locked(u)) {
    sel.disabled = true;
    sel.title = "Only an admin can change a moderator's badge";
  }
  const row = h("tr", { class: `clickable${open ? " open" : ""}`, "aria-expanded": String(open), onclick: () => {
    open ? state.open.delete(u.id) : state.open.add(u.id);
    render();
  } },
  h("td", {}, h("div", { class: "row", style: { gap: ".3rem", flexWrap: "nowrap", alignItems: "flex-start" } },
    h("span", { class: "caret", "aria-hidden": "true" }, "›"), who(u))),
  h("td", {}, sel, u.badge_by ? h("div", { class: "co-meta" }, `${u.badge_by} · ${day(u.badge_at)}`) : null),
  h("td", { class: "num" }, u.answers),
  h("td", { class: "num" }, u.sets),
  h("td", { class: "num" }, u.engine_gap === null ? "–" : fmt1(u.engine_gap)),
  h("td", { class: "num" }, u.flat_share === null ? "–" : `${Math.round(u.flat_share * 100)}%`),
  h("td", {}, day(u.last_played)),
  h("td", {}, day(u.created_at)),
  h("td", {}, locked(u) ? null : h("button", { class: "btn small danger", onclick: (e) => { e.stopPropagation(); remove(u); } }, "Delete")));
  if (!open) return row;
  return [row, h("tr", { class: "detail" }, h("td", { colspan: COLUMNS.length },
    profileBody(u),
    h("p", { class: "co-meta" }, u.reviewed_by ? `Approved by ${u.reviewed_by} on ${day(u.reviewed_at)}` : "No review on record."),
    data.viewer.admin ? h("div", { class: "row" },
      h("button", { class: "btn small", onclick: () => setModerator(u, !u.is_moderator) }, u.is_moderator ? "Remove moderator" : "Make moderator"),
      h("span", { class: "muted small" }, u.is_moderator ? "They keep their account and go back to being a member."
        : "They sign in here with their own username and password.")) : null))];
}

function membersView(list) {
  const q = search.value.trim().toLowerCase();
  const shown = sorted(list.filter((u) => (state.badge === "all" || (state.badge === "mods" ? u.is_moderator : u.badge === state.badge))
    && (!q || [u.username, u.profile.full_name, u.profile.email, u.profile.organisation].join(" ").toLowerCase().includes(q))));
  const w = data.weights;
  return [
    h("p", { class: "muted small" },
      `Badges set how much a member's answers count in crowd scores: high priority ${times(w.high)}, no badge ×1, `,
      `low priority ${times(w.low)}, muted ×0. Guests count ${times(w.guest)}, and together at most `,
      `${Math.round(w.guest_max_share * 100)}% of a card. The live room counts everyone alike, except muted members, who never count.`),
    h("div", { class: "toolbar" }, search, badgeFilter, h("span", { class: "muted small" }, `${shown.length} of ${list.length}`)),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, header()),
      h("tbody", {}, shown.length ? shown.map(memberRows)
        : h("tr", {}, h("td", { colspan: COLUMNS.length, class: "muted" }, list.length ? "No members match." : "No members yet."))))),
    h("p", { class: "muted small", style: { margin: ".7rem 0 0" } },
      "Vs engine and Flat are hints for judging a member's reads; hover the headers for what they measure. Click a row for the profile",
      data.viewer.admin ? ", and to make them a moderator." : "."),
  ];
}

// --- actions --------------------------------------------------------------------------------------------

async function review(u, status, badge = "") {
  try {
    await post(`/api/mod/users/${u.id}/review`, { status, badge });
    delete state.picks[u.id];
    PD.toast(status === "approved" ? `${u.username} is in${badge ? ` · ${BADGE[badge].toLowerCase()}` : ""}` : `${u.username} rejected`);
  } catch (e) { PD.toast(e.message); }
  await refresh();
}

async function setBadge(u, badge) {
  try {
    await post(`/api/mod/users/${u.id}/badge`, { badge }, "PUT");
    PD.toast(`${u.username}: ${BADGE[badge].toLowerCase()}, answers count ${times(weight(badge))}`);
  } catch (e) { PD.toast(e.message); }
  await refresh();
}

async function setModerator(u, on) {
  try {
    await post(`/api/mod/users/${u.id}/moderator`, { moderator: on }, "PUT");
    PD.toast(on ? `${u.username} can moderate now` : `${u.username} isn't a moderator any more`);
  } catch (e) { PD.toast(e.message); }
  await refresh();
}

async function remove(u) {
  if (!confirm(`Delete ${u.username}${u.answers ? ` and all ${plural(u.answers, "answer")}` : ""}? This can't be undone.`)) return;
  try {
    await api(`/api/mod/users/${u.id}`, { method: "DELETE" });
    state.open.delete(u.id);
    PD.toast(`${u.username} deleted`);
  } catch (e) { PD.toast(e.message); }
  await refresh();
}

// --- page -----------------------------------------------------------------------------------------------

function kpi(label, value, sub) {
  return h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}

// Moderators only get this page: links to the admin's tools would just ask them for the admin password.
function trimNav() {
  if (data.viewer.admin) return;
  document.querySelectorAll("nav a[data-nav]").forEach((a) => { if (a.dataset.nav !== "/moderate") a.remove(); });
  document.querySelector("nav .brand small").textContent = "Moderation";
}

function render() {
  if (!data) return;
  trimNav();
  const by = { pending: [], approved: [], rejected: [] };
  for (const u of data.users) (by[u.status] || by.pending).push(u);
  by.pending.reverse(); // oldest first: first come, first reviewed
  state.tab ||= by.pending.length ? "pending" : "approved";
  const members = by.approved;
  const badged = (b) => members.filter((u) => u.badge === b).length;
  const tab = (key, label) => h("button", { class: `btn${state.tab === key ? " primary" : ""}`, "aria-pressed": String(state.tab === key),
    onclick: () => { state.tab = key; render(); } }, `${label} (${by[key].length})`);
  const list = by[state.tab];
  const scroll = window.scrollY;

  $app.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Moderation"),
      h("p", {}, "Let sign-ups in, and set how much each member's answers count.")),
      h("span", { class: "spacer" }),
      h("span", { class: "chip" }, data.viewer.admin ? "Signed in as admin" : `Signed in as ${data.viewer.name}`)),
    h("div", { class: "kpis" },
      kpi("Waiting", by.pending.length, by.pending.length ? `sign-up${by.pending.length === 1 ? "" : "s"} to review` : "all caught up"),
      kpi("Members", members.length, `${badged("high")} high · ${badged("low")} low · ${badged("muted")} muted`),
      kpi("Guests", data.guests, "devices playing without an account")),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" },
        h("div", { class: "seg", role: "group", "aria-label": "Show" },
          tab("pending", "Waiting"), tab("approved", "Members"), tab("rejected", "Rejected"))),
      state.tab === "approved" ? membersView(members)
        : list.length ? h("div", { class: "signups" }, list.map(signupCard))
          : h("p", { class: "muted", style: { margin: 0 } },
            state.tab === "pending" ? "No sign-ups waiting. New ones show up here." : "No rejected sign-ups.")));
  window.scrollTo({ top: scroll });
}

async function refresh(force = true) {
  let fresh;
  try {
    fresh = await api("/api/mod/users");
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
// New sign-ups show up on their own, but never while a dropdown or the search box is in use.
setInterval(() => {
  if (!document.hidden && !$app.contains(document.activeElement)) refresh(false);
}, 15000);
