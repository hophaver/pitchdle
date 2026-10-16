// Host dashboard: crowd vs engine per company, perception flags, ranked next actions, leaderboards.
const { h, api, AXES, AXIS, fmtM, fmt1 } = PD;
const $app = document.getElementById("app");
const state = { realOnly: false, open: new Set(), diveId: null };
let lastSig = null;

const gapClass = (g) => (g === null ? "" : Math.abs(g) >= 1 ? "gap-hi" : Math.abs(g) >= 0.5 ? "gap-mid" : "");
const signed = (n) => (n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${Number(n).toFixed(1)}`);

function companyRow(c) {
  const cm = c.crowd.means || {};
  const row = h("tr", { class: "clickable", onclick: () => {
    state.open.has(c.id) ? state.open.delete(c.id) : state.open.add(c.id);
    refresh();
  } },
  h("td", {}, h("b", {}, c.name), h("div", { class: "muted small" }, `${c.sector}${c.is_real ? " · real" : ""}${c.active ? "" : " · hidden"}`)),
  h("td", { class: "num" }, c.crowd.n),
  AXES.map((a) => h("td", { class: "num" }, fmt1(cm[a]), h("span", { class: "muted" }, ` / ${fmt1(c.engine.axes[a])}`))),
  h("td", { class: "num" }, fmt1(c.crowd.composite)),
  h("td", { class: "num", style: { color: "var(--accent)" } }, fmt1(c.engine.composite)),
  h("td", { class: `num ${gapClass(c.gap)}` }, signed(c.gap)),
  h("td", { class: "num" }, c.sensitivity ? signed(c.sensitivity.composite) : "–"),
  h("td", { class: "num" }, c.crowd.consensus === null ? "–" : fmt1(c.crowd.consensus)),
  h("td", { class: "num" }, `${c.coverage.assessed}/${c.coverage.total}`),
  h("td", {}, c.flags.map((f) => h("span", { class: `flag ${f.key}`, title: f.detail }, f.label))));
  if (!state.open.has(c.id)) return row;
  const detail = h("tr", {}, h("td", { colspan: 14 }, h("div", { class: "grid2" },
    h("div", {},
      h("h3", {}, "Ranked next actions"),
      c.actions.length ? h("ol", {}, c.actions.map((a) => h("li", { style: { marginBottom: ".5rem" } },
        h("b", {}, a.name), h("span", { class: "muted small" }, ` · ${a.kind}${a.stage_fit ? ` · ${a.stage_fit}` : ""} · score ${a.score}`),
        h("div", {}, a.why),
        a.boosted.length ? h("div", { class: "small", style: { color: "var(--accent)" } }, `↑ ${a.boosted.join("; ")}`) : null)))
        : h("p", { class: "muted" }, "No opportunities yet. Add them in Admin.")),
    h("div", {},
      h("h3", {}, "Flags"),
      c.flags.length ? c.flags.map((f) => h("p", {}, h("span", { class: `flag ${f.key}` }, f.label), " ", f.detail))
        : h("p", { class: "muted" }, c.crowd.n < 5 ? "Needs 5+ reads before flags fire." : "Crowd and engine broadly agree."),
      c.sensitivity ? h("p", { class: "small muted" }, "Second-look shift per axis: ",
        AXES.map((a) => `${AXIS[a].name} ${signed(c.sensitivity.axes[a])}`).join(" · "), ` (n=${c.sensitivity.n})`) : null,
      h("h3", {}, "Against the current"),
      c.contrarians.length
        ? h("p", {}, c.contrarians.slice(0, 8).map((x) => `${x.name} (${x.axes.map((a) => AXIS[a].name).join(", ")})`).join(" · "),
          h("div", { class: "muted small" }, "Right while the room was wrong. Worth asking why."))
        : h("p", { class: "muted" }, "Nobody beat the room on this one yet."),
      c.coverage.unknown && c.coverage.unknown.length
        ? h("p", { class: "small thin" }, `Unknown to the engine: ${c.coverage.unknown.join(", ")}`) : null))));
  return [row, detail];
}

async function leaderboards(dives) {
  if (!state.diveId && dives.length) state.diveId = (dives.find((d) => d.players > 0) || dives[0]).id;
  const select = h("select", { onchange: (e) => { state.diveId = Number(e.target.value); refresh(); } },
    dives.map((d) => h("option", { value: d.id, selected: d.id === state.diveId }, `${d.label} (${d.mode}, ${d.players} players)`)));
  const box = h("section", { class: "panel" }, h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, "Leaderboards"),
    h("span", { class: "spacer" }), select));
  if (state.diveId) {
    const b = await api(`/api/dive/${state.diveId}/leaderboard`);
    const list = (title, rows, fmt) => h("div", {}, h("h3", {}, title),
      rows.length ? h("ol", { class: "board" }, rows.map((r, i) => h("li", {}, h("span", {}, `${i + 1}. ${r.name}`), h("span", {}, fmt(r.value)))))
        : h("p", { class: "muted" }, "Nobody yet."));
    box.append(h("div", { class: "grid2" },
      list("🤿 Deepest dive", b.deepest, fmtM),
      list("🌊 Against the current", b.current, (v) => `+${fmtM(v)}`),
      list("🔄 Most moved", b.moved, (v) => `${v} steps`)));
  }
  return box;
}

async function refresh(force = true) {
  let data, dives;
  try {
    [data, dives] = await Promise.all([api(`/api/host/overview?real_only=${state.realOnly}`), api("/api/host/dives")]);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
    return;
  }
  // Background refreshes skip the rebuild when nothing changed (keeps dropdowns and scroll steady).
  const sig = JSON.stringify([data, dives, [...state.open], state.diveId]);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  const flagged = data.companies.filter((c) => c.flags.length);
  const toggle = h("label", { class: "row small" },
    h("input", { type: "checkbox", checked: state.realOnly, onchange: (e) => { state.realOnly = e.target.checked; refresh(); } }),
    "Real votes only (exclude demo seed votes)");
  $app.replaceChildren(
    h("div", { class: "row" }, h("h1", { style: { margin: 0 } }, "Perception vs reality"), h("span", { class: "spacer" }), toggle,
      h("a", { class: "btn small", href: "/api/admin/export.csv" }, "Export CSV"),
      h("a", { class: "btn small", href: "/api/admin/export.json" }, "Export JSON")),
    h("section", { class: "panel" },
      h("h2", {}, "Flags"),
      flagged.length ? h("div", { class: "grid2" }, flagged.map((c) => h("div", {},
        h("b", {}, c.name), h("div", {}, c.flags.map((f) => h("span", { class: `flag ${f.key}`, title: f.detail }, f.label))),
        h("div", { class: "small muted" }, c.flags.map((f) => f.detail).join(" · ")),
        c.actions[0] ? h("div", { class: "small" }, `Next: ${c.actions[0].name}. ${c.actions[0].why}`) : null)))
        : h("p", { class: "muted" }, "No flags yet. Flags need 5+ reads on a company. Admin → “Load demo votes” fills a dive for rehearsal.")),
    h("section", { class: "panel" },
      h("h2", {}, "Companies"),
      h("p", { class: "muted small" }, "Axis cells: crowd / engine. Gap = crowd − engine composite (red ≥ 1.0, amber ≥ 0.5). Sensitivity = how far the second look moved the room. Click a row for next actions."),
      h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["Company", "Reads", ...AXES.map((a) => AXIS[a].name), "Crowd", "Engine", "Gap", "Sens.", "Split", "Coverage", "Flags"].map((t) => h("th", {}, t)))),
        h("tbody", {}, data.companies.map(companyRow))))),
    await leaderboards(dives),
  );
}

refresh();
setInterval(() => { if (!document.hidden) refresh(false); }, 5000);
