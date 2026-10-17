// Moderation: every investor sign-up waits here until a moderator lets it in (players are in at once), and every
// member's profile and play is here. Moderators sign in with their own account; admins (the admin password) also make
// and remove moderators and change moderators' accounts.
// Both also give A'Pelago's own read of each startup, as its representatives.
const { h, api, post, fmt1, ROLES, AXES, AXIS } = PD;
const $app = document.getElementById("app");
const state = { view: location.pathname === "/review" ? "startups" : "people", tab: null, open: new Set(), sort: { key: "joined", dir: -1 }, kind: "all",
  drafts: {} }; // drafts: evaluations being filled in, by company id, so a refresh never loses them
let data = null; // people: /api/mod/users
let startups = null; // /api/mod/evaluations
let lastSig = null;

const LINKS = { linkedin: "LinkedIn", github: "GitHub", portfolio: "Portfolio", cv: "CV", other: "Other link" };

// Kept across renders so typing and choosing aren't interrupted.
const search = h("input", { type: "search", placeholder: "Filter by name, email or organisation", "aria-label": "Filter members",
  oninput: () => render() });

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const day = (iso) => (iso ? iso.slice(0, 10) : "–");
// Links are checked on the server; still, never render anything but plain http(s) as a link.
const safeLink = (url) => (/^https?:\/\//i.test(url || "") ? url : null);
const KIND = { player: "Player", investor: "Investor" };
// A player counts 1 and an investor more.
const weight = (u) => (u.kind === "investor" ? data.weights.investor : 1);
const times = (w) => `×${Number(w)}`;
// Moderator accounts, the viewer's own included, are changed by admins only (the server checks this too).
const locked = (u) => u.is_moderator && !data.viewer.admin;

function who(u) {
  const p = u.profile;
  const meta = [ROLES[p.role], p.organisation, p.location].filter(Boolean).join(" · ");
  return h("div", {},
    h("div", { class: "co-name" }, p.full_name ? [p.full_name, " ", h("span", { class: "handle" }, `@${u.username}`)] : u.username,
      u.is_moderator ? h("span", { class: "chip" }, "moderator") : null, u.is_test ? h("span", { class: "chip" }, "test account") : null),
    meta ? h("div", { class: "co-meta" }, meta) : null);
}

// "linkedin.com/in/jane-doe": a link shown as where it goes, without the scheme.
const linkText = (url) => url.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "");

// How a member has played, in a line of small figures.
function playLine(u) {
  const fig = (label, value, title) => h("div", { class: "pf-fig", title }, h("small", {}, label), h("b", {}, value));
  return h("div", { class: "pf-figs" },
    fig("Answers", u.answers), fig("Sets", u.sets),
    fig("Vs engine", u.engine_gap === null ? "–" : fmt1(u.engine_gap), "Average distance from the engine's evidence-based read, 0–5"),
    fig("Flat", u.flat_share === null ? "–" : `${Math.round(u.flat_share * 100)}%`, "Share of answers with all four calls the same"),
    fig("Last played", day(u.last_played)),
    data ? fig("Counts", times(weight(u)), "How much one of their answers counts in crowd scores") : null);
}

// Everything a member told us when they signed up: who they are, where to find them, what they know and why they
// want in, next to how they've played. Players sign up with a username only, so theirs is just the play.
function profileBody(u) {
  const p = u.profile;
  if (!p.full_name) {
    return h("div", { class: "profile" },
      h("p", { class: "muted small" }, u.kind === "player" ? "A player: they sign up with a username and password only."
        : "No sign-up details: this account didn't come through the sign-up form."),
      playLine(u));
  }
  const links = Object.entries(p.links || {}).filter(([, url]) => safeLink(url));
  const fact = (label, value) => (value ? [h("dt", {}, label), h("dd", {}, value)] : null);
  const review = u.status === "approved" ? `approved by ${u.reviewed_by || "a moderator"} ${day(u.reviewed_at)}`
    : u.status === "rejected" ? `rejected by ${u.reviewed_by || "a moderator"} ${day(u.reviewed_at)}` : "waiting for review";
  return h("div", { class: "profile pf" },
    h("div", { class: "pf-head" },
      h("div", {}, h("h3", {}, p.full_name, " ", h("span", { class: "handle" }, `@${u.username}`)),
        h("div", { class: "co-meta" }, [ROLES[p.role], p.organisation && `at ${p.organisation}`, p.location && `· ${p.location}`].filter(Boolean).join(" "))),
      h("span", { class: "spacer" }),
      h("a", { class: "btn small", href: `mailto:${p.email}` }, "Email ✉")),
    h("div", { class: "pf-grid" },
      h("div", {},
        h("dl", { class: "profile-facts" },
          fact("Email", h("a", { href: `mailto:${p.email}` }, p.email)),
          fact("Does", ROLES[p.role]),
          fact("Organisation", p.organisation),
          fact("Based in", p.location),
          fact("Knows well", p.expertise),
          fact("Signed up", `${day(u.created_at)} · ${review}`)),
        h("div", { class: "sub-head" }, "Why they want to join"),
        h("blockquote", { class: "motivation" }, p.motivation)),
      h("div", {},
        h("div", { class: "sub-head" }, `Links (${links.length})`),
        links.length ? h("ul", { class: "pf-links" }, links.map(([key, url]) => h("li", {},
          h("small", {}, LINKS[key] || key),
          h("a", { href: url, title: url, target: "_blank", rel: "noopener noreferrer nofollow" }, `${linkText(url)} ↗`))))
          : h("p", { class: "muted small" }, "No links."),
        h("div", { class: "sub-head" }, "How they play"),
        playLine(u))));
}

// --- waiting and rejected sign-ups -------------------------------------------------------------------

function signupCard(u) {
  const pending = u.status === "pending";
  return h("article", { class: "signup" },
    h("div", { class: "signup-head" }, who(u), h("span", { class: "spacer" }),
      h("span", { class: "co-meta" }, pending ? `Signed up ${day(u.created_at)}`
        : `Rejected by ${u.reviewed_by || "a moderator"} · ${day(u.reviewed_at)}`)),
    profileBody(u),
    h("div", { class: "signup-actions" },
      h("span", { class: "spacer" }),
      pending ? h("button", { class: "btn danger", onclick: () => review(u, "rejected") }, "Reject")
        : h("button", { class: "btn danger", onclick: () => remove(u) }, "Delete"),
      h("button", { class: "btn primary", onclick: () => review(u, "approved") }, "Approve")));
}

// --- members ------------------------------------------------------------------------------------------

const COLUMNS = [
  { label: "Member", sort: "name" },
  { label: "Kind", sort: "kind", title: "Players are in at once; investors are reviewed here and count for more." },
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
  kind: (u) => u.kind,
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
      onclick: () => { state.sort = { key: col.sort, dir: on ? -state.sort.dir : (["name", "kind"].includes(col.sort) ? 1 : -1) }; render(); } },
    col.label, h("span", { class: "dir" }, on ? (state.sort.dir > 0 ? "↑" : "↓") : ""));
  }));
}

function memberRows(u) {
  const open = state.open.has(u.id);
  const row = h("tr", { class: `clickable${open ? " open" : ""}`, "aria-expanded": String(open), onclick: () => {
    open ? state.open.delete(u.id) : state.open.add(u.id);
    render();
  } },
  h("td", {}, h("div", { class: "row", style: { gap: ".3rem", flexWrap: "nowrap", alignItems: "flex-start" } },
    h("span", { class: "caret", "aria-hidden": "true" }, "›"), who(u))),
  h("td", {}, KIND[u.kind], h("div", { class: "co-meta" }, `counts ${times(weight(u))}`)),
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
    locked(u) ? null : passwordRow(u),
    data.viewer.admin ? h("div", { class: "row" },
      h("button", { class: "btn small", onclick: () => setModerator(u, !u.is_moderator) }, u.is_moderator ? "Remove moderator" : "Make moderator"),
      h("span", { class: "muted small" }, u.is_moderator ? "They keep their account and go back to being a member."
        : "They sign in here with their own username and password.")) : null))];
}

// All members, or only investors or only players.
function kindSeg(list) {
  const n = (k) => (k === "all" ? list.length : list.filter((u) => (k === "mods" ? u.is_moderator : u.kind === k)).length);
  return h("div", { class: "seg", role: "group", "aria-label": "Show accounts" },
    [["all", "All"], ["investor", "Investors"], ["player", "Players"], ["mods", "Moderators"]].map(([k, label]) => h("button", { type: "button",
      "aria-pressed": String(state.kind === k), onclick: () => { state.kind = k; render(); } }, `${label} (${n(k)})`)));
}

function membersView(list) {
  const q = search.value.trim().toLowerCase();
  const shown = sorted(list.filter((u) => (state.kind === "all" || (state.kind === "mods" ? u.is_moderator : u.kind === state.kind))
    && (!q || [u.username, u.profile.full_name, u.profile.email, u.profile.organisation].join(" ").toLowerCase().includes(q))));
  const w = data.weights;
  return [
    h("p", { class: "muted small" },
      `In crowd scores a player's answer counts ×1 and an investor's ${times(w.investor)}. Guests count ${times(w.guest)}, and together at most `,
      `${Math.round(w.guest_max_share * 100)}% of a card.`),
    h("div", { class: "toolbar" }, kindSeg(list), search, h("span", { class: "muted small" }, `${shown.length} of ${list.length}`)),
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

async function review(u, status) {
  try {
    await post(`/api/mod/users/${u.id}/review`, { status });
    PD.toast(status === "approved" ? `${u.username} is in` : `${u.username} rejected`);
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

// A new password the moderator types and then tells the member directly. Their old logins end.
function passwordRow(u) {
  const input = h("input", { type: "text", placeholder: "New password", autocomplete: "off", "aria-label": `New password for ${u.username}`,
    onkeydown: (e) => { if (e.key === "Enter") resetPassword(u, input, btn); } });
  const btn = h("button", { class: "btn small", onclick: () => resetPassword(u, input, btn) }, "Reset password");
  return h("div", { class: "row pw-reset" }, h("span", { class: "caps muted" }, "Password"), input, btn,
    h("span", { class: "muted small" }, "Tell them the new one yourself; they're logged out everywhere."));
}

async function resetPassword(u, input, btn) {
  const password = input.value.trim();
  if (!password) { input.focus(); return; }
  btn.disabled = true;
  try {
    await post(`/api/mod/users/${u.id}/password`, { password }, "PUT");
    PD.toast(`${u.username}'s password is now “${password}”`, 6000);
    input.value = "";
  } catch (e) { PD.toast(e.message); }
  btn.disabled = false;
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

// --- A'Pelago's read of each startup -----------------------------------------------------------------------

function draftOf(c) {
  return (state.drafts[c.id] ||= { scores: { ...(c.mine ? c.mine.scores : {}) }, note: c.mine ? c.mine.note : "" });
}

async function saveEvaluation(c) {
  const d = draftOf(c);
  try {
    await post(`/api/mod/evaluations/${c.id}`, d, "PUT");
    delete state.drafts[c.id];
    PD.toast(`${c.name}: evaluation saved`);
  } catch (e) { PD.toast(e.message); }
  await refresh();
}

async function withdrawEvaluation(c) {
  try {
    await api(`/api/mod/evaluations/${c.id}`, { method: "DELETE" });
    delete state.drafts[c.id];
    PD.toast(`${c.name}: evaluation withdrawn`);
  } catch (e) { PD.toast(e.message); }
  await refresh();
}

// Each startup as the dashboard's opened card: its colour, the pitch big, the facts in boxes, and your four calls as the
// game's rows of 0-5 buttons.
function evaluationCard(c, i) {
  const d = draftOf(c);
  const complete = AXES.every((a) => d.scores[a] !== undefined);
  const site = safeLink(c.website);
  const invested = c.investors.filter((x) => x.status === "invested");
  const sect = (title, ...kids) => h("section", { class: "sect" }, h("div", { class: "caps sect-title" }, title), ...kids);
  const subTitle = (text) => h("div", { class: "caps sub-title" }, text);
  const box = (label, value, cls = "") => h("div", { class: `fact-box ${cls}` }, h("small", { class: "caps" }, label), h("b", {}, value));
  const note = h("textarea", { rows: 3, maxlength: 600, placeholder: "A comment for the team (players don't see it)",
    "aria-label": `Comment on ${c.name}`, oninput: (e) => { d.note = e.target.value; } });
  note.value = d.note;
  const ap = c.apelago;
  return h("article", { class: "card dossier eval-card", style: { "--card": PD.colorFor(i) } },
    h("header", { class: "dossier-head" },
      h("div", { class: "pitch" },
        h("div", { class: "name-row" }, c.emoji ? h("div", { class: "art small", "aria-hidden": "true" }, c.emoji) : null,
          h("div", {}, h("h2", {}, c.name),
            h("div", { class: "row meta" },
              h("span", { class: `tag${c.active ? " in" : ""}` }, c.active ? "In game" : "Not in the game"),
              c.sector ? h("span", { class: "caps sector" }, c.sector) : null,
              site ? h("a", { class: "site", href: site, target: "_blank", rel: "noopener noreferrer nofollow" }, `${PD.hostOf(site)} ↗`) : null))),
        c.one_liner ? h("p", { class: "pitch-line" }, c.one_liner) : null,
        c.claim_ask ? h("p", { class: "ask" }, c.claim_ask) : null),
      h("section", { class: "sect call-box" },
        h("div", { class: "caps sect-title" }, "A'Pelago's read"),
        ap ? [h("p", { class: "note" }, `${plural(ap.n, "reviewer")}: ${ap.reps.join(", ")}`), PD.opinionChart(ap.means, { labelled: true })]
          : h("p", { class: "note" }, "The team's average shows here once you've given yours."))),
    h("div", { class: "dossier-grid" },
      h("div", { class: "col" },
        sect("The startup",
          h("div", { class: "fact-grid" },
            box("Raised so far", c.raised_eur === null || c.raised_eur === undefined ? "Not given" : PD.money(c.raised_eur)),
            box("Investors", invested.length ? String(invested.length) : "None yet"),
            box("Stage", c.stages.length ? c.stages[c.stages.length - 1] : "Not given", "wide")),
          c.stages.length ? [subTitle("Stages passed"), h("ol", { class: "stage-list" }, c.stages.map((st) => h("li", {}, st)))] : null,
          c.investors.length ? [subTitle("Investors"),
            h("ul", { class: "investor-list" }, c.investors.map((x) => h("li", {}, h("b", {}, x.name), " ",
              x.status === "interested" ? h("span", { class: "interested" }, "interested")
                : x.amount_eur ? PD.money(x.amount_eur) : "invested")))] : null),
        c.vision ? sect("Vision", h("div", { class: `vision-text${c.vision.split(/\s+/).length > 110 ? " long" : ""}` },
          c.vision.split(/\n{2,}/).map((para) => h("p", { class: "vision" }, para)))) : null),
      h("div", { class: "col" },
        h("section", { class: "sect eval-call" },
          h("div", { class: "eval-call-head" }, h("span", { class: "caps sect-title" }, "Your read"),
            h("span", { class: "note" }, c.mine ? `You rated it ${day(c.mine.updated_at)}` : "Not rated by you yet")),
          AXES.map((a) => h("div", { class: "eval-axis-row" },
            h("div", { class: "caps axis-label" }, AXIS[a]),
            h("div", { class: "taps", role: "group", "aria-label": AXIS[a] }, [0, 1, 2, 3, 4, 5].map((n) => h("button", {
              type: "button", class: d.scores[a] === n ? "on" : "", "aria-pressed": String(d.scores[a] === n),
              onclick: () => { d.scores[a] = n; render(); } }, n))))),
          note,
          h("div", { class: "eval-actions" },
            c.mine ? h("button", { class: "pill small ghost", onclick: () => withdrawEvaluation(c) }, "Withdraw") : null,
            h("button", { class: "pill small", disabled: !complete, onclick: () => saveEvaluation(c),
              title: complete ? null : "Give all four calls first" }, c.mine ? "Update" : "Save evaluation"))))));
}

function startupsView() {
  const list = [...startups.companies].sort((a, b) => !!a.mine - !!b.mine); // yours to do first
  return list.length ? h("div", { class: "eval-list" }, list.map(evaluationCard))
    : h("p", { class: "muted", style: { margin: 0 } }, "No startups in this mode yet.");
}

// --- page -----------------------------------------------------------------------------------------------

function kpi(label, value, sub) {
  return h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}

// Moderators only get Moderation and Review: links to the admin's tools would just ask them for the admin password.
function trimNav() {
  if (data.viewer.admin) return;
  document.querySelectorAll("nav a[data-nav]").forEach((a) => { if (!["/moderate", "/review"].includes(a.dataset.nav)) a.remove(); });
}

function render() {
  if (!data || !startups) return;
  trimNav();
  const reviewing = state.view === "startups";
  const toRate = startups.companies.filter((c) => !c.mine).length;
  document.title = reviewing ? "Review" : "Moderation";
  const scroll = window.scrollY;
  $app.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, reviewing ? "Review" : "Moderation"),
      h("p", {}, reviewing
        ? ["Rate each startup as an A'Pelago representative, not as a player. Players see the average of every ",
          "representative's read next to their own, after answering; you see it once you've given yours. Comments stay with the team."]
        : "Let investors in and see who plays.")),
    h("span", { class: "spacer" }),
    reviewing && startups.mode !== "live" ? h("span", { class: "chip" }, "Sample startups (demo mode)") : null,
    reviewing ? h("span", { class: "chip" }, toRate ? `${toRate} to rate` : "All rated") : null,
    h("span", { class: "chip" }, data.viewer.admin ? "Signed in as admin" : `Signed in as ${data.viewer.name}`)),
    ...(reviewing ? [startupsView()] : peopleView()));
  window.scrollTo({ top: scroll });
}

function peopleView() {
  const by = { pending: [], approved: [], rejected: [] };
  for (const u of data.users) (by[u.status] || by.pending).push(u);
  by.pending.reverse(); // oldest first: first come, first reviewed
  state.tab ||= by.pending.length ? "pending" : "approved";
  const members = by.approved;
  const tab = (key, label) => h("button", { class: `btn${state.tab === key ? " primary" : ""}`, "aria-pressed": String(state.tab === key),
    onclick: () => { state.tab = key; render(); } }, `${label} (${by[key].length})`);
  const list = by[state.tab];
  return [
    h("div", { class: "kpis" },
      kpi("Waiting", by.pending.length, by.pending.length ? `sign-up${by.pending.length === 1 ? "" : "s"} to review` : "all caught up"),
      kpi("Members", members.length, `${plural(members.filter((u) => u.kind === "investor").length, "investor")} · ${plural(members.filter((u) => u.kind !== "investor").length, "player")}`),
      kpi("Guests", data.guests, "devices playing without an account")),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" },
        h("div", { class: "seg", role: "group", "aria-label": "Show" },
          tab("pending", "Waiting"), tab("approved", "Members"), tab("rejected", "Rejected"))),
      state.tab === "approved" ? membersView(members)
        : list.length ? h("div", { class: "signups" }, list.map(signupCard))
          : h("p", { class: "muted", style: { margin: 0 } },
            state.tab === "pending" ? "No investor sign-ups waiting. New ones show up here." : "No rejected sign-ups.")),
  ];
}

async function refresh(force = true) {
  let fresh;
  try {
    const [users, evaluations] = await Promise.all([api("/api/mod/users"), api("/api/mod/evaluations")]);
    fresh = { users, evaluations };
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
    return;
  }
  // Background refreshes skip the rebuild when nothing changed (keeps scroll and open rows steady).
  const sig = JSON.stringify(fresh);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  data = fresh.users;
  startups = fresh.evaluations;
  render();
}

refresh();
// New sign-ups show up on their own, but never while a dropdown or the search box is in use.
setInterval(() => {
  if (!document.hidden && !$app.contains(document.activeElement)) refresh(false);
}, 15000);
