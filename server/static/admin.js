/* Espace admin DodoTopia : application d'une page, sans dépendance.
   Données : routes /api/admin/* (cookie de session web ; en écriture, en-tête X-Dodo-Admin: 1).
   Tout texte venu du serveur passe par textContent (jamais innerHTML). Graphiques en SVG maison. */
"use strict";
(() => {
  const root = document.getElementById("app");
  const ME = JSON.parse(root.dataset.me || "{}");
  const NF = new Intl.NumberFormat("fr-FR");
  const NF1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
  const CF = new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 });
  const DAYS_FMT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
  const DAYW_FMT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
  const DT_FMT = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });
  const SVGNS = "http://www.w3.org/2000/svg";
  const state = { days: 30, statsCache: new Map(), overview: null, timers: [] };

  // --- utilitaires DOM --------------------------------------------------------------------------------------------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  function s(tag, attrs, ...kids) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
    for (const kid of kids.flat()) if (kid) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const n = (v) => (v === null || v === undefined ? "—" : NF.format(v));
  const compact = (v) => (v === null || v === undefined ? "—" : (Math.abs(v) >= 10000 ? CF.format(v) : NF.format(v)));
  const dayLabel = (d) => DAYS_FMT.format(new Date(d + "T12:00:00"));
  const TODAY = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" });
  const dayLong = (d) => DAYW_FMT.format(new Date(d + "T12:00:00")) + (d === TODAY ? " (en cours)" : "");
  const dt = (iso) => { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? iso : DT_FMT.format(d); };
  function ago(iso) {
    if (!iso) return "—";
    const sec = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(sec)) return iso;
    if (sec < 90) return "à l'instant";
    if (sec < 3600) return `il y a ${Math.round(sec / 60)} min`;
    if (sec < 86400) return `il y a ${Math.round(sec / 3600)} h`;
    if (sec < 86400 * 45) return `il y a ${Math.round(sec / 86400)} j`;
    return dt(iso);
  }
  function bytes(v) {
    if (v === null || v === undefined) return "—";
    const u = ["o", "Ko", "Mo", "Go", "To"]; let i = 0;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${NF1.format(v)} ${u[i]}`;
  }
  function duration(sec) {
    if (sec === null || sec === undefined) return "—";
    const d = Math.floor(sec / 86400), hh = Math.floor(sec % 86400 / 3600), mm = Math.floor(sec % 3600 / 60);
    return d ? `${d} j ${hh} h` : hh ? `${hh} h ${mm} min` : `${mm} min`;
  }
  const sum = (a) => a.reduce((x, y) => x + y, 0);

  let toastTimer;
  function toast(msg, err) {
    let t = document.querySelector(".toast");
    if (!t) { t = h("div", { class: "toast", role: "status", "aria-live": "polite" }); document.body.append(t); }
    t.textContent = msg; t.classList.toggle("err", !!err); t.classList.add("on");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), 3200);
  }

  // --- API ------------------------------------------------------------------------------------------------------------
  async function api(path, opts = {}) {
    const init = { credentials: "same-origin", headers: { Accept: "application/json" }, method: opts.method || "GET" };
    if (init.method !== "GET") init.headers["X-Dodo-Admin"] = "1";
    if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
    const r = await fetch(path, init);
    if (r.status === 401 || r.status === 403) {
      const body = await r.json().catch(() => ({}));
      if ((body.detail || {}).code === "unauthorized" || r.status === 401) { location.href = "/admin/login?error=expired"; }
      throw new Error((body.detail || {}).message || "Accès refusé.");
    }
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error((body.detail || {}).message || `Erreur ${r.status}`);
    return body;
  }
  async function getStats(days) {
    const hit = state.statsCache.get(days);
    if (hit && hit.until > Date.now()) return hit.data;
    const data = await api(`/api/admin/stats?days=${days}`);
    state.statsCache.set(days, { until: Date.now() + 60000, data });
    return data;
  }

  // --- icônes -------------------------------------------------------------------------------------------------------
  const ICONS = {
    dashboard: "M3 13h8V3H3v10Zm0 8h8v-6H3v6Zm10 0h8V11h-8v10Zm0-18v6h8V3h-8Z",
    audience: "M12 5C6 5 2 12 2 12s4 7 10 7 10-7 10-7-4-7-10-7Zm0 11a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z",
    app: "M5 3h14v12H5zM3 17h18v2H3zM12 6v5m-2.5-2.5L12 11l2.5-2.5",
    community: "M12 21s-7-4.4-9.3-9A5.2 5.2 0 0 1 12 6.2 5.2 5.2 0 0 1 21.3 12C19 16.6 12 21 12 21Z",
    live: "M12 12m-3 0a3 3 0 1 0 6 0 3 3 0 1 0-6 0M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8",
    moderation: "M12 2 4 5v6c0 5 3.4 9.5 8 11 4.6-1.5 8-6 8-11V5l-8-3Zm-1.5 14L7 12.5l1.4-1.4 2.1 2.1 5.1-5.1L17 9.5 10.5 16Z",
    reports: "M5 21V4h9l1 2h5v10h-7l-1-2H7v7H5Z",
    diag: "M6 2h9l5 5v15H6V2Zm8 1.5V8h4.5L14 3.5ZM9 12h8v1.6H9V12Zm0 3.5h8v1.6H9v-1.6Zm0 3.5h5v1.6H9V19Z",
    users: "M16 11a4 4 0 1 0-4-4 4 4 0 0 0 4 4ZM8 12a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm8 1c-3 0-8 1.5-8 4.5V20h16v-2.5c0-3-5-4.5-8-4.5ZM8 14c-.4 0-.9 0-1.4.1C4.4 14.5 2 15.6 2 17.5V20h4v-2.5c0-1.4.8-2.6 2-3.5Z",
    releases: "M12 3v12m0 0-4-4m4 4 4-4M4 17v3h16v-3",
    log: "M4 5h16M4 10h16M4 15h10M4 20h7",
    settings: "M12 15.5A3.5 3.5 0 1 0 12 8.5a3.5 3.5 0 0 0 0 7Zm8.5-3.5 2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L15.7 4h-4l-.4 2.8c-.7.3-1.4.7-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.3l-2 1.6 2 3.4 2.4-1c.6.5 1.3.9 2 1.2l.4 2.8h4l.4-2.8c.7-.3 1.4-.7 2-1.2l2.4 1 2-3.4-2-1.6c.1-.8.1-1.5 0-2.3Z",
  };
  function icon(name) {
    const stroke = ["app", "live", "releases", "log"].includes(name);
    return s("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" },
      s("path", stroke ? { d: ICONS[name], fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" }
        : { d: ICONS[name], fill: "currentColor" }));
  }

  // --- graphiques ---------------------------------------------------------------------------------------------------
  // Maximum de l'axe = 4 graduations « rondes » (1, 2, 2,5, 5 × 10^k ; entières dès que v ≥ 4).
  function niceMax(v) {
    if (v <= 4) return 4;
    const raw = v / 4, p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 2.5, 3, 5, 10]) {
      const step = m * p;
      if (step >= raw && (step >= 1 && Number.isInteger(step))) return step * 4;
    }
    return 40 * p;
  }

  // Réagit aux changements de largeur (le graphique est redessiné, jamais étiré).
  const resizeObs = new ResizeObserver((entries) => {
    for (const e of entries) { const fn = e.target._redraw; if (fn && e.target._w !== Math.round(e.contentRect.width)) fn(); }
  });

  /* Courbes par jour : crosshair + infobulle listant toutes les séries, légende dès 2 séries, valeur en bout de ligne. */
  function lineChart({ labels, series, height = 220, area = false, fmt = n, labelFmt = dayLong, tickFmt = dayLabel }) {
    const box = h("div", { class: "chart" });
    const legend = series.length > 1 ? h("ul", { class: "legend" }, series.map((se) =>
      h("li", {}, h("span", { class: `key bg-${se.cls}` }), se.name))) : null;
    const holder = h("div", { class: "chart" });
    const tip = h("div", { class: "tip", role: "status" });
    box.append(...(legend ? [legend] : []), holder);
    holder.append(tip);
    let idx = null;

    function draw() {
      const W = Math.max(260, Math.round(holder.clientWidth || 600));
      holder._w = W;
      // Étiquettes de fin : seulement si elles ne se chevauchent pas (sinon légende + infobulle suffisent).
      const maxAll = niceMax(Math.max(1, ...series.flatMap((se) => se.values)));
      const ends = series.map((se) => se.values[se.values.length - 1] / maxAll * (height - 36)).sort((a, b) => a - b);
      const endLabels = series.length <= 3 && ends.every((v, i) => i === 0 || v - ends[i - 1] >= 14);
      const P = { l: 44, r: endLabels ? 50 : 12, t: 10, b: 26 };
      const iw = W - P.l - P.r, ih = height - P.t - P.b;
      const max = niceMax(Math.max(1, ...series.flatMap((se) => se.values)));
      const N = labels.length;
      const x = (i) => P.l + (N <= 1 ? iw / 2 : (i * iw) / (N - 1));
      const y = (v) => P.t + ih - (v / max) * ih;
      const svg = s("svg", { viewBox: `0 0 ${W} ${height}`, height, role: "img", tabindex: "0",
        "aria-label": `${series.map((se) => se.name).join(", ")} : graphique sur ${N} points (flèches pour parcourir)` });
      for (let k = 0; k <= 4; k++) {
        const v = (max * k) / 4, yy = y(v);
        svg.append(s("line", { class: k === 0 ? "baseline" : "gridline", x1: P.l, x2: W - P.r, y1: yy, y2: yy }));
        svg.append(s("text", { class: "tick", x: P.l - 8, y: yy + 4, "text-anchor": "end" }, compact(v)));
      }
      const every = Math.max(1, Math.ceil(N / Math.max(2, Math.floor(iw / 80))));
      for (let i = 0; i < N; i += every) {
        svg.append(s("text", { class: "tick", x: x(i), y: height - 6, "text-anchor": i === 0 ? "start" : "middle" }, tickFmt(labels[i])));
      }
      for (const se of series) {
        const pts = se.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
        if (area || se.area) {
          svg.append(s("path", { class: `area ${se.cls}`, d: `M${x(0)},${y(0)} L${pts.join(" L")} L${x(N - 1)},${y(0)} Z` }));
        }
        svg.append(s("polyline", { class: `line ${se.cls}`, points: pts.join(" ") }));
        if (endLabels && N) {
          const last = se.values[N - 1];
          svg.append(s("circle", { class: `dot ${se.cls}`, cx: x(N - 1), cy: y(last), r: 4 }));
          svg.append(s("text", { class: "endlabel", x: x(N - 1) + 8, y: y(last) + 4 }, compact(last)));
        }
      }
      const cross = s("line", { class: "cross", y1: P.t, y2: P.t + ih, visibility: "hidden" });
      const dots = series.map((se) => s("circle", { class: `dot ${se.cls}`, r: 4, visibility: "hidden" }));
      svg.append(cross, ...dots);
      const hit = s("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent" });
      svg.append(hit);

      function show(i) {
        idx = Math.max(0, Math.min(N - 1, i));
        const xx = x(idx);
        cross.setAttribute("x1", xx); cross.setAttribute("x2", xx); cross.setAttribute("visibility", "visible");
        series.forEach((se, k) => { dots[k].setAttribute("cx", xx); dots[k].setAttribute("cy", y(se.values[idx])); dots[k].setAttribute("visibility", "visible"); });
        tip.replaceChildren(h("div", { class: "t-head", text: labelFmt(labels[idx]) }),
          ...series.map((se) => h("div", { class: "t-row" }, h("span", { class: `key bg-${se.cls}` }), h("b", { text: fmt(se.values[idx]) }), h("span", { text: se.name }))));
        tip.classList.add("on");
        const scale = holder.clientWidth / W;
        const left = xx * scale;
        tip.style.left = `${Math.min(holder.clientWidth - tip.offsetWidth - 4, Math.max(0, left + 12 > holder.clientWidth - tip.offsetWidth ? left - tip.offsetWidth - 12 : left + 12))}px`;
        tip.style.top = `${P.t}px`;
      }
      function hide() { idx = null; tip.classList.remove("on"); cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); }
      svg.addEventListener("pointermove", (e) => {
        const r = svg.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        if (px < P.l - 10 || px > W - P.r + 10) return hide();
        show(Math.round(((px - P.l) / iw) * (N - 1)));
      });
      svg.addEventListener("pointerleave", hide);
      svg.addEventListener("focus", () => show(idx ?? N - 1));
      svg.addEventListener("blur", hide);
      svg.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") { show((idx ?? N - 1) - 1); e.preventDefault(); }
        if (e.key === "ArrowRight") { show((idx ?? 0) + 1); e.preventDefault(); }
      });
      holder.querySelector("svg")?.remove();
      holder.prepend(svg);
    }
    holder._redraw = draw;
    requestAnimationFrame(() => { draw(); resizeObs.observe(holder); });
    return box;
  }

  /* Colonnes (histogrammes, tailles de salon) : barres ≤ 24 px, bout arrondi, valeur au sommet. */
  function columns(items, { height = 180, cls = "s1", fmt = n } = {}) {
    const holder = h("div", { class: "chart" });
    const tip = h("div", { class: "tip" });
    holder.append(tip);
    function draw() {
      const W = Math.max(240, Math.round(holder.clientWidth || 400)); holder._w = W;
      const P = { l: 8, r: 8, t: 18, b: 24 };
      const iw = W - P.l - P.r, ih = height - P.t - P.b;
      const max = Math.max(1, ...items.map((i) => i.value));
      const band = iw / Math.max(1, items.length), bw = Math.min(24, band * 0.6);
      const svg = s("svg", { viewBox: `0 0 ${W} ${height}`, height, role: "img", "aria-label": items.map((i) => `${i.label} : ${fmt(i.value)}`).join(", ") });
      svg.append(s("line", { class: "baseline", x1: P.l, x2: W - P.r, y1: P.t + ih, y2: P.t + ih }));
      items.forEach((it, i) => {
        const cx = P.l + band * i + band / 2, bh = (it.value / max) * ih, x0 = cx - bw / 2, y0 = P.t + ih - bh;
        const r = Math.min(4, bh, bw / 2);
        const d = bh <= 0 ? "" : `M${x0},${P.t + ih} V${y0 + r} Q${x0},${y0} ${x0 + r},${y0} H${x0 + bw - r} Q${x0 + bw},${y0} ${x0 + bw},${y0 + r} V${P.t + ih} Z`;
        const g = s("g", { class: "col", tabindex: "0" });
        g.append(s("rect", { x: cx - band / 2, y: P.t, width: band, height: ih, fill: "transparent" }));
        if (d) g.append(s("path", { class: cls, d }));
        g.append(s("text", { class: "tick", x: cx, y: Math.max(P.t - 4, y0 - 5), "text-anchor": "middle" }, compact(it.value)));
        g.append(s("text", { class: "tick", x: cx, y: height - 6, "text-anchor": "middle" }, it.label));
        const on = () => {
          tip.replaceChildren(h("div", { class: "t-head", text: it.label }), h("div", { class: "t-row" }, h("b", { text: fmt(it.value) })));
          tip.classList.add("on");
          const sc = holder.clientWidth / W;
          tip.style.left = `${Math.min(holder.clientWidth - tip.offsetWidth, Math.max(0, cx * sc - tip.offsetWidth / 2))}px`;
          tip.style.top = "0px";
        };
        g.addEventListener("pointerenter", on); g.addEventListener("focus", on);
        g.addEventListener("pointerleave", () => tip.classList.remove("on")); g.addEventListener("blur", () => tip.classList.remove("on"));
        svg.append(g);
      });
      holder.querySelector("svg")?.remove();
      holder.prepend(svg);
    }
    holder._redraw = draw;
    requestAnimationFrame(() => { draw(); resizeObs.observe(holder); });
    return items.length ? holder : h("p", { class: "empty", text: "Pas encore de données." });
  }

  /* Classement horizontal (HTML) : libellé, valeur, part du total. */
  function barList(items, { color = "", pct = true, fmt = n, link = null, empty = "Pas encore de données." } = {}) {
    if (!items || !items.length) return h("p", { class: "empty", text: empty });
    const max = Math.max(1, ...items.map((i) => i.value));
    const tot = sum(items.map((i) => i.value)) || 1;
    return h("ul", { class: "bars" }, items.map((it) => {
      const fill = h("div", { class: `fill ${color}` });
      fill.style.width = `${(it.value / max) * 100}%`;
      const lab = link ? h("a", { class: "lab", href: link(it), text: it.label, title: it.label }) : h("span", { class: "lab", text: it.label, title: it.label });
      return h("li", {}, lab, h("span", { class: "val" }, fmt(it.value), pct ? h("span", { class: "pct", text: `${NF1.format((it.value * 100) / tot)} %` }) : null),
        h("div", { class: "track" }, fill));
    }));
  }

  function sparkline(values, cls = "s1") {
    if (!values || values.length < 2) return null;
    const W = 120, H = 28, max = Math.max(1, ...values);
    const pts = values.map((v, i) => `${((i * W) / (values.length - 1)).toFixed(1)},${(H - 3 - (v / max) * (H - 6)).toFixed(1)}`);
    return s("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true" },
      s("polyline", { points: pts.join(" "), fill: "none", class: `line ${cls}`, "stroke-width": "1.5", "vector-effect": "non-scaling-stroke" }));
  }

  const WEEKDAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."];
  function heatmap(grid) {
    const max = Math.max(0, ...grid.flat());
    if (!max) return h("p", { class: "empty", text: "Pas encore de pages vues sur la période." });
    const wrap = h("div", { class: "heat", role: "img", "aria-label": "Pages vues par jour de semaine et par heure (heure de Paris)" });
    wrap.append(h("span"));
    for (let hh = 0; hh < 24; hh++) wrap.append(h("span", { class: "x-lab", text: hh % 3 === 0 ? String(hh) : "" }));
    grid.forEach((row, wd) => {
      wrap.append(h("span", { class: "h-lab", text: WEEKDAYS[wd] }));
      row.forEach((v, hh) => {
        const q = v ? Math.min(6, 1 + Math.floor((v / max) * 5.999)) : 0;
        wrap.append(h("span", { class: `cell${q ? " q" + q : ""}`, title: `${WEEKDAYS[wd]} ${hh} h : ${n(v)} page(s) vue(s)` }));
      });
    });
    const legend = h("div", { class: "heat-legend" }, "Moins", ...[0, 1, 2, 3, 4, 5, 6].map((q) => h("span", { class: `cell${q ? " q" + q : ""}` })), "Plus");
    return h("div", {}, wrap, legend);
  }

  function dataTable(labels, series) {
    const table = h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Jour" }), series.map((se) => h("th", { class: "r", text: se.name })))),
      h("tbody", {}, labels.slice().reverse().map((d, ri) => {
        const i = labels.length - 1 - ri;
        return h("tr", {}, h("td", { text: dayLong(d) }), series.map((se) => h("td", { class: "r", text: n(se.values[i]) })));
      })));
    return h("details", {}, h("summary", { class: "small muted", text: "Voir les données" }), h("div", { class: "table-wrap" }, table));
  }

  // --- blocs de mise en page ----------------------------------------------------------------------------------------
  function tile(label, value, { sub = "", delta = null, spark = null, alert = false, upGood = true, href = null } = {}) {
    let deltaEl = null;
    if (delta !== null && delta !== undefined) {
      const dir = delta > 0.5 ? "up" : delta < -0.5 ? "down" : "flat";
      const good = dir === "flat" ? "flat" : ((dir === "up") === upGood ? "up" : "down");
      deltaEl = h("span", { class: `delta ${good}`, title: "Deuxième moitié de la période comparée à la première" },
        `${delta > 0 ? "▲ +" : delta < 0 ? "▼ " : ""}${NF1.format(delta)} %`);
    }
    const body = [h("div", { class: "label", text: label }), h("div", { class: "value", text: typeof value === "number" ? compact(value) : value }),
      h("div", { class: "sub" }, deltaEl, deltaEl && sub ? " · " : "", sub), spark];
    return href ? h("a", { class: `tile${alert ? " alert" : ""}`, href, style: null }, ...body) : h("div", { class: `tile${alert ? " alert" : ""}` }, ...body);
  }
  function card(title, content, { sub = "", extra = null, cls = "" } = {}) {
    return h("section", { class: `card ${cls}` }, h("header", {}, h("h2", { text: title }), sub ? h("span", { class: "small muted", text: sub }) : null, extra), content);
  }
  function kv(pairs) { return h("dl", { class: "kv" }, pairs.flatMap(([k, v]) => [h("dt", { text: k }), h("dd", {}, v instanceof Node ? v : String(v))])); }
  function who(u) {
    const img = u.avatar_url ? h("img", { src: u.avatar_url, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("span", { class: "ph" });
    return h("span", { class: "who" }, img, h("span", {}, u.username || u.name || "?"));
  }
  const statusPill = (st) => h("span", { class: `pill ${{ approved: "ok", pending: "warn", rejected: "bad" }[st] || ""}`, text: { approved: "publié", pending: "en attente", rejected: "refusé" }[st] || st });
  function tot(data, key) { return data.totals[key] || { total: 0, delta_pct: null }; }
  function periodLabel(days) { return days === 7 ? "7 derniers jours" : days === 365 ? "12 derniers mois" : `${days} derniers jours`; }

  // --- coque -----------------------------------------------------------------------------------------------------------
  const SECTIONS = [
    ["dashboard", "Tableau de bord"], ["audience", "Audience du site"], ["app", "App & téléchargements"],
    ["community", "Communauté & contenu"], ["live", "Salons & serveur"], null,
    ["moderation", "Modération"], ["reports", "Signalements"], ["diag", "Rapports de diagnostic"], ["users", "Comptes"], null,
    ["releases", "Versions"], ["log", "Journal admin"], ["settings", "Réglages & webhook"],
  ];
  const WITH_PERIOD = new Set(["dashboard", "audience", "app", "community", "live"]);
  const nav = h("nav", { class: "nav", "aria-label": "Sections" });
  const badges = {};
  for (const it of SECTIONS) {
    if (!it) { nav.append(h("div", { class: "sep" })); continue; }
    const [id, label] = it;
    const a = h("a", { href: `#${id}`, "data-id": id }, icon(id), h("span", { text: label }));
    if (id === "moderation" || id === "reports") { badges[id] = h("span", { class: "badge zero", "aria-label": "en attente" }); a.append(badges[id]); }
    nav.append(a);
  }
  const titleEl = h("h1");
  const period = h("div", { class: "seg", role: "group", "aria-label": "Période" });
  for (const d of [7, 30, 90, 365]) {
    period.append(h("button", { type: "button", "aria-pressed": String(d === state.days), onclick: () => { state.days = d; period.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.textContent === labelDays(d)))); route(); }, text: labelDays(d) }));
  }
  function labelDays(d) { return d === 365 ? "12 mois" : `${d} j`; }
  const csv = h("a", { class: "btn sm", href: "#", text: "Export CSV", onclick: (e) => { e.currentTarget.href = `/api/admin/stats.csv?days=${Math.max(state.days, 30)}`; } });
  const filters = h("div", { class: "filters" }, period, csv);
  const content = h("div", { id: "content" });
  const logoutForm = h("form", { method: "post", action: "/admin/logout" }, h("button", { class: "btn sm", type: "submit", text: "Déconnexion" }));
  const meEl = h("div", { class: "me" }, ME.avatar_url ? h("img", { src: ME.avatar_url, alt: "", referrerpolicy: "no-referrer" }) : null, h("span", { text: ME.username || "" }), logoutForm);
  root.replaceChildren(h("div", { class: "shell" },
    h("aside", { class: "side" }, h("div", { class: "brand" }, h("img", { src: "/static/logo.png", alt: "" }), h("div", {}, "DodoTopia", h("small", { text: "Espace admin" }))), nav,
      h("div", { class: "sep" }), h("a", { class: "small muted", href: "/", target: "_blank", rel: "noopener", text: "Voir le site ↗" })),
    h("main", { class: "main" }, h("div", { class: "top" }, titleEl, meEl), filters, content)));

  function clearTimers() { state.timers.forEach(clearInterval); state.timers = []; }

  async function route() {
    clearTimers();
    const hash = (location.hash || "#dashboard").slice(1);
    const [id, arg] = hash.split("/");
    const known = SECTIONS.filter(Boolean).find((x) => x[0] === id);
    const sectionId = id === "user" ? "users" : known ? id : "dashboard";
    nav.querySelectorAll("a").forEach((a) => { if (a.dataset.id === sectionId) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    titleEl.textContent = id === "user" ? "Compte" : (known || SECTIONS[0])[1];
    document.title = `${titleEl.textContent} · DodoTopia Admin`;
    filters.hidden = !WITH_PERIOD.has(sectionId) || id === "user";
    content.classList.add("loading");
    try {
      const view = await (VIEWS[id === "user" ? "user" : sectionId])(arg);
      content.replaceChildren(view);
    } catch (e) {
      content.replaceChildren(h("div", { class: "notice bad", role: "alert", text: `Impossible de charger cette section : ${e.message}` }));
    } finally {
      content.classList.remove("loading");
    }
  }

  async function refreshBadges() {
    try {
      const o = await api("/api/admin/overview");
      state.overview = o;
      const pend = o.songs.pending + o.drawings.pending;
      badges.moderation.textContent = pend; badges.moderation.classList.toggle("zero", !pend);
      badges.reports.textContent = o.reports_open; badges.reports.classList.toggle("zero", !o.reports_open);
      return o;
    } catch { return state.overview; }
  }

  // --- vues ------------------------------------------------------------------------------------------------------------
  const VIEWS = {};

  VIEWS.dashboard = async () => {
    const [o, d] = await Promise.all([refreshBadges(), getStats(state.days)]);
    const S = d.series, L = d.days;
    const frag = h("div");
    const pend = o.songs.pending + o.drawings.pending;
    if (pend || o.reports_open || !o.webhook.configured) {
      frag.append(h("div", { class: "notice", role: "status" },
        pend ? h("span", {}, h("a", { href: "#moderation", text: `${pend} contenu(s) à modérer` }), ". ") : null,
        o.reports_open ? h("span", {}, h("a", { href: "#reports", text: `${o.reports_open} signalement(s) ouvert(s)` }), ". ") : null,
        !o.webhook.configured ? h("span", {}, "Aucune notification Discord : ", h("a", { href: "#settings", text: "configurer le webhook" }), ".") : null));
    }
    frag.append(h("p", { class: "small muted", text: `Période : ${periodLabel(state.days)} · évolution = seconde moitié de la période comparée à la première.` }));
    frag.append(h("div", { class: "tiles" },
      tile("Visiteurs", tot(d, "visitors").total, { delta: tot(d, "visitors").delta_pct, spark: sparkline(S.visitors), sub: `aujourd'hui ${n(o.today.visitors)}` }),
      tile("Pages vues", tot(d, "pv").total, { delta: tot(d, "pv").delta_pct, spark: sparkline(S.pv), sub: `aujourd'hui ${n(o.today.pv)}` }),
      tile("Apps actives (moy./jour)", Math.round(tot(d, "app_active").total / L.length), { delta: tot(d, "app_active").delta_pct, spark: sparkline(S.app_active, "s3"), sub: `aujourd'hui ${n(o.today.app_active)}` }),
      tile("Téléchargements de l'app", tot(d, "dl_app").total, { delta: tot(d, "dl_app").delta_pct, spark: sparkline(S.dl_app, "s2"), sub: `total ${n(o.app_downloads)}` }),
      tile("Nouveaux comptes", tot(d, "signups").total, { delta: tot(d, "signups").delta_pct, spark: sparkline(S.signups, "s7"), sub: `total ${n(o.users.total)}` }),
      tile("Morceaux téléchargés", tot(d, "dl_song").total, { delta: tot(d, "dl_song").delta_pct, spark: sparkline(S.dl_song, "s4"), sub: `total ${n(o.song_downloads)}` }),
      tile("Parties en salon", tot(d, "room_start").total, { delta: tot(d, "room_start").delta_pct, spark: sparkline(S.room_start, "s5") }),
      tile("En direct", `${n(o.live.players)} joueur(s)`, { sub: `${n(o.live.rooms)} salon(s) · ${n(o.live.playing)} en partie`, href: "#live" }),
    ));
    frag.append(h("div", { class: "grid g2" },
      card("Audience du site", h("div", {}, lineChart({ labels: L, series: [{ name: "Visiteurs", values: S.visitors, cls: "s1" }, { name: "Pages vues", values: S.pv, cls: "s2" }] }),
        dataTable(L, [{ name: "Visiteurs", values: S.visitors }, { name: "Pages vues", values: S.pv }]))),
      card("Utilisation de l'app", h("div", {}, lineChart({ labels: L, series: [{ name: "Apps actives", values: S.app_active, cls: "s3" }, { name: "Téléchargements", values: S.dl_app, cls: "s2" }, { name: "Connexions", values: S.logins, cls: "s7" }] }),
        dataTable(L, [{ name: "Apps actives", values: S.app_active }, { name: "Téléchargements", values: S.dl_app }, { name: "Connexions", values: S.logins }]))),
      card("Comptes", kv([["Total", n(o.users.total)], ["Nouveaux 24 h / 7 j / 30 j", `${n(o.users.new_24h)} / ${n(o.users.new_7d)} / ${n(o.users.new_30d)}`],
        ["Actifs 24 h / 7 j / 30 j", `${n(o.users.active_24h)} / ${n(o.users.active_7d)} / ${n(o.users.active_30d)}`], ["Bannis", n(o.users.banned)],
        ["Connexions aujourd'hui", n(o.today.logins)]])),
      card("Contenu", kv([["Morceaux publiés", n(o.songs.approved)], ["En attente", n(o.songs.pending)], ["Refusés", n(o.songs.rejected)],
        ["Dessins publiés / en attente", `${n(o.drawings.approved)} / ${n(o.drawings.pending)}`], ["Likes", n(o.likes)],
        ["Dernière version", o.latest_release ? `${o.latest_release.version} · ${n(o.latest_release.downloads)} téléchargements` : "—"]])),
      card("Top pages", barList(d.breakdowns.pages.slice(0, 8))),
      card("D'où viennent les visiteurs", barList(d.breakdowns.referrers.slice(0, 8), { color: "c3", empty: "Aucun site référent sur la période (accès direct ou moteurs sans référent)." })),
    ));
    return frag;
  };

  VIEWS.audience = async () => {
    const d = await getStats(state.days);
    const S = d.series, L = d.days, B = d.breakdowns;
    return h("div", {},
      h("div", { class: "tiles" },
        tile("Visiteurs", tot(d, "visitors").total, { delta: tot(d, "visitors").delta_pct, spark: sparkline(S.visitors) }),
        tile("Pages vues", tot(d, "pv").total, { delta: tot(d, "pv").delta_pct, spark: sparkline(S.pv, "s2") }),
        tile("Pages / visiteur", tot(d, "visitors").total ? NF1.format(tot(d, "pv").total / tot(d, "visitors").total) : "—"),
        tile("Robots", tot(d, "bots").total, { spark: sparkline(S.bots, "s7"), sub: "non comptés dans l'audience" }),
        tile("Pages introuvables (404)", tot(d, "http_404").total, { upGood: false, delta: tot(d, "http_404").delta_pct }),
      ),
      h("div", { class: "grid g2" },
        card("Visiteurs et pages vues", h("div", {}, lineChart({ labels: L, series: [{ name: "Visiteurs", values: S.visitors, cls: "s1", area: true }, { name: "Pages vues", values: S.pv, cls: "s2" }], height: 260 }),
          dataTable(L, [{ name: "Visiteurs", values: S.visitors }, { name: "Pages vues", values: S.pv }])), { cls: "span2" }),
        card("Quand les visiteurs viennent", heatmap(d.heatmap), { sub: "heure de Paris", cls: "span2" }),
        card("Pages les plus vues", barList(B.pages)),
        card("Sites référents", barList(B.referrers, { color: "c3", empty: "Aucun référent externe." })),
        card("Langue du site (visiteurs)", barList(B.visitors_lang.length ? B.visitors_lang : B.langs, { color: "c7" })),
        card("Appareils", barList(B.devices, { color: "c2" })),
        card("Navigateurs", barList(B.browsers)),
        card("Systèmes", barList(B.os, { color: "c3" })),
        card("Robots d'indexation", barList(B.bots, { color: "c7" }), { sub: "Google, Bing, Discord…" }),
        card("Confidentialité", h("p", { class: "small muted", text: "Mesure sans cookie : un visiteur = une empreinte (IP + navigateur) salée par un secret du jour, effacée le lendemain. Impossible de relier deux jours ou de retrouver une IP ; le total de la période additionne donc les visiteurs de chaque jour." })),
      ));
  };

  VIEWS.app = async () => {
    const [d, rel] = await Promise.all([getStats(state.days), api("/api/admin/releases-stats")]);
    const S = d.series, L = d.days, B = d.breakdowns;
    const versions = rel.items.filter((r) => r.published_at).slice(0, 10).reverse().map((r) => ({ label: r.version, value: r.downloads }));
    return h("div", {},
      h("div", { class: "tiles" },
        tile("Apps actives (moy./jour)", Math.round(tot(d, "app_active").total / L.length), { delta: tot(d, "app_active").delta_pct, spark: sparkline(S.app_active, "s3") }),
        tile("Téléchargements", tot(d, "dl_app").total, { delta: tot(d, "dl_app").delta_pct, spark: sparkline(S.dl_app, "s2") }),
        tile("Connexions Discord", tot(d, "logins").total, { delta: tot(d, "logins").delta_pct, spark: sparkline(S.logins, "s7") }),
        tile("Appels d'API de l'app", tot(d, "app_api").total, { spark: sparkline(S.app_api) }),
        tile("Imports par lien", tot(d, "imports").total, { spark: sparkline(S.imports, "s4") }),
      ),
      h("div", { class: "grid g2" },
        card("Installations actives par jour", h("div", {}, lineChart({ labels: L, series: [{ name: "Apps actives", values: S.app_active, cls: "s3", area: true }] }),
          dataTable(L, [{ name: "Apps actives", values: S.app_active }])), { sub: "une installation = un couple IP + version par jour" }),
        card("Téléchargements par jour", h("div", {}, lineChart({ labels: L, series: [{ name: "Téléchargements", values: S.dl_app, cls: "s2", area: true }] }),
          dataTable(L, [{ name: "Téléchargements", values: S.dl_app }]))),
        card("Versions utilisées", barList(B.app_versions, { color: "c3", empty: "Aucun client DodoTopia vu sur la période." }), { sub: "installations actives cumulées par jour" }),
        card("Systèmes des joueurs", barList(B.app_platforms, { color: "c7" })),
        card("Téléchargements par plateforme", barList(B.dl_platforms, { color: "c2" })),
        card("Téléchargements par version", barList(B.dl_versions, { color: "c2" })),
        card("D'où partent les téléchargements", barList(B.dl_sources.map((x) => ({ ...x, label: { site: "Page Télécharger du site", app: "Mise à jour automatique", direct: "Lien direct" }[x.label] || x.label })))),
        card("Téléchargements cumulés par version", columns(versions, { cls: "s2" }), { sub: "depuis toujours" }),
        card("Connexions", barList(B.logins.map((x) => ({ ...x, label: x.label === "web" ? "Espace admin (site)" : "Application" })), { color: "c7" })),
        card("Fonctions de l'app appelées", barList(B.app_api)),
      ));
  };

  VIEWS.community = async () => {
    const d = await getStats(state.days);
    const S = d.series, L = d.days, B = d.breakdowns, C = d.content, M = C.moderation;
    const songLink = (it) => `${ME.public_url}/api/songs/${it.id}/download`;
    const songItems = (arr, key) => arr.map((r) => ({ id: r.id, label: r.artist ? `${r.title} — ${r.artist}` : r.title, value: r[key] }));
    return h("div", {},
      h("div", { class: "tiles" },
        tile("Nouveaux comptes", tot(d, "signups").total, { delta: tot(d, "signups").delta_pct, spark: sparkline(S.signups, "s7") }),
        tile("Morceaux déposés", tot(d, "songs_uploaded").total, { delta: tot(d, "songs_uploaded").delta_pct, spark: sparkline(S.songs_uploaded) }),
        tile("Dessins déposés", tot(d, "drawings_uploaded").total, { delta: tot(d, "drawings_uploaded").delta_pct, spark: sparkline(S.drawings_uploaded, "s5") }),
        tile("Likes", tot(d, "likes").total, { delta: tot(d, "likes").delta_pct, spark: sparkline(S.likes, "s8") }),
        tile("Morceaux téléchargés", tot(d, "dl_song").total, { delta: tot(d, "dl_song").delta_pct, spark: sparkline(S.dl_song, "s4") }),
        tile("Signalements", tot(d, "reports").total, { upGood: false, delta: tot(d, "reports").delta_pct }),
      ),
      h("div", { class: "grid g2" },
        card("Comptes et connexions", h("div", {}, lineChart({ labels: L, series: [{ name: "Nouveaux comptes", values: S.signups, cls: "s7" }, { name: "Connexions", values: S.logins, cls: "s1" }] }),
          dataTable(L, [{ name: "Nouveaux comptes", values: S.signups }, { name: "Connexions", values: S.logins }]))),
        card("Dépôts et likes", h("div", {}, lineChart({ labels: L, series: [{ name: "Morceaux", values: S.songs_uploaded, cls: "s1" }, { name: "Dessins", values: S.drawings_uploaded, cls: "s5" }, { name: "Likes", values: S.likes, cls: "s3" }] }),
          dataTable(L, [{ name: "Morceaux", values: S.songs_uploaded }, { name: "Dessins", values: S.drawings_uploaded }, { name: "Likes", values: S.likes }]))),
        card("Morceaux les plus téléchargés", barList(B.top_song_downloads, { color: "c2" }), { sub: periodLabel(state.days) }),
        card("Morceaux les plus téléchargés", barList(songItems(C.top_songs_downloads, "downloads"), { color: "c2", link: songLink }), { sub: "depuis toujours" }),
        card("Morceaux les plus aimés", barList(songItems(C.top_songs_likes, "likes"), { color: "c3" })),
        card("Dessins les plus aimés", barList(C.top_drawings.map((r) => ({ label: `${r.title} (${r.w}×${r.h})`, value: r.likes })), { color: "c3" })),
        card("Meilleurs contributeurs", C.top_uploaders.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", { text: "Compte" }), h("th", { class: "r", text: "Morceaux" }), h("th", { class: "r", text: "Dessins" }), h("th", { class: "r", text: "Téléch." }))),
          h("tbody", {}, C.top_uploaders.map((u) => h("tr", {}, h("td", {}, h("a", { href: `#user/${u.id}` }, who(u))), h("td", { class: "r", text: n(u.songs) }), h("td", { class: "r", text: n(u.drawings) }), h("td", { class: "r", text: n(u.downloads) }))))))
          : h("p", { class: "empty", text: "Personne n'a encore publié." })),
        card("Instruments visés", barList(C.instruments, { color: "c7" })),
        card("Étiquettes", barList(C.tags)),
        card("Licences", barList(C.licenses, { color: "c3" })),
        card("Sources déclarées", barList(C.sources, { color: "c2" })),
        card("Imports par lien", barList(B.imports, { color: "c2", empty: "Aucun import sur la période." })),
        card("Durée des morceaux", columns(C.durations)),
        card("Nombre de notes", columns(C.note_counts, { cls: "s7" })),
        card("Modération", kv([["Contenus examinés", n(M.reviewed)], ["Taux de validation", M.approval_rate === null ? "—" : `${NF1.format(M.approval_rate)} %`],
          ["Délai médian", M.median_delay_h === null ? "—" : `${NF1.format(M.median_delay_h)} h`], ["Délai 90e centile", M.p90_delay_h === null ? "—" : `${NF1.format(M.p90_delay_h)} h`],
          ["Signalements traités", M.report_outcomes.length ? M.report_outcomes.map((x) => `${x.label} : ${x.value}`).join(" · ") : "—"]])),
      ));
  };

  VIEWS.live = async () => {
    const [lv, d] = await Promise.all([api("/api/admin/live"), getStats(state.days)]);
    const wrap = h("div");
    const render = (lv) => {
      const S = d.series, L = d.days;
      const players = sum(lv.rooms.map((r) => r.players.filter((p) => p.connected).length));
      const lat = lv.latency || {};
      const st = lv.storage, disk = st.disk;
      const meter = (used, total) => { const m = h("div", { class: `meter${used / total > 0.85 ? " hot" : ""}` }, h("span")); m.firstChild.style.width = `${Math.min(100, (used * 100) / total)}%`; return m; };
      const liveLabels = lv.live.map((x) => x.t);
      wrap.replaceChildren(
        h("div", { class: "tiles" },
          tile("Salons ouverts", lv.rooms.length, { sub: `${lv.rooms.filter((r) => r.state !== "lobby").length} en partie` }),
          tile("Joueurs connectés", players),
          tile("Temps de réponse (médiane)", lat.p50 === null || lat.p50 === undefined ? "—" : `${NF1.format(lat.p50)} ms`, { sub: lat.count ? `p95 ${NF1.format(lat.p95)} ms · p99 ${NF1.format(lat.p99)} ms · ${n(lat.count)} req. / 15 min` : "" }),
          tile("Erreurs 5xx (15 min)", lat.errors || 0, { alert: (lat.errors || 0) > 0 }),
          tile("En ligne depuis", duration(lv.server.uptime_s), { sub: `serveur ${lv.server.version} · ${lv.server.db}` }),
          tile("Sessions ouvertes", lv.sessions.app + lv.sessions.web, { sub: `${n(lv.sessions.app)} app · ${n(lv.sessions.web)} site` }),
        ),
        h("div", { class: "grid g2" },
          card("Dernières 24 h (minute par minute)", lv.live.length > 1 ? lineChart({ labels: liveLabels, series: [{ name: "Joueurs", values: lv.live.map((x) => x.players), cls: "s1" }, { name: "Salons", values: lv.live.map((x) => x.rooms), cls: "s3" }],
            labelFmt: (t) => t.replace("T", " "), tickFmt: (t) => t.slice(11) }) : h("p", { class: "empty", text: "Les mesures démarrent une minute après le lancement du serveur." }), { sub: "mémoire du serveur, remis à zéro au redémarrage" }),
          card("Requêtes par minute (24 h)", lv.live.length > 1 ? lineChart({ labels: liveLabels, series: [{ name: "Requêtes / min", values: lv.live.map((x) => x.requests), cls: "s7", area: true }], labelFmt: (t) => t.replace("T", " "), tickFmt: (t) => t.slice(11) }) : h("p", { class: "empty", text: "—" })),
          card("Salons par jour", h("div", {}, lineChart({ labels: L, series: [{ name: "Salons créés", values: S.room_create, cls: "s3" }, { name: "Parties lancées", values: S.room_start, cls: "s1" }, { name: "Pic de joueurs", values: S.peak_players, cls: "s5" }] }),
            dataTable(L, [{ name: "Salons créés", values: S.room_create }, { name: "Parties", values: S.room_start }, { name: "Pic joueurs", values: S.peak_players }, { name: "Pic salons", values: S.peak_rooms }]))),
          card("Joueurs par partie", columns(d.breakdowns.room_sizes, { cls: "s5" })),
          card("Salons en cours", lv.rooms.length ? h("div", { class: "rooms" }, lv.rooms.map((r) => h("div", { class: "card" },
            h("div", { class: "room-code", text: r.code }),
            h("div", { class: "small muted", text: `${{ lobby: "Salle d'attente", countdown: "Compte à rebours", playing: "En partie" }[r.state] || r.state} · ${r.players.length}/${r.max_players} · ouvert ${duration(r.age_s)}` }),
            r.song ? h("div", { class: "small" }, "♪ ", r.song) : null,
            h("ul", { class: "players" }, r.players.map((p) => h("li", {}, h("span", { class: p.connected ? "dot-on" : "dot-off", title: p.connected ? "connecté" : "déconnecté" }),
              h("span", { text: p.name }), p.host ? h("span", { class: "pill admin", text: "chef" }) : null, h("span", { class: "small muted", text: `${p.instrument || ""} ${p.version ? "· v" + p.version : ""}` })))))))
            : h("p", { class: "empty", text: "Aucun salon ouvert en ce moment." }), { cls: "span2", sub: "actualisé toutes les 15 s" }),
          card("Stockage", h("div", {},
            disk ? h("div", {}, h("div", { class: "small", text: `Disque : ${bytes(disk.used)} utilisés sur ${bytes(disk.total)} (${bytes(disk.free)} libres)` }), meter(disk.used, disk.total)) : null,
            kv([["Base de données", bytes(st.db_bytes)], ...Object.entries(st.folders).map(([k, v]) => [k, `${bytes(v.bytes)} · ${n(v.files)} fichier(s)`])]))),
          card("Serveur", kv([["Version", lv.server.version], ["Python", lv.server.python], ["Système", lv.server.platform], ["Base", lv.server.db],
            ["Client minimum", lv.server.min_client], ["Adresse publique", lv.server.public_url], ["Limitation de débit", lv.server.rate_limit ? "active" : "désactivée"],
            ["IndexNow", lv.server.indexnow ? "actif" : "—"], ["Annonces des versions", lv.server.announce_webhook ? "webhook configuré" : "—"], ["File de notifications", n(lv.server.notify_queue)]])),
          card("Erreurs serveur par jour", h("div", {}, lineChart({ labels: L, series: [{ name: "5xx", values: S.http_5xx, cls: "s8" }, { name: "4xx (hors 404)", values: S.http_4xx, cls: "s4" }] }))),
          card("Dernières erreurs 5xx", lv.errors.length ? h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {}, lv.errors.map((e) => h("tr", {}, h("td", { class: "small", text: dt(e.at) }), h("td", { text: `${e.method} ${e.path}` }), h("td", { class: "r", text: e.status })))))) : h("p", { class: "empty", text: "Aucune erreur depuis le démarrage. 🎉" })),
        ));
    };
    render(lv);
    state.timers.push(setInterval(async () => { try { render(await api("/api/admin/live")); } catch { /* garde l'affichage */ } }, 15000));
    return wrap;
  };

  // --- modération ---
  const mod = { kind: "songs", status: "pending", page: 1 };
  VIEWS.moderation = async () => {
    const wrap = h("div");
    const kindSeg = h("div", { class: "seg", role: "group", "aria-label": "Type" });
    const statusSeg = h("div", { class: "seg", role: "group", "aria-label": "Statut" });
    const seg = (el, key, opts) => { el.replaceChildren(...opts.map(([v, lab]) => h("button", { type: "button", "aria-pressed": String(mod[key] === v), text: lab, onclick: () => { mod[key] = v; mod.page = 1; load(); } }))); };
    const list = h("div");
    async function load() {
      seg(kindSeg, "kind", [["songs", "Morceaux"], ["drawings", "Dessins"]]);
      seg(statusSeg, "status", [["pending", "En attente"], ["approved", "Publiés"], ["rejected", "Refusés"]]);
      list.classList.add("loading");
      try {
        const data = await api(`/api/admin/${mod.kind}?status=${mod.status}&page=${mod.page}&per_page=30`);
        list.replaceChildren(renderItems(data), pager(data, (p) => { mod.page = p; load(); }));
      } catch (e) { list.replaceChildren(h("div", { class: "notice bad", text: e.message })); }
      list.classList.remove("loading");
    }
    function act(item, action, reason) {
      return api(`/api/admin/${mod.kind}/${item.id}/${action}`, { method: "POST", body: action === "reject" ? { reason: reason || "" } : undefined })
        .then(() => { toast(action === "approve" ? "Publié ✔" : "Refusé"); refreshBadges(); state.statsCache.clear(); load(); })
        .catch((e) => toast(e.message, true));
    }
    function actions(item) {
      const box = h("div", { class: "actions" });
      const form = h("form", { class: "reject-form", hidden: true },
        h("input", { type: "text", name: "reason", maxlength: "500", placeholder: "Motif du refus (visible par l'auteur)", "aria-label": "Motif du refus" }),
        h("button", { class: "btn danger sm", type: "submit", text: "Confirmer le refus" }),
        h("button", { class: "btn sm", type: "button", text: "Annuler", onclick: () => { form.hidden = true; } }));
      form.addEventListener("submit", (e) => { e.preventDefault(); act(item, "reject", form.reason.value); });
      if (item.status !== "approved") box.append(h("button", { class: "btn primary sm", type: "button", text: "Publier", onclick: () => act(item, "approve") }));
      if (item.status !== "rejected") box.append(h("button", { class: "btn danger sm", type: "button", text: "Refuser…", onclick: () => { form.hidden = false; form.reason.focus(); } }));
      return [box, form];
    }
    function renderItems(data) {
      if (!data.items.length) return h("div", { class: "card" }, h("p", { class: "empty", text: mod.status === "pending" ? "Rien à modérer. Tout est à jour ✨" : "Aucun élément." }));
      if (mod.kind === "drawings") {
        return h("div", { class: "draw-grid" }, data.items.map((it) => {
          const [box, form] = actions(it);
          return h("div", { class: "card draw-card" },
            h("a", { href: it.image_url, target: "_blank", rel: "noopener" }, h("img", { src: it.thumb_url, alt: it.title, loading: "lazy" })),
            h("h3", { text: it.title }),
            h("div", { class: "small muted" }, `${it.w}×${it.h} · `, h("a", { href: `#user/${it.uploader_id}`, text: it.uploader_name || "?" }), ` · ${ago(it.created_at)}`, it.has_cells ? " · grille incluse" : ""),
            it.reject_reason ? h("div", { class: "small", text: `Motif : ${it.reject_reason}` }) : null,
            statusPill(it.status), box, form);
        }));
      }
      return h("div", { class: "mod-list" }, data.items.map((it) => {
        const [box, form] = actions(it);
        const mins = Math.floor(it.duration_s / 60), secs = Math.round(it.duration_s % 60);
        return h("div", { class: "card mod-item" },
          h("div", {},
            h("h3", {}, it.title, it.artist ? h("span", { class: "muted", text: ` — ${it.artist}` }) : null),
            h("div", { class: "meta" },
              h("span", {}, "par ", h("a", { href: `#user/${it.uploader_id}`, text: it.uploader_name || "?" })),
              h("span", { text: `${mins} min ${String(secs).padStart(2, "0")}` }), h("span", { text: `${n(it.note_count)} notes` }),
              h("span", { text: bytes(it.size) }), it.instrument ? h("span", { text: `🎵 ${it.instrument}` }) : null,
              h("span", { text: `licence : ${it.license}` }), (it.tags || []).length ? h("span", { text: `#${it.tags.join(" #")}` }) : null,
              it.source_url ? h("a", { href: it.source_url, target: "_blank", rel: "noopener noreferrer", text: it.source_name || "source" }) : null,
              h("span", { text: ago(it.created_at), title: dt(it.created_at) }), statusPill(it.status),
              it.status === "approved" ? h("span", { text: `${n(it.downloads)} téléch. · ${n(it.likes)} ♥` }) : null),
            it.reject_reason ? h("div", { class: "small", text: `Motif : ${it.reject_reason}` }) : null,
            h("div", { class: "small muted", text: `Fichier : ${it.original_name || "—"}` })),
          h("div", { class: "actions" }, h("a", { class: "btn sm", href: `/api/songs/${it.id}/download`, text: "Télécharger le .mid" }), box),
          form);
      }));
    }
    wrap.append(h("div", { class: "filters" }, kindSeg, statusSeg), list);
    await load();
    return wrap;
  };

  function pager(data, go) {
    if (!data.pages || data.pages <= 1) return h("div", { class: "pager small muted", text: `${n(data.total)} élément(s)` });
    return h("div", { class: "pager" }, h("span", { class: "small muted", text: `${n(data.total)} élément(s) · page ${data.page}/${data.pages}` }),
      h("button", { class: "btn sm", type: "button", text: "← Précédente", disabled: data.page <= 1, onclick: () => go(data.page - 1) }),
      h("button", { class: "btn sm", type: "button", text: "Suivante →", disabled: data.page >= data.pages, onclick: () => go(data.page + 1) }));
  }

  // --- signalements ---
  let reportsOpen = 1;
  VIEWS.reports = async () => {
    const data = await api(`/api/admin/reports?open=${reportsOpen}`);
    const seg = h("div", { class: "seg", role: "group" }, [[1, "Ouverts"], [0, "Tous"]].map(([v, lab]) =>
      h("button", { type: "button", "aria-pressed": String(reportsOpen === v), text: lab, onclick: () => { reportsOpen = v; route(); } })));
    const resolve = (r, action) => api(`/api/admin/reports/${r.id}/resolve`, { method: "POST", body: { action } })
      .then(() => { toast(action === "dismiss" ? "Signalement classé" : "Contenu supprimé"); refreshBadges(); route(); }).catch((e) => toast(e.message, true));
    const rows = data.items.map((r) => {
      const target = r.target_type === "drawing" ? h("a", { href: `/api/drawings/${r.target_id}.png`, target: "_blank", rel: "noopener", text: r.target_title || `dessin #${r.target_id}` })
        : r.target_id ? h("a", { href: `/api/songs/${r.target_id}/download`, text: r.target_title || `morceau #${r.target_id}` }) : h("span", { class: "muted", text: "(supprimé)" });
      return h("tr", {},
        h("td", {}, h("span", { class: "pill", text: r.target_type === "drawing" ? "dessin" : "morceau" }), " ", target, r.target_status ? h("span", {}, " ", statusPill(r.target_status)) : null),
        h("td", { text: r.reason }), h("td", {}, h("a", { href: `#user/${r.reporter_id}`, text: r.reporter_name })),
        h("td", { class: "small", text: ago(r.created_at), title: dt(r.created_at) }),
        h("td", {}, r.resolved_at ? h("span", { class: "pill", text: r.resolution || "traité" }) : h("div", { class: "actions" },
          h("button", { class: "btn sm", type: "button", text: "Classer", onclick: () => resolve(r, "dismiss") }),
          r.target_id ? h("button", { class: "btn danger sm", type: "button", text: "Supprimer le contenu", onclick: (e) => {
            const b = e.currentTarget; if (b.dataset.armed) return resolve(r, "remove_target"); b.dataset.armed = "1"; b.textContent = "Confirmer la suppression"; } }) : null)));
    });
    return h("div", {}, h("div", { class: "filters" }, seg),
      h("div", { class: "card" }, rows.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Contenu", "Motif", "Signalé par", "Quand", ""].map((t) => h("th", { text: t })))), h("tbody", {}, rows)))
        : h("p", { class: "empty", text: "Aucun signalement ouvert. 👍" })));
  };

  // --- rapports de diagnostic (bouton « Envoyer un rapport » de l'app : journaux + captures dans un zip) ---
  VIEWS.diag = async (arg) => {
    if (arg) {
      const d = await api(`/api/admin/diag-reports/${encodeURIComponent(arg)}/files`);
      const r = d.report;
      const del = h("button", { class: "btn danger sm", type: "button", text: "Supprimer", onclick: (e) => {
        const b = e.currentTarget; if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "Confirmer la suppression"; return; }
        api(`/api/admin/diag-reports/${encodeURIComponent(r.code)}`, { method: "DELETE" }).then(() => { toast("Rapport supprimé"); location.hash = "#diag"; }).catch((err) => toast(err.message, true)); } });
      return h("div", {},
        h("div", { class: "filters" }, h("a", { class: "btn sm", href: "#diag", text: "← Tous les rapports" }),
          h("a", { class: "btn sm", href: `/api/admin/diag-reports/${encodeURIComponent(r.code)}`, text: "Télécharger le zip" }), del),
        card(`Rapport ${r.code}`, kv([["Reçu", dt(r.created_at)], ["Compte", r.user_id ? h("a", { href: `#user/${r.user_id}`, text: r.username || `#${r.user_id}` }) : "sans compte"],
          ["Version", r.version || "—"], ["Système", r.os || "—"], ["Taille", bytes(r.size)], ["Description", r.note || "—"]])),
        card("Contenu", h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", { text: "Fichier" }), h("th", { class: "r", text: "Taille" }))),
          h("tbody", {}, d.files.map((f) => h("tr", {}, h("td", { class: "num", text: f.name }), h("td", { class: "r", text: bytes(f.size) }))))))));
    }
    const data = await api("/api/admin/diag-reports");
    const rows = data.items.map((r) => h("tr", {},
      h("td", {}, h("a", { class: "num", href: `#diag/${r.code}`, text: r.code })),
      h("td", { text: r.note ? (r.note.length > 90 ? r.note.slice(0, 90) + "…" : r.note) : "—" }),
      h("td", {}, r.user_id ? h("a", { href: `#user/${r.user_id}`, text: r.username || `#${r.user_id}` }) : h("span", { class: "muted", text: "sans compte" })),
      h("td", { class: "small", text: r.version || "—" }), h("td", { class: "r small", text: bytes(r.size) }),
      h("td", { class: "small", text: ago(r.created_at), title: dt(r.created_at) })));
    return h("div", {}, h("p", { class: "small muted", text: `Les rapports sont effacés au bout de ${n(data.ttl_days)} jours. Le joueur te donne le code affiché par l'app.` }),
      h("div", { class: "card" }, rows.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Code", "Description", "Compte", "Version", "Taille", "Reçu"].map((t, i) => h("th", { class: i === 4 ? "r" : null, text: t })))), h("tbody", {}, rows)))
        : h("p", { class: "empty", text: "Aucun rapport reçu." })));
  };

  // --- comptes ---
  const uq = { q: "", filter: "all", sort: "recent", page: 1 };
  VIEWS.users = async () => {
    const wrap = h("div");
    const search = h("input", { type: "search", placeholder: "Pseudo ou ID Discord", value: uq.q, "aria-label": "Rechercher un compte" });
    let deb;
    search.addEventListener("input", () => { clearTimeout(deb); deb = setTimeout(() => { uq.q = search.value; uq.page = 1; load(); }, 250); });
    const filter = h("select", { "aria-label": "Filtre", onchange: (e) => { uq.filter = e.target.value; uq.page = 1; load(); } },
      [["all", "Tous"], ["active", "Actifs (7 j)"], ["uploaders", "Contributeurs"], ["admins", "Admins"], ["banned", "Bannis"]].map(([v, l]) => h("option", { value: v, text: l, selected: uq.filter === v })));
    const sort = h("select", { "aria-label": "Tri", onchange: (e) => { uq.sort = e.target.value; load(); } },
      [["recent", "Plus récents"], ["seen", "Vus récemment"], ["content", "Plus de contenus"], ["name", "Nom"]].map(([v, l]) => h("option", { value: v, text: l, selected: uq.sort === v })));
    const table = h("div", { class: "card" });
    async function load() {
      table.classList.add("loading");
      try {
        const d = await api(`/api/admin/users?q=${encodeURIComponent(uq.q)}&filter=${uq.filter}&sort=${uq.sort}&page=${uq.page}`);
        table.replaceChildren(d.items.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Compte", "ID Discord", "Inscrit", "Vu", "Morceaux", "Dessins", "Likes", ""].map((t, i) => h("th", { class: i >= 4 && i <= 6 ? "r" : null, text: t })))),
          h("tbody", {}, d.items.map((u) => h("tr", {},
            h("td", {}, h("a", { href: `#user/${u.id}` }, who(u))), h("td", { class: "small muted num", text: u.discord_id }),
            h("td", { class: "small", text: ago(u.created_at), title: dt(u.created_at) }), h("td", { class: "small", text: ago(u.last_seen_at), title: dt(u.last_seen_at) }),
            h("td", { class: "r", text: n(u.songs) }), h("td", { class: "r", text: n(u.drawings) }), h("td", { class: "r", text: n(u.likes_given) }),
            h("td", {}, u.is_admin ? h("span", { class: "pill admin", text: "admin" }) : null, u.banned ? h("span", { class: "pill bad", text: "banni" }) : null))))))
          : h("p", { class: "empty", text: "Aucun compte ne correspond." }), pager(d, (p) => { uq.page = p; load(); }));
      } catch (e) { table.replaceChildren(h("div", { class: "notice bad", text: e.message })); }
      table.classList.remove("loading");
    }
    wrap.append(h("div", { class: "filters" }, search, filter, sort), table);
    await load();
    return wrap;
  };

  VIEWS.user = async (id) => {
    const d = await api(`/api/admin/users/${encodeURIComponent(id)}`);
    const u = d.user;
    const post = (path, msg) => api(path, { method: "POST" }).then(() => { toast(msg); route(); }).catch((e) => toast(e.message, true));
    const confirmBtn = (label, cls, fn) => h("button", { class: `btn sm ${cls}`, type: "button", text: label, onclick: (e) => {
      const b = e.currentTarget; if (b.dataset.armed) return fn(); b.dataset.armed = "1"; b.textContent = `Confirmer : ${label.toLowerCase()}`; } });
    const actions = h("div", { class: "actions" },
      !u.is_admin && !u.banned ? confirmBtn("Bannir", "danger", () => post(`/api/admin/users/${u.id}/ban`, "Compte banni")) : null,
      u.banned ? h("button", { class: "btn sm", type: "button", text: "Débannir", onclick: () => post(`/api/admin/users/${u.id}/unban`, "Compte débanni") }) : null,
      d.sessions.length ? confirmBtn("Déconnecter partout", "", () => post(`/api/admin/users/${u.id}/revoke`, "Sessions révoquées")) : null);
    const table = (rows, cols) => rows.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c[2] || null, text: c[0] })))),
      h("tbody", {}, rows.map((r) => h("tr", {}, cols.map((c) => { const v = c[1](r); return h("td", { class: c[2] || null }, v instanceof Node ? v : String(v ?? "—")); })))))) : h("p", { class: "empty", text: "Rien." });
    return h("div", {},
      h("p", {}, h("a", { href: "#users", text: "← Tous les comptes" })),
      h("div", { class: "grid g2" },
        card(u.username, h("div", {}, h("div", { class: "who" }, u.avatar_url ? h("img", { src: u.avatar_url, alt: "", referrerpolicy: "no-referrer" }) : null,
          u.is_admin ? h("span", { class: "pill admin", text: "admin" }) : null, u.banned ? h("span", { class: "pill bad", text: "banni" }) : null),
          kv([["N°", u.id], ["ID Discord", u.discord_id], ["Inscrit", dt(u.created_at)], ["Vu", `${ago(u.last_seen_at)} (${dt(u.last_seen_at)})`],
            ["Morceaux", n(u.songs)], ["Dessins", n(u.drawings)], ["Likes donnés", n(u.likes_given)], ["Signalements faits", n(u.reports_made)]]), actions)),
        card("Sessions ouvertes", table(d.sessions, [["Type", (r) => (r.kind === "web" ? "site (admin)" : "app")], ["Ouverte", (r) => dt(r.created_at)], ["Dernier usage", (r) => ago(r.last_used_at)], ["Expire", (r) => dt(r.expires_at)]])),
        card("Morceaux", table(d.songs, [["Titre", (r) => h("a", { href: `/api/songs/${r.id}/download`, text: r.title })], ["Statut", (r) => statusPill(r.status)], ["Téléch.", (r) => n(r.downloads), "r"], ["♥", (r) => n(r.likes), "r"], ["Déposé", (r) => ago(r.created_at)]]), { cls: "span2" }),
        card("Dessins", table(d.drawings, [["Titre", (r) => h("a", { href: `/api/drawings/${r.id}.png`, target: "_blank", rel: "noopener", text: r.title })], ["Taille", (r) => `${r.w}×${r.h}`], ["Statut", (r) => statusPill(r.status)], ["♥", (r) => n(r.likes), "r"], ["Déposé", (r) => ago(r.created_at)]])),
        card("Signalements faits", table(d.reports, [["Cible", (r) => `${r.target_type} #${r.song_id || r.drawing_id || "?"}`], ["Motif", (r) => r.reason], ["Issue", (r) => r.resolution || "ouvert"], ["Quand", (r) => ago(r.created_at)]])),
      ));
  };

  // --- versions ---
  VIEWS.releases = async () => {
    const d = await api("/api/admin/releases-stats");
    if (!d.items.length) return h("div", { class: "card" }, h("p", { class: "empty", text: "Aucune version publiée." }));
    const pub = d.items.filter((r) => r.published_at);
    return h("div", {},
      h("div", { class: "grid g2" },
        card("Téléchargements par version", columns(pub.slice(0, 12).reverse().map((r) => ({ label: r.version, value: r.downloads })), { cls: "s2" }), { cls: "span2" })),
      h("div", { class: "section-title" }),
      h("div", { class: "mod-list" }, d.items.map((r) => card(`DodoTopia ${r.version}`, h("div", {},
        h("p", { class: "small muted" }, r.published_at ? `Publiée ${dt(r.published_at)}` : "Non publiée", r.mandatory ? " · obligatoire" : "", r.announced_at ? " · annoncée sur Discord" : ""),
        r.assets.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Plateforme" }), h("th", { text: "Fichier" }), h("th", { class: "r", text: "Taille" }), h("th", { class: "r", text: "Téléchargements" }))),
          h("tbody", {}, r.assets.map((a) => h("tr", {}, h("td", { text: a.platform }), h("td", { class: "small", text: a.filename }), h("td", { class: "r", text: bytes(a.size) }), h("td", { class: "r", text: n(a.downloads) })))))) : null,
        r.notes ? h("details", {}, h("summary", { class: "small muted", text: "Notes de version" }), h("p", { class: "small", text: r.notes })) : null),
        { sub: `${n(r.downloads)} téléchargements` }))));
  };

  // --- journal ---
  let logPage = 1;
  VIEWS.log = async () => {
    const d = await api(`/api/admin/log?page=${logPage}`);
    return h("div", { class: "card" }, d.items.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Quand", "Admin", "Action", "Cible", "Détail"].map((t) => h("th", { text: t })))),
      h("tbody", {}, d.items.map((r) => h("tr", {}, h("td", { class: "small", text: dt(r.created_at) }), h("td", {}, r.admin_id ? h("a", { href: `#user/${r.admin_id}`, text: r.admin_name || "?" }) : (r.admin_name || "?")),
        h("td", { text: r.label }), h("td", { text: r.target || "" }), h("td", { class: "small muted", text: r.detail || "" }))))))
      : h("p", { class: "empty", text: "Aucune action enregistrée pour l'instant." }), pager(d, (p) => { logPage = p; route(); }));
  };

  // --- réglages ---
  VIEWS.settings = async () => {
    const cfg = await api("/api/admin/settings");
    const url = h("input", { type: "url", name: "webhook", placeholder: "https://discord.com/api/webhooks/…", autocomplete: "off", spellcheck: "false", "aria-label": "URL du webhook Discord" });
    url.style.width = "100%";
    const mention = h("input", { type: "text", inputmode: "numeric", value: cfg.mention || "", placeholder: "ID du rôle (facultatif)", "aria-label": "ID du rôle à mentionner" });
    const save = (body, msg) => api("/api/admin/settings", { method: "PUT", body }).then(() => { toast(msg); route(); }).catch((e) => toast(e.message, true));
    const status = cfg.webhook_set
      ? h("div", { class: "notice" }, "Webhook actif : ", h("code", { text: cfg.webhook_masked }), cfg.source === "env" ? " (variable DISCORD_ADMIN_WEBHOOK du serveur)" : " (enregistré ici)")
      : h("div", { class: "notice bad" }, "Aucun webhook : les notifications sont désactivées.");
    const events = h("div", {}, cfg.events.map((ev) => h("label", { class: "check" }, h("input", { type: "checkbox", name: ev.id, checked: ev.enabled }), ev.label)));
    return h("div", { class: "grid g2" },
      card("Webhook Discord", h("div", {},
        h("p", { class: "small muted" }, "Dans Discord : Paramètres du salon → Intégrations → Webhooks → Nouveau webhook → Copier l'URL. Colle-la ici : l'URL complète n'est plus jamais réaffichée."),
        status, h("div", { class: "sep" }), h("p", {}, url),
        h("div", { class: "actions" },
          h("button", { class: "btn primary", type: "button", text: "Enregistrer l'URL", onclick: () => { if (!url.value.trim()) return toast("Colle d'abord l'URL du webhook.", true); save({ webhook_url: url.value.trim() }, "Webhook enregistré"); } }),
          h("button", { class: "btn", type: "button", text: "Envoyer un test", disabled: !cfg.webhook_set, onclick: () => api("/api/admin/settings/test", { method: "POST" }).then(() => toast("Message de test envoyé ✔")).catch((e) => toast(e.message, true)) }),
          cfg.source === "site" ? h("button", { class: "btn danger", type: "button", text: "Retirer", onclick: () => save({ webhook_url: "" }, "Webhook retiré") }) : null),
        h("p", { class: "small muted", text: `Envoyés depuis le démarrage : ${n(cfg.delivery.sent)} · échecs : ${n(cfg.delivery.failed)}${cfg.delivery.last_failure ? " · dernier échec : " + cfg.delivery.last_failure : ""}` }))),
      card("Que notifier ?", h("div", {}, events,
        h("p", { class: "small muted", text: "Mention d'un rôle Discord pour ce qui demande une action (modération, signalements, erreurs) :" }), h("p", {}, mention),
        h("button", { class: "btn primary", type: "button", text: "Enregistrer", onclick: () => {
          const chosen = {}; events.querySelectorAll("input").forEach((i) => { chosen[i.name] = i.checked; });
          save({ events: chosen, mention: mention.value.trim() }, "Préférences enregistrées");
        } }))),
      card("Accès", h("div", {}, h("p", { class: "small muted", text: "Les administrateurs sont les comptes Discord listés dans la variable ADMIN_DISCORD_IDS du serveur (Dokploy). Connexion au site : 7 jours, prolongés à chaque visite." }),
        h("ul", {}, cfg.admins.map((id) => h("li", { class: "num", text: id }))))),
      card("Statistiques", h("p", { class: "small muted", text: "Les compteurs sont gardés en mémoire et écrits en base chaque minute. Le résumé quotidien part à 9 h (heure de Paris) avec les chiffres de la veille. Aucun cookie n'est déposé chez les visiteurs du site." })),
    );
  };

  window.addEventListener("hashchange", route);
  route();
  refreshBadges();
  setInterval(refreshBadges, 60000);
})();
