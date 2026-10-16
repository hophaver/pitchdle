// Projector wall: QR lobby → the live card → crowd vs engine for that card → how the room read every card.
const { h, api, AXES, AXIS, fmt1, colorFor } = PD;
const $stage = document.getElementById("stage");
let lastKey = null;
let deadline = null;

const qr = (path, small = false) => h("img", { class: `qr${small ? " small" : ""}`, src: `/qr?path=${encodeURIComponent(path)}`, alt: "QR code to join" });
const card = (color, ...kids) => h("section", { class: "card", style: { "--card": color } }, ...kids);
const stage = (...nodes) => $stage.replaceChildren(...nodes);

// Six bars of crowd answers with a dashed marker where the engine landed.
function axisChart(axis, share, engine) {
  const max = Math.max(1, ...share);
  return h("div", { class: "wall-axis" },
    h("div", { class: "caps" }, AXIS[axis]),
    h("div", { class: "bars", style: { marginTop: "2.2em" } },
      share.map((pct) => h("i", { style: { height: `${Math.max(3, (pct / max) * 100)}%` } })),
      h("div", { class: "marker", style: { left: `${((engine + 0.5) / 6) * 100}%` } }, h("span", {}, `engine ${fmt1(engine)}`))),
    h("div", { class: "bars-x" }, share.map((pct, b) => h("span", {}, `${b} · ${pct}%`))));
}

function pitch(c) {
  return h("div", {},
    h("div", { class: "pitch-head" },
      h("div", {}, h("div", { class: "caps sector" }, c.sector), h("p", { class: "pitch-line" }, c.one_liner)),
      c.emoji ? h("div", { class: "art", style: { width: "18vh", height: "19.5vh", fontSize: "10vh" } }, c.emoji) : null),
    h("p", { class: "ask" }, c.claim_ask),
    h("div", { class: "who", style: { fontSize: "1.4em" } }, `— ${c.name}`));
}

function render(w) {
  const i = w.card_index;
  switch (w.phase) {
    case "idle":
    case "lobby": {
      const live = w.phase === "lobby";
      return stage(card(colorFor(0), h("div", { class: "split" },
        h("div", { class: "hero", style: { textAlign: "left" } },
          h("h1", {}, "Would you"), h("span", { class: "hand" }, "back"), h("h1", {}, "this?"),
          h("p", { class: "caps", style: { fontSize: "1.1em", marginTop: "1.4em" } }, live ? w.join_url : w.join_url.replace(/\/live$/, "/play"))),
        h("div", { class: "stat" }, qr(live ? "/live" : "/play"),
          live ? h("p", { class: "caps", style: { fontSize: "1.1em" } }, h("span", { dataset: { joined: "1" } }, w.joined), " here") : null))));
    }
    case "open":
    case "locked":
      return stage(card(colorFor(i), h("div", { class: "split" },
        pitch(w.card),
        h("div", { style: { display: "grid", gap: "4vh" } },
          h("div", { class: "stat" }, h("b", { dataset: { timer: "1" } }, w.phase === "open" ? "" : "✓"),
            h("span", { class: "caps" }, w.phase === "open" ? "seconds" : "locked")),
          h("div", { class: "stat" }, h("b", { dataset: { votes: "1" } }, w.votes), h("span", { class: "caps" }, "answers")),
          h("div", { class: "row", style: { justifyContent: "center" } }, qr("/live", true))))));
    case "revealed": {
      const rv = w.reveal;
      return stage(card(colorFor(i),
        h("div", { class: "row" },
          w.card.emoji ? h("div", { class: "art small" }, w.card.emoji) : null,
          h("h2", { style: { fontSize: "2.4em" } }, w.card.name),
          h("span", { class: "spacer" }),
          h("div", { class: "vs" },
            h("div", {}, h("b", {}, fmt1(rv.room.composite)), h("div", { class: "caps" }, `crowd · ${rv.room.n}`)),
            h("div", {}, h("b", { style: { color: "var(--yellow)" } }, fmt1(rv.engine.composite)), h("div", { class: "caps" }, "engine")))),
        rv.room.n
          ? h("div", { class: "wall-axes" }, AXES.map((a) => axisChart(a, rv.room.share[a], rv.engine.axes[a])))
          : h("p", { class: "wait-title" }, "No answers on this one"),
        rv.callout ? h("div", { class: "callout" }, rv.callout.text) : null));
    }
    case "final": {
      const x = (v) => `${(v / 5) * 100}%`;
      return stage(card(colorFor(0),
        h("div", { class: "row" }, h("h2", { style: { fontSize: "2.6em" } }, "How the room read it"), h("span", { class: "spacer" }),
          h("div", { class: "legend" },
            h("span", {}, h("i", { style: { background: "var(--white)" } }), "crowd"),
            h("span", {}, h("i", { style: { background: "var(--yellow)" } }), "engine"))),
        h("div", { class: "final-rows" }, (w.cards || []).map((c) => h("div", { class: "final-row" },
          h("div", { class: "name" }, `${c.card.emoji || ""} ${c.card.name}`),
          h("div", { class: "track" },
            c.room.n ? h("div", { class: "dotm crowd", style: { left: x(c.room.composite) } }, fmt1(c.room.composite)) : null,
            h("div", { class: "dotm engine", style: { left: x(c.engine.composite) } }, fmt1(c.engine.composite))))))));
    }
    default:
      return stage(h("p", {}, w.phase));
  }
}

function tick() {
  if (!deadline) return;
  const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
  document.querySelectorAll("[data-timer]").forEach((el) => { el.textContent = `${left}`; });
}
setInterval(tick, 250);

async function poll() {
  let w;
  try {
    w = await api("/api/live/wall");
  } catch {
    return; // keep the last screen; the next poll retries
  }
  document.getElementById("counts").textContent = w.dive ? `${w.dive.label} · ${w.joined} players` : "";
  deadline = w.remaining !== null ? Date.now() + w.remaining * 1000 : null;
  document.querySelectorAll("[data-joined]").forEach((el) => { el.textContent = w.joined; });
  document.querySelectorAll("[data-votes]").forEach((el) => { el.textContent = w.votes; });
  if (w.key !== lastKey) {
    lastKey = w.key;
    render(w);
  }
  tick();
}

poll();
setInterval(poll, 2000);
