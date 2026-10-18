// Game: the sets already played (with the crowd's read next to the engine's) and what's queued, queued by hand or
// generated for the next days. In live mode a startup plays one day only, unless a major update brings it back.
// Who plays is on Moderation › People.
const { h, api, post, fmt1 } = PD;
const $app = document.getElementById("app");

const TABS = [{ key: "next", label: "Next games" }, { key: "past", label: "Past games" }];
// A game queued by hand starts with five cards, like the daily ones. "+ Add a card" takes it up to MAX_CARDS
// (MAX_SET_CARDS in app/main.py) and each card's ✕ down to one.
const DEFAULT_CARDS = 5;
const MAX_CARDS = 20;
const S = { tab: Tool.hashTab(TABS.map((t) => t.key), "next"), dives: [], companies: [], pool: null, open: new Map(),
  picks: Array(DEFAULT_CARDS).fill("") };

const byId = () => Object.fromEntries(S.companies.map((c) => [c.id, c]));
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const dayLabel = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) : "Any day");

// The startups in a game as chips; one a major update brought back is marked.
function chips(d) {
  const all = byId();
  const back = new Set(S.pool ? S.pool.updated : []);
  return h("div", { class: "g-chips" }, d.company_ids.map((id) => all[id]).filter(Boolean).map((c) =>
    h("span", { class: `g-chip${back.has(c.id) && d.when !== "past" ? " back" : ""}`, title: c.sector || null },
      c.name, back.has(c.id) && d.when !== "past" ? h("small", {}, " ↻ updated") : null)));
}

async function demoAnswers(d) {
  try {
    const r = await post("/api/admin/demo-votes", { dive_id: d.id, players: 30 });
    PD.toast(`${r.inserted} demo answers added`);
  } catch (e) { PD.toast(e.message); }
  S.open.delete(d.id);
  await refresh();
}

async function del(d) {
  if (!confirm(`Delete ${d.label} and its answers?`)) return;
  await post(`/api/admin/dives/${d.id}`, undefined, "DELETE");
  await refresh();
}

function kpi(label, value, sub) {
  return h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}

function kpis() {
  const inGame = S.companies.filter((c) => c.active).length;
  const next = S.dives.filter((d) => d.when !== "past");
  const lastQueued = next.map((d) => d.date).filter(Boolean).sort().pop();
  const played = S.dives.filter((d) => d.when === "past");
  const live = S.pool && !S.pool.repeats;
  return h("div", { class: "kpis" },
    live ? kpi("Unplayed startups", S.pool.eligible.length,
      S.pool.updated.length ? `of ${inGame} in the game · ${S.pool.updated.length} back after a major update` : `of ${inGame} in the game`)
      : kpi("In the game", inGame, "demo companies rotate"),
    kpi("Games queued", next.length, lastQueued ? `through ${dayLabel(lastQueued)}` : "nothing queued"),
    kpi("Games played", played.length, played.length ? `${played.reduce((n, d) => n + d.players, 0)} players in all` : "none yet"));
}

// --- past games -------------------------------------------------------------------------------------

async function toggle(d) {
  if (S.open.has(d.id)) S.open.delete(d.id);
  else S.open.set(d.id, await api(`/api/host/dives/${d.id}`));
  render();
}

function detail(d) {
  const det = S.open.get(d.id);
  if (!det) return null;
  return h("div", { class: "table-wrap g-detail" }, h("table", { class: "data" },
    h("thead", {}, h("tr", {}, ["Startup", "Answers", "Crowd", "Engine", "Gap"].map((t, i) => h("th", { class: i ? "num" : "" }, t)))),
    h("tbody", {}, det.cards.map((c) => {
      const gap = c.crowd.n && c.engine !== null ? c.crowd.composite - c.engine : null;
      return h("tr", {}, h("td", {}, c.name), h("td", { class: "num" }, c.crowd.n),
        h("td", { class: "num" }, c.crowd.n ? fmt1(c.crowd.composite) : "–"), h("td", { class: "num" }, fmt1(c.engine)),
        h("td", { class: "num" }, gap === null ? "–" : `${gap > 0 ? "+" : ""}${gap.toFixed(1)}`));
    }))));
}

function gameRow(d, actions) {
  return h("article", { class: `g-row${d.when === "today" ? " today" : ""}` },
    h("div", { class: "g-when" }, h("b", {}, d.when === "today" ? "Today" : dayLabel(d.date)), h("span", {}, d.label)),
    h("div", { class: "g-body" }, chips(d), d.when === "past" ? detail(d) : null),
    h("div", { class: "g-stats" }, d.when === "past" || d.answers ? [h("b", {}, d.players), h("span", {}, d.players === 1 ? "player" : "players")] : null),
    h("div", { class: "g-actions" }, actions));
}

function pastTab() {
  const past = S.dives.filter((d) => d.when === "past");
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Past games"), h("span", { class: "muted small" }, plural(past.length, "game"))),
    past.length ? h("div", { class: "g-list" }, past.map((d) => gameRow(d,
      h("button", { class: "btn small", onclick: () => toggle(d) }, S.open.has(d.id) ? "Hide" : "Crowd vs engine"))))
      : h("p", { class: "empty" }, "No past games yet."));
}

// --- next games -------------------------------------------------------------------------------------

// Queue the next games by themselves: one a day on the next days without a game. Live startups play once.
function generator() {
  const live = S.pool && !S.pool.repeats;
  const left = live ? S.pool.eligible.length : S.companies.filter((c) => c.active).length;
  const count = h("input", { type: "number", min: 1, max: 60, value: S.genCount || 7, "aria-label": "How many games",
    oninput: (e) => { S.genCount = Number(e.target.value) || 7; } });
  const cards = h("input", { type: "number", min: 1, max: 10, value: S.genCards || 5, "aria-label": "Cards per game",
    oninput: (e) => { S.genCards = Number(e.target.value) || 5; } });
  async function generate(btn) {
    btn.disabled = true;
    try {
      const made = await post("/api/admin/dives/generate", { count: Number(count.value), cards: Number(cards.value) });
      const short = made.length < Number(count.value) ? ` (ran out of unplayed startups)` : "";
      PD.toast(`${plural(made.length, "game")} queued: ${dayLabel(made[0].date)} to ${dayLabel(made[made.length - 1].date)}${short}`, 6000);
    } catch (e) { PD.toast(e.message, 6000); }
    await refresh();
  }
  const enough = Math.floor(left / (S.genCards || 5));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Generate next games")),
    h("p", { class: "muted small" }, live
      ? `One game a day on the next free days. Each startup plays one day only; ${left} unplayed is enough for about ${plural(enough, "game")}. A major update from “Update all cards” makes a startup eligible once more.`
      : `One game a day on the next free days, rotating the ${left} demo companies so the least-shown go first.`),
    h("div", { class: "g-form" },
      h("label", {}, "Games", count),
      h("label", {}, "Cards each", cards),
      h("button", { class: "btn primary", disabled: !left, onclick: (e) => generate(e.currentTarget) },
        left ? "Generate" : live ? "No unplayed startups left" : "No companies in the game")));
}

function builder() {
  const label = h("input", { type: "text", placeholder: "e.g. Ocean week special", value: S.label || "", oninput: (e) => { S.label = e.target.value; } });
  const date = h("input", { type: "date", value: S.date || "", oninput: (e) => { S.date = e.target.value; } });
  const startups = [...S.companies].sort((a, b) => b.active - a.active || a.name.localeCompare(b.name))
    .map((c) => [c.id, `${c.name}${c.active ? "" : " (not in game)"}`]);
  const last = S.picks.length <= 1;
  const picks = S.picks.map((v, i) => h("div", { class: "g-pick" },
    Tool.dropdown({ label: `Card ${i + 1}`, options: [["", `Card ${i + 1}: empty`], ...startups], value: v, class: "dd-full",
      onChange: (id) => { S.picks[i] = id; } }),
    h("button", { type: "button", class: "btn link g-remove", disabled: last, "aria-label": `Remove card ${i + 1}`,
      title: last ? "A game needs at least one card" : `Remove card ${i + 1}`,
      onclick: () => {
        S.picks.splice(i, 1);
        render();
        // Stay where you were, so a few cards come off one after another.
        const at = Math.min(i, S.picks.length - 1);
        const next = $app.querySelectorAll(".g-picks .g-pick")[at];
        (S.picks.length > 1 ? next?.querySelector(".g-remove") : next?.querySelector(".dd-btn"))?.focus();
      } }, "✕")));
  const full = S.picks.length >= MAX_CARDS;
  const more = h("button", { type: "button", class: "btn small g-add", disabled: full,
    title: full ? `A game holds at most ${MAX_CARDS} startups` : "Add another card to this game",
    onclick: () => {
      S.picks.push("");
      render();
      const slots = $app.querySelectorAll(".g-picks .dd-btn");
      slots[slots.length - 1]?.focus();
    } }, "+ Add a card");
  async function create() {
    const ids = S.picks.map(Number).filter(Boolean);
    if (!label.value.trim() || !ids.length) return PD.toast("Add a label and at least one startup");
    const twice = ids.find((id, i) => ids.indexOf(id) !== i);
    if (twice) return PD.toast(`${byId()[twice]?.name || "A startup"} is in this game twice`);
    try {
      await post("/api/admin/dives", { label: label.value.trim(), company_ids: ids, date: date.value || null });
      S.picks = Array(DEFAULT_CARDS).fill(""); S.label = ""; S.date = "";
      await refresh();
    } catch (e) { PD.toast(e.message); }
  }
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Queue a game by hand")),
    h("p", { class: "muted small" }, "Any startup, played before or not."),
    h("div", { class: "form" }, h("label", {}, "Label", label), h("label", {}, "Date (blank = any day)", date),
      h("div", { class: "g-picks" }, picks, more), h("button", { class: "btn primary", onclick: create }, "Add to queue")));
}

function nextTab() {
  const next = S.dives.filter((d) => d.when !== "past").sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999"));
  return h("div", { class: "split g-split" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", {}, "Queue"), h("span", { class: "muted small" }, plural(next.length, "game"))),
      next.length ? h("div", { class: "g-list" }, next.map((d) => gameRow(d, [
        h("a", { class: "btn small", href: `/play?dive=${d.id}`, target: "_blank" }, "Open ↗"),
        h("button", { class: "btn small", onclick: () => demoAnswers(d) }, "Demo answers"),
        h("button", { class: "btn small danger", onclick: () => del(d) }, "Delete")])))
        : h("p", { class: "empty" }, "Nothing queued. Generate the next games →")),
    h("div", {}, generator(), builder()));
}

// --- page -------------------------------------------------------------------------------------------

function render() {
  const counts = { past: S.dives.filter((d) => d.when === "past").length, next: S.dives.filter((d) => d.when !== "past").length };
  const body = { past: pastTab, next: nextTab }[S.tab]();
  $app.replaceChildren(
    h("div", { class: "head" }, h("h1", {}, "Game"),
      Tool.tabs(TABS.map((t) => ({ ...t, count: counts[t.key] })), S.tab, (k) => { S.tab = k; Tool.setHash(k); render(); })),
    kpis(),
    body);
}

async function refresh() {
  try {
    [S.dives, S.companies, S.pool] = await Promise.all([api("/api/host/dives"), api("/api/admin/companies?pool=current"),
      api("/api/host/game-pool")]);
    render();
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(() => { S.open.clear(); refresh(); });
refresh();
