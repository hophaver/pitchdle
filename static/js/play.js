// Player flow for /play (solo daily dive) and /live (host-paced room).
const { h, api, post, AXES, AXIS, fmtM, fmt1 } = PD;

const $app = document.getElementById("app");
const S = {
  mode: location.pathname.startsWith("/live") ? "live" : "solo",
  me: null,
  dive: null,
  cards: [],
  progress: {},
  depth: 0,
  liveKey: null,
  deadline: null,
};

function view(...nodes) {
  $app.replaceChildren(...nodes);
  window.scrollTo({ top: 0 });
}

// --- depth gauge ------------------------------------------------------------------------------

function initGauge() {
  const gauge = document.getElementById("gauge");
  for (const [from] of PD.ZONES.slice(1)) {
    gauge.append(h("div", { class: "zone-tick", style: { top: `${PD.depthFrac(from) * 100}%` } }));
  }
  updateGauge(0);
}

function updateGauge(depth, announceFrom = null) {
  const diver = document.getElementById("diver");
  diver.style.top = `${PD.depthFrac(depth) * 100}%`;
  PD.setDepth(depth);
  if (announceFrom !== null && depth > announceFrom) {
    const before = PD.zone(announceFrom);
    const after = PD.zone(depth);
    const msg = after.name !== before.name
      ? `${after.emoji} Entering the ${after.name} zone`
      : `+${fmtM(depth - announceFrom)} · ${fmtM(depth)}`;
    const t = document.getElementById("depth-toast");
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 2200);
  }
}

// --- header -------------------------------------------------------------------------------------

function renderMe() {
  const btn = document.getElementById("me-btn");
  btn.textContent = S.me.initials ? `👤 ${S.me.initials}` : S.me.handle;
}

async function editInitials() {
  const value = window.prompt("Your 3-letter initials for the leaderboard (leave empty to stay anonymous):",
    S.me.initials || "");
  if (value === null) return;
  try {
    S.me = await post("/api/me", { initials: value.trim() || null });
    renderMe();
    PD.toast(S.me.initials ? `You're ${S.me.initials} on the board` : "Back to anonymous");
  } catch (e) {
    PD.toast(e.message);
  }
}

function setLabel(text) {
  document.getElementById("dive-label").textContent = text || "";
}

// --- pieces -------------------------------------------------------------------------------------

function progressBar(index, total) {
  return h("div", { class: "progress", "aria-label": `Card ${index + 1} of ${total}` },
    Array.from({ length: total }, (_, i) => h("i", { class: i < index ? "done" : i === index ? "now" : "" })));
}

function pitchPanel(card) {
  return h("section", { class: "panel pitch" },
    h("div", { class: "row" },
      h("span", { class: "chip" }, `🌊 ${card.sector || "blue economy"}`),
      h("span", { class: "chip" }, card.is_real ? "Real startup" : "Fictional")),
    h("h2", {}, card.name),
    h("p", { class: "what" }, card.one_liner),
    h("p", { class: "ask" }, card.claim_ask));
}

// Four rows of 0–5 tap buttons. `was` marks the round-1 answer during the second look.
function axisPicker(initial = {}, onChange = () => {}, was = null) {
  const values = { ...initial };
  const rows = AXES.map((axis) => {
    const buttons = [0, 1, 2, 3, 4, 5].map((n) => h("button", {
      type: "button",
      class: `${values[axis] === n ? "on" : ""}${was && was[axis] === n ? " was" : ""}`,
      "aria-pressed": values[axis] === n ? "true" : "false",
      "aria-label": `${AXIS[axis].name} ${n}`,
      onclick: () => {
        values[axis] = n;
        buttons.forEach((b, i) => { b.classList.toggle("on", i === n); b.setAttribute("aria-pressed", i === n); });
        onChange(values);
      },
    }, n));
    return h("div", { class: "axis" },
      h("div", { class: "axis-head" }, h("b", {}, AXIS[axis].name), h("span", {}, AXIS[axis].hint)),
      h("div", { class: "taps", role: "group", "aria-label": AXIS[axis].name }, buttons));
  });
  return { el: h("div", {}, rows), values };
}

const complete = (v) => AXES.every((a) => Number.isInteger(v[a]));

function timerEl() {
  return h("span", { class: "timer", dataset: { timer: "1" } }, "");
}

function tickTimers() {
  if (!S.deadline) return;
  const left = Math.max(0, Math.round((S.deadline - Date.now()) / 1000));
  document.querySelectorAll("[data-timer]").forEach((el) => {
    el.textContent = `⏱ ${left}s`;
    el.classList.toggle("low", left <= 5);
  });
}
setInterval(tickTimers, 250);

function waiting(emoji, title, text, ...extra) {
  return h("div", { class: "big-wait" }, h("span", { class: "emoji" }, emoji), h("h2", {}, title),
    text ? h("p", { class: "muted" }, text) : null, ...extra);
}

// --- card → guess -------------------------------------------------------------------------------

function showCard(card, index, total, { live = false } = {}) {
  const submit = h("button", { class: "btn primary block", disabled: true }, "Lock it in");
  const picker = axisPicker({}, (v) => { submit.disabled = !complete(v); });
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    try {
      await post("/api/vote", { dive_id: S.dive.id, company_id: card.id, round: 1, scores: picker.values });
      S.progress[card.id] = { ...(S.progress[card.id] || {}), r1: true };
      if (live) showLockedIn(card, index, total);
      else showReveal(card, index, total);
    } catch (e) {
      PD.toast(e.message);
      submit.disabled = false;
    }
  });
  view(
    h("div", { class: "row" }, h("span", { class: "muted small" }, `Card ${index + 1} of ${total}`),
      h("span", { class: "spacer" }), live ? timerEl() : null),
    progressBar(index, total),
    pitchPanel(card),
    h("section", { class: "panel" },
      h("p", { class: "muted small", style: { margin: 0 } }, "Your gut read, 0–5. The crowd and the engine stay hidden until you lock in."),
      picker.el),
    submit,
  );
  tickTimers();
}

function showLockedIn(card, index, total) {
  view(progressBar(index, total),
    waiting("🔒", "Locked in", `Waiting for the host to reveal ${card.name}.`, h("p", {}, timerEl())));
  tickTimers();
}

// --- reveal -------------------------------------------------------------------------------------

function sheetView(r, live) {
  if (!r.sheet) {
    return h("section", { class: "panel" }, h("h3", {}, "You vs the room"),
      h("p", { class: "muted small" }, live
        ? `Fewer than ${r.min_votes} divers answered this card, so there's no room sheet.`
        : `You're one of the first divers. The room sheet appears once ${r.min_votes} people have played this card; it's on your end screen too.`));
  }
  const focus = r.sheet.axes.find((a) => a.axis === r.sheet.focus);
  const rest = r.sheet.axes.filter((a) => a.axis !== r.sheet.focus);
  const more = h("div", { class: "hidden" }, rest.map((row) => PD.sheetAxis(row)));
  const toggle = h("button", { class: "btn small", onclick: () => {
    more.classList.toggle("hidden");
    toggle.textContent = more.classList.contains("hidden") ? "Show all 4 axes" : "Show less";
  } }, "Show all 4 axes");
  return h("section", { class: "panel" },
    h("div", { class: "row" }, h("h3", { style: { margin: 0 } }, "You vs the room"),
      h("span", { class: "spacer" }), h("span", { class: "muted small" }, `${r.room.n} divers`)),
    PD.legend(), PD.sheetAxis(focus), more, toggle);
}

function pointsRow(r) {
  const metres = h("span", { class: "metres" }, "0 m");
  PD.countUp(metres, r.points.card - (r.points.bonus || 0), { ms: 1100, format: (n) => `+${fmtM(n)}` });
  return h("div", { class: "points" },
    metres,
    r.tier ? h("span", { class: "tier" }, h("b", {}, `${r.tier.emoji} ${r.tier.name}`), h("small", {}, r.tier.label)) : null,
    r.points.bonus ? h("span", { class: "bonus" }, `🌊 Against the current +${fmtM(r.points.bonus)}`) : null);
}

function verdict(r) {
  const close = r.you.tiles.every((t) => t.color !== "grey");
  const greens = r.you.tiles.filter((t) => t.color === "green").length;
  if (greens === 4) return "Bullseye. You read it exactly like the engine.";
  if (close) return "You read it like the engine.";
  if (greens >= 2) return "Partly there. Check the arrows for where the engine landed.";
  return "The engine saw this one differently.";
}

async function showReveal(card, index, total, { live = false } = {}) {
  let r;
  try {
    r = await api(`/api/dive/${S.dive.id}/reveal/${card.id}`);
  } catch (e) {
    view(waiting("⚠️", "Couldn't load the reveal", e.message));
    return;
  }
  const before = S.depth;
  const thin = r.company.coverage && r.company.coverage.total
    && r.company.coverage.assessed / r.company.coverage.total < 0.75;
  const next = r.you.r2
    ? (live ? h("p", { class: "muted center" }, "Waiting for the host to open the next card…")
      : h("button", { class: "btn primary block", onclick: () => nextStep() }, index + 1 < total ? "Next card →" : "See your dive →"))
    : h("button", { class: "btn primary block", onclick: () => showSecondLook(card, index, total, r, { live }) }, "🔎 Second look: see the facts");

  view(
    progressBar(index, total),
    h("section", { class: "panel" },
      h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, r.company.name),
        h("span", { class: "spacer" }), h("span", { class: "chip" }, r.company.sector)),
      PD.tiles(r.you.tiles, { animate: true }),
      h("div", { class: "scoreline" },
        h("div", {}, h("b", {}, fmt1(r.you.composite)), h("span", {}, "You")),
        h("div", {}, h("b", {}, fmt1(r.room.composite)), h("span", {}, `Crowd · ${r.room.n}`)),
        h("div", { class: "engine" }, h("b", {}, fmt1(r.engine.composite)), h("span", {}, "Engine read"))),
      pointsRow(r),
      h("p", { class: "verdict" }, verdict(r)),
      r.callout ? h("div", { class: `callout ${r.callout.kind}` }, r.callout.text) : null,
      thin ? h("p", { class: "thin" }, `⚠ Thin evidence: the engine assessed ${r.company.coverage.assessed} of ${r.company.coverage.total} factors.`) : null),
    sheetView(r, live),
    next,
    h("p", { class: "muted small center" }, "Engine read = a demo scoring model on public information, not an expert verdict."),
  );
  S.depth = r.depth;
  setTimeout(() => updateGauge(S.depth, before), 1300);
}

function showSecondLook(card, index, total, r, { live = false } = {}) {
  const stick = h("button", { class: "btn" }, "Stick with my read");
  const revise = h("button", { class: "btn primary", disabled: true }, "Revise");
  const picker = axisPicker(r.you.r1, (v) => {
    revise.disabled = AXES.every((a) => v[a] === r.you.r1[a]);
  }, r.you.r1);

  async function send(stuck) {
    stick.disabled = revise.disabled = true;
    try {
      await post("/api/vote", { dive_id: S.dive.id, company_id: card.id, round: 2, stuck,
        scores: stuck ? r.you.r1 : picker.values });
      S.progress[card.id] = { r1: true, r2: true };
      const r2 = await api(`/api/dive/${S.dive.id}/reveal/${card.id}`);
      showSecondResult(card, index, total, r, r2, { live });
    } catch (e) {
      PD.toast(e.message);
      stick.disabled = false;
      revise.disabled = AXES.every((a) => picker.values[a] === r.you.r1[a]);
    }
  }
  stick.addEventListener("click", () => send(true));
  revise.addEventListener("click", () => send(false));

  view(
    progressBar(index, total),
    h("section", { class: "panel" },
      h("h2", {}, `🔎 ${r.company.name}: the facts`),
      h("div", { class: "facts" }, r.company.facts.map((f) => h("div", { class: "fact" }, h("b", {}, f.label), f.value))),
      h("p", { class: "muted small" }, "Does this change your read? Moving closer to the engine earns half points; moving away costs nothing.")),
    h("section", { class: "panel" }, picker.el),
    h("div", { class: "btns" }, stick, revise),
  );
}

function showSecondResult(card, index, total, r1, r2, { live = false } = {}) {
  const gained = r2.points.card - r1.points.card;
  const before = S.depth;
  view(
    progressBar(index, total),
    h("section", { class: "panel" },
      h("h2", {}, r2.you.stuck ? "You stuck with it" : "Revised"),
      h("p", { class: "muted small" }, "First read"), PD.tiles(r2.you.tiles, { mini: true }),
      r2.you.tiles_r2 && !r2.you.stuck ? [h("p", { class: "muted small" }, "After the facts"), PD.tiles(r2.you.tiles_r2, { mini: true, animate: true })] : null,
      h("p", { class: "verdict" }, gained > 0 ? `The second look took you ${fmtM(gained)} deeper.`
        : r2.you.stuck ? "No change, no penalty." : "No closer to the engine this time; no penalty.")),
    live ? h("p", { class: "muted center" }, "Waiting for the host to open the next card…")
      : h("button", { class: "btn primary block", onclick: () => nextStep() }, index + 1 < total ? "Next card →" : "See your dive →"),
  );
  S.depth = r2.depth;
  if (gained > 0) setTimeout(() => updateGauge(S.depth, before), 300);
}

// --- end screen ---------------------------------------------------------------------------------

function shareText(s) {
  const lines = [`Pitchdle ${s.dive.label} 🤿 ${fmtM(s.depth)} · ${s.zone.emoji} ${s.zone.name}`];
  for (const c of s.cards) {
    lines.push(c.you.tiles.map((t) => PD.TILE_EMOJI[t.color]).join("") + (c.tier ? ` ${c.tier.emoji}` : ""));
  }
  if (s.against) lines.push(`🌊 ${s.against}× against the current`);
  lines.push(`${location.origin}/play`);
  return lines.join("\n");
}

const TIER_RANK = { one: 5, deep: 4, twilight: 3, reef: 2, surface: 1 };

async function showEnd() {
  let s;
  try {
    s = await api(`/api/dive/${S.dive.id}/summary`);
  } catch (e) {
    view(waiting("⚠️", "Couldn't load your dive", e.message));
    return;
  }
  S.depth = s.depth;
  updateGauge(s.depth);
  const metres = h("div", { class: "m" }, "0 m");
  PD.countUp(metres, s.depth, { ms: 1600, format: fmtM });
  const text = shareText(s);
  const sorted = [...s.cards].sort((a, b) =>
    (TIER_RANK[b.tier?.key] || 0) - (TIER_RANK[a.tier?.key] || 0) || b.points.card - a.points.card);

  const boards = h("section", { class: "panel" }, h("h3", {}, "Leaderboards"), h("p", { class: "muted small" }, "Loading…"));
  api(`/api/dive/${S.dive.id}/leaderboard`).then((b) => {
    const list = (title, rows, fmt) => h("div", { style: { marginTop: ".6rem" } }, h("b", {}, title),
      rows.length ? h("ol", { class: "board" }, rows.slice(0, 5).map((r, i) => h("li", {}, h("span", {}, `${i + 1}. ${r.name}`), h("span", {}, fmt(r.value)))))
        : h("p", { class: "muted small" }, "Nobody yet."));
    boards.replaceChildren(h("h3", {}, "Leaderboards"),
      list("🤿 Deepest dive", b.deepest, fmtM),
      list("🌊 Against the current", b.current, (v) => `+${fmtM(v)}`),
      list("🔄 Most moved by the facts", b.moved, (v) => `${v} steps`));
  }).catch(() => boards.remove());

  view(
    h("section", { class: "panel final-depth" },
      h("p", { class: "muted", style: { margin: 0 } }, `Dive ${s.dive.label} complete`),
      metres,
      h("div", { class: "z" }, `${s.zone.emoji} ${s.zone.name} zone`),
      s.rank ? h("p", {}, `#${s.rank} of ${s.of} divers`) : null,
      s.against ? h("p", { class: "bonus", style: { display: "inline-flex" } }, `🌊 ${s.against}× against the current`) : null),
    h("section", { class: "panel" }, h("h3", {}, "The room"),
      h("p", { class: "muted small" }, "Every diver in this dive. You're the bright one."),
      PD.ocean(s.room)),
    h("section", { class: "panel" },
      h("h3", {}, "Share"),
      h("div", { class: "share-box" }, text),
      h("div", { class: "btns" }, h("button", { class: "btn primary", onclick: async () => {
        try { PD.toast((await PD.copyText(text)) === "shared" ? "Shared" : "Copied to clipboard"); } catch { PD.toast("Couldn't copy"); }
      } }, "Share result"))),
    S.me.initials ? null : h("section", { class: "panel row" },
      h("span", {}, "Put your initials on the board?"), h("span", { class: "spacer" }),
      h("button", { class: "btn small", onclick: editInitials }, "Set initials")),
    h("section", { class: "panel" }, h("h3", {}, "Answer sheet"),
      h("p", { class: "muted small" }, "Your cards, deepest reads first. Tap one to see the room."),
      sorted.map((c) => h("details", { class: "answer-card" },
        h("summary", {},
          h("span", {}, h("b", {}, c.company.name), h("br"),
            h("span", { class: "muted small" }, c.tier ? `${c.tier.emoji} ${c.tier.name} · beat ${c.tier.beat}%` : "Too few divers to rank yet")),
          h("span", { style: { textAlign: "right" } }, fmtM(c.points.card),
            c.points.bonus ? h("div", { class: "small", style: { color: "var(--accent)" } }, `🌊 +${c.points.bonus}`) : null)),
        PD.tiles(c.you.tiles, { mini: true }),
        h("p", { class: "small muted" }, `Engine ${fmt1(c.engine.composite)} · crowd ${fmt1(c.room.composite)} · you ${fmt1(c.you.composite)}`),
        c.sheet ? [PD.legend(), c.sheet.axes.map((row) => PD.sheetAxis(row))] : null))),
    boards,
    S.mode === "solo" ? h("p", { class: "muted small center" }, "New dive tomorrow.") : null,
  );
}

// --- solo ---------------------------------------------------------------------------------------

function nextStep() {
  const i = S.cards.findIndex((c) => !(S.progress[c.id] || {}).r2);
  if (i === -1) return showEnd();
  const card = S.cards[i];
  if ((S.progress[card.id] || {}).r1) return showReveal(card, i, S.cards.length);
  return showCard(card, i, S.cards.length);
}

async function startSolo() {
  const q = new URLSearchParams(location.search).get("dive");
  const data = await api(q ? `/api/dive/${encodeURIComponent(q)}` : "/api/dive/today");
  Object.assign(S, { dive: data.dive, cards: data.cards, progress: data.progress, depth: data.depth });
  setLabel(`Dive ${data.dive.label}`);
  updateGauge(S.depth);
  if (!data.cards.length) return view(waiting("🫧", "No cards in this dive", "Add companies in /admin."));
  nextStep();
}

// --- live ---------------------------------------------------------------------------------------

async function livePoll() {
  let st;
  try {
    st = await api("/api/live/state");
  } catch {
    setLabel("Reconnecting…");
    return;
  }
  if (st.dive && (!S.dive || S.dive.id !== st.dive.id)) {
    S.dive = st.dive;
    S.depth = 0;
    updateGauge(0);
  }
  setLabel(st.dive ? `Live · ${st.dive.label}` : "Live");
  S.deadline = st.remaining !== null ? Date.now() + st.remaining * 1000 : null;
  document.querySelectorAll("[data-joined]").forEach((el) => { el.textContent = st.joined; });
  const key = `${st.key}:${st.voted_r1 ? "v" : ""}`;
  if (key === S.liveKey) return;
  S.liveKey = key;
  renderLive(st);
}

function renderLive(st) {
  const total = st.dive ? st.dive.total : 0;
  const idx = st.card_index;
  switch (st.phase) {
    case "idle":
      return view(waiting("🌊", "No live round right now", "When the host starts one, this page joins automatically.",
        h("a", { class: "btn", href: "/play" }, "Play today's dive instead")));
    case "lobby":
      return view(waiting("🤿", "You're in!", null,
        h("p", {}, "You are ", h("b", {}, S.me.initials || S.me.handle)),
        h("p", { class: "muted" }, h("span", { dataset: { joined: "1" } }, st.joined), " divers in the room. Waiting for the host…"),
        h("button", { class: "btn", onclick: editInitials }, S.me.initials ? "Change initials" : "Set initials for the leaderboard")));
    case "open":
      return st.voted_r1 ? showLockedIn(st.card, idx, total) : showCard(st.card, idx, total, { live: true });
    case "locked":
      return st.voted_r1 ? showLockedIn(st.card, idx, total)
        : view(progressBar(idx, total), waiting("⌛", "Time's up", "You missed this card. The next one's coming."));
    case "revealed":
      return st.voted_r1 ? showReveal(st.card, idx, total, { live: true })
        : view(progressBar(idx, total), waiting("👀", "Watch the wall", "You missed this card, but the reveal is up on the big screen."));
    case "final":
      return showEnd();
    default:
      return null;
  }
}

// --- boot ---------------------------------------------------------------------------------------

(async function boot() {
  initGauge();
  document.getElementById("me-btn").addEventListener("click", editInitials);
  try {
    S.me = await api("/api/me");
    renderMe();
    if (S.mode === "live") {
      await livePoll();
      setInterval(livePoll, 2000);
    } else {
      await startSolo();
    }
  } catch (e) {
    view(waiting("⚠️", "Something went wrong", e.message));
  }
})();
