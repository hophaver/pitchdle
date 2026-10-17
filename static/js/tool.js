// Shared by the host pages: nav state, the Demo/Live switch, tabs and the one tooltip.
const Tool = (() => {
  const { h, api, post } = PD;
  let info = null; // the /api/admin/mode payload
  const handlers = [];

  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === location.pathname));

  // A small "?" that explains a definition on hover or focus. Only for readiness levels and thesis fit.
  function tip(text) {
    return h("span", { class: "tip", tabindex: "0", role: "note", "aria-label": text, "data-tip": text }, "?");
  }

  function renderSwitch() {
    const btn = (value, label) => h("button", { type: "button", "aria-pressed": String(info.mode === value),
      onclick: () => setMode(value) }, label);
    document.getElementById("mode-switch").replaceChildren(btn("demo", "Demo"), btn("live", "Live"));
    document.body.dataset.mode = info.mode;
  }

  async function setMode(mode) {
    if (!info || mode === info.mode) return;
    try {
      info = await post("/api/admin/mode", { mode });
      renderSwitch();
      handlers.forEach((fn) => fn(info));
    } catch (e) { PD.toast(e.message); }
  }

  const ready = api("/api/admin/mode").then((m) => { info = m; renderSwitch(); return m; });

  function setInfo(m) {
    const changed = !info || info.mode !== m.mode;
    info = m;
    if (changed) renderSwitch();
  }

  // Tabs live in the URL hash so they survive a reload.
  function hashTab(keys, fallback) {
    const k = location.hash.slice(1);
    return keys.includes(k) ? k : fallback;
  }
  function setHash(key) { history.replaceState(null, "", `#${key}`); }

  function tabs(list, current, pick) {
    return h("div", { class: "tabs", role: "tablist" }, list.map((t) => h("button", {
      type: "button", role: "tab", "aria-selected": String(t.key === current), onclick: () => pick(t.key),
    }, t.label, t.count ? h("span", { class: "count" }, t.count) : null)));
  }

  return { ready, info: () => info, setInfo, setMode, onMode: (fn) => handlers.push(fn), tabs, hashTab, setHash, tip };
})();
