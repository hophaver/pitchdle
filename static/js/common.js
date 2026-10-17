// Shared helpers for every Pitchdle page.
const PD = (() => {
  const AXES = ["novel", "useful", "plausible", "investable"];
  const AXIS = { novel: "Novel", useful: "Useful", plausible: "Plausible", investable: "Investable" };
  // One bold colour per card, in order.
  const COLORS = ["var(--orange)", "var(--blue)", "var(--green)", "var(--navy)", "var(--plum)"];
  const colorFor = (i) => COLORS[((i % COLORS.length) + COLORS.length) % COLORS.length];
  // "What do you do?" on the sign-up form. The keys mirror ROLES in app/main.py.
  const ROLES = {
    founder: "Founder or startup team", investor: "Investor", industry: "Industry or corporate",
    research: "Researcher or academic", engineer: "Engineer or developer", public: "Public sector or NGO",
    student: "Student", other: "Something else",
  };

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
        : Array.isArray(detail) ? detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ") : r.statusText;
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

  // Euros the short way: €650k, €1.2M.
  const short = (n) => String(Math.round(n * 10) / 10);
  const money = (eur) => (eur >= 1e6 ? `€${short(eur / 1e6)}M` : eur >= 1e3 ? `€${short(eur / 1e3)}k` : `€${eur}`);

  // One opinion as four columns on the fixed 0–5 scale, so opinions compare at a glance side by side.
  // `labelled` puts every value on its cap; otherwise a column shows its value on hover and keyboard focus.
  const AXIS_LETTER = { novel: "N", useful: "U", plausible: "P", investable: "I" };
  function opinionChart(scores, { labelled = false } = {}) {
    return h("div", { class: `opc${labelled ? " labelled" : ""}` },
      h("div", { class: "opc-plot" }, AXES.map((a) => {
        const v = short(scores[a]);
        return h("span", { class: "opc-col", tabindex: "0", role: "img", "aria-label": `${AXIS[a]} ${v} out of 5`,
          title: `${AXIS[a]} ${v}`, style: { "--v": Math.max(0, Math.min(5, scores[a])) / 5 } },
        h("i"), h("em", { "aria-hidden": "true" }, v));
      })),
      h("div", { class: "opc-x", "aria-hidden": "true" }, AXES.map((a) => h("span", {}, AXIS_LETTER[a]))));
  }

  // Links come from the server already checked, but never render anything that isn't plain http(s).
  const safeLink = (url) => (/^https?:\/\//i.test(url || "") ? url : null);
  const hostOf = (url) => new URL(url).hostname.replace(/^www\./, "");
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  // A startup's profile: a strip of facts, then the vision, stages and investors behind "Read more".
  // The player's card and the moderators' evaluation share it; each page's CSS colours it.
  function profile(c) {
    const invested = c.investors.filter((i) => i.status === "invested");
    const site = safeLink(c.website);
    const facts = [
      c.raised_eur === null || c.raised_eur === undefined ? null : `${money(c.raised_eur)} raised`,
      c.stages.length ? c.stages[c.stages.length - 1] : null,
      invested.length ? plural(invested.length, "investor") : null,
    ].filter(Boolean);
    const more = c.vision || c.stages.length || c.investors.length;
    return [
      facts.length || site ? h("div", { class: "facts" }, facts.map((f) => h("span", { class: "fact" }, f)),
        site ? h("a", { class: "fact", href: site, target: "_blank", rel: "noopener noreferrer nofollow" }, `${hostOf(site)} ↗`) : null)
        : null,
      more ? h("details", { class: "more" },
        h("summary", {}, "Read more"),
        c.vision ? c.vision.split(/\n{2,}/).map((para) => h("p", {}, para)) : null,
        c.stages.length ? [h("div", { class: "caps more-label" }, "Stages passed"),
          h("ol", { class: "stage-list" }, c.stages.map((stage) => h("li", {}, stage)))] : null,
        c.investors.length ? [h("div", { class: "caps more-label" }, "Investors"),
          h("ul", { class: "investor-list" }, c.investors.map((i) => h("li", {}, h("b", {}, i.name), " ",
            i.status === "interested" ? h("span", { class: "interested" }, "interested")
              : i.amount_eur ? money(i.amount_eur) : "invested")))] : null)
        : null,
    ];
  }

  return { AXES, AXIS, ROLES, colorFor, api, post, h, fmt1, toast, bars, money, opinionChart, safeLink, hostOf, plural, profile };
})();

// Sign out on the host and moderation pages: ends the admin password's sign-in and any account login.
(() => {
  const nav = document.querySelector("body.tool .topnav");
  if (!nav || document.getElementById("login")) return;
  nav.append(PD.h("button", { type: "button", class: "btn link signout", onclick: async () => {
    try { await PD.post("/api/staff/logout", {}); } catch { /* signed out anyway */ }
    location.reload();
  } }, "Sign out"));
})();

// Light / dark on the host pages: a sun and a moon in the nav. The page's <head> sets the theme before it paints
// (the saved choice, else the system's); this only draws the switch and remembers a pick.
(() => {
  const el = document.getElementById("theme-switch");
  if (!el) return;
  const ns = "http://www.w3.org/2000/svg";
  const ICONS = {
    light: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>',
    dark: '<path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z"/>',
  };
  const icon = (key) => {
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = ICONS[key];
    return svg;
  };
  function paint() {
    const now = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    el.replaceChildren(...["light", "dark"].map((key) => PD.h("button", { type: "button", "aria-pressed": String(now === key),
      "aria-label": key === "light" ? "Light mode" : "Dark mode", title: key === "light" ? "Light" : "Dark",
      onclick: () => {
        document.documentElement.dataset.theme = key;
        try { localStorage.setItem("pd.theme", key); } catch { /* private mode */ }
        paint();
      } }, icon(key))));
  }
  paint();
})();
