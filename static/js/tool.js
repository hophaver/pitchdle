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

  // A dropdown in the tool's own style, instead of the browser's select. options: [[value, label], ...].
  // Keyboard: Enter/Space/arrows open it, arrows move, Enter picks, Escape closes.
  function dropdown({ label, options, value, onChange, placeholder = "Pick one", class: cls = "" }) {
    const current = () => options.find(([v]) => String(v) === String(value));
    const wrap = h("div", { class: `dd ${cls}` });
    const text = h("span", { class: "dd-value" });
    const btn = h("button", { type: "button", class: "dd-btn", "aria-haspopup": "listbox", "aria-expanded": "false",
      "aria-label": label || null }, text, h("span", { class: "dd-caret", "aria-hidden": "true" }, "▾"));
    const list = h("ul", { class: "dd-list", role: "listbox", tabindex: "-1", hidden: true });
    let active = 0;
    const paint = () => {
      text.textContent = current() ? current()[1] : placeholder;
      text.classList.toggle("muted", !current());
    };
    const items = () => [...list.children];
    const mark = (i) => {
      active = (i + options.length) % options.length;
      items().forEach((li, k) => li.classList.toggle("active", k === active));
      items()[active]?.scrollIntoView({ block: "nearest" });
    };
    const outside = (e) => { if (!wrap.contains(e.target)) close(); };
    function open() {
      list.replaceChildren(...options.map(([v, l], i) => h("li", { role: "option", "aria-selected": String(String(v) === String(value)),
        onmousedown: (e) => e.preventDefault(), onclick: () => pick(i), onmousemove: () => mark(i) }, l)));
      list.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      wrap.classList.add("open");
      mark(Math.max(0, options.findIndex(([v]) => String(v) === String(value))));
      document.addEventListener("mousedown", outside);
    }
    function close() {
      list.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      wrap.classList.remove("open");
      document.removeEventListener("mousedown", outside);
    }
    function pick(i) {
      value = options[i][0];
      paint();
      close();
      btn.focus();
      onChange(value);
    }
    btn.addEventListener("click", () => (list.hidden ? open() : close()));
    btn.addEventListener("keydown", (e) => {
      if (list.hidden) {
        if (["ArrowDown", "ArrowUp"].includes(e.key)) { e.preventDefault(); open(); }
        return;
      }
      if (e.key === "ArrowDown") { e.preventDefault(); mark(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); mark(active - 1); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(active); }
      else if (e.key === "Escape" || e.key === "Tab") close();
    });
    paint();
    wrap.append(btn, list);
    return wrap;
  }

  return { ready, info: () => info, setInfo, setMode, onMode: (fn) => handlers.push(fn), tabs, hashTab, setHash, tip, dropdown };
})();
