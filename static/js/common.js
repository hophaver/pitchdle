// Shared helpers for every Pitchdle page.
const PD = (() => {
  const AXES = ["novel", "useful", "plausible", "investable"];
  const AXIS = { novel: "Novel", useful: "Useful", plausible: "Plausible", investable: "Investable" };
  // One bold colour per card, in order.
  const COLORS = ["var(--orange)", "var(--blue)", "var(--green)", "var(--navy)", "var(--plum)"];
  const colorFor = (i) => COLORS[((i % COLORS.length) + COLORS.length) % COLORS.length];

  async function api(path, opts = {}) {
    const init = { credentials: "same-origin", method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    // location.origin never carries user:pass@, so this also works when the page was opened that way.
    const r = await fetch(new URL(path, location.origin), init);
    let data = null;
    try { data = await r.json(); } catch { /* empty body */ }
    if (!r.ok) {
      const detail = data && data.detail;
      const msg = typeof detail === "string" ? detail
        : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : r.statusText;
      const err = new Error(msg || `Request failed (${r.status})`);
      err.status = r.status;
      throw err;
    }
    return data;
  }
  const post = (path, body, method = "POST") => api(path, { method, body });

  // Tiny element builder: h("div", {class: "x", onclick: fn}, "text", child, [more])
  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") {
        for (const [prop, val] of Object.entries(v)) {
          if (prop.startsWith("--")) el.style.setProperty(prop, val);
          else el.style[prop] = val;
        }
      } else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    const add = (kid) => {
      if (kid === null || kid === undefined || kid === false) return;
      if (Array.isArray(kid)) kid.forEach(add);
      else el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    };
    kids.forEach(add);
    return el;
  }

  const fmt1 = (n) => (n === null || n === undefined ? "–" : Number(n).toFixed(1));

  let toastTimer;
  function toast(msg, ms = 2800) {
    let el = document.querySelector(".toast");
    if (!el) { el = h("div", { class: "toast", role: "status" }); document.body.append(el); }
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
  }

  // How everyone answered one axis: six bars (0–5), yours highlighted.
  function bars(share, you = null) {
    const max = Math.max(1, ...share);
    return h("div", {},
      h("div", { class: "bars", "aria-hidden": "true" },
        share.map((pct, b) => h("i", { class: b === you ? "you" : "", style: { height: `${Math.max(4, (pct / max) * 100)}%` } }))),
      h("div", { class: "bars-x" }, share.map((pct, b) => h("span", { class: b === you ? "you" : "" }, b))));
  }

  return { AXES, AXIS, colorFor, api, post, h, fmt1, toast, bars };
})();
