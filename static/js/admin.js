// Admin: the background AI work, exports and resets. Companies need no hand-keeping: real startups fill, check and
// join the game by themselves, and their reviews are a click on their Dashboard details card.
const { h, api, post } = PD;
const $app = document.getElementById("app");
const S = { mode: null, poll: null };

// Every real startup is filled, checked for the game and reviewed by itself, when it's added and on startup.
// This shows the last run and starts one by hand.
function readsPanel() {
  const { ready, auto, models } = S.mode.reads;
  const errors = auto.errors || [];
  const any = Object.values(ready).some(Boolean);
  async function readMissing() {
    try {
      const r = await post("/api/admin/autoread", {});
      PD.toast(r.started ? "Working through cards that are missing something…" : "No model has a key: set OPENROUTER_API_KEY in .env");
    } catch (e) { PD.toast(e.message); }
    await refresh();
  }
  return h("section", { class: "panel" }, h("h2", {}, "AI work in the background"),
    h("p", { class: "muted small" }, `Filling profiles and evidence, the game check, screening and card writing: ${S.mode.discover.ai.model} `,
      `(OPENROUTER_MODEL). Reviews: ${models.claude}, ${models.gpt}, ${models.grok}. Set them in .env.`),
    h("p", { class: "small" }, auto.running ? "Working on new cards…"
      : auto.finished_at ? `Last run ${auto.finished_at.slice(0, 16).replace("T", " ")}, ${auto.read.length} card${auto.read.length === 1 ? "" : "s"} done${errors.length ? `, ${errors.length} error${errors.length === 1 ? "" : "s"}` : ""}.`
        : any ? "Not run yet." : "Off until a key is set (OPENROUTER_API_KEY)."),
    errors.length ? h("p", { class: "small bad" }, errors.slice(-5).join(" · ")) : null,
    h("button", { class: `btn${auto.running ? " busy" : ""}`, disabled: auto.running || !any, onclick: readMissing,
      title: "Fill, check and review every card still missing something" }, "Run missing now"));
}

function render() {
  const reset = (scope, label, question, danger) => h("button", { class: `btn${danger ? " danger" : ""}`, onclick: async () => {
    if (!confirm(question)) return;
    await post("/api/admin/reset", { scope });
    PD.toast("Done");
    await refresh();
  } }, label);
  $app.replaceChildren(
    h("div", { class: "head" }, h("h1", {}, "Admin")),
    h("div", { class: "split" },
      h("div", {}, readsPanel(), h("section", { class: "panel" }, h("h2", {}, "Export"),
        h("div", { class: "row" },
          h("a", { class: "btn", href: "/api/admin/export.csv" }, "CSV"),
          h("a", { class: "btn", href: "/api/admin/export.json" }, "JSON")))),
      h("section", { class: "panel" }, h("h2", {}, "Reset"),
        h("div", { class: "row" },
          reset("seed", "Clear demo answers", "Remove the seeded players and their answers?"),
          reset("real", "Clear real answers", "Remove every real player's answers?", true),
          reset("everything", "Reset everything", "Delete all data and reload the sample companies and sets?", true)))));
}

async function refresh() {
  try {
    S.mode = await api("/api/admin/mode");
    Tool.setInfo(S.mode);
    render();
    // Keep polling while the background work runs, so its progress shows up on its own.
    clearTimeout(S.poll);
    if (S.mode.reads.auto.running) S.poll = setTimeout(refresh, 3000);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
  }
}

Tool.onMode(refresh);
refresh();
