// Host control for the live room: start a set, open / lock / reveal each card, finish.
const { h, api, post } = PD;
const $app = document.getElementById("app");
let dives = [];
let selected = null;
let lastSig = null;

async function act(action) {
  try {
    await post("/api/host/live", { action, dive_id: selected });
    await refresh();
  } catch (e) {
    PD.toast(e.message);
  }
}

const PHASE_TEXT = {
  idle: "No live game running.",
  lobby: "Lobby: players are joining from the QR on the wall.",
  open: "Card open: players are voting.",
  locked: "Voting closed. Reveal when ready.",
  revealed: "Revealed: the wall shows crowd vs engine for this card.",
  final: "Finished: phones show each player their results.",
};

async function refresh() {
  let st;
  try {
    [st, dives] = await Promise.all([api("/api/host/live"), dives.length ? dives : api("/api/host/dives")]);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
    return;
  }
  if (selected === null) selected = st.dive ? st.dive.id : (dives.find((d) => d.mode === "live") || dives[0] || {}).id;
  // Rebuild only when something changed, so an open dropdown isn't closed by the 1s refresh.
  const sig = JSON.stringify([st, selected]);
  if (sig === lastSig) return;
  lastSig = sig;
  const btn = (action, label, primary, enabled) => h("button", { class: `btn${primary ? " primary" : ""}`, disabled: !enabled, onclick: () => act(action) }, label);
  const p = st.phase;
  const last = st.dive && st.card_index + 1 >= st.dive.total;
  $app.replaceChildren(
    h("h1", {}, "Live control"),
    h("section", { class: "panel" },
      h("div", { class: "row" },
        h("label", { class: "field", style: { flex: 1 } }, "Set",
          h("select", { onchange: (e) => { selected = Number(e.target.value); }, disabled: p !== "idle" && p !== "final" },
            dives.map((d) => h("option", { value: d.id, selected: d.id === selected }, `${d.label} (${d.mode})`)))),
        btn("start", p === "idle" ? "Start lobby" : "Restart lobby", p === "idle", true),
        btn("stop", "Stop", false, p !== "idle")),
      h("p", { class: "muted small" }, "Live sets only accept answers for the card that’s open. Use a set with mode “live” for the event; you can make one in Admin.")),
    h("section", { class: "panel" },
      h("h2", {}, PHASE_TEXT[p] || p),
      st.dive ? h("p", {}, `${st.dive.label} · card ${Math.max(0, st.card_index + 1)} of ${st.dive.total}`,
        st.card ? h("b", {}, ` · ${st.card.name}`) : null) : null,
      h("div", { class: "row" },
        h("span", { class: "chip" }, `🤿 ${st.joined} in the room`),
        st.card ? h("span", { class: "chip" }, `🗳 ${st.votes} reads`) : null,
        st.remaining !== null ? h("span", { class: "chip" }, `⏱ ${st.remaining}s`) : null),
      h("div", { class: "ctl-buttons", style: { marginTop: "1rem" } },
        btn("open", "Open first card", p === "lobby", p === "lobby"),
        btn("lock", "Lock voting", false, p === "open"),
        btn("reveal", "Reveal", p === "open" || p === "locked", p === "open" || p === "locked"),
        btn("next", last ? "Finish → results" : "Next card", p === "revealed", p === "revealed"),
        btn("final", "Jump to final", false, p !== "idle" && p !== "final"))),
    h("p", { class: "muted small" }, "Open ", h("a", { href: "/wall", target: "_blank" }, "/wall"),
      " on the projector. Players join at /live (QR on the wall)."));
}

refresh();
setInterval(refresh, 1000);
