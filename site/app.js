(() => {
"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const NS = "http://www.w3.org/2000/svg";
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
let data = null, weights = {}, penalty = 100, sector = null, scanned = false, shown = [];

const pct = (x, d = 1) => x == null ? "n/a" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const dir = (x) => x > 0 ? "up" : x < 0 ? "down" : "";
function price(x) {
  if (x == null) return "n/a";
  const d = x < 10 ? 3 : 2;
  return x.toFixed(d).replace(/(\.\d\d)0$/, "$1");
}
async function getJSON(url) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 20000);
  try {
    const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store", signal: ctl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(timer); }
}
const hkt = (iso, opt) => new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Hong_Kong", ...opt }).format(new Date(iso));
const day = (d) => hkt(d + "T12:00:00+08:00", { weekday: "short", day: "numeric", month: "short", year: "numeric" });

// ------------------------------------------------------------------ data
async function load() {
  const [a, b] = await Promise.allSettled([getJSON("data/latest.json"), getJSON("data/status.json")]);
  if (a.status === "fulfilled" && a.value && Array.isArray(a.value.stocks)) {
    data = a.value;
    if (!Object.keys(weights).length) { weights = { ...data.weights }; sliders(); }
    header(b.status === "fulfilled" ? b.value : null);
    return true;
  }
  return false;
}
function notice(text, err) { $("notices").append(el("div", "notice" + (err ? " err" : ""), text)); }

function header(status) {
  $("notices").replaceChildren();
  $("updated").textContent = `Prices as of ${day(data.asof)} close. Last updated ${hkt(data.generated_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} HKT`;
  const age = (Date.now() - new Date(data.asof + "T16:00:00+08:00")) / 864e5;
  if (status && status.ok === false)
    notice(`The scan on ${hkt(status.checked_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} HKT failed, so this is the previous good scan (${day(data.asof)}).`);
  else if (age > 5)
    notice(`These prices are ${Math.floor(age)} days old. That can happen over a long holiday; otherwise the nightly scan may have stopped.`);
  (data.warnings || []).forEach((w) => notice(w));

  const r = data.regime, box = $("regime");
  const look = { "Risk-On": ["▲", "var(--good)"], "Neutral": ["●", "var(--warn)"], "Risk-Off": ["▼", "var(--crit)"] }[r.label] || ["●", "var(--mute)"];
  const msg = {
    "Risk-On": "The index and most stocks are trending up.",
    "Neutral": "Mixed signals: the index and the average stock disagree, or sit in between.",
    "Risk-Off": `Warning: the index is below its ${data.hsi_ma_days}-day average and few stocks are trending up. Long setups face a headwind in these conditions, so only the top ${data.picks["Risk-Off"]} are shown. Treat them as lower-confidence ideas.`,
  }[r.label] || "";
  box.style.setProperty("--c", look[1]);
  const lab = el("div", "lab"); const ico = el("span", "ico", look[0]); ico.setAttribute("aria-hidden", "true"); lab.append(ico, r.label);
  const stat = (big, small, cls) => { const s = el("div", "stat"); s.append(el("b", cls, big), el("span", "", small)); return s; };
  box.replaceChildren(lab,
    stat(`${r.hsi.toLocaleString("en-US", { maximumFractionDigits: 0 })} (${pct(r.hsi_chg)})`, r.index_name),
    stat(`${pct(r.hsi / r.hsi_ma - 1)}`, `vs ${data.hsi_ma_days}-day average (${r.hsi_ma.toLocaleString("en-US", { maximumFractionDigits: 0 })})`),
    stat(`${(r.breadth * 100).toFixed(0)}%`, "of liquid stocks above their 20-day average"),
    el("p", "msg", msg));
  box.hidden = false;
}

// ------------------------------------------------------------------ ranking (same formula as scanner/engine.py)
function score(s) {
  let sum = 0, tot = 0;
  for (const k in weights) { sum += (s.pct[k] ?? 50) * weights[k]; tot += weights[k]; }
  return Math.min(100, Math.max(0, (tot ? sum / tot : 0) - s.pen * penalty / 100));
}
function render() {
  const all = data.stocks.map((s) => ({ ...s, score: score(s) })).sort((a, b) => b.score - a.score);
  const limit = data.picks[data.regime.label] || 15;
  const picks = all.filter((s) => s.setup).slice(0, limit).map((s, i) => ({ ...s, rank: i + 1 }));
  heat(all, picks);
  shown = sector ? picks.filter((s) => s.sector === sector) : picks;
  $("hPicks").textContent = data.regime.label === "Risk-Off" ? `Top ${picks.length} picks (reduced: Risk-Off)` : `Top ${picks.length} picks`;
  $("pickNote").textContent = `From ${data.stocks.length} liquid stocks, ${data.stocks.filter((s) => s.setup).length} with a valid setup.` + (sector ? ` Showing ${sector} only.` : "");
  $("rows").replaceChildren(...shown.flatMap(row));
  const e = $("empty");
  e.hidden = shown.length > 0;
  e.textContent = sector && picks.length ? `None of the current picks are in ${sector}. Select the sector again to clear the filter.` : "No stock shows a valid setup today.";
  $("table").hidden = !shown.length;
  $("csv").disabled = !shown.length;
}

const RAMP = ["#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4"];
function heat(all, picks) {
  const g = {};
  all.forEach((s) => (g[s.sector] ||= []).push(s));
  const tiles = Object.entries(g).map(([name, list]) => {
    const r5 = list.map((s) => s.ret5).filter((x) => x != null).sort((a, b) => a - b);
    const m = r5.length >> 1;
    return { name, n: list.length, avg: list.reduce((t, s) => t + s.score, 0) / list.length,
      med: r5.length ? (r5.length % 2 ? r5[m] : (r5[m - 1] + r5[m]) / 2) : null, picks: picks.filter((p) => p.sector === name).length };
  }).sort((a, b) => b.avg - a.avg);
  $("heat").replaceChildren(...tiles.map((t) => {
    const i = Math.max(0, Math.min(8, Math.floor((t.avg - 30) / 40 * 9)));
    const b = el("button", "tile"); b.type = "button";
    b.style.background = RAMP[i]; b.style.color = i >= 4 ? "#08131f" : "#fff";
    b.setAttribute("aria-pressed", String(sector === t.name));
    b.append(el("span", "s", t.name), el("span", "v", t.avg.toFixed(0)), el("span", "d", `5D median ${pct(t.med)}`),
      el("span", "d", `${t.n} stocks, ${t.picks} pick${t.picks === 1 ? "" : "s"}`));
    b.onclick = () => { sector = sector === t.name ? null : t.name; render(); };
    return b;
  }));
}

function spark(v) {
  const W = 120, H = 34, lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  const x = (i) => 3 + i / (v.length - 1) * (W - 8), y = (p) => H - 4 - (p - lo) / sp * (H - 8);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("role", "img");
  const t = document.createElementNS(NS, "title");
  t.textContent = `Last ${v.length} closes: ${price(v[0])} to ${price(v[v.length - 1])}, low ${price(lo)}, high ${price(hi)}`;
  const p = document.createElementNS(NS, "polyline");
  p.setAttribute("points", v.map((c, i) => `${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(" "));
  p.setAttribute("fill", "none"); p.setAttribute("stroke", "#5598e7"); p.setAttribute("stroke-width", "2"); p.setAttribute("stroke-linejoin", "round");
  const c = document.createElementNS(NS, "circle");
  c.setAttribute("cx", x(v.length - 1)); c.setAttribute("cy", y(v[v.length - 1])); c.setAttribute("r", 3); c.setAttribute("fill", "#f0efec");
  svg.append(t, p, c);
  return svg;
}
function row(s) {
  const p = s.plan, tr = el("tr", "main"), sub = el("tr", "sub");
  const td = (cls, label) => { const n = el("td", cls); if (label) n.dataset.l = label; tr.append(n); return n; };
  td("rank n").textContent = s.rank;
  const k = td("stk"), a = el("a", "", s.name);
  a.href = "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(s.tv); a.target = "_blank"; a.dataset.rank = s.rank; a.rel = "noopener";
  a.title = (s.long || s.name) + ": open TradingView chart";
  k.append(a, el("span", "sm", `${s.tv}, ${s.sector}`));
  td("spark").append(spark(s.spark));
  const sc = td("score n"), bar = el("span", "bar"), fill = el("i"); fill.style.width = s.score + "%"; bar.append(fill);
  sc.append(el("b", "", s.score.toFixed(0)), bar);
  td("setup").append(el("span", "tag", s.setup));
  const c = td("n", "Close"); c.append(price(s.close), el("span", "sm " + dir(s.chg), pct(s.chg)));
  td("n", "Entry zone").append(`${price(p.entry_lo)} – ${price(p.entry_hi)}`);
  const st = td("n", "Stop"); st.append(price(p.stop), el("span", "sm", `${p.stop_basis}, −${p.risk_pct}%`));
  td("n", "Target (2R)").append(price(p.target), el("span", "sm", pct(p.target / p.entry_hi - 1)));
  td("hold", "Hold").append(p.hold);
  const blank = el("td"), cell = el("td"); cell.colSpan = 9;
  const chips = el("div", "chips");
  s.chips.forEach((x) => chips.append(el("span", "chip", x)));
  s.warn.forEach((x) => chips.append(el("span", "chip w", "⚠ " + x)));
  chips.append(el("span", "small muted", p.note));
  cell.append(chips); sub.append(blank, cell);
  return [tr, sub];
}

// ------------------------------------------------------------------ controls
function slider(id, label, get, set, max) {
  const l = el("label"), top = el("span"), out = el("output", "", get()), i = el("input");
  i.type = "range"; i.min = 0; i.max = max; i.step = max > 100 ? 10 : 1; i.value = get(); i.dataset.k = id;
  i.oninput = () => { set(+i.value); out.textContent = i.value + (max > 100 ? "%" : ""); if (scanned) render(); };
  if (max > 100) out.textContent = get() + "%";
  top.append(label, out); l.append(top, i);
  return l;
}
function sliders() {
  $("sliders").replaceChildren(
    ...Object.keys(weights).map((k) => slider(k, data.labels[k] || k, () => weights[k], (v) => { weights[k] = v; }, 40)),
    slider("penalty", "Overextended / RSI penalty", () => penalty, (v) => { penalty = v; }, 200));
}
$("reset").onclick = () => { weights = { ...data.weights }; penalty = 100; sliders(); render(); };

$("csv").onclick = () => {
  const head = ["rank", "ticker", "name", "sector", "score", "setup", "close", "change_pct", "entry_low", "entry_high", "stop", "stop_basis",
    "target_2R", "hold", "ret5_pct", "ret10_pct", "rs20_vs_hsi_pct", "rsi14", "rel_volume", "avg_turnover_hkd", "reasons", "warnings", "prices_as_of"];
  const q = (v) => { let t = String(v ?? ""); if (typeof v === "string" && /^[=+\-@]/.test(t)) t = "'" + t; return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t; };
  const n = (x, m = 1, d = 2) => x == null ? "" : +(x * m).toFixed(d);
  const lines = shown.map((s) => [s.rank, s.tv, s.name, s.sector, n(s.score), s.setup, n(s.close, 1, 3), n(s.chg, 100), s.plan.entry_lo, s.plan.entry_hi,
    s.plan.stop, s.plan.stop_basis, s.plan.target, s.plan.hold, n(s.ret5, 100), n(s.ret10, 100), n(s.rs20, 100), n(s.rsi), n(s.rvol),
    s.turnover, s.chips.join("; "), s.warn.join("; "), data.asof].map(q).join(","));
  const url = URL.createObjectURL(new Blob(["﻿" + [head.join(","), ...lines].join("\r\n")], { type: "text/csv" }));
  const a = el("a"); a.href = url; a.download = `hk-momentum-${data.asof}.csv`; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
};

const wait = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
async function scan() {
  const b = $("scanBtn"), f = $("funnel");
  b.disabled = true; b.classList.add("busy"); b.textContent = "SCANNING"; f.replaceChildren();
  $("scan").classList.remove("done"); $("results").hidden = true;
  const ok = await load().catch(() => false);
  if (!ok && !data) {
    $("notices").replaceChildren(); notice("Could not load the scan results. Check your connection and press SCAN to try again.", true);
    $("updated").textContent = "No data loaded";
  } else {
    if (!ok) notice("Could not refresh, so this is the copy loaded earlier.");
    for (const [label, n] of data.funnel) {
      const li = el("li"); li.append(el("span", "", label), el("b", "", n.toLocaleString("en-US"))); f.append(li);
      await wait(420);
    }
    await wait(250);
    scanned = true; f.replaceChildren(); $("scan").classList.add("done"); $("scanHint").textContent = "";
    render(); $("results").hidden = false;
  }
  b.disabled = false; b.classList.remove("busy"); b.textContent = scanned ? "SCAN AGAIN" : "SCAN";
}
$("scanBtn").onclick = () => scan().catch((e) => {
  console.error(e); notice("Something went wrong while showing the results. Reload the page and try again.", true);
  const b = $("scanBtn"); b.disabled = false; b.classList.remove("busy"); b.textContent = "SCAN";
});
load().then((ok) => { if (!ok) $("updated").textContent = "Press SCAN to load the latest results"; }).catch(console.error);
})();
