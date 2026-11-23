/* NFL Bets — suggestions and alerts only. Never signs in, never places a bet. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const ct = n => n == null ? "—" : (n < 1 && n > 0 ? n.toFixed(1) : Math.round(n)) + "¢";
const ct1 = n => n == null ? "—" : (Math.round(n * 10) / 10).toFixed(n < 10 ? 1 : 0) + "¢";
const pct = n => n == null ? "—" : (n < 1 ? n.toFixed(2) : n < 10 ? n.toFixed(1) : Math.round(n)) + "%";
const NOREC = hint => `<div class="empty">No recommendation.${hint ? `<div class="hint">${esc(hint)}</div>` : ""}</div>`;
const S = { B: null, L: null, tab: localGet("tab") || "pregame", q: "", chip: "All", open: new Set(), comboEdits: {}, prevPrices: {} };
const REPO = "rcarrier1995/nfl-bets";

function localGet(k) { try { return localStorage.getItem("nflbets." + k); } catch (e) { return null; } }
function localSet(k, v) { try { localStorage.setItem("nflbets." + k, v); } catch (e) {} }
function bets() { try { return JSON.parse(localGet("bets") || "[]"); } catch (e) { return []; } }
function saveBets(b) { localSet("bets", JSON.stringify(b)); }

function ago(iso) {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
}
function kick(iso) {
  const d = new Date(iso);
  return d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }).replace(":00", "");
}
const callOf = c => { const k = c.state === "in" && c.liveCall ? c.liveCall : c.call; return k === "Pass" && c.sell && c.state !== "post" && !c.priceStale && !(c.state === "in" && (c.alertsOff || c.paused)) ? "Sell" : k; };
const callsBy = () => Object.fromEntries((S.B?.calls || []).map(c => [c.key, c]));
const gameBy = () => Object.fromEntries((S.B?.games || []).map(g => [g.id, g]));
const COLORS = () => Object.assign({}, ...(S.B?.games || []).map(g => g.colors || {}));
const LOGOS = () => Object.assign({}, ...(S.B?.games || []).map(g => g.logos || {}));
function badge(team, size = "") {
  const c = COLORS()[team] || "#334155";
  const lg = LOGOS()[team];
  // real team logo; if it can't load, the colour badge with the abbreviation shows instead
  if (lg && /^https:\/\/a\.espncdn\.com\//.test(lg)) return `<span class="tb lg-wrap ${size}" style="--c:${esc(c)}"><img src="${esc(lg)}" alt="${esc(team)}" loading="lazy" onerror="this.parentNode.classList.remove('lg-wrap');this.replaceWith(document.createTextNode('${esc(team)}'))"></span>`;
  return `<span class="tb ${size}" style="--c:${esc(c)}">${esc(team)}</span>`;
}
const ICON = {
  inj: '<path d="M12 5v14M5 12h14"/>', wx: '<path d="M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7"/>',
  dome: '<path d="M3 19h18M5 19a7 7 0 0 1 14 0"/>', mu: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  to: '<path d="M4 12a8 8 0 0 1 14-5l2 2M20 12a8 8 0 0 1-14 5l-2-2M20 4v5h-5M4 20v-5h5"/>',
  ch: '<path d="M12 8v4l3 2"/><circle cx="12" cy="12" r="9"/>', link: '<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/>',
  line: '<path d="M4 6h16M4 12h10M4 18h6"/>', search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  trophy: '<path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0V4zM17 6h3a3 3 0 0 1-3 4M7 6H4a3 3 0 0 0 3 4"/>'
};
const ic = k => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[k] || ""}</svg>`;
function toggle(id) { S.open.has(id) ? S.open.delete(id) : S.open.add(id); render(); }
window.toggle = toggle;

// ---------- small visuals ----------
function meter(conf) {
  const lvl = conf?.level || "Low";
  return `<span class="meter ${lvl}"><i></i><i></i><i></i></span><span class="small">Win chance ${lvl}</span>`;
}
function priceBar(price, fair, lo, hi) {
  if (price == null && fair == null) return "";
  const rng = lo != null && hi != null && hi > lo;
  let h = `<div class="pbar${rng ? " hasrng" : ""}">`;
  if (rng) {
    const cl = x => Math.min(92, Math.max(8, x));
    h += `<div class="rng" style="left:${lo}%;width:${hi - lo}%" title="Today's low to high"></div>` + (hi - lo < 16
      ? `<span class="rb" style="left:${cl((lo + hi) / 2)}%">today ${Math.round(lo)}–${Math.round(hi)}¢</span>`
      : `<span class="rb" style="left:${cl(lo)}%">low ${Math.round(lo)}¢</span><span class="rb" style="left:${cl(hi)}%">high ${Math.round(hi)}¢</span>`);
  }
  if (price != null && fair != null) {
    const lo = Math.min(price, fair), hi = Math.max(price, fair);
    h += `<div class="gap ${fair < price ? "neg" : ""}" style="left:${lo}%;width:${hi - lo}%"></div>`;
  }
  if (price != null) h += `<div class="mk" style="left:calc(${price}% - 1px)" title="Price"></div>`;
  if (fair != null) h += `<div class="mk f" style="left:calc(${fair}% - 1px)" title="Fair"></div>`;
  return h + `</div>`;
}
function move(c) {
  const p = c.price, pp = c.prevPrice;
  if (p == null) return "";
  let a = "";
  const fresh = c.priceChangedAt && Date.now() - Date.parse(c.priceChangedAt) < 10 * 60000 ? " flash" : "";
  if (pp != null && pp !== p) a = p < pp ? `<span class="mv-down${fresh}">▼ ${ct(pp - p)}</span>` : `<span class="mv-up${fresh}">▲ ${ct(p - pp)}</span>`;
  return `<span style="white-space:nowrap">${a} <span class="tiny muted">${ago(S.B.generatedAt)}</span></span>`;
}
function bestLine(c) {
  if (!c.bestTime || /^Only at/.test(c.bestTime)) return "";  // the verdict already says the buy-at price
  const now = c.bestTime.startsWith("Now");
  return `<div class="best ${now ? "now" : ""}"><span>⏱ Best time</span><b>${esc(c.bestTime)}</b></div>`;
}
// one plain verdict line, first on every card: what to do and the single main reason
function verdict(c) {
  const live = c.state === "in";
  const call = callOf(c);
  const fair = live ? c.liveFair : c.fair;
  const edge = live ? c.liveEdge : c.edge;
  const buyAt = live ? c.liveBuyAt : c.buyAt;
  const lines = c.liveLines || [];
  let t;
  if (c.priceStale && live) t = "Don't buy: prices are delayed right now";
  else if (live && c.alertsOff) t = "Too late: under 5 minutes left";
  else if (call === "Value") t = `Buy now: ${ct(edge)} below fair after fees`;
  else if (call === "Wait") t = `Wait: buy only at ${ct(buyAt)} or less — you'll get an alert`;
  else if (call === "Sell") t = `Sell if you own it: ${ct(c.sell.bid)} now is ${ct(c.sell.edge)} above fair after fees`;
  else if (live && lines.some(l => l.kind === "to")) t = `Don't buy the drop: ${c.team} has ${lines.find(l => l.kind === "to").text.split(" ")[0]} turnovers`;
  else if (live && lines.some(l => l.kind === "pause")) t = "Don't buy: " + lines.find(l => l.kind === "pause").text.replace(/^⏸\s*/, "").replace(/ — .*/, "");
  else if (c.price == null) t = "No price yet";
  else if (fair == null) t = "Don't buy: no fair price yet";
  else if (c.price > fair) t = `Don't buy: price is ${ct(c.price - fair)} above fair`;
  else if (fair - c.price < 1) t = "Don't buy: price is about fair";
  else t = `Don't buy: only ${ct(fair - c.price)} below fair — too small after fees`;
  return `<div class="verdict v-${call}">${esc(t)}</div>`;
}
// signals that don't change the call right now stay behind one tap
function moreInfo(c, lines, grades = true) {
  const g = (S.B.games || []).find(x => x.id === c.gameId);
  const hasGrades = grades && (g?.grades?.[c.team] || []).length;
  if (!lines.length && !hasGrades) return "";
  const id = "mi:" + c.key;
  let h = `<div class="line u muted" onclick="toggle('${esc(id)}')">More info${lines.length ? ` (${lines.length})` : ""}</div>`;
  if (S.open.has(id)) h += liveInjLines({ ...c, liveLines: lines }) + (hasGrades ? teamChips(g, c.team) : "");
  return h;
}
function gradesToggle(c) {
  const g = (S.B.games || []).find(x => x.id === c.gameId);
  if (!g || !(g.grades?.[c.team] || []).length) return "";
  const id = "gt:" + c.key;
  return `<div class="line u muted" onclick="toggle('${esc(id)}')">${ic("mu")}Team grades</div>${S.open.has(id) ? teamChips(g, c.team) : ""}`;
}
function fairPay(c, fair, buy, call) {
  const pay = call === "Sell" || buy == null ? "" : ` · <b>+${ct(100 - buy)}</b> if it wins${call === "Wait" ? ` at ${ct(buy)}` : ""}`;
  return `Fair ${ct1(fair)}${pay}`;
}

// ---------- bet card ----------
function betCard(c, opts = {}) {
  const call = callOf(c);
  const live = c.state === "in";
  const fair = live ? c.liveFair : c.fair;
  const buyAt = live ? c.liveBuyAt : c.buyAt;
  const id = "c:" + c.key;
  const buy = call === "Wait" ? buyAt : c.price;
  const tags = [];
  if (c.lag && !live) tags.push(`<span class="tag lag">slow price</span>`);
  if (c.price != null && c.price <= 10) tags.push(`<span class="tag look">longshot — cheap contracts lose most</span>`);
  const open = S.open.has(id);
  return `<div class="card bg-${call}" data-card="${esc(c.key)}">
    <div class="row">${badge(c.team)}<div style="min-width:0"><b>${esc(c.name || c.team)}</b>${opts.vs ? `<div class="tiny muted">vs ${esc(c.opp)}</div>` : ""}</div><span class="sp"></span><span class="pill c-${call}">${call === "Wait" ? "Wait for a dip" : LBL(call)}</span></div>
    ${verdict(c)}
    <div class="row" style="margin-top:12px"><span class="hero">${ct(c.price)}</span><span class="sp"></span><span class="small">${move(c)}</span></div>
    <div class="sub">${fairPay(c, fair, buy, call)}</div>
    ${priceBar(c.price, fair, c.dayLo, c.dayHi)}
    ${tags.join("")}
    ${call !== "Pass" && call !== "Sell" ? bestLine(c) : ""}
    <div class="why u" onclick="toggle('${esc(id)}')">Details</div>
    ${open ? cardMore(c) : ""}
  </div>`;
}
function cardMore(c) {
  const r = (c.reasons || []).map(x => `<span class="chipf">${esc(x)}</span>`).join("");
  return `<div class="gdet">${c.why ? `<div class="small" style="margin-bottom:6px">${esc(c.why)}</div>` : ""}${r || ""}<div style="margin-top:8px"><button class="btn pri" onclick="openBreakdown('${esc(c.key)}')">Full breakdown</button></div></div>`;
}

// ---------- game sections ----------
function injLine(g) {
  const key = (g.injuries || []).filter(i => i.starter && (i.status === "Out" || i.status === "Doubtful"));
  const q = (g.injuries || []).filter(i => i.starter && i.status === "Questionable");
  if (!key.length && !q.length) return "";
  const id = "inj:" + g.id;
  let h = `<div class="line u" onclick="toggle('${id}')">${ic("inj")}${key.length} key injur${key.length === 1 ? "y" : "ies"}${q.length ? ` · ${q.length} questionable` : ""}</div>`;
  if (S.open.has(id)) h += `<div class="kv small">${key.concat(q).map(i => `<span><b>${esc(i.team)}</b> ${esc(i.pos)}</span><span>${esc(i.player)} — ${esc(i.status)}${i.top10 ? ` ⭐ top-10` : ""}${i.grade != null ? pgrade(i.grade) : ""}</span>`).join("")}</div>`;
  return h;
}
function wxLine(g) {
  if (g.indoor) return `<div class="line muted">${ic("dome")}Indoors</div>`;
  if (!g.weatherLine) return "";
  const id = "wx:" + g.id;
  let h = `<div class="line u" onclick="toggle('${id}')">${ic("wx")}${esc(g.weatherLine)}</div>`;
  if (S.open.has(id) && g.weather?.hours) h += wxChart(g.weather.hours);
  return h;
}
function muLine(g) {
  const a = g.matchup?.[g.away], h = g.matchup?.[g.home];
  const id = "mu:" + g.id;
  if (!a || !h) return `<div class="line muted">${ic("mu")}Rankings unavailable</div>`;
  const s = `${g.away} pass #${a.passOff?.rank ?? "–"} vs ${g.home} pass D #${h.passDef?.rank ?? "–"} · ${g.home} pass #${h.passOff?.rank ?? "–"} vs D #${a.passDef?.rank ?? "–"}`;
  let out = `<div class="line u" onclick="toggle('${id}')">${ic("mu")}${esc(s)}</div>`;
  if (S.open.has(id)) out += matchupBars(g);
  return out;
}
function sitLine(g) {
  if (!g.situation?.length) return "";
  return `<div class="line">${ic("ch")}<span>${g.situation.map(esc).join(" · ")} <span class="muted">— already in the line</span></span></div>`;
}
const LBL = c => c === "Value" ? "Buy" : c;
// rank chips: #1 green ... #32 red
const chip = (k, r, tip) => `<span class="gchip" title="${esc(tip || "")}" style="--h:${Math.round((32 - r) / 31 * 120)}"><b>#${r}</b>${esc(k)}</span>`;
// player grade 1-10 (from the 0-100 percentile), coloured the same way
const pgrade = g => { const v = Math.max(1, Math.min(10, Math.ceil(g / 10))); return `<span class="gchip" style="--h:${Math.round((v - 1) / 9 * 120)};margin-left:4px"><b>${v}</b>/10</span>`; };
function teamChips(g, team, keys) {
  const gs = (g.grades || {})[team] || [];
  const list = keys ? keys.map(k => gs.find(x => x.k === k)).filter(Boolean) : gs;
  return list.length ? `<div class="gchips">${list.map(x => chip(x.k, x.r, x.tip)).join("")}</div>` : "";
}
function gradesBlock(g) {
  if (!g.grades || !(g.grades[g.away] || []).length) return "";
  const id = "gr:" + g.id;
  let h = `<div class="line u" onclick="toggle('${id}')">${ic("mu")}<span>Team grades <span class="muted">· green good, red bad</span></span></div>`;
  if (S.open.has(id)) h += `<div style="margin:2px 0 8px">${[g.away, g.home].map(t => `<div class="row" style="align-items:flex-start;gap:8px;margin:6px 0">${badge(t, "sm")}${teamChips(g, t)}</div>`).join("")}<div class="tiny muted">NFL rank: #1 best, #32 worst. Info only.</div></div>`;
  return h;
}
function gradeLines(g) {
  const ml = g.matchupLines || [];
  const mk = [g.lineMoveLine, g.bookRangeLine].filter(Boolean);
  if (!ml.length && !mk.length) return "";
  const id = "gl:" + g.id;
  let h = ml.length ? `<div class="line u" onclick="toggle('${id}')">${ic("mu")}<span>${esc(ml[0])} <span class="muted">· last 17 games${ml.length > 1 ? ` · +${ml.length - 1} more` : ""}</span></span></div>` : "";
  if (ml.length && S.open.has(id)) h += `<div class="small" style="margin:2px 0 6px 26px">${ml.map(esc).join("<br>")}<br><span class="muted">Ranks use EPA per play over each team's last 17 games, so they can differ from the season ranks above. Tested every week; they change the price only if they beat the line.</span></div>`;
  for (const m of mk) h += `<div class="line muted">${ic("line")}${esc(m)}</div>`;
  return h;
}
function toLine(g) {
  if (!g.turnovers || g.state === "pre") return "";
  const id = "to:" + g.id;
  const t = g.turnovers;
  let h = `<div class="line u" onclick="toggle('${id}')">${ic("to")}Turnovers ${g.away} ${t[g.away] ?? 0} · ${g.home} ${t[g.home] ?? 0}</div>`;
  if (S.open.has(id)) h += quarterTable(g, ["turnovers"]);
  return h;
}
function changesLine(g) {
  if (!g.changes?.length || g.state !== "pre") return "";
  const id = "ch:" + g.id;
  let h = `<div class="line u" onclick="toggle('${id}')">${ic("ch")}What changed since Thursday (${g.changes.length})</div>`;
  if (S.open.has(id)) h += `<div class="small">${g.changes.map(esc).join("<br>")}</div>`;
  return h;
}
function gameCombosLine(g) {
  const all = [];
  for (const cat of ["standard", "combined"]) for (const [k, r] of Object.entries(S.B.combos[cat] || {})) if (r.combo && r.combo.legs.some(l => l.gameId === g.id)) all.push(`${k}-leg ${cat === "combined" ? "combined" : ""}`.trim());
  if (!all.length) return "";
  return `<div class="line muted">${ic("link")}In ${all.join(", ")} combo</div>`;
}
function liveInjLines(c) {
  return (c.liveLines || []).map((l, i) => {
    const id = `ll:${c.key}:${i}`;
    let h = `<div class="line ${l.detail ? "u" : ""} ${l.kind === "ctx" ? "muted" : ""}" ${l.detail ? `onclick="toggle('${esc(id)}')"` : ""}>${esc(l.text)}</div>`;
    if (l.detail && S.open.has(id)) h += injTile(l.detail);
    return h;
  }).join("");
}

function gameRow(g) {
  const a = g.teams.away, h = g.teams.home;
  const best = [a, h].sort((x, y) => rank(callOf(y)) - rank(callOf(x)) || (y.edge ?? -99) - (x.edge ?? -99))[0];
  const id = "g:" + g.id;
  if (g.state === "post") return finalLine(g);
  if (g.state === "in") return liveCard(g);
  const bc = callOf(best);
  const o = S.open.has(id);
  const tm = c => `<div class="tm">${badge(c.team, "sm")}<span>${esc(c.name || c.team)}</span><span class="sp"></span></div>`;
  let row = `<div class="grow" onclick="toggle('${id}')"><div class="mt sp">${tm(a)}${tm(h)}</div>
    <div class="rt"><span class="kt">${kick(g.kickoff)}</span><span class="pill c-${bc}">${esc(best.team)} ${LBL(bc)}</span></div>
    <span class="chev ${o ? "open" : ""}">›</span></div>`;
  if (o) row += `<div class="card">${gameDetail(g)}</div>`;
  return row;
}
const rank = c => ({ Value: 3, Wait: 2, Sell: 2, Pass: 1 }[c] || 0);
function gameDetail(g) {
  return `<div class="teams2">${betCard(g.teams.away)}${betCard(g.teams.home)}</div>
    ${injLine(g)}${wxLine(g)}${muLine(g)}${gradesBlock(g)}${gradeLines(g)}${sitLine(g)}${toLine(g)}${changesLine(g)}${gameCombosLine(g)}
    ${g.spreadHome != null ? `<div class="line muted">${ic("line")}${esc(g.home)} ${g.spreadHome > 0 ? "+" : ""}${g.spreadHome} · total ${g.total ?? "—"}</div>` : ""}`;
}
function finalLine(g) {
  const id = "f:" + g.id;
  const r = g.result;
  const res = r?.right == null ? "" : r.right ? ` · <span class="ok">✓ ${esc(r.pick)}</span>` : ` · <span class="bad">✗ ${esc(r.pick)}</span>`;
  const sa = g.score.away ?? 0, sh = g.score.home ?? 0;
  let h = `<div class="grow" onclick="toggle('${id}')"><div class="final">${badge(g.away, "sm")}<span class="sc ${sa < sh ? "l" : ""}">${sa}</span><span class="muted">–</span><span class="sc ${sh < sa ? "l" : ""}" style="text-align:left">${sh}</span>${badge(g.home, "sm")}<span class="tiny muted">Final</span><span class="sp"></span><span class="small">${res.replace(/^ · /, "")}</span><span class="chev ${S.open.has(id) ? "open" : ""}">›</span></div></div>`;
  if (S.open.has(id)) h += `<div class="card">${scoreBlock(g)}${quarterTable(g)}${injLine(g)}${toLine(g)}${wxLine(g)}</div>`;
  return h;
}
function scoreBlock(g) {
  const pos = t => g.possession === t ? `<span class="dot" title="ball"></span>` : "";
  return `<div class="score"><div class="tm">${badge(g.away, "lg")}<b>${esc(g.away)}${pos(g.away)}</b><span class="pts">${g.score.away ?? 0}</span></div>
    <div class="clock">${g.state === "in" ? `<b>${g.period >= 5 ? "OT" : "Q" + g.period} ${esc(g.clock)}</b>` : `<b>${esc(g.detail || "")}</b>`}<br><span class="muted">${esc(g.downDist || "")}</span></div>
    <div class="tm">${badge(g.home, "lg")}<b>${esc(g.home)}${pos(g.home)}</b><span class="pts">${g.score.home ?? 0}</span></div></div>`;
}
function quarterTable(g, only) {
  const qs = g.quarters || [];
  if (!qs.length) return "";
  if (only && only[0] === "turnovers") return `<table class="qt"><tr><th>Q</th><th>${esc(g.away)}</th><th>${esc(g.home)}</th></tr>${qs.map(q => `<tr><td>Q${q.q}</td><td>${q.turnovers?.[g.away] ?? 0}</td><td>${q.turnovers?.[g.home] ?? 0}</td></tr>`).join("")}</table>`;
  return `<table class="qt"><tr><th>Q</th><th>Score</th><th>Lead</th><th>Weather</th><th>Injuries</th><th>TO</th><th>QB</th></tr>${qs.map(q =>
    `<tr><td>Q${q.q}</td><td>${q.cumAway}-${q.cumHome}</td><td>${esc(q.leader)}</td><td>${esc(q.weather || "")}</td><td>${esc((q.injuries || []).join(", "))}</td><td>${q.turnovers?.[g.away] ?? 0}/${q.turnovers?.[g.home] ?? 0}</td><td>${esc(Object.values(q.qb || {}).filter(Boolean).join(" / "))}</td></tr>`).join("")}</table>`;
}
// a live game whose price is 2¢ or less on one side is effectively over: one line, no team cards
function decided(g) {
  const a = g.teams.away, h = g.teams.home;
  const lv = c => c.price ?? c.liveFair;
  if (lv(a) == null || lv(h) == null) return "";
  const [w, l] = lv(a) >= lv(h) ? [a, h] : [h, a];
  return lv(l) <= 2 || lv(w) >= 98 ? `${w.team} ${ct(lv(w))} · ${l.team} ${ct(lv(l))}` : "";
}
function liveCard(g) {
  const id = "q:" + g.id;
  const tc = c => {
    const call = callOf(c);
    const ctx = (c.liveLines || []).filter(l => l.kind !== "to" && l.kind !== "pause");
    return `<div class="card bg-${call}" style="margin:6px 0">
      <div class="row">${badge(c.team, "sm")}<b>${esc(c.team)}</b><span class="pill c-${call}">${LBL(call)}</span><span class="sp"></span><span class="hero" style="font-size:28px">${ct(c.price)}</span></div>
      ${verdict(c)}
      <div class="row small" style="margin-top:8px"><span>${fairPay(c, c.liveFair, call === "Wait" ? c.liveBuyAt : c.price, call)}</span><span class="sp"></span>${move(c)}</div>
      ${priceBar(c.price, c.liveFair, c.dayLo, c.dayHi)}
      ${c.dipLine && call !== "Pass" ? `<div class="note">${esc(c.dipLine.replace("Price dropped: now ", "Price fell to ").replace(", was ", " from "))}</div>` : ""}
      ${c.bothOff && call === "Value" ? `<div class="note">${esc(c.bothOff)}</div>` : ""}
      ${call !== "Pass" && call !== "Sell" ? bestLine(c) : ""}
      ${liveInjLines({ ...c, liveLines: ctx.filter(l => l.kind === "inj" || l.kind === "nextq") })}
      ${moreInfo(c, ctx.filter(l => l.kind !== "inj" && l.kind !== "nextq"), false)}
    </div>`;
  };
  const wa = g.teams.away.liveFair, wh = g.teams.home.liveFair;
  const wp = wa != null && wh != null ? `<div class="wpbar"><i style="width:${wa / (wa + wh) * 100}%;background:${esc(COLORS()[g.away] || "#556")}"></i><i style="flex:1;background:${esc(COLORS()[g.home] || "#889")}"></i></div><div class="row tiny muted" style="margin:-6px 0 8px"><span>${pct(wa)} win</span><span class="sp"></span><span>${pct(wh)} win</span></div>` : "";
  return `<div class="card">${scoreBlock(g)}${wp}
    ${decided(g) ? `<div class="note">Decided: ${esc(decided(g))} — nothing to buy or sell</div>` : `<div class="teams2">${tc(g.teams.away)}${tc(g.teams.home)}</div>`}
    <div class="line u" onclick="toggle('${id}')">Quarters · ${(g.quarters || []).map(q => `Q${q.q} ${q.cumAway}-${q.cumHome}`).join(" · ") || "—"}</div>
    ${S.open.has(id) ? quarterTable(g) : ""}
    ${injLine(g)}${decided(g) ? "" : gradesBlock(g) + gradeLines(g)}${toLine(g)}${wxLine(g)}</div>`;
}

// ---------- tabs ----------
function filt(c) {
  const q = S.q.trim().toLowerCase();
  if (q && !(c.team.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q) || c.opp.toLowerCase().includes(q))) return false;
  if (S.chip === "Value" && callOf(c) !== "Value") return false;
  if (S.chip === "Wait" && callOf(c) !== "Wait") return false;
  return true;
}
function banners(kind) {
  const ws = (S.B.banners?.windows || []).slice().reverse();
  return ws.map((w, i) => {
    const id = `win:${w.window}:${w.week}`;
    let h = `<div class="banner"><span class="u" onclick="toggle('${id}')">${esc(w.label)}</span>`;
    if (S.open.has(id)) h += `<div class="small" style="margin-top:6px">${w.games.map(x => `${x.right ? "✓" : "✗"} ${esc(x.final)} · ${esc(x.review)}${x.changes?.length ? `<br><span class="muted">${esc(x.changes.join(" · "))}</span>` : ""}`).join("<br>")}<div style="margin-top:6px"><b>Lesson:</b> ${esc(w.lesson)}</div></div>`;
    return h + `</div>`;
  }).join("");
}

function pregame() {
  const by = callsBy();
  const pre = S.B.calls.filter(c => c.state === "pre");
  const nV = pre.filter(c => c.call === "Value").length, nW = pre.filter(c => c.call === "Wait").length;
  const nG = S.B.games.filter(g => g.state !== "post").length;
  let h = `<div class="ptitle">Pregame</div><div class="stats"><div class="stat"><b class="c-Value">${nV}</b><span>Buy now</span></div><div class="stat"><b class="c-Wait">${nW}</b><span>Wait for a dip</span></div><div class="stat"><b>${nG}</b><span>Games left</span></div></div>
    <div class="searchw">${ic("search")}<input class="search" id="q" placeholder="Search team" value="${esc(S.q)}"></div>
    <div class="chips">${["All", "Value", "Wait"].map(x => `<button class="chip ${S.chip === x ? "on" : ""}" data-chip="${x}">${LBL(x)}</button>`).join("")}</div>`;
  const top = (S.B.top3 || []).map(k => by[k]).filter(Boolean).filter(filt);
  if (top.length) {
    h += `<h2>Top 3 today</h2><div class="rail">${top.map((c, i) => {
      const buy = c.call === "Wait" ? c.buyAt : c.price;
      return `<div class="card bg-${c.call}" onclick="openBreakdown('${esc(c.key)}')"><div class="row">${badge(c.team)}<div><b>${esc(c.team)}</b><div class="tiny muted">vs ${esc(c.opp)}</div></div><span class="sp"></span><span class="pill c-${c.call}">${LBL(c.call)}</span></div>
      <div class="hero" style="margin-top:12px">${ct(c.price)}</div><div class="sub">${c.call === "Wait" ? `Buy at ${ct(c.buyAt)} · ` : ""}Fair ${ct1(c.fair)}</div>
      <div class="small" style="margin-top:6px"><b>+${ct(100 - buy)}</b> if it wins</div>${bestLine(c)}</div>`;
    }).join("")}</div>`;
  }
  const vw = pre.filter(c => ["Value", "Wait"].includes(c.call)).filter(filt).sort((a, b) => rank(b.call) - rank(a.call) || b.edge - a.edge);
  const waits = vw.filter(c => c.call === "Wait");
  const closest = pre.filter(c => c.edge != null).sort((a, b) => b.edge - a.edge)[0];
  const hint = closest ? `Closest: ${closest.team} at ${ct(closest.price)}, edge ${ct1(closest.edge)} · ${S.B.nextCheck || ""}` : S.B.nextCheck;
  h += `<h2>Best bets</h2>${vw.length ? vw.map(c => betCard(c, { vs: 1 })).join("") : NOREC(hint)}`;
  const sells = pre.filter(c => callOf(c) === "Sell").filter(filt);
  if (sells.length) h += `<h2>Sell if you own it</h2>${sells.map(c => betCard(c, { vs: 1 })).join("")}`;
  h += `<h2>Wait list</h2>${waits.length ? waits.map(c => `<div class="grow" onclick="openBreakdown('${esc(c.key)}')">${badge(c.team, "sm")}<b>${esc(c.team)}</b><span class="small">now ${ct(c.price)}</span><span class="sp"></span><span class="small c-Wait">buy at ${ct(c.buyAt)} → +${ct(100 - c.buyAt)}</span></div>`).join("") : NOREC(closest ? `Closest Wait: ${closest.team} at ${ct(closest.price)}, needs fair − 8¢ after fees` : "")}`;
  const games = S.B.games.filter(g => filt(g.teams.away) || filt(g.teams.home) || (S.chip === "All" && !S.q));
  const up = games.filter(g => g.state === "pre"), lvg = games.filter(g => g.state === "in"), fin = games.filter(g => g.state === "post");
  h += `<h2>All games this week <span class="cnt">${games.length}</span></h2>${games.length ? `${lvg.map(gameRow).join("")}${up.length ? `<div class="glist">${up.map(gameRow).join("")}</div>` : ""}${fin.length ? `<div class="glist" style="margin-top:10px">${fin.map(gameRow).join("")}</div>` : ""}` : NOREC()}`;
  return h;
}
function live() {
  const lv = S.B.games.filter(g => g.state === "in");
  const fin = S.B.games.filter(g => g.state === "post");
  const al = S.B.alerts || [];
  let h = `<div class="ptitle">Live</div><div class="psub">${lv.length ? `${lv.length} game${lv.length > 1 ? "s" : ""} in progress` : esc(nextKick() || "No games in progress")}</div>` + banners();
  h += `<h2>Live dip alerts</h2>${al.length ? al.map(a => `<div class="card bg-Value"><div class="row"><b>${esc(a.team)}</b><span class="small muted">${esc(a.game)}</span><span class="sp"></span><span class="hero" style="font-size:26px">${ct(a.price)}</span></div><div class="small"><b>+${ct(a.profit)} if it wins</b> · ${esc(a.confidence)}</div><div class="why">${esc(a.why)}</div></div>`).join("") : NOREC(lv.length ? "" : S.B.nextCheck)}`;
  h += `<h2>Live games</h2>${lv.length ? lv.map(liveCard).join("") : NOREC(nextKick())}`;
  h += `<h2>Final <span class="cnt">${fin.length}</span></h2>${fin.length ? `<div class="glist">${fin.map(finalLine).join("")}</div>` : NOREC()}`;
  return h;
}
function nextKick() {
  const n = S.B.games.filter(g => g.state === "pre").sort((a, b) => a.kickoff.localeCompare(b.kickoff))[0];
  return n ? `Next kickoff: ${n.short} ${kick(n.kickoff)}` : "";
}

// ---------- combos ----------
// estimated combo quote vs legs multiplied (same as engine/config.combo_markup) — an estimate, check Robinhood
const markup = n => n <= 3 ? 1 : n <= 8 ? 1 + 0.07 * (n - 3) / 5 : n <= 10 ? 1.07 + 0.075 * (n - 8) : 1.22 * Math.pow(1.08, n - 10);
function comboTotals(legs) {
  const hit = legs.reduce((p, l) => p * l.fair / 100, 1) * 100;
  const cost = legs.reduce((p, l) => p * l.price / 100, 1) * 100;
  const mk = markup(legs.length), est = cost * mk;
  return { hit, cost, est, mk, maxPay: hit - 2, edge: hit - 2 - est };
}
function tierTag(cost) {
  if (cost < 2) return `<span class="tag look">under 2¢ — look, don't buy</span>`;
  if (cost <= 15) return `<span class="tag good">good price</span>`;
  if (cost <= 20) return "";
  return `<span class="tag above">above your usual range</span>`;
}
function comboCard(cat, k, res) {
  const ek = `${cat}-${k}`;
  const legs = S.comboEdits[ek] || res?.combo?.legs;
  if (!legs || !legs.length) {
    const cl = res?.closest;
    const hint = !res ? "" : res.note && !res.checked ? res.note : `Checked ${Number(res.checked || 0).toLocaleString()} combos across ${res.games} games${cl ? ` · closest miss ${ct1(cl.edge)}` : ""}`;
    return NOREC(hint);
  }
  const t = comboTotals(legs);
  const id = "cb:" + ek;
  const edit = S.open.has(id);
  const w = Math.min(100, t.est / Math.max(t.maxPay, t.est, 0.01) * 100), mx = Math.min(100, t.maxPay / Math.max(t.maxPay, t.est, 0.01) * 100);
  const vc = t.edge >= 3 ? "Value" : t.edge >= 0 ? "Wait" : "Pass";
  const vt = vc === "Value" ? `Buy if the combo costs ${ct1(t.maxPay)} or less` : vc === "Wait" ? `Skip: only ${ct1(t.edge)} below fair — about a fair price` : `Don't buy: costs about ${ct1(-t.edge)} more than it's worth`;
  return `<div class="card bg-${vc}">
    <div class="row"><span class="pill c-${vc}">${legs.length}-leg${S.comboEdits[ek] ? " · edited" : ""}</span><span class="sp"></span>${tierTag(t.est)}</div>
    <div class="verdict v-${vc}">${esc(vt)}</div>
    <div class="row" style="margin-top:12px;align-items:flex-end"><span class="hero">${t.mk > 1 ? "≈" : ""}${ct1(t.est)}</span><span class="sp"></span><span class="small" style="text-align:right"><b class="c-Value">+${ct1(100 - t.est)}</b> if it wins</span></div>
    <div class="mpbar"><div class="cost ${t.est > t.maxPay ? "over" : ""}" style="width:${w}%"></div><div class="max" style="left:calc(${mx}% - 1px)"></div></div>
    <div class="small" style="margin-top:8px"><b>Pay no more than ${ct1(t.maxPay)} for the combo.</b> ${t.mk > 1 ? `<span class="muted">Estimated quote: legs multiplied ${ct1(t.cost)} + ~${Math.round((t.mk - 1) * 100)}% combo markup. Estimate — check the real price in Robinhood.</span>` : `<span class="muted">Legs multiplied: ${ct1(t.cost)}. Check the real price in Robinhood.</span>`}</div>
    <div class="kpis"><div><b>${pct(t.hit)}</b><span>Hits</span></div><div><b>${ct1(t.maxPay)}</b><span>Max pay</span></div><div><b class="${t.edge >= 0 ? "c-Value" : "bad"}">${t.edge >= 0 ? "+" : ""}${ct1(t.edge)}</b><span>Edge</span></div></div>
    <div style="margin-top:8px">${legs.map((l, i) => `<div class="leg" onclick="swapLeg('${ek}',${i})">${badge(l.team, "sm")}<div style="min-width:0"><b>${esc(l.team)}</b> <span class="small muted">vs ${esc(l.opp)}${l.state === "in" ? " · live" : ""}</span><br>${(l.tags || []).map(x => `<span class="tag ${x === "Shoe-in" ? "shoe" : ""}">${esc(x)}</span>`).join("")}</div><span class="sp"></span><span class="small muted">${pct(l.fair)}</span><span class="p">${ct(l.price)}</span>${edit && legs.length > 2 ? `<button class="x" onclick="event.stopPropagation();dropLeg('${ek}',${i})" aria-label="Remove">✕</button>` : ""}</div>`).join("")}</div>
    <div class="row" style="margin-top:10px"><button class="btn" onclick="toggle('${id}')">${edit ? "Done" : "Edit"}</button>${edit ? `<button class="btn" onclick="addLeg('${ek}')">+ Add leg</button>` : ""}${S.comboEdits[ek] ? `<button class="btn" onclick="resetCombo('${ek}')">Reset</button>` : ""}</div>
    ${edit ? `<div class="small muted" style="margin-top:8px">Pick any leg to swap it, ✕ to drop it, or add one. Any size from 2 legs.</div>` : ""}
  </div>`;
}
const comboLegs = (ek) => { const [cat, k] = ek.split("-"); return S.comboEdits[ek] || S.B.combos[cat][k]?.combo?.legs || S.B.combos[cat][k]?.closest?.legs || []; };
window.resetCombo = ek => { delete S.comboEdits[ek]; render(); };
window.dropLeg = (ek, i) => { const l = comboLegs(ek).slice(); l.splice(i, 1); S.comboEdits[ek] = l; render(); };
function legPicker(ek, i, title) {
  const legs = comboLegs(ek);
  const used = new Set(legs.map((l, j) => j === i ? null : l.gameId));
  const alts = (S.B.combos.pool || []).filter(l => !used.has(l.gameId)).sort((a, b) => (b.fair - b.price) - (a.fair - a.price));
  openModal(`<h2>${title}</h2>${alts.length ? alts.map((l, j) => `<div class="leg" onclick="pickLeg('${ek}',${i},${j})">${badge(l.team, "sm")}<div><b>${esc(l.team)}</b> <span class="small muted">vs ${esc(l.opp)}</span><br>${(l.tags || []).map(x => `<span class="tag">${esc(x)}</span>`).join("")}</div><span class="sp"></span><span class="small muted">${pct(l.fair)}</span><span class="p">${ct(l.price)}</span></div>`).join("") : NOREC("Every game is already in this combo")}`);
  window._alts = alts;
}
window.swapLeg = (ek, i) => legPicker(ek, i, `Swap leg ${i + 1}`);
window.addLeg = ek => legPicker(ek, -1, "Add a leg");
window.pickLeg = (ek, i, j) => {
  const legs = comboLegs(ek).slice();
  if (i < 0) legs.push(window._alts[j]); else legs[i] = window._alts[j];
  S.comboEdits[ek] = legs;
  closeModal(); render();
};
function comboSizes(cat) {
  return Object.keys(S.B.combos[cat] || {}).map(Number).sort((a, b) => a - b);
}
function bestSize(cat) {
  const r = S.B.combos[cat] || {};
  const found = comboSizes(cat).filter(k => r[k].combo);
  if (!found.length) return comboSizes(cat)[0];
  return found.sort((a, b) => r[b].combo.edge - r[a].combo.edge)[0];
}
window.setCombo = (cat, k) => { S.ccat = cat; if (k != null) S.csize[cat] = k; render(); };
function combosView() {
  S.csize = S.csize || {};
  const cat = S.ccat || "standard";
  const sizes = comboSizes(cat);
  const r = S.B.combos[cat] || {};
  const k = sizes.includes(S.csize[cat]) ? S.csize[cat] : bestSize(cat);
  const found = sizes.filter(x => r[x].combo).length;
  let h = `<div class="ptitle">Combos</div><div class="psub">${found ? `${found} size${found > 1 ? "s" : ""} clear the bar` : "Nothing clears the bar right now"} · live + upcoming games</div>
    <div class="ctabs"><button class="${cat === "standard" ? "on" : ""}" onclick="setCombo('standard')">All games</button><button class="${cat === "combined" ? "on" : ""}" onclick="setCombo('combined')">Shoe-in + dips</button></div>`;
  h += `<h2>${cat === "standard" ? "Weekly combos — live + upcoming" : "Combined combos — lopsided + TD dip + shoe-in"}</h2>`;
  if (!sizes.length) return h + NOREC(`${S.B.combos.poolGames || 0} games with prices — need 2`);
  h += `<div class="sizes">${sizes.map(x => `<button class="${x === k ? "on" : ""} ${r[x].combo ? "has" : ""}" onclick="setCombo('${cat}',${x})"><b>${x}</b><span>${r[x].combo ? "+" + ct1(r[x].combo.edge) : "legs"}</span></button>`).join("")}</div>`;
  h += comboCard(cat, String(k), r[k]);
  return h;
}

// ---------- learning ----------
function weekOf(b) { return b.week || ""; }
function betStats(list) {
  let w = 0, l = 0, pnl = 0;
  for (const b of list) {
    const qty = Number(b.qty || 1);
    if (b.result === "win") { w++; pnl += (100 - b.price) * qty; }
    else if (b.result === "loss") { l++; pnl -= b.price * qty; }
    else if (b.result === "tie") { pnl += (50 - b.price) * qty; }
  }
  return { w, l, pnl: pnl / 100 };
}
function money(x) { return (x >= 0 ? "+" : "−") + "$" + Math.abs(x).toFixed(2); }
function learning() {
  const L = S.L || {};
  const all = bets();
  const wk = all.filter(b => String(b.week) === String(S.B.week));
  const ws = betStats(wk), at = betStats(all);
  let h = `<div class="ptitle">Learning</div><div class="mybets"><span>This week: ${ws.w}–${ws.l} · ${money(ws.pnl)}</span><span class="small">All: ${money(at.pnl)}</span></div>`;
  h += banners();
  const t = L.totals;
  if (t) h += `<div class="banner"><b>${t.right}/${t.games} right · ${t.pct}%</b> <span class="small muted">(${t.baseline.right}/${t.baseline.games} backtest + ${t.reviewedRight}/${t.reviewed} reviewed)</span></div>`;
  // weekly lessons
  h += `<h2>Weekly lessons</h2>`;
  const wl = (L.weekly || []).slice().reverse();
  h += wl.length ? wl.map(w => {
    const id = "wk:" + w.week;
    return `<div class="banner"><span class="u" onclick="toggle('${id}')">Week ${w.week} — ${w.w}/${w.n} right · Brier ${w.brier}</span>${S.open.has(id) ? `<div class="small" style="margin-top:6px">${esc(w.lesson)}<br>${esc(w.shrink || "")}<br>${calibChart(w.calibration, "By fair value")}${Object.entries(w.combos || {}).map(([k, v]) => `${k} combos hit ${v.hit}/${v.n}`).join(" · ")}</div>` : ""}</div>`;
  }).join("") : NOREC(S.B.nextCheck);
  // calibration
  const bt = L.backtest;
  const useRev = (L.totals?.reviewed || 0) >= 20;
  const calRows = (useRev ? L.calibration : bt?.calibration) || [];
  const calC = (useRev ? L.calibConf : bt?.calibConf) || [];
  const id1 = "cal1";
  const head = calRows.length ? calRows.map(r => `${r.bucket}: ${Math.round(r.actual)}%`).join(" · ") : "—";
  h += `<h2>Calibration</h2><div class="line u" onclick="toggle('${id1}')">${esc(head)}</div>${S.open.has(id1) ? `<div class="ig">${tile("By fair value", calibChart(calRows))}${tile("By confidence", calibChart(calC))}</div><div class="tiny muted">${useRev ? "Reviewed games" : "Rebuilt backtest (Weeks 1–11) until 20 games are reviewed"}</div>` : ""}`;
  if (L.shrink) h += `<div class="line muted small">${esc(L.shrink.note)}</div>`;
  // backtest
  if (bt) {
    const id = "bt";
    h += `<h2>Backtest</h2><div class="line u" onclick="toggle('${id}')">${bt.original.right}/${bt.original.games} · ${bt.original.pct}% (Weeks 1–11)</div>`;
    if (S.open.has(id)) h += `<div class="ig">${tile("By week (rebuilt)", weekBars(bt.byWeek))}${tile("Calls", `<div class="kv"><span>Buy</span><span>${bt.value}</span><span>Wait</span><span>${bt.wait}</span><span>Max edge</span><span>${bt.maxEdge}¢</span><span>Brier</span><span>${bt.brier}</span></div><div class="tiny muted" style="margin-top:4px">Rebuilt ${bt.right}/${bt.games}. Combos hit 10–30%; P&L was Week 9 — not an edge.</div>`)}</div>`;
  }
  // injury research (every player)
  const ir = L.injuryResearch;
  if (ir?.headline) {
    const id = "ir", hd = ir.headline;
    h += `<h2>Injury research</h2><div class="line u" onclick="toggle('${id}')">${hd.out} exits · ${hd.pctReturned}% back (~${hd.medianMinOut} min) · ${hd.keyNonQB} key non-QB</div>`;
    if (S.open.has(id)) h += `<table class="qt"><tr><th>Pos</th><th>Exits</th><th>Back</th><th>Key</th><th>Key rest Q</th><th>Key next Q</th><th>Key rest of game</th></tr>${Object.entries(ir.byPosition).map(([k, v]) => `<tr><td>${k}</td><td>${v.all.n}</td><td>${v.all.returned}</td><td>${v.key.n}</td><td>${sg(v.key.restQDelta)}</td><td>${sg(v.key.nextQDelta)}</td><td>${sg(v.key.swing)}</td></tr>`).join("")}</table><div class="tiny muted">Through week ${ir.throughWeek}. Key = starter who didn't return. Points vs team's normal pace. Small samples — direction, not proof.</div>`;
  }
  // model study
  const ms = L.modelStudy;
  if (ms) {
    const id = "ms";
    h += `<h2>Model check</h2><div class="line u" onclick="toggle('${id}')">Tested on ${ms.trainGames + ms.testGames} games · new model ≈ market</div>`;
    if (S.open.has(id)) h += `<table class="qt"><tr><th>Model</th><th>Log loss 21–25</th><th>2026</th><th>Bets</th></tr>${ms.rows.map(r => `<tr><td>${esc(r.model)}</td><td>${r.trainLogLoss}</td><td>${r.testLogLoss}</td><td>${esc(r.betPnl || "")}</td></tr>`).join("")}</table><div class="tiny muted">Lower log loss = better.</div><div class="small">${ms.findings.map(f => "• " + esc(f)).join("<br>")}</div>${tile("New model calibration, 1,359 games", calibChart(ms.calibrationNew))}`;
  }
  const ts = L.timingStudy;
  if (ts) {
    const id = "ts";
    h += `<h2>Best time to bet</h2><div class="line u" onclick="toggle('${id}')">${ts.games} games tested · no moment is cheap by itself</div>`;
    if (S.open.has(id)) h += `<div class="small" style="margin:6px 0">${esc(ts.finding)} ${esc(ts.note || "")}</div><table class="qt"><tr><th>Spot</th><th>Games</th><th>Priced</th><th>Won</th><th>2026</th></tr>${ts.rows.filter(r => r.n >= 300).map(r => `<tr><td>${esc(r.spot)}</td><td>${r.n}</td><td>${r.price}%</td><td>${r.won}%</td><td>${r.gapTest == null ? "—" : (r.gapTest > 0 ? "+" : "") + r.gapTest}</td></tr>`).join("")}</table><div class="tiny muted">Quarter ends and the play after each TD, 2021–25, checked on 2026. "2026" = won minus priced, in points.</div>`;
  }
  const ss = L.signalsStudy;
  if (ss) {
    const id = "ss";
    h += `<h2>Other signals tested</h2><div class="line u" onclick="toggle('${id}')">${ss.games.toLocaleString()} games · ${ss.rows.filter(r => r.holds).length} of ${ss.rows.length} beat the line</div>`;
    if (S.open.has(id)) h += `<div class="small" style="margin:6px 0">${esc(ss.finding)}</div><table class="qt"><tr><th>#</th><th>Situation</th><th>${esc(ss.train)}</th><th>${esc(ss.test)}</th></tr>${ss.rows.map((r, i) => `<tr><td>${i + 1}</td><td>${esc(r.signal)}</td><td>${r.pts > 0 ? "+" : ""}${r.pts} <span class="muted">(${r.n})</span></td><td>${r.ptsTest > 0 ? "+" : ""}${r.ptsTest} <span class="muted">(${r.nTest})</span></td></tr>`).join("")}</table><div class="tiny muted">Ranked by how steadily each beat (or lost to) the line across both samples. Points vs the closing line per game; ±1 pt is noise at these sizes.</div>`;
  }
  const ps = L.profilesStudy;
  if (ps) {
    const id = "ps";
    const nh = (ps.held || []).length;
    h += `<h2>Team & matchup grades tested</h2><div class="line u" onclick="toggle('${id}')">${ps.games.toLocaleString()} games · ${nh} of ${ps.rows.length} beat the line${ps.builtAt ? ` · re-tested ${ago(ps.builtAt)}` : ""}</div>`;
    if (S.open.has(id)) h += `<div class="small" style="margin:6px 0">${esc(ps.finding)}</div><table class="qt"><tr><th>#</th><th>Grade</th><th>${esc(ps.train)}</th><th>${esc(ps.test)}</th></tr>${ps.rows.map((r, i) => `<tr><td>${i + 1}</td><td>${esc(r.signal)}${r.holds ? ` <span class="ok">✓ used</span>` : ""}<br><span class="tiny muted">${esc(r.unit)}</span></td><td>${r.per1sd > 0 ? "+" : ""}${r.per1sd} <span class="muted">(${r.n})</span></td><td>${r.per1sdTest == null ? "—" : (r.per1sdTest > 0 ? "+" : "") + r.per1sdTest} <span class="muted">(${r.nTest})</span></td></tr>`).join("")}</table>
      <div class="tiny muted">Per one standard step of the grade: points vs the closing line (pre-game) or cents vs the live win price at half time / after Q3 (in-game). A grade is used only if it holds in both columns. Re-tested every week after Monday night.</div>
      ${ps.wpModel ? `<div class="small" style="margin-top:8px"><b>Our own live win %</b>: accuracy (Brier) ${ps.wpModel.brier} vs ${ps.wpModel.brierRef} for the reference model on ${ps.wpModel.nTest.toLocaleString()} 2026 plays; usually within ${ps.wpModel.medianGap}¢. Used as a second opinion: a live Buy needs both models to agree.</div>` : ""}
      ${ps.sigma ? `<div class="small" style="margin-top:6px"><b>Game total and upsets</b>: ${ps.sigma.holds ? "holds — used in the price." : "low/high totals don't change upset odds beyond the line. Not used."} <span class="muted">${esc(ps.sigma.note)}</span></div>` : ""}`;
  }
  const cv = L.clv;
  h += `<h2>Beat the kickoff price?</h2>${cv && cv.n ? `<div class="line">${cv.beat} of ${cv.n} calls got a better price than kickoff · avg ${cv.avg > 0 ? "+" : ""}${cv.avg}¢</div><div class="small">${cv.recent.slice().reverse().map(r => `${esc(r.team)} ${esc(LBL(r.call))} at ${ct(r.entry)} → kickoff ${ct(r.close)} (${r.clv > 0 ? "+" : ""}${r.clv}¢)`).join("<br>")}</div><div class="tiny muted">Getting in cheaper than the kickoff price over many calls is the earliest sign the calls are sharp.</div>` : `<div class="line muted">Tracking started. Each Buy/Wait call is compared with the price at kickoff once its game starts.</div>`}`;
  const rt = L.retest;
  if (rt?.at) h += `<h2>Weekly re-test</h2><div class="line">${esc(rt.summary || "")} <span class="muted">· ${ago(rt.at)}</span></div>`;
  // patterns by call
  const bc = L.byCall || {};
  if (Object.keys(bc).length) h += `<h2>By call type</h2><div class="line">${Object.entries(bc).map(([k, v]) => `${k}: ${v.won}/${v.n} won`).join(" · ")}</div>`;
  // graded
  const gr = (L.graded || []).slice().reverse();
  const gid = "graded";
  h += `<h2>Graded games</h2>${gr.length ? `<div class="line u" onclick="toggle('${gid}')">${gr.filter(r => r.right).length}/${gr.length} right</div>${S.open.has(gid) ? gr.map(r => `<div class="small line">${r.right ? "✓" : "✗"} ${esc(r.final)} · ${esc(r.category)} · Brier ${r.brier}<br><span class="muted">${esc(r.review)}</span></div>`).join("") : ""}` : NOREC()}`;
  // bet log
  h += `<h2>Bet log</h2>${betForm()}${betList(all)}`;
  return h;
}
function betForm() {
  const teams = [...new Set(S.B.calls.map(c => c.team))].sort();
  return `<div class="card"><div class="form">
    <select id="bTeam" class="full">${teams.map(t => `<option>${t}</option>`).join("")}</select>
    <input id="bPrice" type="number" min="1" max="99" step="0.1" placeholder="Price ¢">
    <input id="bQty" type="number" min="1" step="1" placeholder="Contracts" value="1">
    <input id="bDate" type="date" value="${new Date().toISOString().slice(0, 10)}">
    <select id="bRes"><option value="open">Open</option><option value="win">Win</option><option value="loss">Loss</option><option value="tie">Tie</option></select>
    <button class="btn pri full" onclick="addBet()">Add bet</button></div></div>`;
}
function betList(all) {
  if (!all.length) return `<div class="row" style="margin-top:6px"><label class="btn">Import CSV<input type="file" accept=".csv" hidden onchange="importCsv(this)"></label></div>`;
  let run = 0;
  const rows = all.map((b, i) => {
    const q = Number(b.qty || 1);
    const p = b.result === "win" ? (100 - b.price) * q : b.result === "loss" ? -b.price * q : b.result === "tie" ? (50 - b.price) * q : 0;
    run += p;
    return `<div class="leg"><div><b>${esc(b.team)}</b> <span class="small muted">${esc(b.game || "")} ${esc(b.date)}</span><br><span class="small">${ct(b.price)} × ${q}</span></div><span class="sp"></span>
      <select onchange="setRes(${i},this.value)">${["open", "win", "loss", "tie"].map(r => `<option ${b.result === r ? "selected" : ""}>${r}</option>`).join("")}</select>
      <span class="small ${p >= 0 ? "ok" : "bad"}" style="min-width:60px;text-align:right">${b.result === "open" ? "" : money(p / 100)}</span><span class="tiny muted">${money(run / 100)}</span>
      <button class="btn" onclick="delBet(${i})">✕</button></div>`;
  }).join("");
  return `<div class="card">${rows}</div><div class="row"><button class="btn" onclick="exportCsv()">Export CSV</button><label class="btn">Import CSV<input type="file" accept=".csv" hidden onchange="importCsv(this)"></label></div>`;
}
window.addBet = () => {
  const price = Number($("#bPrice").value);
  if (!(price > 0 && price < 100)) return;
  const team = $("#bTeam").value;
  const c = S.B.calls.find(x => x.team === team);
  const all = bets();
  all.push({ team, price, qty: Number($("#bQty").value || 1), date: $("#bDate").value, result: $("#bRes").value, game: c ? `${c.team} vs ${c.opp}` : "", week: S.B.week, season: S.B.season });
  saveBets(all); render();
};
window.setRes = (i, r) => { const a = bets(); a[i].result = r; saveBets(a); render(); };
window.delBet = i => { const a = bets(); a.splice(i, 1); saveBets(a); render(); };
function csvDownload(name, rows) {
  const s = rows.map(r => r.map(x => `"${String(x ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([s], { type: "text/csv" }));
  a.download = name; a.click();
}
window.exportCsv = () => {
  const all = bets();
  let run = 0;
  const rows = [["date", "season", "week", "team", "game", "price_c", "contracts", "result", "profit_$", "running_$"]];
  for (const b of all) {
    const q = Number(b.qty || 1);
    const p = b.result === "win" ? (100 - b.price) * q : b.result === "loss" ? -b.price * q : b.result === "tie" ? (50 - b.price) * q : 0;
    run += p;
    rows.push([b.date, b.season, b.week, b.team, b.game, b.price, q, b.result, (p / 100).toFixed(2), (run / 100).toFixed(2)]);
  }
  rows.push([]); rows.push(["weekly lessons"]);
  for (const w of (S.L?.weekly || [])) rows.push([w.at, w.season, w.week, `${w.w}-${w.l}`, w.acc + "%", w.brier, w.lesson]);
  for (const w of (S.L?.windows || [])) rows.push([w.at, w.season, w.week, w.label, w.lesson]);
  csvDownload("nfl-bets.csv", rows);
};
window.importCsv = inp => {
  const f = inp.files[0]; if (!f) return;
  f.text().then(t => {
    const lines = t.split(/\r?\n/).filter(Boolean);
    const hdr = lines.shift().split(",").map(x => x.replace(/"/g, ""));
    const out = [];
    for (const ln of lines) {
      const v = ln.match(/("([^"]|"")*"|[^,]*)(,|$)/g).map(x => x.replace(/,$/, "").replace(/^"|"$/g, "").replace(/""/g, '"'));
      const o = Object.fromEntries(hdr.map((h, i) => [h, v[i]]));
      if (!o.team || !o.price_c) continue;
      out.push({ date: o.date, season: o.season, week: o.week, team: o.team, game: o.game, price: Number(o.price_c), qty: Number(o.contracts || 1), result: o.result || "open" });
    }
    if (out.length) { saveBets(out); render(); }
  });
};

// ---------- infographic breakdown ----------
function tile(title, body, wide) { return `<div class="tile ${wide ? "wide" : ""}"><h4>${esc(title)}</h4>${body}</div>`; }
function hbar(lab, v, max, txt, alt) { const w = Math.max(0, Math.min(100, (v / max) * 100)); return `<div class="hb"><span class="lab">${esc(lab)}</span><span class="trk"><i class="${alt ? "alt" : ""}" style="width:${w}%"></i></span><span class="val">${esc(txt)}</span></div>`; }
function edgeTile(price, fair, fee) {
  if (price == null || fair == null) return `<div class="muted small">Fair or price missing</div>`;
  const edge = fair - price - fee;
  const W = 300, x = v => 10 + v / 100 * (W - 20);
  const v15 = fair - 15 - fee, v8 = fair - 8 - fee;
  return `<div class="big ${edge >= 15 ? "ok" : edge >= 8 ? "" : "muted"}">${edge >= 0 ? "+" : ""}${edge.toFixed(1)}¢ <span class="small muted">edge after ${fee}¢ fees</span></div>
  <svg viewBox="0 0 ${W} 48" width="100%"><rect x="10" y="18" width="${W - 20}" height="8" rx="4" fill="var(--bar)"/>
   ${v15 > 0 ? `<rect x="10" y="18" width="${x(v15) - 10}" height="8" rx="4" fill="var(--good)" opacity=".35"/>` : ""}
   ${v8 > 0 ? `<line x1="${x(v8)}" x2="${x(v8)}" y1="12" y2="32" stroke="var(--wait)" stroke-width="2"/><text x="${x(v8)}" y="44" text-anchor="middle">8¢ bar ${Math.round(v8)}</text>` : ""}
   ${v15 > 0 ? `<line x1="${x(v15)}" x2="${x(v15)}" y1="12" y2="32" stroke="var(--good)" stroke-width="2"/><text x="${x(v15)}" y="10" text-anchor="middle">15¢ bar ${Math.round(v15)}</text>` : ""}
   <rect x="${x(price) - 2}" y="12" width="4" height="20" rx="2" fill="var(--ink)"/><text x="${x(price)}" y="44" text-anchor="middle">price ${Math.round(price)}</text>
   <rect x="${x(fair) - 2}" y="12" width="4" height="20" rx="2" fill="var(--fair)"/><text x="${x(fair)}" y="10" text-anchor="middle">fair ${Math.round(fair)}</text></svg>`;
}
function confTile(conf) {
  if (!conf) return "";
  return `<div class="row"><span class="big">${conf.score}%</span>${meter(conf)}</div><div class="small">Chance this team wins the game. Buy / Wait / Pass tells you if the price is good.</div><div class="tiny muted">Tested on 1,515 games: High (65%+) won 77%, Med won 59%, Low won 32%.${conf.missing ? " Some data missing for this game." : ""}</div>`;
}
function calibChart(rows, title) {
  if (!rows || !rows.length) return `<div class="muted small">No data yet</div>`;
  const W = 300, H = 90, bw = (W - 20) / rows.length;
  return `${title ? `<div class="tiny muted">${esc(title)}</div>` : ""}<svg viewBox="0 0 ${W} ${H + 24}" width="100%">${rows.map((r, i) => {
    const x = 10 + i * bw, hp = r.pred / 100 * H, ha = r.actual / 100 * H;
    return `<rect x="${x + 4}" y="${H - hp}" width="${bw / 2 - 6}" height="${hp}" fill="var(--bar)"/><rect x="${x + bw / 2}" y="${H - ha}" width="${bw / 2 - 6}" height="${ha}" fill="${r.actual + 3 < r.pred ? "var(--bad)" : "var(--good)"}"/>
      <text x="${x + bw / 2}" y="${H + 10}" text-anchor="middle">${esc(r.bucket)}</text><text x="${x + bw / 2}" y="${H + 20}" text-anchor="middle">${Math.round(r.pred)}→${Math.round(r.actual)}% n${r.n}</text>`;
  }).join("")}</svg>`;
}
function weekBars(bw) {
  const ks = Object.keys(bw || {});
  if (!ks.length) return "";
  const W = 300, H = 60, w = (W - 20) / ks.length;
  return `<svg viewBox="0 0 ${W} ${H + 14}" width="100%">${ks.map((k, i) => { const v = bw[k].right / bw[k].n; return `<rect x="${10 + i * w + 2}" y="${H - v * H}" width="${w - 4}" height="${v * H}" fill="var(--accent)"/><text x="${10 + i * w + w / 2}" y="${H + 11}" text-anchor="middle">W${k}</text>`; }).join("")}</svg>`;
}
function wxChart(hours) {
  if (!hours?.length) return "";
  const W = 300, H = 60, n = hours.length, w = (W - 20) / n;
  const mx = Math.max(30, ...hours.map(h => h.gust || 0));
  return `<svg viewBox="0 0 ${W} ${H + 26}" width="100%">${hours.map((h, i) => {
    const x = 10 + i * w, g = (h.gust || 0) / mx * H, s = (h.wind || 0) / mx * H;
    return `<rect x="${x + 3}" y="${H - g}" width="${w - 6}" height="${g}" fill="var(--wait)" opacity=".45"/><rect x="${x + 3}" y="${H - s}" width="${w - 6}" height="${s}" fill="var(--accent)"/>
      <text x="${x + w / 2}" y="${H + 10}" text-anchor="middle">${h.rel >= 0 ? "+" : ""}${h.rel}h</text><text x="${x + w / 2}" y="${H + 21}" text-anchor="middle">${Math.round(h.temp ?? 0)}° ${Math.round(h.gust ?? 0)}</text>`;
  }).join("")}<line x1="10" x2="${W - 10}" y1="${H - 15 / mx * H}" y2="${H - 15 / mx * H}" stroke="var(--bad)" stroke-dasharray="3 3"/></svg><div class="tiny muted">blue wind · orange gusts · red line 15 mph · temp°/gust per hour from kickoff</div>`;
}
function matchupBars(g) {
  const a = g.matchup?.[g.away], h = g.matchup?.[g.home];
  if (!a || !h) return `<div class="muted small">Rankings unavailable</div>`;
  const row = (lab, t, k) => t?.[k] ? hbar(`${lab}`, 33 - (t[k].rank || 32), 32, `#${t[k].rank} · ${(t[k].epa >= 0 ? "+" : "") + t[k].epa.toFixed(3)} · ${Math.round(t[k].ypg)}y`, k.endsWith("Def")) : `<div class="hb small muted">${lab} — Rankings unavailable</div>`;
  return `<div class="tiny muted">rank of 32 · EPA/play · yds/g</div>
    <div class="small"><b>${esc(g.away)} offense vs ${esc(g.home)} defense</b></div>${row("Pass off", a, "passOff")}${row("Pass def", h, "passDef")}${row("Run off", a, "runOff")}${row("Run def", h, "runDef")}
    <div class="small" style="margin-top:6px"><b>${esc(g.home)} offense vs ${esc(g.away)} defense</b></div>${row("Pass off", h, "passOff")}${row("Pass def", a, "passDef")}${row("Run off", h, "runOff")}${row("Run def", a, "runDef")}
    ${keyPl(g.away, a, g.home, h)}${keyPl(g.home, h, g.away, a)}`;
}
function keyPl(tn, t, on, o) {
  const P = t.players, Q = o.players;
  if (!P && !Q) return "";
  const one = (x, lab) => x ? hbar(lab + " " + x.name, (x.of || 32) + 1 - x.rank, x.of || 32, `#${x.rank}/${x.of}`) + `<div class="tiny muted" style="margin:-2px 0 4px 78px">${esc(x.txt)}</div>` : "";
  return `<div class="small" style="margin-top:8px"><b>${esc(tn)} players vs ${esc(on)} defenders</b></div>${one(P?.QB, "QB")}${one(Q?.Rush, "vs")}${one(P?.WR1, "WR")}${one(Q?.Cover, "vs")}${one(P?.RB1, "RB")}`;
}
function injTile(d) {
  if (!d) return "";
  if (d.pts != null) return `<div class="small">⭐ Next quarter only: ${d.pts} pt (≈${Math.abs(d.pts * 2.5).toFixed(1)}¢), dip alerts paused, then reverts.</div>`;
  const chips = d.starter || d.isQB ? [`base ${d.base}`, `reliance ×${d.rf}`, `matchup ×${d.mf}`, `time ×${d.tf}`, d.gate?.halve ? "backup ×0.5" : "backup ×1", d.state === "confirmed" ? "confirmed ✓" : d.state === "returned" ? "returned" : "watching"] : [d.state === "returned" ? "returned" : d.state === "watch" ? "watching" : "not a starter"];
  if (d.pf) chips.push(`his history ${d.pf} pt`);
  const w = Math.min(100, Math.abs(d.impact) / 4 * 100);
  return `<div class="tile" style="margin:4px 0"><div class="row"><b>${esc(d.full || d.name)}</b><span class="small muted">${esc(d.pos)} · Q${d.q} ${esc(d.clock || "")}</span><span class="sp"></span><b class="${Math.abs(d.impact) >= 1.5 ? "bad" : ""}">${d.impact} pt</b></div>
   <div class="hb"><span class="lab">impact</span><span class="trk"><i class="alt" style="width:${w}%"></i></span><span class="val">${Math.abs(d.impact) >= 1.5 ? "cut " + (Math.abs(d.impact) * 2.5).toFixed(1) + "¢" : "watch"}</span></div>
   ${chips.map(c => `<span class="chipf">${esc(c)}</span>`).join("")}
   <div class="tiny muted" style="margin-top:4px">${esc(d.relianceText || "")}${d.gate?.note ? " · " + esc(d.gate.note) : ""}${(d.flags || []).length ? " · " + esc(d.flags.join(", ")) : ""}</div>${histBlock(d.history, d.pfSrc)}</div>`;
}
const sg = v => v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(1);
function histBlock(h, pfSrc) {
  if (!h) return "";
  let o = `<div style="margin-top:6px"><div class="small"><b>His history</b> · ${esc(h.line || "")}</div>`;
  if (h.events?.length) o += `<table class="qt"><tr><th>Wk</th><th>Q</th><th>Back</th><th>Rest Q</th><th>Next Q</th><th>After back</th><th>EPA/pl</th></tr>${h.events.map(e => `<tr><td>${e.week} ${esc(e.opp || "")}</td><td>${e.q}${e.clock ? " " + e.clock : ""}</td><td>${e.returned ? (e.minOut != null ? e.minOut + "m" : "yes") : "no"}</td><td>${sg(e.restQDelta)}</td><td>${sg(e.nextQDelta)}</td><td>${e.returned ? sg(e.afterRetNextQDelta) : "—"}</td><td>${e.epaDelta == null ? "—" : sg(e.epaDelta * 10) + "/10"}</td></tr>`).join("")}</table><div class="tiny muted">pts vs team's normal pace · EPA per 10 plays while out</div>`;
  if (h.without) o += `<div class="small">Games without him: ${h.without.missed} (wk ${h.without.weeksMissed.join(", ")}) · team EPA/play ${sg(h.without.epaDelta * 10)}/10 vs with him (${h.without.played}g)</div>`;
  const p = h.pos;
  if (p?.all?.n) o += `<div class="small muted">All ${p.all.n} ${esc(Object.keys(h).length ? "" : "")}league exits at his position: back ${p.all.returned}/${p.all.n}, next Q ${sg(p.all.nextQDeltaAll)} pts · starters who didn't return (n=${p.key.n}): next Q ${sg(p.key.nextQDelta)}, rest of game ${sg(p.key.swing)}</div>`;
  if (pfSrc) o += `<div class="tiny muted">His own number used: ${esc(pfSrc)} — shrunk 50%, capped −1 pt.</div>`;
  return o + `</div>`;
}
function partsTile(c) {
  const p = c.parts || {};
  if (p.spread == null) return `<div class="muted small">No sportsbook line</div>`;
  const items = [["Line", p.spread], ["EPA adj", p.epa], ["Weather", p.weather], ["Injuries", p.inj]];
  const mx = Math.max(6, ...items.map(i => Math.abs(i[1] || 0)));
  return items.map(([k, v]) => `<div class="hb"><span class="lab">${k}</span><span class="trk"><i class="${(v || 0) < 0 ? "alt" : ""}" style="width:${Math.abs(v || 0) / mx * 100}%"></i></span><span class="val">${(v || 0) >= 0 ? "+" : ""}${(v || 0).toFixed(1)} pt</span></div>`).join("") +
    `<div class="tiny muted">= ${p.pts >= 0 ? "+" : ""}${p.pts} pts × shrink ${p.shrink} ÷ 13.5 → Φ → fair ${ct1(c.fair)}</div>`;
}
function gaugeTile(g, c) {
  if (g.spreadHome == null) return `<div class="muted small">No sportsbook line</div>`;
  const m = c.side === "home" ? -g.spreadHome : g.spreadHome;
  return `<div class="kv"><span>Spread</span><span><b>${c.team} ${m > 0 ? "−" : "+"}${Math.abs(m)}</b> ${esc(g.book || "")}</span><span>Total</span><span><b>${g.total ?? "—"}</b></span><span>Line says</span><span><b>${ct1(c.fair)}</b></span><span>Market</span><span><b>${ct(c.price)}</b></span></div>${priceBar(c.price, c.fair)}`;
}
function timeline(g) {
  const qs = g.quarters || [];
  if (!qs.length) return `<div class="muted small">Not started</div>`;
  const W = 300, H = 60, mx = Math.max(7, ...qs.map(q => Math.max(q.cumAway, q.cumHome)));
  const pts = k => qs.map((q, i) => `${10 + (i + 1) * (W - 20) / Math.max(4, qs.length)},${H - q[k] / mx * H}`).join(" ");
  return `<svg viewBox="0 0 ${W} ${H + 14}" width="100%"><polyline fill="none" stroke="var(--accent)" stroke-width="2" points="10,${H} ${pts("cumAway")}"/><polyline fill="none" stroke="var(--wait)" stroke-width="2" points="10,${H} ${pts("cumHome")}"/>${qs.map((q, i) => `<text x="${10 + (i + 1) * (W - 20) / Math.max(4, qs.length)}" y="${H + 11}" text-anchor="middle">Q${q.q} ${q.cumAway}-${q.cumHome}</text>`).join("")}</svg><div class="tiny muted">blue ${esc(g.away)} · orange ${esc(g.home)}</div>`;
}
window.openBreakdown = key => {
  const c = callsBy()[key]; if (!c) return;
  const g = gameBy()[c.gameId];
  const live = c.state === "in";
  const fair = live ? c.liveFair : c.fair;
  const L = S.L || {};
  const useRev = (L.totals?.reviewed || 0) >= 20;
  const calRows = (useRev ? L.calibration : L.backtest?.calibration) || [];
  const calC = (useRev ? L.calibConf : L.backtest?.calibConf) || [];
  const inj = (g.injLive || []).filter(i => i.team === c.team);
  const curInj = (g.injuries || []).filter(i => i.team === c.team && i.starter);
  const combos = [];
  for (const cat of ["standard", "combined"]) for (const [k, r] of Object.entries(S.B.combos[cat] || {})) if (r.combo?.legs.some(l => l.team === c.team && l.gameId === c.gameId)) combos.push({ k, cat, r });
  const call = callOf(c);
  openModal(`<div class="row"><b style="font-size:20px">${esc(c.team)}</b><span class="muted">vs ${esc(c.opp)} · ${kick(g.kickoff)}</span></div>
   <div class="row" style="margin:6px 0 10px"><span class="hero">${ct(c.price)}</span><span class="pill c-${call}">${LBL(call)}</span><span class="sp"></span><span class="small">${call === "Wait" ? `Buy at ${ct(live ? c.liveBuyAt : c.buyAt)} · ` : ""}Fair ${ct1(fair)}</span></div>
   <div class="ig">
    ${tile("Fair vs market", edgeTile(c.price, fair, c.fee ?? 2), true)}
    ${tile("Win chance", confTile(c.confidence))}
    ${tile("How fair was built", partsTile(c))}
    ${tile("Spread / total vs market", gaugeTile(g, c))}
    ${tile("Calibration — fair value", calibChart(calRows))}
    ${tile("Calibration — win chance", calibChart(calC))}
    ${tile("Injuries", (inj.length ? inj.map(injTile).join("") : "") + (curInj.length ? curInj.map(i => `<span class="chipf">${esc(i.pos)} ${esc(i.short)} ${esc(i.status)}</span>`).join("") : (inj.length ? "" : `<div class="small muted">No key injuries</div>`)), true)}
    ${tile("Weather by hour", g.indoor ? `<div class="small">Indoors — weather not used</div>` : g.weather?.hours ? wxChart(g.weather.hours) : `<div class="small muted">Weather unavailable</div>`, true)}
    ${tile("Matchups (nflverse)", matchupBars(g), true)}
    ${tile("Score by quarter", timeline(g))}
    ${tile("Turnovers · QB", g.turnovers ? `<div class="kv"><span>${esc(g.away)}</span><span>${g.turnovers[g.away] ?? 0} TO · ${esc(g.qb?.[g.away]?.starter || "")}${g.qb?.[g.away]?.change ? " → " + esc(g.qb[g.away].change.to) : ""}</span><span>${esc(g.home)}</span><span>${g.turnovers[g.home] ?? 0} TO · ${esc(g.qb?.[g.home]?.starter || "")}${g.qb?.[g.home]?.change ? " → " + esc(g.qb[g.home].change.to) : ""}</span></div>` : `<div class="small muted">Not started</div>`)}
    ${combos.length ? tile("Combo legs", combos.map(({ k, cat, r }) => `<div class="small"><b>${k}-leg ${cat === "combined" ? "combined" : ""}</b> · hits ${pct(r.combo.hit)} · cost ${ct1(r.combo.cost)}<br>${r.combo.legs.map(l => `${l.team} ${ct(l.price)} (${pct(l.fair)})`).join(" · ")}</div>`).join(""), true) : ""}
   </div>`);
};

// ---------- add to home screen ----------
let _bip = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); _bip = e; });
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
function installCard() {
  if (isStandalone()) return `<div class="card"><h3>On your home screen</h3><div class="small"><span class="ok">✓ Installed.</span> You're using the app version.</div></div>`;
  return `<div class="card"><h3>Put the app on your home screen</h3>
   <div class="small">One tap from your home screen, full screen, no browser bars.</div>
   <button class="btn pri" style="margin-top:10px;width:100%" onclick="installApp()">Add to Home Screen</button></div>`;
}
const STEP = (n, html) => `<div class="leg" style="cursor:default"><span class="tb sm" style="--c:#16a34a">${n}</span><div class="small" style="min-width:0">${html}</div></div>`;
const SHARE_IC = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><path d="M12 3v12"/><path d="M8 7l4-4 4 4"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>`;
window.installApp = async () => {
  if (_bip) { _bip.prompt(); try { await _bip.userChoice; } catch (e) {} _bip = null; render(); return; }
  const ua = navigator.userAgent;
  const chromeIOS = /CriOS/.test(ua), otherIOS = /FxiOS|EdgiOS|GSA\//.test(ua);
  let steps;
  if (isIOS() && chromeIOS) {
    steps = [
      `Tap the <b>Share</b> button ${SHARE_IC} at the top right, next to the web address.`,
      `Scroll down the list and tap <b>Add to Home Screen</b>.`,
      `Tap <b>Add</b>. The NFL Bets icon appears on your home screen.`];
  } else if (isIOS() && !otherIOS) {
    steps = [
      `Tap the <b>•••</b> button at the bottom right of Safari. (On older iPhones, tap the <b>Share</b> button ${SHARE_IC} at the bottom of the screen instead and skip to step 3.)`,
      `Tap <b>Share</b> ${SHARE_IC}.`,
      `Scroll down and tap <b>Add to Home Screen</b>. If you only see a short list, tap <b>View More</b> first.`,
      `Leave <b>Open as Web App</b> on, then tap <b>Add</b>.`];
  } else if (isIOS()) {
    steps = [`This browser can't add apps to the home screen. Tap <b>Copy link</b> below, open <b>Safari</b>, paste the link, then tap the button again.`];
  } else {
    steps = [
      `Open your browser menu (<b>⋮</b> or <b>•••</b>).`,
      `Tap <b>Add to Home screen</b> or <b>Install app</b>.`,
      `Tap <b>Install</b> / <b>Add</b>.`];
  }
  openModal(`<h2>Add to Home Screen</h2>${steps.map((t, i) => STEP(i + 1, t)).join("")}
    <div class="small muted" style="margin-top:10px">Apple doesn't let a website add itself, so this takes 3 taps once. Siri can't do it.</div>
    <div class="row" style="margin-top:12px"><button class="btn" onclick="copyLink()">Copy link</button><span class="sp"></span><button class="btn pri" onclick="closeModal()">Got it</button></div>
    <div id="copyRes" class="small"></div>`);
};
window.copyLink = async () => {
  const url = location.origin + location.pathname;
  try { await navigator.clipboard.writeText(url); $("#copyRes").innerHTML = `<span class="ok">Link copied.</span>`; }
  catch (e) { $("#copyRes").textContent = url; }
};

// ---------- setup + system ----------
function setup() {
  const p = S.B.push || {};
  const topic = localGet("topic") || p.topic || "";
  const h = S.B.health || {};
  return `<div class="ptitle">Setup</div><h2>Setup & Edge</h2>
  ${installCard()}
  <div class="card"><h3>Phone alerts</h3>
   <div class="small">Status: ${p.topic ? `<span class="ok">topic saved on server</span>` : `<span class="bad">no topic on server</span>`}${p.lastNote ? `<br>${esc(p.lastNote)}` : ""}</div>
   <div class="row" style="margin-top:8px"><input id="topic" placeholder="ntfy topic" value="${esc(topic)}" style="flex:1"><button class="btn pri" onclick="testPush()">Test</button></div>
   <div id="testRes" class="small"></div>
   <div class="small" style="margin:8px 0">Buzzes for: Buy now · Wait prices hit · slow prices · live dips · <b>injury news</b> (starter ruled out, confirmed out in-game, QB change).</div>
   <ol class="small"><li>Install the free <b>ntfy</b> app (App Store / Google Play).</li><li>Tap <b>+</b>, type the topic above, Subscribe.</li><li>Tap <b>Test</b> here — your phone should buzz.</li></ol>
   <div class="small"><a href="https://github.com/${REPO}/edit/main/config.json" target="_blank" rel="noopener">Change the server topic</a> (edit <code>ntfyTopic</code>, Commit).</div>
  </div>
  <div class="card"><h3>Sharper line (many sportsbooks)</h3><div class="small">${S.B.odds?.enabled ? `<span class="ok">On</span> · last check ${ago(S.B.odds.fetchedAt)}${S.B.odds.left != null ? ` · ${S.B.odds.left} free lookups left this month` : ""}${S.B.odds.error ? `<br><span class="bad">${esc(S.B.odds.error)}</span>` : ""}` : `Off — using ESPN's single sportsbook. Add a free key from the-odds-api.com as the repo secret <code>ODDS_API_KEY</code> to switch on.`}</div></div>
  <div class="card"><h3>Sunday inactives check</h3><div class="small">Re-checks inactives and backups now.</div>
   <a class="btn" href="https://github.com/${REPO}/actions/workflows/manual.yml" target="_blank" rel="noopener">Run inactives check</a>
   <div class="tiny muted" style="margin-top:4px">Opens GitHub → tap “Run workflow”, pick <code>inactives</code>.</div></div>
  <div class="card doc"><h3>How pricing works</h3>
   <p><code>fair = Φ((spread + weather + fresh injury news) × 1.15 ÷ 13.5)</code>. The 1.15 scale was fitted on 1,359 games (2021–25) and checked on 2026: calibrated in every bucket. The old ×0.85/×0.80 shrink priced favourites too cheap and lost money in testing, so it's gone.</p>
   <p>Weather/run +1.0–1.5 pts to the run-heavy team in open air if wind ≥15 mph or ≤35°F. QB out −3.5, 2+ WR/CB out −1 — only when the news is fresh (not out Thursday, line moved &lt;2 pts); otherwise the line already priced it.</p>
   <p>EPA is shown (matchup bars, breakdown) but not added to the price: every EPA weight tested made the fairs worse.</p>
   <p>Edge = fair − price − fee (fee 2¢: Robinhood commission ≤1¢ + exchange fee ≤1¢). <b>Buy</b> ≥15¢. <b>Wait for a dip</b> 8–15¢, buy-at = fair − 15¢ − fee. Else <b>Pass</b>.</p>
   <p>Win chance = the chance the team wins the game (from the line). High 65%+, Med 45–65%, Low under 45%. It is not a bet rating: Buy / Wait / Pass is.</p>
   <p>Combos: every game set, every side (2^N). Hit % = product of fairs. Max pay = fair − 2¢. One leg per game (same-game legs are correlated). Shoe-in = fair ≥70¢ only.</p></div>
  <div class="card doc"><h3>How it works — rules</h3><ul class="small">
   <li>Live dip alert needs: price ≥15¢ under live fair after fees, AND payout up ≥20% vs the pre-drop price (profit = 100 − price; 60¢→52¢ = 40→48 = +20%), AND a lopsided game (spread ≥7).</li>
   <li>No alerts with under 5:00 left in Q4 or in OT.</li><li>QB change in Q1–Q3 (or Q4 within 14) pauses that team. Q4 garbage time (lead ≥21) ignored.</li>
   <li>2+ turnovers = downgrade, never a dip buy.</li><li>Live checks every 10 min while games are on. Live fair = ESPN win probability, minus injury cuts.</li></ul></div>
  <div class="card doc"><h3>Injury formula</h3><p class="small"><code>Impact = Base × Reliance × Matchup × Time × Confirmed</code>; fair cut ≈ Impact × 2.5¢. Base WR −2.0, CB −1.0, DL −1.25, LB −1.25, ST −1.0, OL/S/RB/TE 0. Reliance clamp(0.6 + 0.4 × share ÷ median, 0.8–1.2) — the written 0.8 + 0.4 didn't match your worked examples, so this version reproduces them. Matchup CB/S: 0.7 + 0.6 × opp pass share; DL/LB: run share. Time 0.25 + 0.75 × secs left ÷ 3600. Confirmed only when out through the next quarter or ruled out. Proven backup halves. Multiple: worst + 0.5 × second, cap −3. QB −3.5 × Time (cap −4, halved for a proven backup). |Impact| &lt;1.5 = watch; ≥1.5 cut fair + pause dips that quarter; ≥2.0 also pause Buy/Wait. ⭐ NextQFactor: top-10 (prior-week EPA) or QB out → −1.0 pt (−1.5 QB) next quarter only.</p></div>
  <div class="card doc"><h3>Data sources & limits</h3><ul class="small">
   <li>Prices: Kalshi public API (no sign-in). It's a <b>proxy</b> — Robinhood routes NFL contracts to Kalshi, Rothera or Crypto.com per contract. Always confirm the price in the Robinhood app.</li>
   <li>Scores, odds (one book), injuries, win probability: ESPN unofficial API (can change without notice).</li>
   <li>Stats, EPA, depth charts, rosters, snaps: nflverse (weekly).</li><li>Weather: Open-Meteo forecast, hourly kickoff −1h to +5h, gusts included.</li>
   <li>Final inactives only at T-90 min. QB change inferred from play-by-play, with lag. No free backup grade — derived from nflverse.</li>
   <li>Bet log lives on this device only. Use Export/Import CSV to move it between phone and computer.</li></ul></div>
  <div class="card doc"><h3>Honest edge</h3><ul class="small"><li>Realistic edge 1–3¢. Model error ±3–5 pts pregame (the free model matches the sportsbook; edge = Kalshi lagging the line or late news), ±5–8 live. Markets are efficient.</li><li>Backtest market price was devigged moneyline — Kalshi history isn't free (biggest gap).</li><li>Weather rule never fired in Weeks 1–11. Live backtest estimated, not traded. 10-leg combos are essentially unplayable at a 1¢ tick after fees.</li><li>Backtest P&L was driven by Week 9 — not an edge.</li></ul></div>
  <div class="card"><h3>Feed health</h3>${healthTable(h)}</div>
  <div class="card"><h3>Display</h3><div class="row"><button class="btn" onclick="theme('light')">Light</button><button class="btn" onclick="theme('dark')">Dark</button><button class="btn" onclick="theme('')">Auto</button></div></div>`;
}
function healthTable(h) {
  return `<div class="kv small">${Object.entries(h).map(([k, v]) => `<span><b>${esc(k)}</b></span><span>${v.ok ? `<span class="ok">ok</span>` : `<span class="bad">down</span>`} · last ok ${ago(v.lastOk)}${v.error && !v.ok ? " · " + esc(v.error) : ""}</span>`).join("")}</div>`;
}
window.theme = t => { document.documentElement.dataset.theme = t || "auto"; localSet("theme", t || "auto"); };
window.testPush = () => {
  const t = $("#topic").value.trim();
  if (!t) { $("#testRes").textContent = "Enter a topic first."; return; }
  localSet("topic", t);
  fetch(`${(S.B.push && S.B.push.server) || "https://ntfy.sh"}/${encodeURIComponent(t)}`, { method: "POST", body: "Test from NFL Bets ✅", headers: { Title: "NFL Bets test" } })
    .then(r => { $("#testRes").innerHTML = r.ok ? `<span class="ok">Sent — check your phone.</span>` : `<span class="bad">Failed (${r.status}).</span>`; })
    .catch(e => { $("#testRes").innerHTML = `<span class="bad">Failed: ${esc(e.message)}</span>`; });
};
function systemModal() {
  const h = S.B.health || {};
  const au = (S.L?.audit || []).slice().reverse();
  openModal(`<h2>⚙ System / Details</h2><div class="card"><h3>Feeds</h3>${healthTable(h)}<div class="small muted" style="margin-top:6px">Board ${ago(S.B.generatedAt)} · stats ${ago(S.B.tablesBuiltAt)}</div></div>
   <div class="card"><h3>Phone alerts</h3><div class="small">${esc(S.B.push?.lastNote || "No push sent yet")}</div></div>
   <div class="card"><h3 class="u" onclick="document.getElementById('aud').hidden=!document.getElementById('aud').hidden">Audit trail (${au.length})</h3>
   <div id="aud" hidden>${au.map(a => `<div class="small line">${esc(a.t.slice(5, 16).replace("T", " "))} · <b>${esc(a.team)}</b> ${esc(a.from || "new")} → ${esc(a.call)} · fair ${ct1(a.fair)} · price ${ct(a.price)}${a.buyAt ? ` · buy ${ct(a.buyAt)}` : ""} · conf ${a.conf}</div>`).join("")}</div></div>`);
}
window.systemModal = systemModal;

// ---------- modal / render ----------
function openModal(html) { $("#modalBody").innerHTML = html; $("#modal").hidden = false; }
function closeModal() { $("#modal").hidden = true; }
window.closeModal = closeModal;

function render() {
  if (!S.B) return;
  $("#weekLabel").textContent = `NFL Bets · Week ${S.B.week}`;
  const age = (Date.now() - Date.parse(S.B.generatedAt)) / 60000;
  $("#updated").textContent = `Updated ${ago(S.B.generatedAt)}`;
  $("#dot").classList.toggle("stale", age > 30);
  const nLive = S.B.games.filter(g => g.state === "in").length;
  const bdg = document.querySelector('[data-tab=live] .badge'); bdg.hidden = !nLive; bdg.textContent = nLive;
  $("#gear").classList.toggle("on", S.tab === "setup");
  const fn = S.B.feedNotes || [];
  $("#feedNote").hidden = !fn.length; $("#feedNote").textContent = fn.join(" · ");
  const wb = S.B.banners?.weekly;
  const wid = "weeklyban";
  $("#weeklyBanner").innerHTML = wb ? `<div class="banner"><span class="u" onclick="toggle('${wid}')">${esc(wb.label)}${weekPnl(wb.week)}</span>${S.open.has(wid) ? `<div class="small" style="margin-top:6px">${esc(wb.lesson)}<br>Brier ${wb.brier} · ${Object.entries(wb.categories || {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>` : ""}</div>` : "";
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === S.tab));
  const views = { pregame, live, combos: combosView, learning, setup };
  const y = window.scrollY;
  const v = $("#view");
  v.innerHTML = views[S.tab]() + `<button class="sysbtn" onclick="systemModal()">System / Details</button>`;
  if (S._lastTab !== S.tab) { v.classList.remove("enter"); void v.offsetWidth; v.classList.add("enter"); S._lastTab = S.tab; }
  window.scrollTo(0, y);
  const q = $("#q");
  if (q) { q.oninput = e => { S.q = e.target.value; const pos = e.target.selectionStart; render(); const n = $("#q"); n.focus(); n.setSelectionRange(pos, pos); }; }
  document.querySelectorAll("[data-chip]").forEach(b => b.onclick = () => { S.chip = b.dataset.chip; render(); });
}
function weekPnl(week) {
  const wk = bets().filter(b => String(b.week) === String(week) && b.result !== "open");
  if (!wk.length) return "";
  return ` · bets ${money(betStats(wk).pnl)}`;
}

async function load() {
  try {
    const [b, l] = await Promise.all([
      fetch("data/board.json?t=" + Date.now()).then(r => r.json()),
      fetch("data/learning.json?t=" + Date.now()).then(r => r.json()).catch(() => null)]);
    S.B = b; S.L = l; render();
  } catch (e) {
    if (!S.B) $("#view").innerHTML = `<div class="empty">Couldn't load data. Pull to refresh.</div>`;
  }
}
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; localSet("tab", S.tab); window.scrollTo(0, 0); render(); });
$("#gear").onclick = () => { S.tab = "setup"; document.querySelectorAll("#tabs button").forEach(b => b.classList.remove("on")); window.scrollTo(0, 0); render(); };
$("#modalClose").onclick = closeModal;
$("#modal").onclick = e => { if (e.target.id === "modal") closeModal(); };
const th = localGet("theme"); if (th) document.documentElement.dataset.theme = th;   // default: dark
load();
setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js", { updateViaCache: "none" }).then(r => r.update()).catch(() => {});
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!reloaded) { reloaded = true; location.reload(); } });
}
// If a newer version of the app is published, reload once so page, styles and script always match.
const MY_V = (document.querySelector('script[src*="app.js"]')?.getAttribute("src") || "").split("v=")[1] || "";
async function checkVersion() {
  try {
    const html = await fetch("./?nv=" + Date.now(), { cache: "no-store" }).then(r => r.text());
    const v = (html.match(/app\.js\?v=([0-9a-f]+)/) || [])[1];
    if (v && MY_V && v !== MY_V) location.reload();
  } catch (e) {}
}
checkVersion();
setInterval(() => { if (document.visibilityState === "visible") checkVersion(); }, 120000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkVersion(); });
