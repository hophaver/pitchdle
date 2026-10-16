// Projector wall: lobby with QR → live card → room-sheet reveal + depth chart → final depths.
const { h, api, AXES, fmtM, fmt1 } = PD;
const $body = document.getElementById("body");
let lastKey = null;
let deadline = null;

function show(single, ...nodes) {
  $body.className = `wall-body${single ? " single" : ""}`;
  $body.replaceChildren(...nodes);
}

const qr = (path, small = false) => h("img", { class: `qr${small ? " small" : ""}`, src: `/qr?path=${encodeURIComponent(path)}`, alt: "QR code to join" });

function divers(list) {
  return PD.ocean(list.map((d, i) => ({ ...d, me: false, idx: i })), { height: 420 });
}

function render(w) {
  const card = w.card;
  switch (w.phase) {
    case "idle":
      return show(true, h("div", {},
        h("h1", {}, "Read the pitch. Guess the engine."),
        h("p", { class: "muted", style: { fontSize: "1.3em" } }, "Scan to play today's dive"),
        h("div", { style: { display: "flex", justifyContent: "center", margin: "2vh 0" } }, qr("/play")),
        h("p", { class: "muted" }, w.join_url.replace(/\/live$/, "/play"))));
    case "lobby":
      return show(true, h("div", {},
        h("h1", {}, "Scan to join the dive"),
        h("div", { style: { display: "flex", justifyContent: "center", margin: "2vh 0" } }, qr("/live")),
        h("p", { style: { fontSize: "1.3em" } }, w.join_url),
        h("p", { class: "huge", dataset: { joined: "1" } }, w.joined),
        h("p", { class: "muted" }, "divers in the room")));
    case "open":
    case "locked":
      return show(false,
        h("div", { class: "panel pitch" },
          h("p", { class: "muted" }, `Card ${w.card_index + 1} of ${w.dive.total} · ${card.sector}`),
          h("h2", {}, card.name),
          h("p", { class: "what" }, card.one_liner),
          h("p", { class: "ask" }, card.claim_ask),
          h("p", { class: "muted", style: { marginTop: "2em" } }, "Novel · Useful · Plausible · Investable, 0–5 on your phone")),
        h("div", { class: "side" },
          h("div", { class: "panel stat" }, h("span", {}, w.phase === "open" ? "Time left" : "Voting closed"),
            h("div", { class: "huge", dataset: { timer: "1" } }, w.phase === "open" ? "" : "🔒")),
          h("div", { class: "panel stat" }, h("span", {}, "Reads locked in"), h("div", { class: "huge", dataset: { votes: "1" } }, w.votes)),
          h("div", { class: "panel row" }, qr("/live", true), h("span", { class: "muted" }, "Late? Scan to join"))));
    case "revealed": {
      const rv = w.reveal;
      const sheet = rv.room.n
        ? h("div", { class: "sheet-grid" }, AXES.map((a) => PD.sheetAxis({
          axis: a, share: rv.room.share[a], mode: rv.room.mode[a], engine: rv.engine.axes[a], mean: rv.room.means[a],
        }, { big: true })))
        : h("p", { class: "muted" }, "No reads on this card.");
      return show(false,
        h("div", { class: "panel" },
          h("div", { class: "row" }, h("h1", { style: { margin: 0 } }, card.name), h("span", { class: "spacer" }), PD.legend(false)),
          h("div", { class: "vs" },
            h("div", {}, h("span", { class: "muted" }, "Crowd "), h("b", {}, fmt1(rv.room.composite))),
            h("div", { class: "engine" }, h("span", { class: "muted" }, "Engine "), h("b", {}, fmt1(rv.engine.composite))),
            h("div", {}, h("span", { class: "muted" }, `${rv.room.n} reads`))),
          sheet,
          rv.callout ? h("div", { class: `callout ${rv.callout.kind}` }, rv.callout.text) : null,
          rv.against ? h("p", { class: "bonus", style: { display: "inline-flex", fontSize: "1.1em" } },
            `🌊 ${rv.against} diver${rv.against === 1 ? "" : "s"} went against the current, and were right`) : null),
        h("div", { class: "side" },
          h("div", { class: "panel" }, h("b", {}, "The facts"),
            rv.facts.map((f) => h("p", { style: { margin: ".4em 0" } }, h("span", { class: "muted" }, `${f.label}: `), f.value))),
          h("div", { class: "panel", style: { flex: 1, minHeight: 0 } }, h("b", {}, "Depth chart"), divers(w.divers || []))));
    }
    case "final": {
      const top = (w.divers || []).slice(0, 5);
      return show(false,
        h("div", { class: "panel", style: { display: "flex", flexDirection: "column" } },
          h("h1", {}, "Final depths"), h("div", { style: { flex: 1 } }, divers(w.divers || []))),
        h("div", { class: "side" },
          h("div", { class: "panel" }, h("h2", {}, "🤿 Deepest divers"),
            h("ol", { class: "top5" }, top.map((d, i) => h("li", {},
              h("span", {}, `${["🥇", "🥈", "🥉", "4.", "5."][i]} ${d.name}`),
              h("span", {}, fmtM(d.depth), d.against ? ` · 🌊${d.against}` : ""))))),
          h("div", { class: "panel row" }, qr("/play", true), h("span", { class: "muted" }, "Play today's solo dive"))));
    }
    default:
      return show(true, h("p", {}, w.phase));
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
    document.getElementById("label").textContent = "Reconnecting…";
    return;
  }
  document.getElementById("label").textContent = w.dive ? `Live · ${w.dive.label}` : "";
  document.getElementById("counts").textContent = w.phase === "idle" ? "" : `🤿 ${w.joined} in the room`;
  deadline = w.remaining !== null ? Date.now() + w.remaining * 1000 : null;
  document.querySelectorAll("[data-joined]").forEach((el) => { el.textContent = w.joined; });
  document.querySelectorAll("[data-votes]").forEach((el) => { el.textContent = w.votes; });
  // Depth chart refreshes while revealed, as second-look answers arrive.
  const key = `${w.key}:${w.phase === "revealed" || w.phase === "final" ? JSON.stringify(w.divers || []) : ""}`;
  if (key !== lastKey) {
    const sameCard = lastKey && lastKey.split(":").slice(0, 3).join(":") === w.key;
    lastKey = key;
    if (sameCard && w.phase === "revealed") {
      const chart = $body.querySelector(".ocean");
      if (chart) { chart.replaceWith(divers(w.divers || [])); return; }
    }
    render(w);
  }
  tick();
}

poll();
setInterval(poll, 2000);
