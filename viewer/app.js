/* Rule explorer: draws precomputed engine replays (viewer/data, written by viewer/build_data.py). No computation of
   rules happens here: a combination is a set of rule choices, and a line is the replay that was run with them. */
"use strict";
(function () {
  // colour slots of the saved combinations; the first two are the paper's (orange = today's rules, blue = the proposal)
  const PALETTE = ["#E8683A", "#2F74D0", "#17996A", "#8E5BD0", "#C9457F", "#B8860B", "#1291A6"];
  const DASH = [[], [7, 3], [2, 3], [9, 3, 2, 3], [4, 4], [12, 4], [2, 2, 6, 2]];
  const FIXED = { today: 0, proposal: 1 };
  const REF = "#77776F", MUTE = "#6b6b6b", GRID = "#e9e7e2";
  const STORE = "rule-explorer.v1";
  const S = { idx: null, runs: {}, test: null, tab: "mark", saved: [], votes: null, plots: [], xr: null, sync: false };
  const $ = (id) => document.getElementById(id);
  const el = (tag, props, kids) => { const e = Object.assign(document.createElement(tag), props || {}); (kids || []).forEach((k) => e.append(k)); return e; };

  window.BS = {
    index(d) { S.idx = d; start(); },
    run(test, combo, d) {
      d.x = d.t.map((s) => s / 60); if (d.t_lift) d.xl = d.t_lift.map((s) => s / 60);   // minutes from time zero
      S.runs[test + "/" + combo] = d;
    },
  };

  // ---- data ------------------------------------------------------------------------------------------------------
  const combo = (id) => S.idx.combos.find((c) => c.id === id);
  const test = () => S.idx.tests.find((t) => t.id === S.test);
  const has = (id) => test().combos.includes(id);
  function load(testId, comboId) {
    const k = testId + "/" + comboId;
    if (S.runs[k]) return Promise.resolve(S.runs[k]);
    return new Promise((ok, fail) => {
      const s = el("script", { src: `data/${testId}/${comboId}.js?v=${S.idx.commit}` });   // a rebuild changes the url, so no stale cache
      s.onload = () => (S.runs[k] ? ok(S.runs[k]) : fail(new Error("empty file " + s.src)));
      s.onerror = () => fail(new Error("could not load " + s.src));
      document.head.append(s);
    });
  }
  function label(c) {
    if (c.name) return c.name;
    // a custom combination: the frozen one it starts from, then what it changes
    const base = combo(c.mark === "today" ? "today" : "proposal");
    return [base.name].concat(S.idx.axes.filter((a) => c[a.key] !== base[a.key]).map((a) => a.values[c[a.key]].short)).join(" · ");
  }

  // ---- saved combinations ----------------------------------------------------------------------------------------
  function restore() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(STORE)); } catch (e) { /* storage unavailable: defaults */ }
    if (!Array.isArray(saved) || !saved.length) saved = [{ id: "today", on: true }, { id: "proposal", on: true }];
    S.saved = [];
    saved.forEach((s) => { if (combo(s.id)) add(s.id, s.on !== false, false); });
  }
  function persist() {
    try { localStorage.setItem(STORE, JSON.stringify(S.saved.map((s) => ({ id: s.id, on: s.on })))); } catch (e) { /* not saved */ }
  }
  function freeSlot(id) {
    if (id in FIXED) return FIXED[id];
    const used = new Set(S.saved.map((s) => s.slot));
    for (let i = 2; i < PALETTE.length; i++) if (!used.has(i)) return i;
    return -1;
  }
  function add(id, on, save) {
    if (S.saved.some((s) => s.id === id)) return false;
    const slot = freeSlot(id);
    if (slot < 0) return false;
    S.saved.push({ id, on, slot });
    if (save !== false) persist();
    return true;
  }
  const shown = () => S.saved.filter((s) => s.on && has(s.id));

  // ---- controls --------------------------------------------------------------------------------------------------
  function start() {
    const sel = $("test"); let group = null, og = null;
    S.idx.tests.forEach((t) => {
      if (t.group !== group) { group = t.group; og = el("optgroup", { label: group }); sel.append(og); }
      og.append(el("option", { value: t.id, textContent: t.title }));
    });
    S.test = S.idx.tests[0].id;
    sel.onchange = () => { S.test = sel.value; S.xr = null; render(); };
    restore();
    S.pick = Object.assign({}, combo("proposal") || S.idx.combos[0]);
    $("mark-pick").replaceChildren(...Object.entries(S.idx.axes.find((a) => a.key === "mark").values).map(([v, o]) => el("option", { value: v, textContent: o.label })));
    $("mark-pick").onchange = () => choose("mark", $("mark-pick").value);
    $("sheet").addEventListener("click", (e) => {
      const opt = e.target.closest(".opt"), chip = e.target.closest(".slot");
      if (opt && !opt.disabled) { S.open = null; choose(opt.dataset.slot, opt.dataset.value); }
      else if (chip) { S.open = S.open === chip.dataset.slot ? null : chip.dataset.slot; refreshBuilder(); }
    });
    refreshBuilder();
    $("builder").onsubmit = (e) => { e.preventDefault(); const c = picked(); if (c && add(c.id, true)) { refreshBuilder(); render(); } };
    $("votes-combo").onchange = () => { S.votes = $("votes-combo").value; render(); };
    let timer = null;
    window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => S.plots.forEach((p) => p.setSize({ width: $("panels").clientWidth, height: p.height })), 120); });
    render();
  }

  // ---- the formula sheet -----------------------------------------------------------------------------------------
  // The formulas of the rules being picked, written out. A highlighted term is a choice: clicking it lists the versions
  // that were replayed. SLOT: the choosable terms (rule axis -> TeX of each value); SHEET: the lines of each mark formula.
  const T = String.raw;
  const SLOT = {
    tau: { title: "Averaging time", tex: { 300: T`\tau = 5\ \text{min}`, 1800: T`\tau = 30\ \text{min}`, 7200: T`\tau = 2\ \text{h}` } },
    anchor: { title: "Correction step: is the anchor pulled back toward the mark?", tex: {
      none: T`A_t = \tilde A_t`,
      book: T`A_t = \tilde A_t \ \text{ if } B_{t-1} \text{ was between } V_{t-1} \text{ and } A_{t-1}, \ \text{ else } \operatorname{clip}\big(\tilde A_t,\ [V_t,\ M_{t-1}]\big)`,
      always: T`A_t = \operatorname{clip}\big(\tilde A_t,\ [V_t,\ M_{t-1}]\big)` } },
    sizing: { title: "Size of a liquidation", tex: {
      slices: T`\text{a first order for } 20\%\ \text{of } |q|, \ \text{then full size during a 30 s cooldown}`,
      cutback: T`\Delta q = \Big(1 - \dfrac{\text{equity}}{\text{IM}}\Big)\,|q| \ \text{ at every update}` } },
  };
  const MARK = T`M_t = \operatorname{clip}\big(\operatorname{med}(X^1_t,\ X^2_t,\ B_t),\ M_{t-1}(1 \pm 1\%)\big)`;
  const CAPPED = T`O_t = O_{t-1} + \big(1 - e^{-\Delta t / 30\,\text{min}}\big)\,\operatorname{clip}\big(\text{mid}_t - O_{t-1},\ \pm 1\%\,O_{t-1}\big)`;
  const LIQ = ["Liquidation", [T`\text{below maintenance margin, above \$100k:}\quad`, { slot: "sizing" }]];
  const SHEET = {
    today: [
      ["Oracle", [T`O_t = \mathcal{D}_t\big(\operatorname{clip}(E_t,\ O_{t-1}(1 \pm c))\big)`]],
      ["Input 1", [T`X^1_t = \mathcal{D}_t\big(\operatorname{clip}(O_t,\ M_{t-1}(1 \pm c))\big)`]],
      ["Input 2", [T`X^2_t = \mathcal{D}_t\big(\operatorname{clip}(E_t + e_t,\ \text{within } c \text{ of its last value and of } O_{t-1})\big)`]],
      ["Mark", [MARK]],
      ["Market closed", [T`O_t = O_{t-1} + \big(1 - e^{-\Delta t / 30\,\text{min}}\big)\,(\text{mid}_t - O_{t-1}) \quad \text{scheduled closures only}`]],
      LIQ,
    ],
    three: [
      ["Feed vote", [T`V_t = E_t \ \text{ if the feed is live, else } O_t`]],
      ["Anchor", [T`\tilde A_t = A_{t-1} + \big(1 - e^{-\Delta t / \tau}\big)\,(V_t - A_{t-1}), \quad`, { slot: "tau" }]],
      ["", [{ slot: "anchor" }]],
      ["Mark", [T`M_t = \operatorname{clip}\big(\operatorname{med}(V_t,\ A_t,\ B_t),\ M_{t-1}(1 \pm 1\%)\big)`]],
      ["Feed not live", [CAPPED]],
      LIQ,
    ],
  };
  const KEY = {
    today: T`E \text{ external price} \quad B \text{ xyz order book (median of bid, ask, last trade)} \quad c = 0.5\% \quad \mathcal{D}_t(x) = \operatorname{clip}\big(x,\ E_t(1 \pm 1/\text{maxLev})\big) \quad e_t \text{ 150 s average of mid} - E`,
    three: T`E \text{ external price} \quad B \text{ xyz order book (median of bid, ask, last trade)} \quad O \text{ internal price} \quad \text{live: venue open and } E \text{ changed in one of the last two updates}`,
  };
  const math = (tex) => { try { return katex.renderToString(tex, { output: "mathml", throwOnError: false }); } catch (e) { return "<code>" + tex.replace(/</g, "&lt;") + "</code>"; } };

  // the replayed combination with the picked rules, and with one rule changed
  const picked = () => S.idx.combos.find((c) => S.idx.axes.every((a) => c[a.key] === S.pick[a.key]));
  const withRule = (key, value) => {
    const same = (c, keys) => keys.every((k) => c[k] === S.pick[k]);
    const pool = S.idx.combos.filter((c) => c[key] === value);
    if (key !== "mark") return pool.find((c) => same(c, S.idx.axes.map((a) => a.key).filter((k) => k !== key)));
    return pool.find((c) => c.name) || pool[0];   // "Start from": the frozen combination itself
  };
  function choose(key, value) {
    const c = withRule(key, value);
    if (c) S.pick = Object.assign({}, c);
    S.open = null;
    refreshBuilder();
  }
  function refreshBuilder() {
    const lines = SHEET[S.pick.mark], frozen = combo(S.pick.mark === "today" ? "today" : "proposal");
    $("mark-pick").value = S.pick.mark;
    $("sheet").innerHTML = lines.map(([name, parts]) => {
      const eq = parts.map((p) => (typeof p === "string" ? math(p)
        : `<button type="button" class="slot${S.pick[p.slot] !== frozen[p.slot] ? " changed" : ""}" data-slot="${p.slot}" aria-expanded="${S.open === p.slot}" title="${SLOT[p.slot].title}: click to change">${math(SLOT[p.slot].tex[S.pick[p.slot]])}</button>`)).join("");
      const tray = parts.filter((p) => typeof p !== "string" && p.slot === S.open).map((p) => {
        const opts = Object.keys(SLOT[p.slot].tex).filter((v) => S.idx.combos.some((c) => c[p.slot] === v));
        return `<div class="tray" role="radiogroup" aria-label="${SLOT[p.slot].title}"><div class="tray-h">${SLOT[p.slot].title}</div>` + opts.map((v) => {
          const ok = v === S.pick[p.slot] || withRule(p.slot, v);
          return `<button type="button" class="opt" role="radio" aria-checked="${v === S.pick[p.slot]}" data-slot="${p.slot}" data-value="${v}"${ok ? "" : " disabled"}>${math(SLOT[p.slot].tex[v])}${ok ? "" : "<small>not replayed with the other choices</small>"}</button>`;
        }).join("") + "</div>";
      }).join("");
      return `<div class="line"><span class="what">${name}</span><div class="eq">${eq}</div></div>${tray}`;
    }).join("") + `<div class="key">${math(KEY[S.pick.mark])}</div>`;
    const c = picked(), n = c ? S.idx.tests.filter((t) => t.combos.includes(c.id)).length : 0;
    const dup = c && S.saved.some((s) => s.id === c.id), full = c && !dup && freeSlot(c.id) < 0;
    $("add").disabled = !c || dup || full;
    $("add").textContent = c ? `Add “${label(c)}”` : "Add";
    $("builder-note").textContent = !c ? "Not replayed." : dup ? "Already in your list."
      : full ? `${PALETTE.length} at most: remove one first.` : `Replayed in ${n} of ${S.idx.tests.length} tests.`;
  }

  function chips() {
    $("chips").replaceChildren(...S.saved.map((s) => {
      const c = combo(s.id), missing = !has(s.id);
      const sw = el("span", { className: "swatch" }); sw.style.borderTopColor = PALETTE[s.slot];
      if (DASH[s.slot].length) sw.style.borderTopStyle = "dashed";
      const name = el("button", { type: "button", className: "name", title: missing ? "Not replayed for this test" : s.on ? "Click to hide" : "Click to show" }, [sw, label(c)]);
      name.onclick = () => { s.on = !s.on; persist(); render(); };
      const rm = el("button", { type: "button", textContent: "✕", title: "Remove" }); rm.setAttribute("aria-label", "Remove " + label(c));
      rm.onclick = () => { S.saved = S.saved.filter((x) => x !== s); persist(); refreshBuilder(); render(); };
      return el("span", { className: "chip" + (s.on ? "" : " off") + (missing ? " missing" : "") }, [name, rm]);
    }));
  }

  // ---- tabs ------------------------------------------------------------------------------------------------------
  const TABS = { mark: "Mark", liq: "Liquidations", votes: "Inputs", table: "Figures" };
  function tabs() {
    $("tabs").replaceChildren(...Object.keys(TABS).map((k) => {
      const b = el("button", { type: "button", textContent: TABS[k] }); b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(k === S.tab));
      b.onclick = () => { S.tab = k; render(); };
      return b;
    }));
  }

  // ---- formats ---------------------------------------------------------------------------------------------------
  const pct = (v) => v.toFixed(2) + "%";
  const usdM = (v) => (Math.abs(v) >= 0.995 ? "$" + v.toFixed(2) + "M" : "$" + Math.round(v * 1000) + "k");
  const price = (lines) => { const m = Math.max(...lines.flatMap((l) => l.y).filter((v) => v != null)); const d = m >= 1000 ? 1 : m >= 10 ? 2 : 4; return (v) => v.toFixed(d); };

  // ---- charts ----------------------------------------------------------------------------------------------------
  function align(lines) {
    const a = lines[0].x, same = lines.every((l) => l.x.length === a.length && l.x[0] === a[0] && l.x[a.length - 1] === a[a.length - 1]);
    if (same) return [a].concat(lines.map((l) => l.y));
    const xs = Array.from(new Set(lines.flatMap((l) => l.x))).sort((p, q) => p - q), at = new Map(xs.map((v, i) => [v, i]));
    return [xs].concat(lines.map((l) => { const y = new Array(xs.length).fill(null); l.x.forEach((v, i) => { y[at.get(v)] = l.y[i]; }); return y; }));
  }
  function panel(title, lines, fmt, height) {
    const box = el("div", { className: "panel" }, [el("h2", { textContent: title })]);
    $("panels").append(box);
    if (!lines.length) { box.append(el("p", { className: "muted", textContent: "No combination to show: add one, or show a hidden one." })); return; }
    const font = "12px Arial, Helvetica, sans-serif";
    const series = [{ label: "Minute", value: (u, v) => (v == null ? "–" : v.toFixed(2)) }].concat(lines.map((l) => {
      const s = { label: l.label, stroke: l.color, width: l.width || 2, dash: l.dash, spanGaps: true, points: { show: false }, value: (u, v) => (v == null ? "–" : fmt(v)) };
      if (l.step) s.paths = uPlot.paths.stepped({ align: 1 });
      return s;
    }));
    const u = new uPlot({
      width: $("panels").clientWidth, height: height || 360, series,
      scales: { x: { time: false } }, cursor: { drag: { x: true, y: false } }, legend: { live: true },
      axes: [
        { stroke: MUTE, font, labelFont: font, grid: { show: false }, ticks: { stroke: GRID }, label: "Minutes from time zero", labelSize: 22 },
        { stroke: MUTE, font, grid: { stroke: GRID, width: 1 }, ticks: { show: false }, size: 68, values: (u, vals) => vals.map(fmt) },
      ],
      hooks: {
        draw: [(u) => {   // time zero
          const x = u.valToPos(0, "x", true), b = u.bbox;
          if (x < b.left || x > b.left + b.width) return;
          const c = u.ctx; c.save(); c.strokeStyle = "#b5b5b0"; c.lineWidth = devicePixelRatio; c.setLineDash([4 * devicePixelRatio, 4 * devicePixelRatio]);
          c.beginPath(); c.moveTo(x, b.top); c.lineTo(x, b.top + b.height); c.stroke(); c.restore();
        }],
        setScale: [(u, key) => {   // the same zoom on every panel, kept when the tab or the combinations change
          if (key !== "x" || S.sync) return;
          S.xr = [u.scales.x.min, u.scales.x.max]; S.sync = true;
          S.plots.forEach((p) => { if (p !== u) p.setScale("x", { min: S.xr[0], max: S.xr[1] }); });
          S.sync = false;
        }],
      },
    }, align(lines), box);
    S.plots.push(u);
    if (S.xr) { S.sync = true; u.setScale("x", { min: S.xr[0], max: S.xr[1] }); S.sync = false; }
  }
  const lineOf = (s, x, y, extra) => Object.assign({ label: label(combo(s.id)), color: PALETTE[s.slot], dash: DASH[s.slot], x, y }, extra || {});

  function draw(list, runs) {
    const t = test(), first = runs[0];
    const ref = first ? [{ label: "External price", color: REF, width: 1.2, x: first.x, y: first.E }] : [];
    if (S.tab === "mark") {
      const lines = ref.concat(list.map((s, i) => lineOf(s, runs[i].x, runs[i].M)));
      panel("Mark price (USD)", lines, lines.length ? price(lines) : pct, 330);
      if (t.has_base) panel("How far the attack moves the mark", list.map((s, i) => lineOf(s, runs[i].xl, runs[i].lift)), pct, 230);
      else panel("Mark above the external price", list.map((s, i) => lineOf(s, runs[i].x, runs[i].M.map((m, k) => (m == null || !runs[i].E[k] ? null : (m / runs[i].E[k] - 1) * 100)))), pct, 230);
    } else if (S.tab === "liq") {
      panel("Liquidated through the order book ($, running total)", list.map((s, i) => lineOf(s, runs[i].x, runs[i].book, { step: true })), usdM, 250);
      panel("Taken over by the vault ($, running total)", list.map((s, i) => lineOf(s, runs[i].x, runs[i].vault, { step: true })), usdM, 250);
    } else if (S.tab === "votes") {
      const avail = S.saved.filter((s) => has(s.id));
      if (!avail.some((s) => s.id === S.votes)) S.votes = avail.length ? avail[0].id : null;
      $("votes-combo").replaceChildren(...avail.map((s) => el("option", { value: s.id, textContent: label(combo(s.id)) })));
      $("votes-combo").value = S.votes;
      if (!S.votes) { panel("The inputs of the mark", [], pct); return; }
      return load(t.id, S.votes).then((r) => {
        const three = combo(S.votes).mark === "three", s = S.saved.find((x) => x.id === S.votes);
        const lines = [
          { label: "External price", color: REF, width: 1.2, x: r.x, y: r.E },
          { label: three ? "Feed vote" : "Input 1", color: "#B8860B", width: 1.4, x: r.x, y: r.V },
          { label: three ? "Anchor" : "Input 2", color: "#8E5BD0", width: 1.4, dash: [7, 3], x: r.x, y: r.A },
          { label: "Order book", color: "#17996A", width: 1.4, dash: [2, 3], x: r.x, y: r.B },
          { label: "Mark (median)", color: PALETTE[s.slot], width: 2.4, x: r.x, y: r.M },
        ];
        panel("The three inputs and the mark (USD)", lines, price(lines), 440);
      });
    }
  }

  function table(list, runs) {
    const t = test(), crash = t.kind === "crash";
    const num = (v, f) => (v == null ? "–" : f(v));
    const cols = [
      crash ? ["Largest gap, mark to external price", (s) => num(s.gap_max, pct)]
            : ["Largest move of the mark", (s) => num(s.lift, (v) => (v > 0 ? "+" : "") + pct(v))],
      ["Taken over by the vault", (s) => `${num(s.inherited, usdM)} (${s.takeovers})`],
    ];
    if (!crash && t.has_base) cols.push(["Of which caused by the attack", (s) => num(s.inherited_added, (v) => (v > 0.0005 ? "+" : "") + usdM(v))]);
    const needs = runs.some((r) => r.summary.need != null);
    if (needs) cols.push(["Capital the vault needs", (s) => num(s.need, usdM)], ["Money to avoid ADL", (s) => num(s.adl, usdM)]);
    const head = el("tr", {}, [el("th", { textContent: "Combination" })].concat(cols.map((c) => el("th", { textContent: c[0] }))));
    const rows = list.map((s, i) => {
      const sw = el("span", { className: "swatch" }); sw.style.borderTopColor = PALETTE[s.slot];
      return el("tr", {}, [el("td", {}, [sw, label(combo(s.id))])].concat(cols.map((c) => el("td", { textContent: c[1](runs[i].summary) }))));
    });
    $("table").replaceChildren(el("table", { className: "sum" }, [el("thead", {}, [head]), el("tbody", {}, rows)]),
      el("p", { className: "muted", textContent: "Whole replayed day; takeovers counted in brackets." }));
  }

  function render() {
    const t = test();
    $("test").value = t.id; $("test-sub").textContent = t.sub; $("zero").textContent = t.zero.toLowerCase();
    chips(); tabs();
    S.plots.forEach((p) => p.destroy()); S.plots = []; $("panels").replaceChildren();
    const isTable = S.tab === "table";
    $("table").hidden = !isTable; $("panels").hidden = isTable; $("hint").hidden = isTable; $("votes-pick").hidden = S.tab !== "votes";
    const list = shown(), at = t.id + "|" + S.tab + "|" + list.map((s) => s.id).join(",") + "|" + S.votes;
    S.at = at;
    // allSettled, not all: one missing replay drops its own line instead of blanking every chart. Drawing is outside
    // the data catch, so a blocked chart library is reported as itself and not as missing data.
    Promise.allSettled(list.map((s) => load(t.id, s.id))).then((res) => {
      if (S.at !== at) return;   // the user moved on while the files loaded
      const keep = [], runs = [], lost = [];
      res.forEach((r, i) => (r.status === "fulfilled" ? (keep.push(list[i]), runs.push(r.value)) : lost.push(list[i].name || list[i].id)));
      const warn = lost.length ? el("p", { className: "muted", textContent: "Not drawn (no replay for this test): " + lost.join(", ") + "." }) : null;
      if (!keep.length) { $("panels").replaceChildren(el("p", { textContent: "No replay of this test is available. Run viewer/build_data.py to export them." })); $("panels").hidden = false; return; }
      try {
        if (isTable) table(keep, runs); else draw(keep, runs);
      } catch (e) {
        $("panels").replaceChildren(el("p", { textContent: "Cannot draw this view: " + e.message + " (the chart library may be blocked)." }));
        $("panels").hidden = false;
        return;
      }
      if (warn) (isTable ? $("table") : $("panels")).append(warn);
    });
  }
})();
