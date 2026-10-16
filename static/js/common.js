// Shared helpers for every Pitchdle page.
const PD = (() => {
  const AXES = ["novel", "useful", "plausible", "investable"];
  const AXIS = {
    novel: { name: "Novel", hint: "New or surprising?" },
    useful: { name: "Useful", hint: "Would people actually use it?" },
    plausible: { name: "Plausible", hint: "Can this actually work?" },
    investable: { name: "Investable", hint: "Would you put money in?" },
  };
  const ZONES = [
    [0, "Sunlight", "☀️"],
    [200, "Twilight", "🌗"],
    [1000, "Midnight", "🌑"],
    [4000, "Abyss", "🦑"],
    [6000, "Hadal", "🕳️"],
  ];
  const MAX_DEPTH = 10000;
  const TILE_EMOJI = { green: "🟩", yellow: "🟨", grey: "⬛" };

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
      else if (k === "html") el.innerHTML = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
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

  function zone(depth) {
    let z = ZONES[0];
    for (const candidate of ZONES) if (depth >= candidate[0]) z = candidate;
    return { from: z[0], name: z[1], emoji: z[2] };
  }

  // Square-root depth scale: keeps the shallow zones readable next to the abyss.
  const depthFrac = (d) => Math.sqrt(Math.min(Math.max(d || 0, 0), MAX_DEPTH) / MAX_DEPTH);

  const fmtM = (n) => `${Math.round(n || 0).toLocaleString("en-US")} m`;
  const fmt1 = (n) => (n === null || n === undefined ? "–" : Number(n).toFixed(1));

  function setDepth(depth) {
    document.body.style.setProperty("--d", Math.min(1, (depth || 0) / 7000).toFixed(3));
  }

  let toastTimer;
  function toast(msg, ms = 2800) {
    let el = document.querySelector(".toast");
    if (!el) { el = h("div", { class: "toast", role: "status" }); document.body.append(el); }
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
  }

  function countUp(el, to, { from = 0, ms = 900, format = (n) => Math.round(n) } = {}) {
    const start = performance.now();
    const tick = (t) => {
      const p = Math.min(1, (t - start) / ms);
      el.textContent = format(from + (to - from) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function tiles(list, { animate = false, mini = false } = {}) {
    return h("div", { class: `tiles${animate ? " animate" : ""}${mini ? " mini" : ""}` },
      list.map((t, i) => h("div", { class: "tile-wrap" },
        mini ? null : h("small", {}, AXIS[t.axis].name),
        h("div", { class: `tile ${t.color}`, style: animate ? { animationDelay: `${i * 0.28}s` } : null,
          "aria-label": `${AXIS[t.axis].name}: you said ${t.value}, ${t.color}` },
          String(t.value), h("span", { class: "arrow" }, t.arrow)))));
  }

  // Where a 0-5 value sits across six equal bucket columns, as a CSS left %.
  const bucketLeft = (v) => `${((v + 0.5) / 6) * 100}%`;

  // One axis of the room sheet: what share of the room picked each bucket, with markers.
  function sheetAxis(row, { big = false } = {}) {
    const max = Math.max(1, ...row.share);
    return h("div", { class: "sheet-axis" },
      h("h4", {}, h("span", {}, AXIS[row.axis].name),
        h("span", {}, `crowd ${fmt1(row.mean)} · engine ${fmt1(row.engine)}`)),
      h("div", { class: "bars", style: big ? { height: "12vh" } : null },
        row.share.map((pct, b) => h("div", { class: `bar${row.you === b ? " you" : ""}` },
          h("div", { class: "pct" }, `${pct}%`),
          h("div", { class: "fill", style: { height: `${(pct / max) * 78}%` } })))),
      h("div", { class: "bar-labels" }, [0, 1, 2, 3, 4, 5].map((b) => h("div", {}, b))),
      h("div", { class: "bar-marks" },
        row.you !== undefined && row.you !== null
          ? h("span", { class: "mark you", style: { left: bucketLeft(row.you), color: "var(--accent)" }, title: "You" }, "●") : null,
        h("span", { class: "mark crowd", style: { left: bucketLeft(row.mode), marginLeft: row.you === row.mode ? "12px" : 0 }, title: "Crowd favourite" }, "◆"),
        h("span", { class: "mark engine", style: { left: bucketLeft(row.engine), top: "-2px" }, title: "Engine read" }, "▼")),
      row.text ? h("p", { class: `sheet-text ${row.kind}` }, row.text) : null);
  }

  const legend = (withYou = true) => h("div", { class: "legend" },
    withYou ? h("span", { class: "you" }, "● you") : null,
    h("span", { class: "crowd" }, "◆ crowd favourite"),
    h("span", { class: "engine" }, "▼ engine read"));

  // Room depth chart: every diver as a dot at their depth.
  function ocean(divers, { height = 260 } = {}) {
    const box = h("div", { class: "ocean", style: { height: `${height}px` } });
    const y = (d) => `${3 + depthFrac(d) * 94}%`;
    for (const [from, name, emoji] of ZONES) {
      box.append(h("div", { class: "zl", style: { top: y(from) } }, `${emoji} ${name} · ${fmtM(from)}`));
    }
    divers.forEach((d, i) => {
      const x = 8 + ((i * 0.6180339887) % 1) * 84; // golden-ratio scatter, stable per rank
      box.append(h("div", { class: `dot${d.me ? " me" : ""}`, style: { top: y(d.depth), left: `${d.me ? 50 : x}%` },
        title: `${d.name ? d.name + ": " : ""}${fmtM(d.depth)}` }));
    });
    return box;
  }

  async function copyText(text) {
    if (navigator.share && /Mobi|Android|iPhone/i.test(navigator.userAgent)) {
      try { await navigator.share({ text }); return "shared"; } catch { /* fall through */ }
    }
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return "copied";
    }
    const ta = h("textarea", { style: { position: "fixed", opacity: 0 } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    return "copied";
  }

  return { AXES, AXIS, ZONES, MAX_DEPTH, TILE_EMOJI, api, post, h, zone, fmtM, fmt1, setDepth, toast, countUp,
    tiles, sheetAxis, legend, ocean, copyText, bucketLeft, depthFrac };
})();
