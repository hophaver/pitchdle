// Host dashboard: crowd vs engine per company, perception flags, ranked next actions.
const { h, api, AXES, AXIS, fmt1 } = PD;
const $app = document.getElementById("app");
const state = { realOnly: false, open: new Set() };
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
  h("td", { class: "num" }, h("b", {}, fmt1(c.engine.composite))),
  h("td", { class: `num ${gapClass(c.gap)}` }, signed(c.gap)),
  h("td", { class: "num" }, c.crowd.consensus === null ? "–" : fmt1(c.crowd.consensus)),
  h("td", { class: "num" }, `${c.coverage.assessed}/${c.coverage.total}`),
  h("td", {}, c.flags.map((f) => h("span", { class: `flag ${f.key}`, title: f.detail }, f.label))));
  if (!state.open.has(c.id)) return row;
  const detail = h("tr", {}, h("td", { colspan: 12 }, h("div", { class: "grid2" },
    h("div", {},
      h("h3", {}, "Ranked next actions"),
      c.actions.length ? h("ol", {}, c.actions.map((a) => h("li", { style: { marginBottom: ".5rem" } },
        h("b", {}, a.name), h("span", { class: "muted small" }, ` · ${a.kind}${a.stage_fit ? ` · ${a.stage_fit}` : ""} · score ${a.score}`),
        h("div", {}, a.why),
        a.boosted.length ? h("div", { class: "small", style: { color: "#a8341a" } }, `↑ ${a.boosted.join("; ")}`) : null)))
        : h("p", { class: "muted" }, "No opportunities yet. Add them in Admin.")),
    h("div", {},
      h("h3", {}, "Flags"),
      c.flags.length ? c.flags.map((f) => h("p", {}, h("span", { class: `flag ${f.key}` }, f.label), " ", f.detail))
        : h("p", { class: "muted" }, c.crowd.n < 5 ? "Needs 5+ answers before flags fire." : "Crowd and engine broadly agree."),
      c.coverage.unknown && c.coverage.unknown.length
        ? h("p", { class: "small thin" }, `Unknown to the engine: ${c.coverage.unknown.join(", ")}`) : null))));
  return [row, detail];
}

async function refresh(force = true) {
  let data;
  try {
    data = await api(`/api/host/overview?real_only=${state.realOnly}`);
  } catch (e) {
    $app.replaceChildren(h("p", { class: "callout" }, e.message));
    return;
  }
  // Background refreshes skip the rebuild when nothing changed (keeps scroll and open rows steady).
  const sig = JSON.stringify([data, [...state.open]]);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  const flagged = data.companies.filter((c) => c.flags.length);
  const toggle = h("label", { class: "row small" },
    h("input", { type: "checkbox", checked: state.realOnly, onchange: (e) => { state.realOnly = e.target.checked; refresh(); } }),
    "Real answers only (hide demo votes)");
  $app.replaceChildren(
    h("div", { class: "row" }, h("h1", {}, "Perception vs reality"), h("span", { class: "spacer" }), toggle,
      h("a", { class: "btn small", href: "/api/admin/export.csv" }, "Export CSV"),
      h("a", { class: "btn small", href: "/api/admin/export.json" }, "Export JSON")),
    h("section", { class: "panel" },
      h("h2", {}, "Flags"),
      flagged.length ? h("div", { class: "grid2" }, flagged.map((c) => h("div", {},
        h("b", {}, c.name), h("div", {}, c.flags.map((f) => h("span", { class: `flag ${f.key}`, title: f.detail }, f.label))),
        h("div", { class: "small muted" }, c.flags.map((f) => f.detail).join(" · ")),
        c.actions[0] ? h("div", { class: "small" }, `Next: ${c.actions[0].name}. ${c.actions[0].why}`) : null)))
        : h("p", { class: "muted" }, "No flags yet. Flags need 5+ answers on a company. Admin → “Load demo votes” fills a set for rehearsal.")),
    h("section", { class: "panel" },
      h("h2", {}, "Companies"),
      h("p", { class: "muted small" }, "Axis cells: crowd / engine. Gap = crowd − engine (red ≥ 1.0, amber ≥ 0.5). Split = how much the crowd disagrees with itself. Click a row for next actions."),
      h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["Company", "Answers", ...AXES.map((a) => AXIS[a]), "Crowd", "Engine", "Gap", "Split", "Coverage", "Flags"].map((t) => h("th", {}, t)))),
        h("tbody", {}, data.companies.map(companyRow))))),
  );
}

refresh();
setInterval(() => { if (!document.hidden) refresh(false); }, 5000);
