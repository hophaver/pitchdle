// Player flow for /play (today's set, self-paced) and /live (host-paced room).
// Answer every card first; you vs the crowd is shown only at the end.
const { h, api, post, AXES, AXIS, fmt1, colorFor } = PD;

const $app = document.getElementById("app");
const S = {
  mode: location.pathname.startsWith("/live") ? "live" : "solo",
  set: null,
  cards: [],
  answered: new Set(),
  liveKey: null,
  deadline: null,
};

function show(...nodes) {
  $app.replaceChildren(...nodes.flat().filter(Boolean));
  window.scrollTo({ top: 0 });
}

function card(color, ...kids) {
  return h("section", { class: "card", style: { "--card": color } }, ...kids);
}

function cardTop(index, total, right) {
  return h("div", { class: "card-top" },
    h("span", { class: "brand" }, h("b", {}, "Pitch"), h("span", {}, "dle")),
    total ? h("span", { class: "pips", "aria-label": `Card ${index + 1} of ${total}` },
      Array.from({ length: total }, (_, i) => h("i", { class: i <= index ? "on" : "" }))) : null,
    h("span", {}, right ?? setLabel()));
}

// "#3" reads as "No. 3"; named sets (like the live one) keep their name.
const setLabel = () => (!S.set ? "" : S.set.label.startsWith("#") ? `No. ${S.set.label.slice(1)}` : S.set.label);

const pill = (label, onclick, attrs = {}) => h("button", { class: "pill", onclick, ...attrs }, label);

// --- start ----------------------------------------------------------------------------------------

function showStart() {
  const started = S.answered.size > 0;
  show(card(colorFor(0),
    cardTop(-1, 0),
    h("div", { class: "hero" },
      h("h1", {}, "Would you"),
      h("span", { class: "hand" }, "back"),
      h("h1", {}, "this?"),
      h("p", { class: "caps" }, `${S.cards.length} startups · 4 calls each`)),
    h("div", { class: "actions" },
      pill(started ? "Continue →" : "Play today's →", () => nextCard()))));
}

// --- one card -------------------------------------------------------------------------------------

function showCard(c, index, total, { live = false } = {}) {
  const values = {};
  const lock = pill("Lock it in ↵", null, { disabled: true, class: "pill ghost block" });
  const rows = AXES.map((axis) => {
    const buttons = [0, 1, 2, 3, 4, 5].map((n) => h("button", {
      type: "button", "aria-label": `${AXIS[axis]} ${n}`, "aria-pressed": "false",
      onclick: () => {
        values[axis] = n;
        buttons.forEach((b, i) => { b.classList.toggle("on", i === n); b.setAttribute("aria-pressed", i === n); });
        const ready = AXES.every((a) => values[a] !== undefined);
        lock.disabled = !ready;
        lock.classList.toggle("ghost", !ready);
      },
    }, n));
    return h("div", {}, h("div", { class: "caps axis-label" }, AXIS[axis]), h("div", { class: "taps" }, buttons));
  });

  const el = card(colorFor(index),
    cardTop(index, total, live ? h("span", { class: "timer", dataset: { timer: "1" } }, "") : null),
    h("div", { class: "pitch-head" },
      h("div", {}, h("div", { class: "caps sector" }, c.sector), h("p", { class: "pitch-line" }, c.one_liner)),
      c.emoji ? h("div", { class: "art", "aria-hidden": "true" }, c.emoji) : null),
    h("p", { class: "ask" }, c.claim_ask),
    h("div", { class: "who" }, `— ${c.name}`),
    h("div", { class: "axes" }, rows),
    h("div", { class: "actions" }, lock));

  lock.addEventListener("click", async () => {
    lock.disabled = true;
    try {
      await post("/api/vote", { dive_id: S.set.id, company_id: c.id, scores: values });
      S.answered.add(c.id);
      el.classList.add("out");
      setTimeout(() => (live ? showLocked(index, total) : nextCard()), 230);
    } catch (e) {
      PD.toast(e.message);
      lock.disabled = false;
    }
  });
  show(el);
  tickTimers();
}

function nextCard() {
  const i = S.cards.findIndex((c) => !S.answered.has(c.id));
  if (i === -1) return showResults();
  return showCard(S.cards[i], i, S.cards.length);
}

// --- live waiting states ----------------------------------------------------------------------------

const dots = () => h("div", { class: "dots" }, h("i"), h("i"), h("i"));

function waitCard(color, index, total, mark, title, sub, ...extra) {
  return card(color, cardTop(index, total), h("div", { class: "big-mark" }, mark),
    h("div", { class: "wait-title" }, title), sub ? h("div", { class: "wait-sub" }, sub) : null, ...extra);
}

function showLocked(index, total) {
  show(waitCard(colorFor(index), index, total, "✓", "Locked in", "next one soon", dots()));
}

function tickTimers() {
  if (!S.deadline) return;
  const left = Math.max(0, Math.round((S.deadline - Date.now()) / 1000));
  document.querySelectorAll("[data-timer]").forEach((el) => {
    el.textContent = `${left}s`;
    el.classList.toggle("low", left <= 5);
  });
}
setInterval(tickTimers, 250);

// --- results ----------------------------------------------------------------------------------------

const VERDICT = { higher: "Higher than the crowd", with: "With the crowd", lower: "Lower than the crowd" };

function headline(leans) {
  const most = Object.entries(leans).sort((a, b) => b[1] - a[1])[0][0];
  if (most === "higher") return ["You're more", "bullish", "than the crowd"];
  if (most === "lower") return ["You're", "tougher", "than the crowd"];
  return ["You're in", "sync", "with the crowd"];
}

function resultCard(r, i) {
  const nums = (scores) => h("div", { class: "nums" },
    AXES.map((a) => h("div", {}, h("b", {}, typeof scores[a] === "number" && !Number.isInteger(scores[a]) ? fmt1(scores[a]) : scores[a]),
      h("small", {}, AXIS[a]))));
  const crowd = Object.fromEntries(r.axes.map((x) => [x.axis, x.crowd]));
  return card(colorFor(i),
    h("div", { class: "result-head" },
      r.card.emoji ? h("div", { class: "art small", "aria-hidden": "true" }, r.card.emoji) : null,
      h("div", {}, h("div", { class: "result-name" }, r.card.name), h("div", { class: "caps sector" }, r.card.sector))),
    h("div", { class: "block you" }, h("div", { class: "caps" }, "You said"), nums(r.you.scores)),
    h("div", { class: "block crowd" }, h("div", { class: "caps" }, `Everyone · ${r.crowd.n}`), nums(crowd)),
    h("div", { class: "verdict" }, VERDICT[r.lean]),
    h("div", { class: "caps dist-title" }, "How everyone answered"),
    r.axes.map((x) => h("div", { class: "dist" }, h("div", { class: "name" }, AXIS[x.axis]), PD.bars(x.share, x.you))));
}

async function showResults() {
  let r;
  try {
    r = await api(`/api/dive/${S.set.id}/results`);
  } catch (e) {
    show(waitCard(colorFor(0), -1, 0, "…", "Not yet", e.message));
    return;
  }
  if (!r.cards.length) {
    show(waitCard(colorFor(0), -1, 0, "–", "No answers", "you didn't answer any cards"));
    return;
  }
  const [a, b, c] = headline(r.summary.leans);
  const { leans } = r.summary;
  show(
    h("section", { class: "card summary" },
      cardTop(-1, 0),
      h("h1", {}, a, " ", h("span", { class: "hand" }, b), " ", c),
      h("div", { class: "tally" },
        h("div", {}, h("b", {}, `${leans.higher}`), h("span", {}, "Higher ↑")),
        h("div", {}, h("b", {}, `${leans.with}`), h("span", {}, "With =")),
        h("div", {}, h("b", {}, `${leans.lower}`), h("span", {}, "Lower ↓")))),
    r.cards.map(resultCard),
  );
}

// --- solo -------------------------------------------------------------------------------------------

async function startSolo() {
  const q = new URLSearchParams(location.search).get("dive");
  const data = await api(q ? `/api/dive/${encodeURIComponent(q)}` : "/api/dive/today");
  S.set = data.dive;
  S.cards = data.cards;
  S.answered = new Set(data.answered);
  if (!S.cards.length) return show(waitCard(colorFor(0), -1, 0, "–", "No cards today", "check back soon"));
  if (S.answered.size === S.cards.length) return showResults();
  return showStart();
}

// --- live -------------------------------------------------------------------------------------------

async function livePoll() {
  let st;
  try {
    st = await api("/api/live/state");
  } catch {
    return; // keep showing the last screen; the next poll retries
  }
  if (st.dive) S.set = st.dive;
  S.deadline = st.remaining !== null ? Date.now() + st.remaining * 1000 : null;
  document.querySelectorAll("[data-joined]").forEach((el) => { el.textContent = st.joined; });
  const key = `${st.key}:${st.voted ? "v" : ""}`;
  if (key === S.liveKey) return;
  S.liveKey = key;
  renderLive(st);
}

function renderLive(st) {
  const total = st.dive ? st.dive.total : 0;
  const i = st.card_index;
  switch (st.phase) {
    case "idle":
      return show(card(colorFor(0), cardTop(-1, 0, ""),
        h("div", { class: "hero" }, h("h1", {}, "No live"), h("span", { class: "hand" }, "game"), h("h1", {}, "right now")),
        h("div", { class: "actions" }, h("a", { class: "pill", href: "/play" }, "Play today's →"))));
    case "lobby":
      return show(card(colorFor(0), cardTop(-1, 0, ""),
        h("div", { class: "hero" }, h("h1", {}, "You're"), h("span", { class: "hand" }, "in"),
          h("p", { class: "caps" }, h("span", { dataset: { joined: "1" } }, st.joined), " here")),
        dots()));
    case "open":
      return st.voted ? showLocked(i, total) : showCard(st.card, i, total, { live: true });
    case "locked":
      return st.voted ? showLocked(i, total) : show(waitCard(colorFor(i), i, total, "✕", "Missed it", "next one soon", dots()));
    case "revealed":
      return show(waitCard(colorFor(i), i, total, "👀", "Eyes up", "on the big screen", dots()));
    case "final":
      return showResults();
    default:
      return null;
  }
}

// --- boot -------------------------------------------------------------------------------------------

(async function boot() {
  try {
    await api("/api/me"); // sets the device cookie before anything else
    if (S.mode === "live") {
      await livePoll();
      setInterval(livePoll, 2000);
    } else {
      await startSolo();
    }
  } catch (e) {
    show(waitCard(colorFor(0), -1, 0, "!", "Something broke", e.message));
  }
})();
