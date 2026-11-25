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
// "starts in 2h 10m" when a game kicks off within 12 hours
function soon(iso) {
  const m = Math.round((Date.parse(iso) - Date.now()) / 60000);
  if (!(m > 0 && m < 720)) return "";
  return m < 60 ? `Starts in ${m}m` : `Starts in ${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ""}`;
}
const byKick = (a, b) => String(a.kickoff).localeCompare(String(b.kickoff));
// finished games fold away (Rick 2026-11-25); open/closed is remembered on this device
function pastGames(fin, key) {
  if (!fin.length) return "";
  const open = localGet("past." + key) === "1";
  return `<details class="others past"${open ? " open" : ""} ontoggle="localSet('past.${key}', this.open ? '1' : '0')"><summary>Finished games (${fin.length}) · ${fin.filter(g => g.result?.right).length} of ${fin.filter(g => g.result?.right != null).length} picks right</summary><div class="tiny muted" style="margin:6px 2px">✓ our pick won · ✗ our pick lost</div><div class="glist">${fin.map(finalLine).join("")}</div></details>`;
}
const callOf = c => { const k = c.state === "in" && c.liveCall ? c.liveCall : c.call; return k === "Pass" && c.sell && c.state !== "post" && !c.priceStale && !(c.state === "in" && (c.alertsOff || c.paused)) ? "Sell" : k; };
const nextCalls = () => (S.B?.nextWeek || []).flatMap(g => [g.teams.away, g.teams.home]);
const callsBy = () => Object.fromEntries((S.B?.calls || []).concat(nextCalls()).map(c => [c.key, c]));
const gameBy = () => Object.fromEntries((S.B?.games || []).concat(S.B?.nextWeek || []).map(g => [g.id, g]));
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
// Letter grades (Rick 2026-11-23): win chance only. Buy / Wait / Pass is the price.
const GRADE_CUTS = [[85, "A+"], [75, "A"], [60, "B"], [45, "C"]], COMBO_CUTS = [[33, "A"], [15, "B"], [7, "C"]];
const GRADE_TESTED = { "A+": 92, A: 80, B: 67, C: 54, F: 32 };
const gradeOf = (p, cuts = GRADE_CUTS) => p == null ? null : (cuts.find(([lo]) => p >= lo) || [0, "F"])[1];
const grd = (g, sm) => g ? `<span class="grd g${g.replace("+", "p")}${sm ? " sm" : ""}" title="Grade ${g}">${g}</span>` : "";
const gradeKey = () => `<div class="gkey tiny muted">${grd("A+", 1)} 85%+ to win ${grd("A", 1)} 75–85% ${grd("B", 1)} 60–75% ${grd("C", 1)} 45–60% ${grd("F", 1)} under 45% · Buy / Wait / Pass = the price</div>`;
const comboKey = () => `<div class="gkey tiny muted">Combo grade: ${grd("A", 1)} hits 1 in 3 or better ${grd("B", 1)} 1 in 7 ${grd("C", 1)} 1 in 14 ${grd("F", 1)} rarer</div>`;
function meter(conf, p) {
  const g = gradeOf(p ?? conf?.win ?? conf?.score);
  return `${grd(g)}<span class="small">Win chance</span>`;
}
function priceBar(price, fair, lo, hi, start) {
  if (price == null && fair == null) return "";
  const rng = lo != null && hi != null && hi > lo;
  let h = `<div class="pbar${rng ? " hasrng" : ""}${start != null ? " hasst" : ""}">`;
  if (start != null) h += `<div class="st" style="left:calc(${start}% - 5px)" title="Price at kickoff"></div><span class="stl" style="left:${Math.min(90, Math.max(10, start))}%">start ${Math.round(start)}¢</span>`;
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
  return h + `</div><div class="pkey">${price != null ? `<span><i></i>price ${ct(price)}</span>` : ""}${fair != null ? `<span><i class="f"></i>our fair price ${ct1(fair)}</span>` : ""}</div>`;
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
  if (c.priceStale) t = "Don't buy: prices are delayed right now";
  else if (c.dataHold && c.state !== "post") t = "On hold: data looks off right now — check Robinhood";
  else if (live && c.alertsOff) t = "Too late: under 5 minutes left";
  else if (call === "Value") t = `Buy now: ${ct(edge)} below fair after fees`;
  else if (call === "Wait" && c.lineCheck && !live) t = c.lineCheck.buyUnder ? `Check the line: buy under ${ct(c.lineCheck.buyUnder)} — the sportsbook line may be behind the news` : "Check the line: the sportsbook line may be behind the news";
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
  const g = gameBy()[c.gameId];
  const hasGrades = grades && (g?.grades?.[c.team] || []).length;
  if (!lines.length && !hasGrades && grades) return "";
  const id = "mi:" + c.key;
  let h = `<div class="line u muted" onclick="toggle('${esc(id)}')">More info${lines.length ? ` (${lines.length})` : ""}</div>`;
  if (S.open.has(id)) h += liveInjLines({ ...c, liveLines: lines }) + (grades ? (hasGrades ? teamChips(g, c.team) : "") : teamInfo(c) + winLose(c));
  return h;
}
function gradesToggle(c) {
  const g = gameBy()[c.gameId];
  if (!g || !(g.grades?.[c.team] || []).length) return "";
  const id = "gt:" + c.key;
  return `<div class="line u muted" onclick="toggle('${esc(id)}')">${ic("mu")}Team grades</div>${S.open.has(id) ? teamChips(g, c.team) : ""}`;
}
function fairPay(c, fair, buy, call) {
  const pay = call === "Sell" || buy == null ? "" : ` · <b>+${ct(100 - buy)}</b> if it wins${call === "Wait" ? ` at ${ct(buy)}` : ""}`;
  return `Fair ${ct1(fair)}${pay}`;
}

// close games (fair 40-60¢): only the levers that matter, only the ones that apply
function closeTag(c) {
  const live = c.state === "in";
  const fair = live ? c.liveFair : c.fair;
  if (fair == null || fair < 40 || fair > 60 || c.state === "post") return "";
  const fee = c.fee ?? 2, g = gameBy()[c.gameId] || {};
  const L = [];
  const buy = Math.floor(fair - 15 - fee), wait = Math.floor(fair - 8 - fee);
  if (buy > 0) L.push(`Buy only at ${buy}¢ or less${wait > buy ? ` (Wait zone ${buy + 1}–${wait}¢)` : ""}`);
  if (c.lag && !live) L.push("Slow price: Kalshi hasn't caught up with the line yet");
  const q = (g.injuries || []).filter(i => i.team === c.team && i.starter && i.status === "Questionable");
  if (q.length) L.push(`Injury watch: ${q.slice(0, 3).map(i => `${i.pos} ${i.player.split(" ").slice(-1)[0]}`).join(", ")} questionable — could tip it`);
  if (live && c.liveBuyAt) L.push(`Live dip target: ${c.liveBuyAt}¢`);
  const sharp = /Consensus/.test(g.book || "");
  L.push(sharp ? `Line: ${g.book}` : `Line: one sportsbook${g.book ? ` (${g.book})` : ""} — multi-book line is off`);
  return `<div class="note"><b>Close game</b><br>${L.map(esc).join("<br>")}</div>`;
}

// ---------- "I bought this" (idea 7): folded away, can be hidden in Setup (Rick 2026-11-25) ----------
const showBought = () => localGet("bought") !== "off";
function boughtBox(spec) {
  if (!showBought() || spec.price == null) return "";
  const id = "bb" + (S.buyN = (S.buyN || 0) + 1);
  S.buy[id] = spec;
  const qty = spec.kind === "combo" ? Math.max(1, Math.floor(500 / Math.max(spec.price, 0.1))) : 1;
  return `<details class="bought" onclick="event.stopPropagation()"><summary>I bought this</summary>
    <div class="row" style="margin-top:8px;gap:8px"><label class="small">Price ¢<input id="${id}p" type="number" min="0.1" max="99" step="0.1" value="${Math.round(spec.price * 10) / 10}"></label>
    <label class="small">Contracts<input id="${id}q" type="number" min="1" step="1" value="${qty}"></label>
    <button class="btn pri" onclick="saveBought('${id}')">Save</button></div>
    <div class="tiny muted" id="${id}m">Goes in your bet log (Learning). Win or loss fills in by itself after the game.</div></details>`;
}
window.saveBought = id => {
  const sp = S.buy[id], price = Number($("#" + id + "p").value), qty = Math.max(1, Math.round(Number($("#" + id + "q").value) || 1));
  if (!sp || !(price > 0 && price < 100)) { $("#" + id + "m").textContent = "Type the price you paid (1–99¢)."; return; }
  const all = bets();
  all.push({ kind: sp.kind, team: sp.team, game: sp.game, gameId: sp.gameId, legs: sp.legs, grade: sp.grade, call: sp.call,
    price, qty, date: new Date().toISOString().slice(0, 10), result: "open", week: S.B.week, season: S.B.season });
  saveBets(all);
  $("#" + id + "m").innerHTML = `<span class="ok">Saved ✓ — ${qty} × ${ct(price)}. See Learning → Your bets.</span>`;
};
// open bets settle themselves once their games are final (this week's games only; you can still set it by hand)
function settleBets() {
  const G = gameBy(), all = bets();
  let changed = false;
  const res = (gid, team) => {
    const g = G[gid];
    if (!g || g.state !== "post" || g.score?.away == null || g.score?.home == null) return null;
    const a = g.score.away, h = g.score.home;
    if (a === h) return "tie";
    return (a > h ? g.away : g.home) === team ? "win" : "loss";
  };
  for (const b of all) {
    if (b.result !== "open") continue;
    let r = null;
    if (b.kind === "combo" && b.legs?.length) {
      const rs = b.legs.map(l => res(l.gameId, l.team));
      r = rs.includes("loss") ? "loss" : rs.every(x => x === "win") ? "win" : null;
    } else if (b.gameId) r = res(b.gameId, b.team);
    if (r) { b.result = r; b.auto = true; changed = true; }
  }
  if (changed) saveBets(all);
}
// your real record by grade (bets saved with a grade)
function gradeRecord(all) {
  const done = all.filter(b => b.result !== "open" && b.grade);
  if (!done.length) return "";
  const keys = ["A+", "A", "B", "C", "F"].filter(k => done.some(b => b.kind !== "combo" && b.grade === k));
  const row = (lab, list) => { const st = betStats(list); return `<span class="rec">${lab} <b>${st.w}–${st.l}</b> <span class="${st.pnl >= 0 ? "ok" : "bad"}">${money(st.pnl)}</span></span>`; };
  const combos = done.filter(b => b.kind === "combo");
  return `<div class="card"><div class="small" style="margin-bottom:6px"><b>Your record by grade</b></div><div class="recs">${keys.map(k => row(grd(k, 1), done.filter(b => b.kind !== "combo" && b.grade === k))).join("")}${combos.length ? row("Combos", combos) : ""}</div></div>`;
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
    <div class="row">${badge(c.team)}<div style="min-width:0"><b>${esc(c.name || c.team)}</b>${opts.vs ? `<div class="tiny muted">vs ${esc(c.opp)}</div>` : ""}</div><span class="sp"></span>${grd(gradeOf(fair))}<span class="pill c-${call}">${call === "Wait" ? "Wait for a dip" : LBL(call)}</span></div>
    ${verdict(c)}
    <div class="row" style="margin-top:12px"><span class="hero">${ct(c.price)}</span><span class="sp"></span><span class="small">${move(c)}</span></div>
    <div class="sub">${fairPay(c, fair, buy, call)}</div>
    ${priceBar(c.price, fair, c.dayLo, c.dayHi)}
    ${fair != null ? `<div class="small muted" style="margin-top:6px">Win chance ${Math.round(fair)}% · grade ${gradeOf(fair)} picks won ${GRADE_TESTED[gradeOf(fair)]}% in testing</div>` : ""}
    ${tags.join("")}
    ${gapLine(c)}${thinLine(c)}${feedLines(c)}
    ${closeTag(c)}
    ${call !== "Pass" && call !== "Sell" ? bestLine(c) : ""}
    ${c.state !== "post" ? boughtBox({ kind: "single", team: c.team, game: `${c.team} vs ${c.opp}`, gameId: c.gameId, grade: gradeOf(fair), call: LBL(call), price: c.price }) : ""}
    <div class="why u" onclick="toggle('${esc(id)}')">Details</div>
    ${open ? cardMore(c) : ""}
  </div>`;
}
// sportsbooks vs Robinhood (idea 9): only with the Odds API key on, only when the gap is 3¢+
function gapLine(c) {
  if (c.state !== "pre" || c.bookGap == null || Math.abs(c.bookGap) < 3) return "";
  const g = Math.round(c.bookGap);
  return `<div class="info">Sportsbooks give ${esc(c.team)} ${Math.round(c.bookP)}% · Robinhood ${ct(c.price)} → <b>${g > 0 ? `${g}¢ cheaper than the books` : `${-g}¢ dearer than the books`}</b></div>`;
}
// few trades or a wide buy/sell gap (idea 10): shown only when it applies
const thinLine = c => c.thin ? `<div class="info warn">${esc(c.thin)}</div>` : "";
// extra free feeds (2026-11-25), info only, each shown only when it matters
function practiceKey(c) {   // a QB on the report, or a starter who missed the last practice
  return (c.practice || []).filter(p => p.qb || p.dnp).slice(0, 2);
}
function feedLines(c) {
  if (c.state === "post") return "";
  let h = "";
  if (c.polyLine) h += `<div class="info">${esc(c.polyLine)}</div>`;
  if (c.moneyLine) h += `<div class="info">${esc(c.moneyLine)}</div>`;
  const n = (c.news || [])[0];
  if (n && c.state === "pre") h += `<div class="info">📰 ${esc(ago(n.at))}: ${esc(n.headline)}</div>`;
  const p = c.state === "pre" ? practiceKey(c) : [];
  if (p.length) h += `<div class="info warn">Practice: ${p.map(x => `${esc(x.pos)} ${esc(x.player)} ${esc(x.line)}`).join(" · ")}</div>`;
  return h;
}
// Details: the second opinions and the full practice list; a feed that failed shows "unavailable"
function feedInfo(c) {
  const fpi = c.fpi != null ? `ESPN FPI ${Math.round(c.fpi)}%${c.fpiNote ? ` <span class="muted">(${esc(c.fpiNote)})</span>` : ""}` : `ESPN FPI <span class="muted">unavailable</span>`;
  const poly = c.poly ? `Polymarket ${ct(c.poly.ask)}` : `Polymarket <span class="muted">unavailable</span>`;
  let h = `<div class="small" style="margin:4px 0"><b>Second opinions:</b> ${fpi} · ${poly} <span class="muted">· info only</span></div>`;
  if (c.practice == null) h += `<div class="small muted" style="margin:4px 0">Practice report unavailable</div>`;
  else if (c.practice.length) h += `<div class="small" style="margin:4px 0"><b>Practice (starters):</b><br>${c.practice.map(p => `${esc(p.pos)} ${esc(p.player)} — ${esc(p.line)}${p.injury ? ` <span class="muted">(${esc(p.injury)})</span>` : ""}`).join("<br>")}</div>`;
  if ((c.news || []).length) h += `<div class="small" style="margin:4px 0"><b>News:</b><br>${c.news.map(n => `${esc(ago(n.at))}: ${esc(n.headline)}`).join("<br>")}</div>`;
  return h;
}
// this team's own info only: its injuries, its side of the matchup, its grades
function teamInfo(c) {
  const g = gameBy()[c.gameId];
  if (!g) return "";
  const t = c.team, o = c.opp, mu = g.matchup?.[t], mo = g.matchup?.[o];
  const inj = (g.injuries || []).filter(i => i.team === t && i.starter && ["Out", "Doubtful", "Questionable"].includes(i.status));
  let h = `<div class="small" style="margin:4px 0"><b>Injuries:</b> ${inj.length ? inj.map(i => `${esc(i.pos)} ${esc(i.player)} — ${esc(i.status)}${i.top10 ? " ⭐" : ""}${i.grade != null ? pgrade(i.grade) : ""}`).join("<br>") : "no starters out"}</div>`;
  h += mu && mo ? `<div class="small" style="margin:4px 0"><b>This season:</b> pass #${mu.passOff?.rank ?? "–"} vs ${esc(o)} pass D #${mo.passDef?.rank ?? "–"} · run #${mu.runOff?.rank ?? "–"} vs run D #${mo.runDef?.rank ?? "–"}</div>`
    : `<div class="small muted" style="margin:4px 0">Rankings unavailable</div>`;
  const ch = teamChips(g, t);
  if (ch) h += `<div class="small" style="margin:6px 0 2px"><b>Grades</b> <span class="muted">· last 17 games · #1 best, #32 worst</span></div>${ch}`;
  h += formInfo(g, t);
  h += feedInfo(c);
  return h;
}
// form, coach style and backup QB (context only: none beat the price in testing)
function formInfo(g, t) {
  const f = g.form?.[t];
  if (!f) return "";
  let h = `<div class="small" style="margin:4px 0"><b>Form:</b> ${esc(f.record)}${f.last5 ? ` · last 5 ${esc(f.last5.split("").join(" "))}` : ""}${f.lines.length ? ` · ${esc(f.lines.join(" · "))}` : ""}</div>`;
  if (f.coach.length) h += `<div class="small" style="margin:4px 0"><b>Coach${f.coachName ? ` ${esc(f.coachName)}` : ""}:</b> ${esc(f.coach.join(" · "))} <span class="muted">· #1 = most</span></div>`;
  const b = f.backupQB;
  if (b) {
    const id = "bqb:" + g.id + t, p = b.profile;
    h += `<div class="note small"><span class="u" onclick="toggle('${id}')"><b>Backup QB:</b> ${esc(b.text)}${b.drop != null ? ` · about ${b.drop > 0 ? b.drop : 0} pts worse than ${esc(b.starter)}` : ""}</span>`;
    if (S.open.has(id) && p) {
      h += `<div style="margin-top:4px">${b.oppRush ? `${esc(b.oppRush)}<br>` : ""}By season: ${(p.bySeason || []).map(r => `${r[0]} ${r[2] >= 0 ? "+" : ""}${r[2].toFixed(2)} (${r[1]} db)`).join(" · ") || "—"}<br>INT rate ${p.intRate ?? "–"}%${p.byQ ? ` · by quarter ${Object.entries(p.byQ).map(([q, v]) => `Q${q} ${v[0] >= 0 ? "+" : ""}${v[0].toFixed(2)}`).join(" ")} <span class="muted">(quarter splits don't repeat year to year — noise)</span>` : ""}</div>`;
    }
    h += `<div class="tiny muted">EPA per dropback, 2021+ play-by-play. "Pts worse" is an estimate (EPA gap × 36 dropbacks); the line already prices it in tests.</div></div>`;
  }
  return h;
}
// "Why it could win / lose today": 2-3 short reasons each, only from data on the board
function winLose(c) {
  const g = gameBy()[c.gameId];
  if (!g) return "";
  const t = c.team, o = c.opp, mu = g.matchup?.[t], mo = g.matchup?.[o];
  const W = [], L = [];   // [weight, text]
  const fair = c.state === "in" ? c.liveFair : c.fair;
  if (c.state === "in" && g.score) {
    const me = g.home === t ? g.score.home : g.score.away, them = g.home === t ? g.score.away : g.score.home;
    if (me > them) W.push([99, `Leading ${me}–${them}`]); else if (me < them) L.push([99, `Trailing ${me}–${them}`]);
  } else if (g.spreadHome != null && g.spreadHome !== 0) {
    const sp = g.home === t ? g.spreadHome : -g.spreadHome;   // negative = favoured
    if (sp < 0) W.push([99, `Favoured by ${Math.abs(sp)} pts`]); else L.push([99, `Underdog by ${sp} pts`]);
  }
  const outs = (g.injuries || []).filter(i => i.starter && ["Out", "Doubtful"].includes(i.status));
  const mine = outs.filter(i => i.team === t), theirs = outs.filter(i => i.team === o);
  const nm = l => l.slice(0, 2).map(i => `${i.pos} ${i.player.split(" ").slice(-1)[0]}`).join(", ") + (l.length > 2 ? ` +${l.length - 2}` : "");
  const DM = [];   // [weight, text] — only factors big enough to tilt a game
  const qb = l => l.find(i => i.pos === "QB");
  if (theirs.length) W.push([4 + theirs.length + (qb(theirs) ? 5 : 0), `${o} missing ${nm(theirs)}`]);
  if (mine.length) L.push([4 + mine.length + (qb(mine) ? 5 : 0), `Missing ${nm(mine)}`]);
  if (qb(theirs)) DM.push([50, `${o} without starting QB ${qb(theirs).player} (worth about 3.5 pts)`]);
  if (qb(mine)) DM.push([50, `${t} without starting QB ${qb(mine).player} (worth about 3.5 pts)`]);
  for (const l of (c.liveLines || [])) if (l.kind === "inj" && l.detail && Math.abs(l.detail.impact ?? 0) >= 1.5) DM.push([40, l.text]);
  if (mu && mo) {
    for (const [off, def, label] of [["passOff", "passDef", "pass"], ["runOff", "runDef", "run"]]) {
      const a = mu[off]?.rank, d = mo[def]?.rank, oa = mo[off]?.rank, md = mu[def]?.rank;
      if (a && d && d - a >= 8) W.push([d - a, `Its ${label} game (#${a}) vs a weak ${label} D (#${d})`]);
      if (a && d && Math.abs(d - a) >= 20) DM.push([Math.abs(d - a), `${t}'s ${label} game (#${a}) vs ${o}'s ${label} D (#${d})`]);
      if (oa && md && Math.abs(oa - md) >= 20) DM.push([Math.abs(oa - md), `${o}'s ${label} game (#${oa}) vs ${t}'s ${label} D (#${md})`]);
      if (a && d && a - d >= 8) L.push([a - d, `Its ${label} game (#${a}) vs a strong ${label} D (#${d})`]);
      if (oa && md && oa - md >= 8) W.push([oa - md, `Its ${label} D (#${md}) vs a weak ${label} attack (#${oa})`]);
      if (oa && md && md - oa >= 8) L.push([md - oa, `${o}'s ${label} attack (#${oa}) vs its ${label} D (#${md})`]);
    }
  }
  const gs = g.grades?.[t] || [];
  const best = gs.filter(x => x.r <= 5).sort((a, b) => a.r - b.r)[0], worst = gs.filter(x => x.r >= 28).sort((a, b) => b.r - a.r)[0];
  if (best) W.push([3, `${best.k} #${best.r} in the NFL`]);
  if (worst) L.push([3, `${worst.k} #${worst.r} in the NFL`]);
  const fm = g.form?.[t], fo = g.form?.[o];
  if (fm?.backupQB?.drop >= 3) DM.push([55, `${t} starting backup QB ${fm.backupQB.backup} — about ${fm.backupQB.drop} pts worse than ${fm.backupQB.starter}`]);
  if (fo?.backupQB?.drop >= 3) DM.push([55, `${o} starting backup QB ${fo.backupQB.backup} — about ${fo.backupQB.drop} pts worse than ${fo.backupQB.starter}`]);
  if (fm?.backupQB) L.push([6, `Backup QB ${fm.backupQB.backup} starting`]);
  if (fo?.backupQB) W.push([6, `${o} on backup QB ${fo.backupQB.backup}`]);
  for (const x of fm?.lines || []) (/^(Won|Lost) \d+ straight/.test(x) ? (x.startsWith("Won") ? W : L) : L).push([1, x]);
  const ex = g.experts?.top || [];
  if (ex.length >= 3) {
    const k = ex.filter(r => r.team === t).length;
    if (k >= ex.length - 1) W.push([2, `${k} of ${ex.length} top experts pick ${t}`]);
    else if (k <= 1) L.push([2, `${ex.length - k} of ${ex.length} top experts pick ${o}`]);
  }
  if (c.weatherWhy) { (/favors/.test(c.weatherWhy) && c.weatherWhy.includes(o) ? L : W).push([2, c.weatherWhy]); DM.push([30, c.weatherWhy]); }
  const dm = DM.sort((x, y) => y[0] - x[0])[0];
  const top = a => a.sort((x, y) => y[0] - x[0]).slice(0, 3).map(x => `<li>${esc(x[1])}</li>`).join("");
  if (!W.length && !L.length && !dm) return "";
  return `${dm ? `<div class="note" style="color:var(--gold)"><b>⚡ Difference maker:</b> ${esc(dm[1])}</div>` : ""}<div class="wl"><div><b class="ok">Could win</b><ul>${top(W) || "<li class=muted>Nothing stands out</li>"}</ul></div><div><b class="bad">Could lose</b><ul>${top(L) || "<li class=muted>Nothing stands out</li>"}</ul></div></div>
    <div class="tiny muted">${fair != null ? `Win chance ${Math.round(fair)}% already counts all of this.` : ""}</div>`;
}
// price-and-line chart (review 2026-11-23): Kalshi price for each team, plus the sportsbook line turned into a win %
const PHI = x => 0.5 * (1 + Math.sign(x) * Math.sqrt(1 - Math.exp(-2 * x * x / Math.PI)));
function priceChart(g) {
  const H = (g.hist || []).filter(r => r[2] != null || r[3] != null);
  if (H.length < 2) return "";
  const t = H.map(r => Date.parse(r[0])), t0 = t[0], t1 = Math.max(t[t.length - 1], t0 + 1);
  const W = 320, Ht = 130, P = 26, x = v => P + (v - t0) / (t1 - t0) * (W - P - 6), y = v => 6 + (100 - v) / 100 * (Ht - 22);
  const col = COLORS(), ca = col[g.away] || "#60a5fa", chh = col[g.home] || "#f97316";
  const path = (i, f = v => v) => H.map((r, k) => r[i] == null ? null : [x(t[k]), y(f(r[i]))]).filter(Boolean)
    .map((p, k, arr) => (k ? `L${p[0].toFixed(1)},${(arr[k - 1][1]).toFixed(1)}L` : "M") + `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const lineP = s => 100 * PHI(-s * 1.15 / 13.5);   // home win % implied by the line (same scale as our fair)
  const grid = [25, 50, 75].map(v => `<line x1="${P}" x2="${W - 6}" y1="${y(v)}" y2="${y(v)}" stroke="var(--faint)" stroke-width=".5" stroke-dasharray="2 3"/><text x="2" y="${y(v) + 3}" font-size="9" fill="var(--muted)">${v}¢</text>`).join("");
  const day = d => new Date(d).toLocaleDateString([], { weekday: "short", hour: "numeric" });
  const last = H[H.length - 1];
  return `<div class="small" style="margin:6px 0 2px"><b>Price &amp; line</b> <span class="muted">· since ${esc(day(t0))}</span></div>
    <svg viewBox="0 0 ${W} ${Ht}" width="100%" style="max-width:420px;display:block" role="img" aria-label="Kalshi prices and sportsbook line over time">${grid}
      <path d="${path(1, lineP)}" fill="none" stroke="var(--muted)" stroke-width="1.2" stroke-dasharray="4 3"/>
      <path d="${path(2)}" fill="none" stroke="${ca}" stroke-width="2"/><path d="${path(3)}" fill="none" stroke="${chh}" stroke-width="2"/>
      <text x="${P}" y="${Ht - 4}" font-size="9" fill="var(--muted)">${esc(day(t0))}</text><text x="${W - 6}" y="${Ht - 4}" font-size="9" fill="var(--muted)" text-anchor="end">${esc(day(t1))}</text></svg>
    <div class="tiny muted"><span style="color:${ca}">━</span> ${esc(g.away)} ${last[2] != null ? ct(last[2]) : ""} · <span style="color:${chh}">━</span> ${esc(g.home)} ${last[3] != null ? ct(last[3]) : ""} · ┄ sportsbook line as ${esc(g.home)} win % (${last[1] != null ? `${esc(g.home)} ${last[1] > 0 ? "+" : ""}${last[1]}` : "no line"})</div>`;
}
function h2hDetails(g, inner) {
  const id = "h2h:" + g.id;
  return `<div class="line u" onclick="toggle('${id}')">${ic("mu")}Head-to-head details</div>${S.open.has(id) ? `<div style="margin-left:4px">${inner}</div>` : ""}`;
}
function cardMore(c) {
  const r = (c.reasons || []).map(x => `<span class="chipf">${esc(x)}</span>`).join("");
  const why = c.why && !/fair|edge/i.test(c.why) ? c.why : "";
  return `<div class="gdet">${why ? `<div class="small" style="margin-bottom:6px">${esc(why)}</div>` : ""}${r || ""}${teamInfo(c)}${winLose(c)}<div style="margin-top:8px"><button class="btn pri" onclick="openBreakdown('${esc(c.key)}')">Full breakdown</button></div></div>`;
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
  const mk = [g.bookRangeLine].filter(Boolean);
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

// "SF −3.5 (opened −3) · O/U 45.5" — the sportsbook line, favourite first
function spreadTxt(g) {
  // show the real market line (ESPN's book), not our model-equivalent spread
  const real = g.espnSpread != null;
  let sp = real ? g.espnSpread : g.spreadHome;
  if (sp == null) return "";
  if (!real) sp = Math.round(sp * 2) / 2;
  const fav = sp < 0 ? g.home : g.away, n = x => Math.abs(x) === 0 ? "PK" : "−" + Math.abs(x);
  const op = g.openSpread;
  const moved = op != null && Math.abs(op - sp) >= 0.5 ? ` (opened ${(op < 0) === (sp < 0) ? n(op) : `${op < 0 ? g.home : g.away} ${n(op)}`})` : "";
  return `Spread ${sp === 0 ? "Pick'em" : `${fav} ${n(sp)}`}${moved}${g.total != null ? ` · Over/under ${g.total}` : ""}`;
}
// expert picks (CBS + NFL.com): one short line by the spread, full list in head-to-head details
function expertsLine(g) {
  const e = g.experts;
  if (!e || !e.top?.length) return "";
  const c = {};
  for (const r of e.top) c[r.team] = (c[r.team] || 0) + 1;
  const txt = Object.entries(c).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${t} ${n}`).join(" · ");
  return `<div class="tiny muted" style="margin-top:2px">Top ${e.top.length} experts: <b>${esc(txt)}</b></div>`;
}
// watch tags (combo study) + expert spots: one skinny banner at the top of the card, on that team's side.
// Tags only — they never change the call. Tap the card for the why.
// our confidence (win chance) for both teams, on every game row
// a 5c+ gap between the sportsbooks and Robinhood shows on the game row too (only with the Odds API key on)
function rowGap(g) {
  const c = [g.teams.away, g.teams.home].filter(c => c.state === "pre" && c.bookGap != null && c.bookGap >= 5).sort((x, y) => y.bookGap - x.bookGap)[0];
  return c ? `<div class="tiny" style="color:var(--fair);margin-top:2px">${esc(c.team)} ${Math.round(c.bookGap)}¢ cheaper than the sportsbooks</div>` : "";
}
function winLine(g) {
  const f = c => { const p = c.state === "in" && c.liveFair != null ? c.liveFair : c.fair; return p != null ? `<span class="wt"><b>${esc(c.team)}</b> ${Math.round(p)}%${grd(gradeOf(p), 1)}${c.price != null && c.state !== "post" ? `<span class="wp">${ct(c.price)}</span>` : ""}</span>` : ""; };
  const a = f(g.teams.away), h = f(g.teams.home);
  return a || h ? `<div class="winl muted" title="Win chance">${a}${h}</div>` : "";
}
// every chip names the team to bet on first, then the reason (naming the team it's about)
const lastName = n => String(n || "").split(" ").slice(-1)[0];
function tagText(w, g) {
  const t = w.team, o = w.opp || (t === g.away ? g.home : g.away);
  const n = w.n ?? +((/without (\d+)/.exec(w.why || "") || [])[1] || 0);
  const qb = w.qb ? lastName(w.qb) : "", fe = Math.round(S.B.watch?.edges?.[w.tag] ?? 3);
  switch (w.tag) {
    case "Elite QB, weak D": return [t, `elite QB${qb ? " " + qb : ""}, ${t}'s own D is weak (market underrates)`];
    case "Their D banged up": return [t, `${o} D banged up${n ? ` (${n} key defenders out)` : ""}`];
    case "QB + WR1 beat their secondary": return [t, `${qb && w.wr ? `${qb} + ${lastName(w.wr)}` : "QB + WR1"} beat ${o}'s pass D`];
    case "Hot streak overpriced": return [o, `${t} on a hot streak, priced about ${fe}¢ too high`];
    case "Key WR out": return [o, `${t} missing key WR${w.players?.length ? " " + w.players.map(lastName).join(", ") : ""}, priced about ${fe}¢ too high`];
    case "Underdog experts pick": return [t, `underdog experts like ${t}`];
  }
  return [t, w.tag];
}
// next week's game is worth betting early: a value tag says a team wins 5c+ more than its price, or the call is already Buy
function earlyValue(g) {
  return (g.watch || []).some(w => w.kind !== "fade" && (S.B.watch?.edges?.[w.tag] ?? 0) > 0 && w.price != null && (g.teams.away.team === w.team ? g.teams.away : g.teams.home).fair >= w.price)
    || [g.teams.away, g.teams.home].some(c => callOf(c) === "Value");
}
function tagBar(g, id) {
  const items = { [g.away]: [], [g.home]: [] };
  for (const w of g.watch || []) {
    const [pickT, why] = tagText(w, g);
    if (!items[pickT]) continue;
    const fade = w.kind === "fade";
    items[pickT].push([fade ? "fade" : "good", pickT, why + (w.inGame ? " · now" : ""), w.early]);
  }
  const e = g.experts;
  if (e?.agree && items[e.agree]) items[e.agree].push(["exp", e.agree, `all ${e.n} experts like ${e.agree}`]);
  if (e?.dogPicks?.length && items[e.dog]) items[e.dog].push(["exp", e.dog, `${e.dogPicks.map(lastName).join(", ")} pick${e.dogPicks.length > 1 ? "" : "s"} underdog ${e.dog}`]);
  if (!items[g.away].length && !items[g.home].length) return "";
  const chips = items[g.away].concat(items[g.home]);
  return `<div class="wban"${id ? ` onclick="toggle('${id}')"` : ""}><div class="wcol">${chips.map(([k, p, x, early]) => `<span class="wchip ${k}"><b>ⓘ ${early ? "Early info" : "Info"} · ${esc(p)}:</b> ${esc(x)}</span>`).join("")}</div></div>`;
}
function watchLine(g) {
  if (!g.watch?.length) return "";
  return `<div class="small" style="margin:8px 0 2px"><b>Watch tags</b> <span class="muted">· tags only, tracked live (see Learning)</span></div>` +
    g.watch.map(w => `<div class="tiny" style="margin-top:2px"><span class="tag info">${esc(w.tag)}</span> <b>${esc(w.team)}</b> · ${esc(w.why)}</div>`).join("");
}
function expertsBlock(g) {
  const e = g.experts;
  if (!e || !e.n) return "";
  const pc = x => x == null ? "" : `${x >= 0 ? "+" : ""}${x.toFixed(1)}%`;
  let h = `<div class="small" style="margin:8px 0 2px"><b>Expert picks</b> <span class="muted">· top ${e.top.length} by profit, ${esc((S.B.experts?.seasons || []).join(" + ") || "this season")}</span></div>`;
  h += e.top.map(r => `<div class="small">#${r.rank} ${esc(r.name)} → <b>${esc(r.team)}</b>${r.score ? ` (${esc(r.score)})` : ""}${r.ats ? ` · ATS ${esc(r.ats)}` : ""} <span class="muted">· ${r.pct}% right, ${pc(r.roi)} profit</span></div>`).join("");
  h += `<div class="small muted">All ${e.n} experts: ${Object.entries(e.count).map(([t, n]) => `${esc(t)} ${n}`).join(" · ")}</div>`;
  for (const r of e.reasons || []) h += `<div class="note small">“${esc(r.text)}” <span class="muted">— ${esc(r.name)}, NFL.com (picked ${esc(r.team || "")})</span></div>`;
  return h + `<div class="tiny muted">Context only. Experts haven't beaten the line yet (see Learning).</div>`;
}
// head-to-head history: this season + last
function h2hHist(g) {
  const H = g.h2h;
  if (!H || !H.meetings?.length) return "";
  const a = g.teams.away.team, h = g.teams.home.team;
  let out = `<div class="small" style="margin:8px 0 2px"><b>Met before</b> <span class="muted">· this season and last</span></div>`;
  H.meetings.slice().reverse().forEach((m, i) => {
    const id = `hh:${g.id}:${i}`;
    const ld = (m.leaders || []).filter(x => x && x !== "tied");
    const led = ld.length === 3 && new Set(ld).size === 1 ? `${ld[0]} led after Q1, Q2 and Q3` : m.leaders?.length ? `led after Q1/Q2/Q3: ${m.leaders.join(", ")}` : "";
    const cov = m.vsLine == null ? "" : m.vsLine === 0 ? "push vs line" : `${m.vsLine > 0 ? a : h} covered`;
    out += `<div class="small u" onclick="toggle('${id}')">${m.season} Wk ${m.week}: <b>${esc(a)} ${m.score[0]}–${m.score[1]} ${esc(h)}</b> · ${esc(led)}${cov ? ` · ${esc(cov)}` : ""}</div>`;
    if (S.open.has(id)) {
      out += `<div class="note small">${m.first ? `First score: ${esc(m.first)}<br>` : ""}${m.quarters?.length ? `By quarter: ${m.quarters.map((q, j) => `Q${j + 1} ${q[0]}–${q[1]}`).join(" · ")}<br>` : ""}${m.favBy != null ? `Line: ${m.favBy > 0 ? `${esc(a)} −${m.favBy}` : m.favBy < 0 ? `${esc(h)} −${-m.favBy}` : "pick'em"}<br>` : ""}Listed starting QBs: ${esc(m.qb?.[0] || "?")} vs ${esc(m.qb?.[1] || "?")}`;
      for (const t of [a, h]) { const p = m.players?.[t]; if (p) out += `<br><b>${esc(t)}</b> (${p.turnovers} TO): ${esc(p.lines.join(" · "))}`; }
      out += `</div>`;
    }
  });
  if (H.changes?.length) out += `<div class="small" style="color:var(--gold)">Since then: ${esc(H.changes.join(" · "))}</div>`;
  return out + `<div class="tiny muted">Context only. Past meetings didn't predict results beyond the line in tests (see Learning).</div>`;
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
  let row = `${tagBar(g, id)}<div class="grow" onclick="toggle('${id}')"><div class="mt sp">${tm(a)}${tm(h)}${spreadTxt(g) ? `<div class="tiny muted" style="margin-top:2px">${esc(spreadTxt(g))}</div>` : ""}${expertsLine(g)}${winLine(g)}${rowGap(g)}</div>
    <div class="rt"><span class="kt">${soon(g.kickoff) || kick(g.kickoff)}</span><span class="pill c-${bc}">${esc(best.team)} ${LBL(bc)}</span></div>
    <span class="chev ${o ? "open" : ""}">›</span></div>`;
  if (o) row += `<div class="card">${gameDetail(g)}</div>`;
  return row;
}
const rank = c => ({ Value: 3, Wait: 2, Sell: 2, Pass: 1 }[c] || 0);
function gameDetail(g) {
  return `<div class="teams2">${betCard(g.teams.away)}${betCard(g.teams.home)}</div>
    ${h2hDetails(g, `${priceChart(g)}${injLine(g)}${wxLine(g)}${muLine(g)}${gradesBlock(g)}${gradeLines(g)}${sitLine(g)}${toLine(g)}${changesLine(g)}${gameCombosLine(g)}${h2hHist(g)}${expertsBlock(g)}`)}`;
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
function liveCard(g) {
  const id = "q:" + g.id;
  const tc = c => {
    const call = callOf(c);
    const ctx = (c.liveLines || []).filter(l => l.kind !== "to" && l.kind !== "pause");
    return `<div class="card bg-${call}" style="margin:6px 0">
      <div class="row">${badge(c.team, "sm")}<b>${esc(c.team)}</b><span class="pill c-${call}">${LBL(call)}</span><span class="sp"></span><span class="hero" style="font-size:28px">${ct(c.price)}</span></div>
      ${verdict(c)}
      <div class="row small" style="margin-top:8px"><span>${fairPay(c, c.liveFair, call === "Wait" ? c.liveBuyAt : c.price, call)}</span><span class="sp"></span>${move(c)}</div>
      ${priceBar(c.price, c.liveFair, c.dayLo, c.dayHi, c.pregamePrice)}
      ${thinLine(c)}${feedLines(c)}
      ${closeTag(c)}
      ${boughtBox({ kind: "single", team: c.team, game: `${c.team} vs ${c.opp}`, gameId: c.gameId, grade: gradeOf(c.liveFair ?? c.fair), call: LBL(call), price: c.price })}
      ${c.dipLine && call !== "Pass" ? `<div class="note">${esc(c.dipLine.replace("Price dropped: now ", "Price fell to ").replace(", was ", " from "))}</div>` : ""}
      ${c.bothOff && call === "Value" ? `<div class="note">${esc(c.bothOff)}</div>` : ""}
      ${call !== "Pass" && call !== "Sell" ? bestLine(c) : ""}
      ${liveInjLines({ ...c, liveLines: ctx.filter(l => l.kind === "inj" || l.kind === "nextq") })}
      ${moreInfo(c, ctx.filter(l => l.kind !== "inj" && l.kind !== "nextq"), false)}
    </div>`;
  };
  const wa = g.teams.away.liveFair, wh = g.teams.home.liveFair;
  const wp = wa != null && wh != null ? `<div class="wpbar"><i style="width:${wa / (wa + wh) * 100}%;background:${esc(COLORS()[g.away] || "#556")}"></i><i style="flex:1;background:${esc(COLORS()[g.home] || "#889")}"></i></div><div class="row tiny muted" style="margin:-6px 0 8px"><span>${pct(wa)} win</span><span class="sp"></span><span>${pct(wh)} win</span></div>` : "";
  const spr = spreadTxt(g) ? `<div class="tiny muted" style="text-align:center;margin:-4px 0 8px">Pregame: ${esc(spreadTxt(g))}${expertsLine(g)}</div>` : "";
  return `<div class="card">${tagBar(g)}${scoreBlock(g)}${driveBox(g)}${spr}${wp}
    <div class="teams2">${tc(g.teams.away)}${tc(g.teams.home)}</div>
    <div class="line u" onclick="toggle('${id}')">Quarters · ${(g.quarters || []).map(q => `Q${q.q} ${q.cumAway}-${q.cumHome}`).join(" · ") || "—"}</div>
    ${S.open.has(id) ? quarterTable(g) : ""}
    ${h2hDetails(g, `${priceChart(g)}${injLine(g)}${muLine(g)}${gradesBlock(g)}${gradeLines(g)}${toLine(g)}${wxLine(g)}${h2hHist(g)}${watchLine(g)}${expertsBlock(g)}`)}</div>`;
}

// ---------- live drive tracker ----------
// Every play straight from ESPN's free game feed (the phone reads it every 15 s while a live card is on screen).
// Field: home end zone on the left, away on the right. x = ESPN yardLine (yards from the home goal line).
S.drv = S.drv || {};
const DS = {   // engine/drive_study.py, nflverse 2016-2025 regular season + playoffs (2,761 games)
  rzMove: 5, lateSwing: 4,
};
async function driveOdds() {
  if (S.dodds !== undefined) return S.dodds;
  S.dodds = null;
  try { S.dodds = (await fetch("data/drive_odds.json?t=" + Date.now()).then(r => r.json())).t; } catch (e) {}
  return S.dodds;
}
function scoreChance(ytez, down, dist) {
  const T = S.dodds;
  if (!T || ytez == null || !(down >= 1 && down <= 4)) return null;
  const yb = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].find(h => ytez <= h) || 100;
  const db = ytez <= dist ? "goal" : dist <= 3 ? "1-3" : dist <= 6 ? "4-6" : dist <= 10 ? "7-10" : "11+";
  const r = T[`${yb}|${down}|${db}`];
  return r ? { td: r[0], fg: r[1] } : null;
}
function playKind(p) {
  const t = (p.type?.text || "").toLowerCase();
  if (/interception|fumble recovery \(opponent\)|fumble return|blocked|safety/.test(t)) return "to";
  if (p.scoringPlay) return "score";
  if (/penalty/.test(t)) return "pen";
  if (/kickoff|punt|field goal|extra point|two-point/.test(t)) return "kick";
  if (/timeout|end period|end of|two-minute|end game/.test(t)) return "skip";
  if (/sack/.test(t)) return "sack";
  if (/incompletion/.test(t)) return "inc";
  if (/pass|reception/.test(t)) return "pass";
  if (/rush/.test(t)) return "run";
  return "other";
}
function playFlags(p, kind) {
  const x = (p.text || "").toLowerCase(), f = [];
  if (p.scoringPlay && /touchdown/.test((p.type?.text || "").toLowerCase() + " " + x)) f.push("TD");
  else if (p.scoringPlay) f.push(/field goal/.test(x) ? "FG" : "Score");
  if (kind === "to") f.push(/interception|intercepted/.test(x) ? "INT" : /fumble/.test(x) ? "Fumble" : "Turnover");
  if (/injur/.test(x)) f.push("Injury");
  if (p.start?.down === 4 && /run|pass|inc|sack/.test(kind)) f.push("4th-down try");
  if (/challenge|replay|reversed|upheld/.test(x)) f.push("Review");
  if (Math.abs(p.statYardage || 0) >= 20 && /run|pass/.test(kind)) f.push("Big play");
  return f;
}
function parseDrives(sum) {
  const comp = sum.header?.competitions?.[0] || {};
  const ab = {}, teams = {};
  for (const c of comp.competitors || []) {
    const t = c.team || {};
    ab[t.id] = t.abbreviation;
    teams[t.abbreviation] = { name: (t.name || t.nickname || t.abbreviation || "").toUpperCase(), color: t.color ? "#" + t.color : null,
      alt: t.alternateColor ? "#" + t.alternateColor : null, logo: (t.logos || [])[0]?.href || null };
  }
  const wp = {};
  for (const w of sum.winprobability || []) wp[w.playId] = w.homeWinPercentage;
  const d = sum.drives || {};
  const all = [...(d.previous || [])];
  if (d.current && !all.some(x => x.id === d.current.id)) all.push(d.current);
  const plays = [];
  const drives = all.map(dr => {
    const ps = (dr.plays || []).map(p => {
      const kind = playKind(p);
      return { id: p.id, kind, flags: playFlags(p, kind), text: p.text || "", q: p.period?.number, clock: p.clock?.displayValue || "",
        team: ab[p.start?.team?.id] || dr.team?.abbreviation || "", yds: p.statYardage,
        x0: p.start?.yardLine, x1: p.end?.yardLine, dd: p.start?.shortDownDistanceText || "", spot: p.start?.possessionText || "",
        end: { team: ab[p.end?.team?.id] || "", down: p.end?.down, dist: p.end?.distance, ytez: p.end?.yardsToEndzone, x: p.end?.yardLine },
        wp: wp[p.id], t: p.wallclock ? Date.parse(p.wallclock) : null };
    }).filter(p => p.kind !== "skip");
    plays.push(...ps);
    return { id: dr.id, team: dr.team?.abbreviation || "", desc: dr.description || "", result: dr.displayResult || dr.result || "",
      plays: ps, done: dr.id !== d.current?.id };
  });
  for (let i = 1; i < plays.length; i++) if (plays[i].wp != null && plays[i - 1].wp != null) plays[i].dwp = plays[i].wp - plays[i - 1].wp;
  return { drives, plays, teams, at: Date.now() };
}
async function pollDrives(force) {
  if (!S.B || (!document.querySelector(".drv") && !force) || document.visibilityState !== "visible") return;
  await driveOdds();
  const lv = S.B.games.filter(g => g.state === "in");
  await Promise.all(lv.map(async g => {
    try {
      const sum = await fetch(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=${g.id}&t=${Date.now()}`).then(r => r.json());
      S.drv[g.id] = parseDrives(sum);
      const el = document.getElementById("drv-" + g.id);
      if (el) el.outerHTML = driveBox(g);
    } catch (e) {}
  }));
}
const KLBL = { run: "Run", pass: "Pass", inc: "Incomplete", sack: "Sack", pen: "Penalty", to: "Turnover", score: "Score", kick: "Kick", other: "Play" };
function shortPlay(p) {
  const t = p.text.replace(/^\([^)]*\)\s*/, "").replace(/\s*\([^)]*\)\.?$/, "").replace(/\s+/g, " ");
  return t.length > 90 ? t.slice(0, 88) + "…" : t;
}
const homeWP = (g, team, v) => team === g.home ? v : 1 - v;
function wpTag(g, p) {
  if (p.wp == null) return "";
  const who = p.team === g.away ? g.away : g.home;
  const v = homeWP(g, who, p.wp), dv = p.dwp == null ? null : (who === g.home ? p.dwp : -p.dwp);
  const big = dv != null && Math.abs(dv) >= 0.05;
  return ` <span class="wpd ${big ? "big" : ""}">${esc(who)} ${Math.round(v * 100)}%${dv != null && Math.round(dv * 100) ? ` (${dv > 0 ? "+" : ""}${Math.round(dv * 100)})` : ""}</span>`;
}
const flagChips = p => (p.flags || []).map(f => `<span class="pf f-${f.split(/[ -]/)[0].toLowerCase()}">${esc(f)}</span>`).join("");
function contrast(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || ""); if (!m) return "#fff";
  const n = parseInt(m[1], 16), l = (0.299 * (n >> 16) + 0.587 * (n >> 8 & 255) + 0.114 * (n & 255)) / 255;
  return l > 0.6 ? "#111" : "#fff";
}
function ezColors(T, team, fb) {
  const t = T?.[team] || {}, bg = t.color || fb || "#334";
  const alt = t.alt && t.alt.toLowerCase() !== bg.toLowerCase() ? t.alt : null;
  return { bg, ink: contrast(bg), alt };
}
function fieldSvg(g, D, dr, sit) {
  const C = COLORS(), L = LOGOS(), T = D.teams || {};
  const W = 380, EZ = 34, Y = W - 2 * EZ, sx = y => EZ + (Math.max(0, Math.min(100, y)) / 100) * Y;
  const ps = (dr?.plays || []).filter(p => p.x0 != null && p.x1 != null && p.kind !== "kick").slice(-8);
  const lane = 14, top = 20, H = Math.max(112, top + ps.length * lane + 22);
  const hz = ezColors(T, g.home, C[g.home]), az = ezColors(T, g.away, C[g.away]);
  const logo = t => T[t]?.logo || L[t];
  let s = `<svg class="field" viewBox="0 0 ${W} ${H}" role="img" aria-label="Field with this drive's plays">
    <defs><linearGradient id="turf-${g.id}" x1="0" x2="1"><stop offset="0" stop-color="#1d5a32"/><stop offset=".5" stop-color="#23693a"/><stop offset="1" stop-color="#1d5a32"/></linearGradient>
    <clipPath id="fc-${g.id}"><rect x="0" y="0" width="${W}" height="${H}" rx="9"/></clipPath></defs><g clip-path="url(#fc-${g.id})">
    <rect x="0" y="0" width="${W}" height="${H}" fill="url(#turf-${g.id})"/>`;
  for (let y = 0; y < 100; y += 10) if ((y / 10) % 2) s += `<rect x="${sx(y)}" y="0" width="${sx(y + 10) - sx(y)}" height="${H}" fill="rgba(255,255,255,.035)"/>`;
  const ez = (x, z, team, rot) => `<rect x="${x}" y="0" width="${EZ}" height="${H}" fill="${esc(z.bg)}"/>` +
    (z.alt ? `<rect x="${rot > 0 ? x + 2 : x + EZ - 4}" y="0" width="2" height="${H}" fill="${esc(z.alt)}" opacity=".9"/>` : "") +
    `<text x="${x + EZ / 2}" y="${H / 2}" class="ezt" fill="${z.ink}" transform="rotate(${rot} ${x + EZ / 2} ${H / 2})" textLength="${Math.min(H - 16, (T[team]?.name || team).length * 9)}" lengthAdjust="spacingAndGlyphs">${esc(T[team]?.name || team)}</text>`;
  s += ez(0, hz, g.home, -90) + ez(W - EZ, az, g.away, 90);
  s += `<line x1="${EZ}" y1="0" x2="${EZ}" y2="${H}" class="gl"/><line x1="${W - EZ}" y1="0" x2="${W - EZ}" y2="${H}" class="gl"/>`;
  for (let y = 5; y < 100; y += 5) s += `<line x1="${sx(y)}" y1="0" x2="${sx(y)}" y2="${H}" class="${y % 10 ? "yl5" : "yl"}"/>`;
  for (let y = 1; y < 100; y++) if (y % 5) s += `<line x1="${sx(y)}" y1="2" x2="${sx(y)}" y2="5" class="hm"/><line x1="${sx(y)}" y1="${H - 5}" x2="${sx(y)}" y2="${H - 2}" class="hm"/>`;
  for (let y = 10; y < 100; y += 10) s += `<text x="${sx(y)}" y="15" class="yn">${y <= 50 ? y : 100 - y}</text><text x="${sx(y)}" y="${H - 8}" class="yn">${y <= 50 ? y : 100 - y}</text>`;
  const mid = logo(g.home);
  if (mid) s += `<image href="${esc(mid)}" x="${sx(50) - 22}" y="${H / 2 - 22}" width="44" height="44" opacity=".22"/>`;
  if (sit?.x != null) {
    if (sit.rz) s += `<rect x="${sit.toRight ? sx(80) : sx(0)}" y="0" width="${sx(20) - sx(0)}" height="${H}" class="rzz"/>`;
    s += `<line x1="${sx(sit.x)}" y1="0" x2="${sx(sit.x)}" y2="${H}" class="los"/>`;
    if (sit.fd != null && sit.fd > 0 && sit.fd < 100) s += `<line x1="${sx(sit.fd)}" y1="0" x2="${sx(sit.fd)}" y2="${H}" class="fdl"/>`;
  }
  ps.forEach((p, i) => {
    const y = top + 4 + i * lane, a = sx(p.x0), b = sx(p.x1), dir = b >= a ? 1 : -1;
    s += `<line x1="${a}" y1="${y}" x2="${b}" y2="${y}" class="pl k-${p.kind}"/>`;
    s += Math.abs(b - a) > 4 ? `<path d="M${b} ${y} l${-6 * dir} -4 v8 z" class="ph k-${p.kind}"/>` : `<circle cx="${a}" cy="${y}" r="3" class="ph k-${p.kind}"/>`;
  });
  if (sit?.x != null) {
    const bl = logo(sit.team);
    s += `<g transform="translate(${sx(sit.x)} ${H - 22})"><ellipse rx="7.5" ry="4.5" class="ball"/><line x1="-3" x2="3" y1="0" y2="0" stroke="#fff" stroke-width="1"/></g>`;
    if (bl) s += `<image href="${esc(bl)}" x="${sx(sit.x) + (sit.toRight ? -26 : 10)}" y="${H - 31}" width="16" height="16"/>`;
  }
  return s + `</g></svg>`;
}
function winChart(g, D) {
  // x = play number, with older plays squeezed so the latest 30 plays get half the width
  let pts = D.plays.filter(p => p.wp != null);
  if (pts.length < 4) return "";
  const zoom = S.wz?.[g.id], qNow = pts[pts.length - 1].q;
  if (zoom) { const z = pts.filter(p => p.q === qNow); if (z.length >= 4) pts = z; }
  const n = pts.length, W = 340, H = 104, P = 24, R = 46;
  const k = n > 45 ? n - 30 : 0;   // Rick's idea: squeeze older plays, the last 30 get half the width
  const fx = i => !k ? i / Math.max(1, n - 1) : i <= k ? 0.5 * i / k : 0.5 + 0.5 * (i - k) / Math.max(1, n - 1 - k);
  const x = i => P + fx(i) * (W - P - R), y = v => 8 + (100 - v) / 100 * (H - 20);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.wp * 100).toFixed(1)}`).join("");
  // Kalshi price from our own checks, placed at the play nearest in time
  const ts = pts.map(p => p.t);
  const near = t => { let b = -1, bd = Infinity; ts.forEach((v, i) => { if (v && Math.abs(v - t) < bd) { bd = Math.abs(v - t); b = i; } }); return bd < 15 * 60000 ? b : -1; };
  const K = (g.hist || []).filter(r => r[3] != null).map(r => [near(Date.parse(r[0])), r[3]]).filter(k => k[0] >= 0);
  const kd = K.map(([i, v]) => `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.2" class="kdot"/>`).join("");
  const grid = [25, 50, 75].map(v => `<line x1="${P}" x2="${W - R + 4}" y1="${y(v)}" y2="${y(v)}" class="cg"/><text x="2" y="${y(v) + 3}" class="ct">${v}%</text>`).join("");
  // quarter breaks
  let qs = "";
  pts.forEach((p, i) => { if (i && p.q !== pts[i - 1].q) qs += `<line x1="${x(i - .5)}" x2="${x(i - .5)}" y1="6" y2="${H - 10}" class="qb"/><text x="${x(i - .5) + 2}" y="${H - 2}" class="ct">${p.q >= 5 ? "OT" : "Q" + p.q}</text>`; });
  // big plays (10+ pt swings): biggest first, skip any that would sit within 12px of one already shown
  const keep = [];
  pts.map((p, i) => [Math.abs(p.dwp || 0), i]).filter(b => b[0] >= 0.10).sort((a, b) => b[0] - a[0])
    .forEach(([, i]) => { if (i < n - 1 && keep.every(j => Math.abs(x(j) - x(i)) >= 12)) keep.push(i); });
  const big = keep.map(i => `<circle cx="${x(i).toFixed(1)}" cy="${y(pts[i].wp * 100).toFixed(1)}" r="3.2" class="sdot"><title>${esc(pts[i].flags[0] || KLBL[pts[i].kind] || "Big play")}: ${esc(shortPlay(pts[i]))}</title></circle>`).join("");
  const last = pts[pts.length - 1], lv = Math.round(last.wp * 100), lk = K.length ? K[K.length - 1][1] : null;
  const now = `<circle cx="${x(n - 1)}" cy="${y(lv)}" r="4.5" class="nowd"/><text x="${x(n - 1) + 8}" y="${y(lv) + 4}" class="nowt">${lv}%</text>` +
    (lk != null ? `<text x="${x(n - 1) + 8}" y="${Math.min(H - 4, Math.max(10, y(lk) + 4 + (Math.abs(y(lk) - y(lv)) < 12 ? 12 : 0)))}" class="nowk">${Math.round(lk)}¢</text>` : "");
  return `<div class="wch"><div class="row tiny muted" style="margin:6px 0 2px;gap:6px"><span><b style="color:var(--ink)">${esc(g.home)} win chance</b> · <span style="color:var(--fair)">━</span> ESPN · <span class="kd">●</span> Kalshi price · <span class="sd">○</span> big play</span><span class="sp"></span><button class="zbtn" onclick="S.wz=S.wz||{};S.wz['${g.id}']=!S.wz['${g.id}'];render()">${zoom ? "Whole game" : "This quarter"}</button></div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="ESPN win chance per play and Kalshi price">${grid}${qs}<path d="${line}" fill="none" stroke="var(--fair)" stroke-width="1.8" stroke-linejoin="round"/>${kd}${big}${now}</svg></div>`;
}
function clockSecs(c) { const m = /^(\d+):(\d+)$/.exec(c || ""); return m ? +m[1] * 60 + +m[2] : null; }
function toDots(n) { return n == null ? "" : `<span class="tos" title="${n} timeouts left">${[0, 1, 2].map(i => `<i class="${i < n ? "on" : ""}"></i>`).join("")}</span>`; }
function driveBox(g) {
  const D = S.drv[g.id];
  if (!D) return `<div class="drv" id="drv-${g.id}"><div class="tiny muted">Loading plays from ESPN…</div></div>`;
  const last = D.drives[D.drives.length - 1];
  const dr = last && last.plays.some(p => p.kind !== "kick") ? last : D.drives[D.drives.length - 2] || last;
  const real = D.plays.filter(p => p.kind !== "other" || p.text);
  const lp = real[real.length - 1];
  // where the ball is now: the last play's end spot, down and distance (ESPN)
  let sit = null;
  if (lp && lp.end.x != null) {
    const off = lp.end.team || g.possession || lp.team, toRight = off === g.home;   // home drives toward the away end zone (right)
    const dist = lp.end.dist, ytez = lp.end.ytez;
    sit = { x: lp.end.x, team: off, toRight, ytez, down: lp.end.down, dist,
      fd: dist && ytez > dist ? lp.end.x + (toRight ? dist : -dist) : null, rz: ytez > 0 && ytez <= 20 };
  }
  const dd = sit && sit.down >= 1 && sit.down <= 4 ? `${["", "1st", "2nd", "3rd", "4th"][sit.down]} & ${sit.ytez <= sit.dist ? "Goal" : sit.dist}` : (g.downDist || "");
  const spotTxt = sit && sit.ytez != null ? (sit.ytez === 50 ? "50" : sit.ytez < 50 ? `${sit.team === g.home ? g.away : g.home} ${sit.ytez}` : `${sit.team} ${100 - sit.ytez}`) : "";
  const sc = sit ? scoreChance(sit.ytez, sit.down, sit.dist) : null;
  const secs = clockSecs(g.clock), twoMin = (g.period === 2 || g.period >= 4) && secs != null && secs <= 120;
  const head = `<div class="drvh"><div class="row" style="gap:6px;flex-wrap:wrap"><b class="dd">${esc(dd || "Between plays")}</b>${spotTxt ? `<span class="small muted">at ${esc(spotTxt)}</span>` : ""}${sit ? `<span class="small muted">· ${esc(sit.team)} ball</span>` : ""}${sit?.rz ? `<span class="tag rz">Red zone</span>` : ""}${twoMin ? `<span class="tag twom">Two-minute drill</span>` : ""}</div>
    <div class="row tiny muted" style="gap:8px;flex-wrap:wrap;margin-top:3px">${g.toA != null ? `<span>${esc(g.away)} ${toDots(g.toA)}</span><span>${esc(g.home)} ${toDots(g.toH)}</span>` : ""}${sc ? `<span>This drive: <b style="color:var(--ink)">TD ${sc.td}%</b> · FG ${sc.fg}%</span>` : ""}<span class="sp"></span><span>${dr ? esc(`${dr.team} drive: ${dr.desc || dr.plays.length + " plays"}${dr.done && dr.result ? " · " + dr.result : ""}`) : ""}</span></div></div>`;
  // banners: big swing on the last play, other team in the red zone
  let ban = "";
  const sw = [...real].reverse().find(p => p.dwp != null);
  if (sw && Math.abs(sw.dwp) >= 0.10 && Date.now() - (sw.t || 0) < 10 * 60000) {
    const gain = sw.dwp > 0 ? g.home : g.away, to = Math.round(homeWP(g, gain, sw.wp) * 100), from = Math.round(homeWP(g, gain, sw.wp - sw.dwp) * 100);
    const late = g.period >= 4 && secs != null && secs < 600;
    ban += `<div class="dban swing"><b>Big swing: ${esc(gain)} ${from}% → ${to}%</b> on ${sw.flags[0] === "TD" ? "a touchdown" : "a " + esc((sw.flags[0] || KLBL[sw.kind] || "play").toLowerCase())}. Check the Kalshi price before it moves.${late ? ` <span class="muted">Late swings, 2016–25: the team that gained won ~${DS.lateSwing} pts less often than the new win % said. Info only.</span>` : ""}</div>`;
  }
  if (sit?.rz) {
    const def = sit.team === g.home ? g.away : g.home;
    ban += `<div class="dban hold"><b>${esc(def)} backers, hold off?</b> ${esc(sit.team)} is in the red zone. Prices usually move about ${DS.rzMove}¢ by the end of a red-zone drive, either way. Buying now or after was equally fair in 2016–25 tests, so waiting only avoids the jump.</div>`;
  }
  const recent = real.filter(p => p.kind !== "other").slice(-6).reverse();
  const tick = recent.map(p => `<span class="tk k-${p.kind}"><i></i><b>${esc(p.team)}</b> ${flagChips(p)}${esc(KLBL[p.kind])}${p.yds != null && /run|pass|sack|pen/.test(p.kind) ? ` ${p.yds > 0 ? "+" : ""}${p.yds}` : ""}: ${esc(shortPlay(p))}${wpTag(g, p)}</span>`).join("");
  const id = "dl:" + g.id;
  const list = S.open.has(id) ? `<div class="drvl">${(dr?.plays || []).filter(p => shortPlay(p)).slice().reverse().map(p => `<div class="pp"><span class="dotk k-${p.kind}"></span><span class="tiny muted">Q${p.q} ${esc(p.clock)} · ${esc(p.dd || "")}${p.spot ? " at " + esc(p.spot) : ""}</span> ${flagChips(p)}<br><span class="small">${esc(shortPlay(p))}</span>${wpTag(g, p)}</div>`).join("")}</div>` : "";
  return `<div class="drv" id="drv-${g.id}">${head}${ban}${fieldSvg(g, D, dr, sit)}
    <div class="legend tiny muted">${[["k-run", "Run"], ["k-pass", "Pass"], ["k-inc", "Incomplete"], ["k-sack", "Sack"], ["k-pen", "Penalty"], ["k-to", "Turnover"], ["fd", "1st down"], ["los", "Ball spot"]].map(([k, t]) => `<span><i class="lg ${k}"></i>${t}</span>`).join("")}</div>
    ${recent.length ? `<div class="ticker" onclick="toggle('${id}')"><div class="tkin">${tick}${tick}</div></div>` : ""}
    ${winChart(g, D)}
    <div class="line u tiny" onclick="toggle('${id}')">${S.open.has(id) ? "Hide" : "Show"} every play this drive · win % from ESPN</div>${list}</div>`;
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
      <div class="row" style="margin-top:12px"><span class="hero">${ct(c.price)}</span><span class="sp"></span><span class="small">${move(c)}</span></div><div class="sub">${c.call === "Wait" ? `Buy at ${ct(c.buyAt)} · ` : ""}Fair ${ct1(c.fair)}</div>
      <div class="small" style="margin-top:6px"><b>+${ct(100 - buy)}</b> if it wins</div>${bestLine(c)}</div>`;
    }).join("")}</div>`;
  }
  const vw = pre.filter(c => ["Value", "Wait"].includes(c.call)).filter(filt).sort((a, b) => rank(b.call) - rank(a.call) || b.edge - a.edge);
  const waits = vw.filter(c => c.call === "Wait");
  const closest = pre.filter(c => c.edge != null).sort((a, b) => b.edge - a.edge)[0];
  const need = c => Math.max(1, Math.ceil(15 - c.edge));
  const hint = closest ? `Closest: ${closest.team} at ${ct(closest.price)} — it would need to drop about ${need(closest)}¢ to be a Buy. ${S.B.nextCheck || ""}` : S.B.nextCheck;
  const sells = pre.filter(c => callOf(c) === "Sell").filter(filt);
  const quiet = !vw.length && !sells.length && !top.length;
  const cut = h.indexOf('<div class="stats">');
  if (quiet) {   // nothing to buy: one short line, then the games
    h = h.slice(0, cut) + `<div class="quiet"><b>Nothing to buy right now.</b> <span class="muted">${esc(hint || "")}</span></div>` + h.slice(h.indexOf('<div class="searchw">'), h.indexOf('<div class="chips">'));
  }
  const picksAt = quiet ? h.length : h.indexOf("<h2>Top 3 today</h2>") >= 0 ? h.indexOf("<h2>Top 3 today</h2>") : h.length;
  if (!quiet) h += `<h2>Best bets</h2>${vw.length ? vw.map(c => betCard(c, { vs: 1 })).join("") : NOREC(hint)}`;
  if (sells.length) h += `<h2>Sell if you own it</h2>${sells.map(c => betCard(c, { vs: 1 })).join("")}`;
  if (!quiet) h += `<h2>Wait list</h2>${waits.length ? waits.map(c => `<div class="grow" onclick="openBreakdown('${esc(c.key)}')">${badge(c.team, "sm")}<b>${esc(c.team)}</b><span class="small">now ${ct(c.price)}</span><span class="sp"></span><span class="small c-Wait">buy at ${ct(c.buyAt)} → +${ct(100 - c.buyAt)}</span></div>`).join("") : NOREC(closest ? `Closest: ${closest.team} at ${ct(closest.price)} — a Wait needs it about ${Math.max(1, Math.ceil(8 - closest.edge))}¢ cheaper` : "")}`;
  const games = S.B.games.filter(g => filt(g.teams.away) || filt(g.teams.home) || (S.chip === "All" && !S.q));
  const up = games.filter(g => g.state === "pre").sort(byKick), lvg = games.filter(g => g.state === "in").sort(byKick), fin = games.filter(g => g.state === "post").sort(byKick);
  const nw = (S.B.nextWeek || []).filter(g => filt(g.teams.away) || filt(g.teams.home) || (S.chip === "All" && !S.q));
  const es = S.B.earlyStudy || {};
  const nwVal = nw.filter(earlyValue), nwRest = nw.filter(g => !earlyValue(g));
  const nextSec = `<h2>Next week · worth betting early <span class="cnt">${nwVal.length}</span></h2>
    <div class="tiny muted" style="margin:-4px 0 8px">Early: injury news can still move these. ${es.n ? `So far the early price was ${es.avg > 0 ? `${es.avg}¢ cheaper` : `${-es.avg}¢ dearer`} than at kickoff on average (${es.cheaper} cheaper, ${es.dearer} dearer, ${es.n} teams).` : "We're tracking whether early prices beat kickoff prices."}</div>
    ${nw.length ? (nwVal.length ? `<div class="glist">${nwVal.map(gameRow).join("")}</div>` : NOREC("No early value yet: no team wins 5¢+ more than its price")) +
      (nwRest.length ? `<details class="others"${S.othersOpen ? " open" : ""} ontoggle="S.othersOpen = this.open"><summary>Other games next week (${nwRest.length}) · no early value</summary><div class="glist">${nwRest.map(gameRow).join("")}</div></details>` : "")
      : NOREC("Kalshi hasn't listed next week's games yet")}`;
  h += `<h2>All games this week <span class="cnt">${games.length}</span></h2>${gradeKey()}${games.length ? `${lvg.map(gameRow).join("")}${up.length ? `<div class="glist${quiet ? " wide" : ""}">${up.map(g => `<div class="gitem${S.open.has("g:" + g.id) ? " open" : ""}">${gameRow(g)}</div>`).join("")}</div>` : ""}${pastGames(fin, "pre")}` : NOREC()}`;
  // desktop: games on the left, picks on the right (one column on a phone, picks first)
  const picksEnd = h.indexOf("<h2>All games this week");
  const head = h.slice(0, picksAt), picks = h.slice(picksAt, picksEnd), gamesH = h.slice(picksEnd);
  if (quiet) return `${head}${gamesH}${nextSec}`;   // nothing to buy: games use the full width (two columns on a computer)
  return `${head}<div class="cols"><div class="colR">${picks}</div><div class="colL">${gamesH}${nextSec}</div></div>`;
}
function live() {
  const lv = S.B.games.filter(g => g.state === "in").sort(byKick);
  const fin = S.B.games.filter(g => g.state === "post");
  const al = S.B.alerts || [];
  let h = `<div class="ptitle">Live</div><div class="row"><div class="psub">${lv.length ? `${lv.length} game${lv.length > 1 ? "s" : ""} in progress` : `<b>No games live yet.</b> ${esc(nextKick() || "")}`}</div><span class="sp"></span><button class="btn" onclick="refreshNow(this)">↻ Refresh</button></div>
    ${lv.length ? `<div class="tiny muted" style="margin:-4px 0 8px">${S.scoreAt ? "Score: live from ESPN · " : ""}Prices &amp; calls: ${esc(ago(S.B.generatedAt))}, checked every 6 min</div>` : ""}` + banners();
  if (al.length) h += `<h2>Live dip alerts</h2>${al.length ? al.map(a => `<div class="card bg-Value"><div class="row"><b>${esc(a.team)}</b><span class="small muted">${esc(a.game)}</span><span class="sp"></span><span class="hero" style="font-size:26px">${ct(a.price)}</span></div><div class="small"><b>+${ct(a.profit)} if it wins</b> · ${/^[ABCF]$/.test(a.confidence) ? `grade ${grd(a.confidence, 1)}` : esc(a.confidence)}</div><div class="why">${esc(a.why)}</div></div>`).join("") : NOREC(lv.length ? "" : S.B.nextCheck)}`;
  if (lv.length) h += `<h2>Live games</h2>${lv.map(liveCard).join("")}`;
  if (fin.length) h += `<div style="margin-top:14px">${pastGames(fin.slice().sort(byKick), "live")}</div>`;
  return h;
}
function nextKick() {
  const n = S.B.games.filter(g => g.state === "pre").sort((a, b) => a.kickoff.localeCompare(b.kickoff))[0];
  return n ? `Next kickoff: ${n.short} ${kick(n.kickoff)}` : "";
}

// ---------- combos ----------
// estimated combo quote vs legs multiplied (same as engine/config.combo_markup) — an estimate, check Robinhood
// review 2026-11-23: real combo quotes run ~26% above the legs multiplied (Kalshi, Sept 2026 report) -- learned from
// Rick's own Robinhood quotes (saved on this device), shrunk toward 26% until there are several
const MK0 = 1.26, MK_K = 5;
const quotes = () => { try { return JSON.parse(localStorage.getItem("quotes") || "[]"); } catch (e) { return []; } };
// Markup shrinks as the combo gets pricier (Rick's quote 2026-11-24: JAX+CIN+DAL legs 61.2¢, Robinhood 60.1¢).
// ~26% on 1¢ longshots, ~20% at 8¢, ~1.5% at 61¢; then scaled by real quotes (Rick's saved + the app's shared list).
const mkCurve = c => 1 + ((S.B?.comboMarkup || MK0) - 1) * Math.pow(1 - Math.min(99, Math.max(0, c)) / 100, 3);
const allQuotes = () => [...(S.B?.comboQuotes || []), ...quotes()].filter(x => x.legs > 0 && x.quote > 0);
const mkFactor = () => { const q = allQuotes(); return q.length ? (MK_K + q.reduce((a, x) => a + x.quote / (x.legs * mkCurve(x.legs)), 0)) / (MK_K + q.length) : 1; };
const mkLearned = (c = 8) => mkCurve(c) * mkFactor();
const markup = (n, c = 8) => n < 2 ? 1 : Math.max(mkLearned(c), n <= 10 ? 1 : 1.22 * Math.pow(1.08, n - 10));
window.saveQuote = () => {
  const el = document.getElementById("rhq"), v = parseFloat(el?.value);
  if (!(v > 0 && v < 100) || !S.lastLegs) return;
  const q = quotes(); q.push({ legs: S.lastLegs, quote: v, n: S.lastN, at: new Date().toISOString() });
  try { localStorage.setItem("quotes", JSON.stringify(q.slice(-50))); } catch (e) {}
  render();
};
window.clearQuotes = () => { try { localStorage.removeItem("quotes"); } catch (e) {} render(); };
function comboTotals(legs) {
  const hit = legs.reduce((p, l) => p * l.fair / 100, 1) * 100;
  const cost = legs.reduce((p, l) => p * l.price / 100, 1) * 100;
  const mk = markup(legs.length, cost), est = cost * mk;
  return { hit, cost, est, mk, maxPay: hit - 2, edge: hit - 2 - est };
}
function tierTag(cost) {
  if (cost < 2) return `<span class="tag look">under 2¢ — look, don't buy</span>`;
  if (cost <= 15) return `<span class="tag good">good price</span>`;
  if (cost <= 20) return "";
  return `<span class="tag above">above your usual range</span>`;
}
function comboCard(cat, k, res, safe) {
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
  const vtS = safe && vc === "Wait" ? `About a fair price — OK if you want a likely winner. Pay ${ct1(t.maxPay)} or less` : vt;
  return `<div class="card bg-${vc}">
    <div class="row"><span class="pill c-${vc}">${legs.length}-leg${S.comboEdits[ek] ? " · edited" : ""}</span><span class="sp"></span>${tierTag(t.est)}${hitChip(t.hit)}</div>
    <div class="verdict v-${vc}">${esc(vtS)}</div>
    ${safe ? `<div class="safehit"><b>${pct(t.hit)}</b><span>chance every leg wins</span></div>` : ""}
    ${stake5(t.est)}
    <div class="row" style="margin-top:12px;align-items:flex-end"><span class="hero">${t.mk > 1 ? "≈" : ""}${ct1(t.est)}</span><span class="sp"></span><span class="small" style="text-align:right"><b class="c-Value">+${ct1(100 - t.est)}</b> if it wins</span></div>
    <div class="mpbar"><div class="cost ${t.est > t.maxPay ? "over" : ""}" style="width:${w}%"></div><div class="max" style="left:calc(${mx}% - 1px)"></div></div>
    <div class="small" style="margin-top:8px"><b>Pay no more than ${ct1(t.maxPay)} for the combo.</b> ${t.mk > 1 ? `<span class="muted">Teams' prices multiplied ${ct1(t.cost)} + about ${Math.round((t.mk - 1) * 100)}% Robinhood combo markup.</span>` : `<span class="muted">Teams' prices multiplied: ${ct1(t.cost)}.</span>`}</div>
    <div class="kpis"><div><b>${pct(t.hit)}</b><span>Hits</span></div><div><b>${ct1(t.maxPay)}</b><span>Max pay</span></div><div><b class="${t.edge >= 0 ? "c-Value" : "bad"}">${t.edge >= 0 ? "+" : ""}${ct1(t.edge)}</b><span>Edge</span></div></div>
    <div style="margin-top:8px">${legs.map((l, i) => [l, i]).sort((x, y) => legRank(x[0], y[0])).map(([l, i]) => `<div class="leg" onclick="swapLeg('${ek}',${i})">${badge(l.team, "sm")}<div style="min-width:0"><b>${esc(l.team)}</b> <span class="small muted">vs ${esc(l.opp)}${l.state === "in" ? " · live" : ""}</span><br>${(l.tags || []).map(x => `<span class="tag ${x === "Shoe-in" ? "shoe" : ""}">${esc(x)}</span>`).join("")}</div><span class="sp"></span><span class="small muted">${pct(l.fair)}</span>${grd(gradeOf(l.fair), 1)}<span class="p">${ct(l.price)}</span>${edit && legs.length > 2 ? `<button class="x" onclick="event.stopPropagation();dropLeg('${ek}',${i})" aria-label="Remove">✕</button>` : ""}</div>`).join("")}</div>
    ${boughtBox({ kind: "combo", team: legs.map(l => l.team).join("+"), game: `${legs.length}-team combo`, legs: legs.map(l => ({ team: l.team, gameId: l.gameId })), grade: gradeOf(t.hit, COMBO_CUTS), price: t.est })}
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
  const alts = (S.B.combos.pool || []).filter(l => !used.has(l.gameId)).sort(legRank);
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
// combo from watch-tag legs only: tested win % beats the price by 5c+ (info only, calls unchanged)
function watchCombo(k) {
  const W = S.B.combos.watch || {};
  const wk = W[String(k)] ? String(k) : Object.keys(W).filter(x => W[x]?.combo).sort((a, b) => b - a)[0];
  let h = `<h2>Watch-tag combo${wk ? ` — ${wk} legs` : ""}</h2><div class="small muted" style="margin:-4px 0 8px">Only legs whose tested win % beats their price by ${W.gap || 5}¢+ (watch tags), most likely to win first. Tags are info only — check the call on each leg.</div>`;
  h += wk ? `<div class="safehit"><b>${W[wk].est}%</b><span>our chance every leg wins · costs about ${W[wk].cost}¢</span></div>${comboCard("watch", wk, W[wk], true)}` : NOREC(`${W.legs || 0} leg${W.legs === 1 ? "" : "s"} win 5¢+ more than their price right now — need 2`);
  const N = S.B.combos.watchNext || {};
  const nk = Object.keys(N).filter(x => N[x]?.combo).sort((a, b) => b - a)[0];
  if (nk) h += `<h2>Next week · early watch-tag combo — ${nk} legs</h2><div class="small muted" style="margin:-4px 0 8px">Same rule on next week's early prices and injury reports. Early: news can still change these.</div><div class="safehit"><b>${N[nk].est}%</b><span>our chance every leg wins · costs about ${N[nk].cost}¢</span></div>${comboCard("watchNext", nk, N[nk], true)}`;
  return h;
}
const ctabTop = () => `<button class="${(S.ccat || "top") === "top" ? "on" : ""}" onclick="setCombo('top')">Top picks</button>`;

// combo badge: letter grade from its real hit chance + "1 in N"
const hitChip = hit => { const n = Math.max(1, Math.round(100 / Math.max(hit, 0.1))); return `${grd(gradeOf(hit, COMBO_CUTS))}<span class="cconf">${n <= 1 ? "Hits almost always" : `Hits about 1 in ${n}`}</span>`; };
// Rick's combo habit: a $5 bonus bet (never more than $10)
function stake5(cost) {
  if (!cost || cost <= 0) return "";
  const n = Math.floor(500 / (cost + 2)), back = n * 1, profit = back - 5;   // about 2c a contract in fees (same as the app's fee buffer)
  return `<div class="small"><b>$5 → about ${n} contracts → wins about $${back.toFixed(0)}</b> <span class="muted">(profit about $${profit.toFixed(0)} after fees)${cost > 10 ? " · over 10¢: not a bonus bet" : ""}</span></div>`;
}
// three big numbers on every combo: chance, cost, what $5 wins
function big3(hit, cost) {
  const n = cost > 0 ? Math.floor(500 / (cost + 2)) : 0;
  return `<div class="big3"><div><b>${pct(hit)}</b><span>chance it hits</span></div><div><b>${ct1(cost)}</b><span>cost</span></div><div><b>${n ? "$" + n : "—"}</b><span>$5 wins</span></div></div>`;
}
const legHead = `<div class="leghead"><span>Team</span><span class="sp"></span><span>Our chance</span><span>Price</span></div>`;
const comboWarn = () => `<div class="quiet small"><b>Check Robinhood's real price first.</b> <span class="muted">Cheap combos there cost more than the teams' prices multiplied (we add about ${Math.round((markup(2, 8) - 1) * 100)}% at 8¢); pricey favourite combos are close to the product (your 60.1¢ JAX+CIN+DAL quote). Skip a combo if Robinhood's price is 10%+ above our cost.</span></div>${comboKey()}`;
function topCard(c, i) {
  return `<div class="card">
    <div class="row"><b>#${i + 1} · ${c.size} teams</b><span class="sp"></span>${hitChip(c.hit)}</div>
    ${big3(c.hit, c.cost)}
    <div class="tiny muted">${c.hit >= c.cost + 2 ? `Our chance beats the cost by ${(c.hit - c.cost).toFixed(1)}¢` : c.hit >= c.cost ? "About a fair price" : `Costs ${(c.cost - c.hit).toFixed(1)}¢ more than our chance`}${c.cost > 10 ? " · over 10¢: not a bonus bet" : ""}${c.reused ? ` · shares ${c.reused} game${c.reused > 1 ? "s" : ""} with a pick above` : ""}</div>
    ${boughtBox({ kind: "combo", team: c.legs.map(l => l.team).join("+"), game: `${c.size}-team combo`, legs: c.legs.map(l => ({ team: l.team, gameId: l.gameId })), grade: gradeOf(c.hit, COMBO_CUTS), price: c.cost })}
    <div style="margin-top:8px">${legHead}${c.legs.slice().sort(legRank).map(l => `<div class="leg">${badge(l.team, "sm")}<div style="min-width:0"><b>${esc(l.team)}</b> <span class="small muted">vs ${esc(l.opp)}</span>${l.dog ? ` <span class="tag look">underdog</span>` : ""}<br>${(l.why || []).map(x => `<span class="tag info">${esc(x)}</span>`).join("")}</div><span class="sp"></span><span class="small muted">${Math.round(l.est)}%</span>${grd(gradeOf(l.est), 1)}<span class="p">${ct(l.price)}</span></div>`).join("")}</div>
  </div>`;
}
// ---------- build your own combo: Rick taps teams, we analyse it (all in the browser, from the board) ----------
const lsGet = k => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
// same leg estimate as the Top picks (engine/topcombos.legs_for): our fair + best value tag, fades move value to the other side
function buildLegs(gl) {
  const E = S.B.watch?.edges || {}, out = [];
  for (const g of gl || []) {
    if (g.state !== "pre") continue;
    const T = [g.teams.away, g.teams.home], adj = {}, good = {}, why = {};
    for (const c of T) { adj[c.team] = 0; good[c.team] = 0; why[c.team] = []; }
    for (const w of g.watch || []) {
      const e = E[w.tag] || 0, o = T.find(c => c.team !== w.team)?.team;
      if (w.kind === "fade") { adj[w.team] -= e; if (o) { adj[o] += e; why[o].push(`${w.team} ${w.tag.toLowerCase()}`); } }
      else if (w.team in good) { good[w.team] = Math.max(good[w.team], e); why[w.team].push(w.tag); }
    }
    for (const c of T) {
      if (!c.price || c.fair == null || c.price < 3 || c.price > 97) continue;
      out.push({ gameId: g.id, team: c.team, opp: c.opp, price: c.price, fair: c.fair, call: callOf(c), why: why[c.team],
        est: Math.max(1, Math.min(97, Math.round(c.fair * 10) / 10)) });   // tags shown, never added
    }
  }
  return out;
}
window.buildWeek = w => { S.bld = { week: w, sel: {} }; lsSet("bld", S.bld); render(); };
window.buildTap = (gid, team) => { const s = S.bld.sel; s[gid] === team ? delete s[gid] : s[gid] = team; lsSet("bld", S.bld); render(); };
// Rick 2026-11-24: every combo list best to worst — win chance first, then cheaper
const legRank = (x, y) => ((y.est ?? y.fair) - (x.est ?? x.fair)) || (x.price - y.price);
const comboRank = (x, y) => (y.hit - x.hit) || (x.cost - y.cost);
// Rick 2026-11-24: one-tap combos. "A" = every A-graded team (75%+ to win).
// "AB" = every A and B team (60%+), no cap. Legs are listed best to worst.
function gradePick(pool, mode) {
  const ok = mode === "A+" ? ["A+"] : mode === "A" ? ["A+", "A"] : ["A+", "A", "B"];
  return pool.filter(l => ok.includes(gradeOf(l.est))).sort(legRank);
}
window.buildGrade = mode => {
  S.bld = S.bld || lsGet("bld") || { week: "thisWeek", sel: {} };
  const legsOf = w => buildLegs(w === "nextWeek" ? S.B.nextWeek : S.B.games);
  let pick = gradePick(legsOf(S.bld.week), mode);
  if (pick.length < 2) {   // none left this week (or next): use the other week if it has some
    const other = S.bld.week === "nextWeek" ? "thisWeek" : "nextWeek", op = gradePick(legsOf(other), mode);
    if (op.length > pick.length) { S.bld.week = other; pick = op; }
  }
  if (mode === "A+" && pick.length < 3) {   // Rick 2026-11-24: A+ combo is at least 3 teams; fill with the next most likely
    const used = new Set(pick.map(l => l.gameId));
    for (const l of legsOf(S.bld.week).sort(legRank)) { if (pick.length >= 3) break; if (!used.has(l.gameId)) { pick.push(l); used.add(l.gameId); } }
  }
  S.bld.sel = {};
  for (const l of pick) S.bld.sel[l.gameId] = l.team;
  lsSet("bld", S.bld); S.ccat = "build"; render(); window.scrollTo(0, 0);
};
window.buildAllA = () => buildGrade("A");
window.buildClear = () => { S.bld.sel = {}; lsSet("bld", S.bld); render(); };
window.buildSwap = (gid, ngid, team) => { delete S.bld.sel[gid]; S.bld.sel[ngid] = team; lsSet("bld", S.bld); render(); };
function buildView() {
  S.bld = S.bld || lsGet("bld") || { week: "thisWeek", sel: {} };
  const B = S.bld, gl = B.week === "nextWeek" ? S.B.nextWeek : S.B.games;
  const pool = buildLegs(gl), by = Object.fromEntries(pool.map(l => [l.gameId + "|" + l.team, l]));
  for (const gid of Object.keys(B.sel)) if (!by[gid + "|" + B.sel[gid]]) delete B.sel[gid];   // game started or no price
  const legs = Object.entries(B.sel).map(([gid, t]) => by[gid + "|" + t]).sort(legRank);
  let h = `<div class="ptitle">Combos</div><div class="psub">Build your own · tap a team in each game you want</div>${comboTabs("build")}${comboWarn()}
    <div class="ctabs" style="margin-top:6px"><button class="${B.week === "thisWeek" ? "on" : ""}" onclick="buildWeek('thisWeek')">This week</button><button class="${B.week === "nextWeek" ? "on" : ""}" onclick="buildWeek('nextWeek')">Next week (early)</button></div>`;
  h += buildAnalysis(legs, pool);
  const best = g => Math.max(...pool.filter(l => l.gameId === g.id).map(l => l.est));
  const games = (gl || []).filter(g => pool.some(l => l.gameId === g.id)).sort((x, y) => best(y) - best(x));
  const nAp = gradePick(pool, "A+").length, nA = gradePick(pool, "A").length, nAB = gradePick(pool, "AB").length;
  h += `<div class="row" style="margin:10px 0 2px;flex-wrap:wrap"><button class="btn pri" onclick="buildGrade('A+')"${nAp ? "" : " disabled"}>${grd("A+", 1)}A+ combo (${nAp} A+${nAp < 3 ? " + best" : ""})</button><button class="btn pri" onclick="buildGrade('A')"${nA ? "" : " disabled"}>${grd("A", 1)}Select all A picks (${nA})</button><button class="btn pri" onclick="buildGrade('AB')"${nAB >= 2 ? "" : " disabled"}>${grd("A", 1)}${grd("B", 1)}All A + B picks (${nAB})</button></div><div class="tiny muted">Teams are listed best to worst. Tap ✕ on the weakest to raise the chance it hits.</div>${nA ? "" : `<div class="tiny muted">No team is graded A ${B.week === "nextWeek" ? "next week" : "in the games left this week"}.</div>`}`;
  h += `<h2>Pick teams <span class="cnt">${games.length}</span></h2>`;
  if (!games.length) return h + NOREC(B.week === "nextWeek" ? "Kalshi hasn't listed next week's games yet" : "No upcoming games with prices right now");
  const btn = (g, c) => {
    const l = by[g.id + "|" + c.team];
    if (!l) return `<button class="bt" disabled>${esc(c.team)}<span>no price</span></button>`;
    return `<button class="bt ${B.sel[g.id] === c.team ? "on" : ""}" onclick="buildTap('${esc(g.id)}','${esc(c.team)}')">${badge(c.team, "sm")}<b>${esc(c.team)}</b><span>${ct(l.price)} · wins ${Math.round(l.est)}% ${grd(gradeOf(l.est), 1)}</span></button>`;
  };
  h += `<div class="card" style="padding:8px">${games.map(g => `<div class="bpair"><div class="tiny muted">${esc(g.short || "")} · ${esc(kick(g.kickoff))}</div><div class="brow">${btn(g, g.teams.away)}${btn(g, g.teams.home)}</div></div>`).join("")}</div>`;
  h += `<div class="tiny muted" style="margin-top:8px">Win chance = our fair value, same as Top picks (watch tags are shown, not added). Info only: check each leg's Buy/Wait/Pass, and Robinhood's real combo price.</div>`;
  return h;
}
function buildAnalysis(legs, pool) {
  if (legs.length < 2) return `<div class="card"><div class="small"><b>${legs.length ? "Pick at least one more team." : "Tap teams below to build a combo."}</b> <span class="muted">We'll show the chance it hits, what it costs, what $5 wins, weak legs and better swaps.</span></div></div>`;
  const k = legs.length, prod = f => legs.reduce((a, l) => a * f(l) / 100, 1) * 100;
  const hit = prod(l => l.est), legsCost = prod(l => l.price), cost = legsCost * markup(k, legsCost);
  S.lastLegs = legsCost; S.lastN = k;
  const r1 = x => Math.round(x * 10) / 10;
  // one line per leg that has a problem; Pass/Sell only flagged this week (next week's early calls are mostly Pass)
  const flags = [], bad = new Set(), early = S.bld.week === "nextWeek";
  for (const l of legs) {
    const why = [];
    if (l.est < 45) why.push("weak leg, one loss sinks the combo");
    else if (l.est < l.price - 2) why.push(`costs more than its chance (${ct(l.price)})`);
    if (l.price < 50 && l.est < 50) why.push("underdog we don't expect to win");
    if (!early && (l.call === "Pass" || l.call === "Sell")) why.push(`${LBL(l.call)} on its own`);
    if (l.est < 45 || l.est < l.price - 2) bad.add(l);
    if (why.length) flags.push(`<b>${esc(l.team)}</b> ${Math.round(l.est)}%: ${why.join(", ")}`);
  }
  // swaps: for each problem leg, the open leg that best improves chance + value (like Top picks); stay under 10c when you were
  const used = new Set(legs.map(l => l.gameId)), cap = cost <= 10 ? 10 : Infinity;
  const score = (h, c) => (h - c) + 0.15 * h;
  const swaps = [];
  for (const l of [...bad].sort((a, b) => a.est - b.est)) {
    const find = lim => {
      let best = null;
      for (const x of pool) {
        if (used.has(x.gameId) || x.est < 55 || x.est < x.price - 2 || swaps.some(s => s.alt.gameId === x.gameId)) continue;
        const nh = hit / l.est * x.est, nc = cost / l.price * x.price;
        if (nc > lim) continue;
        const sc = score(nh, nc);
        if (sc > score(hit, cost) && (!best || sc > best.sc)) best = { alt: x, nh, nc, sc };
      }
      return best;
    };
    const best = find(cap) || find(Infinity);
    if (best) swaps.push({ l, alt: best.alt, txt: `Swap <b>${esc(l.team)}</b> → <b>${esc(best.alt.team)}</b> (${ct(best.alt.price)}, wins ${Math.round(best.alt.est)}%): chance ${r1(hit)}% → ${r1(best.nh)}%, cost ${r1(cost)}¢ → ${r1(best.nc)}¢${best.nc > 10 && cost <= 10 ? " (over 10¢)" : ""}` });
  }
  const verdict = hit >= cost + 2 ? `<span style="color:var(--good)">Our chance beats the cost by ${r1(hit - cost)}¢</span>` : hit >= cost ? "About a fair price" : `<span style="color:var(--bad)">Costs ${r1(cost - hit)}¢ more than our chance</span>`;
  return `<div class="card">
    <div class="row"><b>Your combo · ${k} teams</b><span class="sp"></span>${hitChip(hit)}</div>
    ${big3(hit, cost)}
    <div class="tiny muted">${verdict} · teams' prices multiplied ${r1(legsCost)}¢ + about ${Math.round((markup(k, legsCost) - 1) * 100)}% Robinhood markup${cost > 10 ? " · over 10¢: not a bonus bet" : ""}</div>
    <div style="margin-top:8px">${legHead}${legs.map(l => `<div class="leg">${badge(l.team, "sm")}<div style="min-width:0"><b>${esc(l.team)}</b> <span class="small muted">vs ${esc(l.opp)}</span> <span class="small" style="color:var(--${{ Value: "good", Wait: "wait", Pass: "bad", Sell: "sell" }[l.call] || "muted"})">${esc(LBL(l.call) || "")}</span><br>${l.why.map(x => `<span class="tag info">${esc(x)}</span>`).join("")}</div><span class="sp"></span><span class="small muted">${Math.round(l.est)}%</span>${grd(gradeOf(l.est), 1)}<span class="p">${ct(l.price)}</span><button class="x" onclick="buildTap('${esc(l.gameId)}','${esc(l.team)}')" aria-label="Remove">✕</button></div>`).join("")}</div>
    ${flags.length ? `<div class="small" style="margin-top:8px"><b>Watch out</b>${flags.map(f => `<div class="tiny" style="margin-top:3px">⚠ ${f}</div>`).join("")}</div>` : `<div class="small" style="margin-top:8px;color:var(--good)">No weak legs: every leg is 45%+ and priced at or under its chance.</div>`}${early ? `<div class="tiny muted" style="margin-top:4px">Next week's prices are early: news can still move them.</div>` : ""}
    ${swaps.length ? `<div class="small" style="margin-top:8px"><b>Better swaps</b>${swaps.map(s => `<div class="tiny" style="margin-top:3px">${s.txt} <button class="btn sm" onclick="buildSwap('${esc(s.l.gameId)}','${esc(s.alt.gameId)}','${esc(s.alt.team)}')">Swap</button></div>`).join("")}</div>` : ""}
    <div class="small" style="margin-top:10px"><b>Robinhood's real price?</b> <span class="muted">Type the combo quote you see and we learn the true markup.</span>
      <div class="row" style="margin-top:6px;gap:6px"><input id="rhq" type="number" inputmode="decimal" step="0.1" min="0.1" max="99" placeholder="e.g. 11.5" style="width:90px">¢ <button class="btn sm" onclick="saveQuote()">Save</button></div>
      <div class="tiny muted" style="margin-top:4px">Markup now: +${Math.round((mkLearned(8) - 1) * 100)}% on an 8¢ combo, +${Math.round((mkLearned(60) - 1) * 100)}% on a 60¢ one ${quotes().length ? `from your ${quotes().length} quote${quotes().length > 1 ? "s" : ""} (<a href="#" onclick="event.preventDefault();clearQuotes()">reset</a>)` : "(starting estimate)"}.</div></div>
    <div class="row" style="margin-top:10px"><button class="btn" onclick="buildClear()">Clear</button></div>
  </div>`;
}
const comboTabs = cat => `<div class="ctabs">${ctabTop()}<button class="${cat === "build" ? "on" : ""}" onclick="setCombo('build')">Build your own</button><button class="${cat === "standard" ? "on" : ""}" onclick="setCombo('standard')">All games</button><button class="${cat === "combined" ? "on" : ""}" onclick="setCombo('combined')">Sure things + dips</button></div>`;
function topCombosView() {
  const T = S.B.topCombos || {};
  let h = `<div class="ptitle">Combos</div><div class="psub">Top picks · this week and next week</div>${comboTabs("top")}${comboWarn()}<div class="row" style="margin:6px 0;flex-wrap:wrap"><button class="btn pri" onclick="buildGrade('A+')">${grd("A+", 1)}A+ combo (3+ teams) →</button><button class="btn pri" onclick="buildGrade('A')">${grd("A", 1)}Combo of all A picks →</button><button class="btn pri" onclick="buildGrade('AB')">${grd("A", 1)}${grd("B", 1)}Combo of all A + B picks →</button></div>`;
  const sec = (w, title, early) => {
    const x = T[w] || {};
    h += `<h2>${title} · 3 under ${T.cheapMax || 10}¢</h2><div class="small muted" style="margin:-4px 0 8px">Best chance to hit for under ${T.cheapMax || 10}¢, using as few of the same games as possible. Built mostly from favourites (they've been slightly underpriced); an underdog only when we expect it to win.${early ? " Early prices: news can change these." : ""}</div>`;
    h += (x.cheap || []).length ? x.cheap.slice().sort(comboRank).map(topCard).join("") : NOREC(`${x.legs || 0} teams with prices`);
    h += `<h2>${title} · best value + chance</h2><div class="small muted" style="margin:-4px 0 8px">Any price: the best mix of our win chance and what it costs.</div>`;
    h += (x.value || []).length ? x.value.slice().sort(comboRank).map(topCard).join("") : NOREC();
  };
  sec("thisWeek", "This week");
  sec("nextWeek", "Next week (early)", true);
  const r = T.record || {};
  if (r.cheap?.n || r.value?.n) h += `<div class="small muted" style="margin-top:8px">Track record: under-10¢ picks hit ${r.cheap.won} of ${r.cheap.n} (we expected ${r.cheap.expected}); value picks ${r.value.won} of ${r.value.n} (expected ${r.value.expected}).</div>`;
  h += `<div class="tiny muted" style="margin-top:8px">Info only — check each leg's Buy/Wait/Pass. Our chance = our fair value. Watch tags are shown for info, not added to the chance.</div>`;
  return h;
}
function combosView() {
  S.csize = S.csize || {};
  const cat = S.ccat || "top";
  if (cat === "top") return topCombosView();
  if (cat === "build") return buildView();
  const sizes = comboSizes(cat);
  const r = S.B.combos[cat] || {};
  const k = sizes.includes(S.csize[cat]) ? S.csize[cat] : bestSize(cat);
  const found = sizes.filter(x => r[x].combo).length;
  let h = `<div class="ptitle">Combos</div><div class="psub">${found ? `${found} size${found > 1 ? "s" : ""} clear the bar` : "Nothing clears the bar right now"} · live + upcoming games</div>
    ${comboTabs(cat)}`;
  h += `<h2>${cat === "standard" ? "Weekly combos — live + upcoming" : "Sure things + dips — big favourites plus teams that dipped"}</h2>`;
  if (!sizes.length) return h + NOREC(`${S.B.combos.poolGames || 0} games with prices — need 2`) + (cat === "standard" ? watchCombo() : "");
  h += `<div class="sizes">${sizes.map(x => `<button class="${x === k ? "on" : ""} ${r[x].combo ? "has" : ""}" onclick="setCombo('${cat}',${x})"><b>${x}</b><span>${r[x].combo ? "+" + ct1(r[x].combo.edge) : "legs"}</span></button>`).join("")}</div>`;
  h += comboCard(cat, String(k), r[k]);
  if (cat === "standard") {
    const sr = (S.B.combos.safer || {})[String(k)];
    const mf = sr?.minFair || 60;
    h += `<h2>Safer ${k}-leg combo — every leg ${mf}%+ to win</h2><div class="small muted" style="margin:-4px 0 8px">Most likely to hit while still costing no more than max pay. One loss loses the combo, so this favours winners over value.</div>`;
    h += sr ? comboCard("safer", String(k), sr, true) : NOREC(`Not enough teams at ${mf}%+ for ${k} legs`);
    h += watchCombo(k);
  }
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
  let h = `<div class="ptitle">Learning</div><div class="mybets"><span>This week: ${ws.w}–${ws.l} · ${money(ws.pnl)}</span><span class="small">All: ${money(at.pnl)}</span></div>${gradeRecord(all)}`;
  h += banners();
  const t = L.totals;
  if (t) h += `<div class="banner"><b>${t.right}/${t.games} right · ${t.pct}%</b> <span class="small muted">(${t.baseline.right}/${t.baseline.games} backtest + ${t.reviewedRight}/${t.reviewed} reviewed)</span></div>`;
  // calibration
  const bt = L.backtest;
  const useRev = (L.totals?.reviewed || 0) >= 20;
  const calRows = (useRev ? L.calibration : bt?.calibration) || [];
  const calC = (useRev ? L.calibConf : bt?.calibConf) || [];
  const id1 = "cal1";
  const head = calRows.length ? calRows.map(r => `${r.bucket}: ${Math.round(r.actual)}%`).join(" · ") : "—";
  h += `<h2>Were our chances right?</h2><div class="line u" onclick="toggle('${id1}')">${esc(head)}</div>${S.open.has(id1) ? `<div class="ig">${tile("By fair value", calibChart(calRows))}${tile("By grade", calibChart(calC))}</div><div class="tiny muted">${useRev ? "Reviewed games" : "Rebuilt backtest (Weeks 1–11) until 20 games are reviewed"}</div>` : ""}`;
  if (L.shrink) h += `<div class="line muted small">${esc(L.shrink.note)}</div>`;
  // everything below is past research: folded into one line (Rick 2026-11-25: main views = what matters now)
  const topH = h;
  h = "";
  // weekly lessons
  h += `<h2>Weekly lessons</h2>`;
  const wl = (L.weekly || []).slice().reverse();
  h += wl.length ? wl.map(w => {
    const id = "wk:" + w.week;
    const money = n => `${n >= 0 ? "+" : "−"}$${Math.abs(n / 100).toFixed(2)}`;
    const bu = w.buys?.n ? `Buy calls ${money(w.buys.net)} on ${w.buys.n} (per contract, after fees)` : "No Buy calls graded";
    return `<div class="banner"><span class="u" onclick="toggle('${id}')">Week ${w.week} — ${bu}</span>${S.open.has(id) ? `<div class="small" style="margin-top:6px">${esc(w.lesson)}<br>${esc(w.shrink || "")}<br>Picks ${w.w}/${w.n} right · Brier ${w.brier}<br>${calibChart(w.calibration, "By fair value")}${Object.entries(w.combos || {}).map(([k, v]) => `${k} combos hit ${v.hit}/${v.n}${v.net != null ? ` (${money(v.net)} a contract)` : ""}`).join(" · ")}</div>` : ""}</div>`;
  }).join("") : NOREC(S.B.nextCheck);
  // experts
  const E = S.B.experts;
  if (E?.table?.length) {
    const id = "exp";
    const pc = x => x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(1)}%`;
    const top = E.table.filter(r => r.rank && r.rank <= (E.top || []).length);
    h += `<h2>Expert picks</h2><div class="line u" onclick="toggle('${id}')">Showing top ${top.length} of ${E.table.length}: ${esc(top.map(r => r.name.split(" ").slice(-1)[0]).join(", "))}</div>`;
    if (S.open.has(id)) {
      h += `<table class="qt"><tr><th>#</th><th>Expert</th><th>Right</th><th>Profit</th><th>Underdogs</th></tr>${E.table.map(r => `<tr><td>${r.rank || "–"}</td><td>${esc(r.name)} <span class="muted">${esc(r.source)}</span></td><td>${r.w}-${r.n - r.w} (${r.pct}%)</td><td class="${(r.roi ?? 0) >= 0 ? "ok" : "bad"}">${pc(r.roi)}${Object.keys(r.bySeason || {}).length > 1 ? `<div class="tiny muted">${Object.entries(r.bySeason).sort((a, b) => b[0] - a[0]).map(([y, v]) => `${y.slice(2)}: ${pc(v.roi)}`).join(" · ")}</div>` : ""}</td><td>${r.dog[1]}/${r.dog[0]} · ${r.dog[2] >= 0 ? "+" : ""}${r.dog[2]}u</td></tr>`).join("")}</table>`;
      const b = E.baseline || {}, a = E.agree || {};
      h += `<div class="small muted" style="margin-top:6px">Profit = per 1-unit pick at the moneyline when they picked. Always picking the favourite: ${pc(b.fav?.roi)}. Always the underdog: ${pc(b.dog?.roi)}.${a.all ? ` When every expert agreed: won ${a.all.pct}% vs ${a.all.implied}% the price implied (${a.all.n} games) — no extra edge, so it's a tag only.` : ""} ${E.dogExperts?.length && E.dogGroup?.n ? ` Underdog experts (${esc(E.dogExperts.map(n => n.split(" ").slice(-1)[0]).join(", "))}): their underdog picks won ${E.dogGroup.w} of ${E.dogGroup.n}, ${E.dogGroup.profit >= 0 ? "+" : ""}${E.dogGroup.profit} units — small sample, picked after the fact.` : ""} Ranked by profit over ${esc((E.seasons || []).join(" + "))}, re-ranked every week. Sources: ${esc((E.sources || []).join(", "))}.</div>`;
    }
  }
  // watch tags
  const W = S.B.watch;
  if (W?.live) {
    const id = "wt";
    const sm = Object.entries(W.live).map(([k, v]) => `${k} ${v.n ? `${v.w}/${v.n}` : "0 yet"}`).join(" · ");
    h += `<h2>Watch tags</h2><div class="line u" onclick="toggle('${id}')">${esc(sm)} · tag only</div>`;
    if (S.open.has(id)) h += `<table class="qt"><tr><th>Tag</th><th>Live</th><th>Tested</th></tr>${Object.entries(W.live).map(([k, v]) => `<tr><td>${esc(k)}${W.edges ? `<div class="tiny muted">edge now ${W.edges[k] > 0 ? "+" : ""}${W.edges[k]}¢ (started ${W.prior?.[k]}¢)</div>` : ""}</td><td>${v.n ? `${v.w}/${v.n} won at ${v.price}¢ avg · ${v.netPer >= 0 ? "+" : ""}${v.netPer}¢ each after fee` : "none graded yet"}</td><td class="small">${esc((W.study || {})[k] || "")}</td></tr>`).join("")}</table><div class="tiny muted">Both beat the price in older and recent years, but were found by searching many combinations, so they don't change prices or calls. They're tracked here from now on. Each week the edge we use moves toward how the tag actually did, slowly: our own results count as much as the study only after ${W.learnK || 150} games.</div>${(() => { const r = S.B.topCombos?.record; return r ? `<div class="small" style="margin-top:6px"><b>Suggested combos</b>: under-10¢ hit ${r.cheap.won} of ${r.cheap.n} (expected ${r.cheap.expected}, ${r.cheap.net >= 0 ? "+" : ""}${r.cheap.net}¢ for 1 contract each) · value ${r.value.won} of ${r.value.n} (expected ${r.value.expected}, ${r.value.net >= 0 ? "+" : ""}${r.value.net}¢)</div>` : ""; })()}`;
  }
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
    h += `<h2>Injury research</h2><div class="line u" onclick="toggle('${id}')">${hd.out} exits · ${hd.pctReturned}% back (about ${hd.medianMinOut} min) · ${hd.keyNonQB} key non-QB</div>`;
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
  const fs = L.formStudy;
  if (fs?.rows) {
    const id = "fs";
    const n = fs.rows.length + (fs.coach || []).length, held = (fs.held || []).length;
    const pc = x => x == null ? "—" : `${x > 0 ? "+" : ""}${x}`;
    h += `<h2>Streaks, turnovers, coaches, backup QBs</h2><div class="line u" onclick="toggle('${id}')">${held} of ${n} beat the price · context only${fs.at ? ` · tested ${ago(fs.at)}` : ""}</div>`;
    if (S.open.has(id)) {
      h += `<table class="qt"><tr><th>Spot</th><th>Older years</th><th>Recent years</th></tr>${fs.rows.map(r => `<tr><td>${esc(r.spot)}${r.note && /line/.test(r.note) ? `<br><span class="tiny muted">${esc(r.note)}</span>` : ""}</td><td>${r.fit ? `won ${r.fit.won}% vs price ${r.fit.price}% (${pc(r.fit.diff)}, ±${r.fit.se}) <span class="muted">n ${r.fit.n}</span>` : "—"}</td><td>${r.check ? `${pc(r.check.diff)} (±${r.check.se}) <span class="muted">n ${r.check.n}</span>` : "—"}</td></tr>`).join("")}</table>`;
      h += `<div class="small" style="margin-top:6px"><b>Coach style</b> vs the line (pts per 1 SD, 2021-24 / 2025-26): ${(fs.coach || []).map(c => `${esc(c.label)} ${pc(c.per1sd)} / ${pc(c.per1sdTest)}`).join(" · ")}</div>`;
      const q = fs.qbTraits || {};
      h += `<div class="small" style="margin-top:6px"><b>Do QB traits repeat next season?</b> ${Object.entries(q).filter(([k]) => k !== "n").map(([k, v]) => `${esc(k)} ${v}`).join(" · ")} <span class="muted">(1 = always, 0 = random). EPA and sack rate are real traits; INT rate and quarter splits (slow starter, strong Q3) are mostly noise.</span></div>`;
      h += `<div class="tiny muted">"vs price" = how often they won minus what the moneyline said. A spot counts only if it's 2.5+ SE in older years and holds in recent years. Older years: 2006–20 (2021–24 for turnovers).</div>`;
    }
  }
  const hs = L.h2hStudy;
  if (hs?.rows) {
    const id = "hs", pc = x => x == null ? "—" : `${x > 0 ? "+" : ""}${x}`;
    h += `<h2>Head-to-head history tested</h2><div class="line u" onclick="toggle('${id}')">${(hs.held || []).length} of ${hs.rows.length} beat the price · context only</div>`;
    if (S.open.has(id)) h += `<table class="qt"><tr><th>Last meeting (within 2 seasons)</th><th>2006–20</th><th>2021+</th></tr>${hs.rows.map(r => `<tr><td>${esc(r.spot)}</td><td>${r.fit ? `${pc(r.fit.diff)} (±${r.fit.se}) <span class="muted">n ${r.fit.n}</span>` : "—"}</td><td>${r.check ? `${pc(r.check.diff)} (±${r.check.se}) <span class="muted">n ${r.check.n}</span>` : "—"}</td></tr>`).join("")}</table><div class="tiny muted">Win % minus what the moneyline said. Last meeting's result vs the line explains ${hs.slope ? `${hs.slope.fit[0]} pts per pt (older) and ${hs.slope.check?.[0]} (recent)` : "nothing"} of this game vs the line — about zero.</div>`;
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
  const ro = localGet("research") === "1";
  const research = `<details class="others research"${ro ? " open" : ""} ontoggle="localSet('research', this.open ? '1' : '0')"><summary>Research &amp; tests · weekly lessons, experts, watch tags, studies</summary>${h}</details>`;
  const fo = localGet("betform") === "1";
  const log = `<h2>Your bets</h2>${betList(all)}<details class="others"${fo ? " open" : ""} ontoggle="localSet('betform', this.open ? '1' : '0')"><summary>Add a bet by hand</summary>${betForm()}</details>`;
  return topH + log + research;
}
function betForm() {
  const teams = [...new Set(S.B.calls.map(c => c.team))].sort();
  return `<div class="card"><div class="form">
    <select id="bTeam" class="full">${teams.map(t => `<option>${t}</option>`).join("")}</select>
    <input id="bPrice" type="number" min="1" max="99" step="0.1" placeholder="Price ¢">
    <input id="bQty" type="number" min="1" step="1" placeholder="Contracts" value="1">
    <input id="bDate" type="date" value="${new Date().toISOString().slice(0, 10)}">
    <select id="bRes"><option value="open">Open</option><option value="win">Win</option><option value="loss">Loss</option><option value="tie">Tie</option></select>
    <button class="btn pri full" onclick="addBet()">Add bet</button><div id="bMsg" class="small bad"></div></div></div>`;
}
function betList(all) {
  if (!all.length) return `<div class="line muted small">No bets yet. Tap “I bought this” on a pick or combo and it shows up here.</div><div class="row" style="margin-top:6px"><label class="btn">Import CSV<input type="file" accept=".csv" hidden onchange="importCsv(this)"></label></div>`;
  let run = 0;
  const rows = all.map((b, i) => {
    const q = Number(b.qty || 1);
    const p = b.result === "win" ? (100 - b.price) * q : b.result === "loss" ? -b.price * q : b.result === "tie" ? (50 - b.price) * q : 0;
    run += p;
    return `<div class="leg"><div style="flex:1;min-width:0"><b>${esc(b.team)}</b> ${b.grade ? grd(b.grade, 1) : ""} <span class="small muted">${esc(b.game || "")} ${esc(b.date)}${b.auto ? " · settled by itself" : ""}</span><br><span class="small">${ct(b.price)} × ${q}</span></div><span class="sp"></span>
      <select onchange="setRes(${i},this.value)">${["open", "win", "loss", "tie"].map(r => `<option ${b.result === r ? "selected" : ""}>${r}</option>`).join("")}</select>
      <span class="small ${p >= 0 ? "ok" : "bad"}" style="min-width:60px;text-align:right">${b.result === "open" ? "" : money(p / 100)}</span><span class="tiny muted">${money(run / 100)}</span>
      <button class="btn" onclick="delBet(${i})">✕</button></div>`;
  }).join("");
  return `<div class="card">${rows}</div><div class="row"><button class="btn" onclick="exportCsv()">Export CSV</button><label class="btn">Import CSV<input type="file" accept=".csv" hidden onchange="importCsv(this)"></label></div>`;
}
window.addBet = () => {
  const price = Number($("#bPrice").value);
  if (!(price > 0 && price < 100)) { $("#bMsg").textContent = "Type the price you paid (1–99¢) first."; $("#bPrice").focus(); return; }
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
  return `<div class="big ${edge >= 15 ? "ok" : edge >= 8 ? "" : "muted"}">${edge >= 0 ? "+" : ""}${edge.toFixed(1)}¢ <span class="small muted">below our fair price, after ${fee}¢ fees</span></div>
  <svg viewBox="0 0 ${W} 48" width="100%"><rect x="10" y="18" width="${W - 20}" height="8" rx="4" fill="var(--bar)"/>
   ${v15 > 0 ? `<rect x="10" y="18" width="${x(v15) - 10}" height="8" rx="4" fill="var(--good)" opacity=".35"/>` : ""}
   ${v8 > 0 ? `<line x1="${x(v8)}" x2="${x(v8)}" y1="12" y2="32" stroke="var(--wait)" stroke-width="2"/><text x="${x(v8)}" y="44" text-anchor="middle">8¢ bar ${Math.round(v8)}</text>` : ""}
   ${v15 > 0 ? `<line x1="${x(v15)}" x2="${x(v15)}" y1="12" y2="32" stroke="var(--good)" stroke-width="2"/><text x="${x(v15)}" y="10" text-anchor="middle">15¢ bar ${Math.round(v15)}</text>` : ""}
   <rect x="${x(price) - 2}" y="12" width="4" height="20" rx="2" fill="var(--ink)"/><text x="${x(price)}" y="44" text-anchor="middle">price ${Math.round(price)}</text>
   <rect x="${x(fair) - 2}" y="12" width="4" height="20" rx="2" fill="var(--fair)"/><text x="${x(fair)}" y="10" text-anchor="middle">fair ${Math.round(fair)}</text></svg>`;
}
function confTile(conf) {
  if (!conf) return "";
  return `<div class="row"><span class="big">${conf.score}%</span>${meter(conf)}</div><div class="small">Chance this team wins the game. Buy / Wait / Pass tells you if the price is good.</div><div class="tiny muted">Tested on 1,521 games: A+ (85%+) won 92%, A (75–85%) won 80%, B (60–75%) won 67%, C (45–60%) won 54%, F (under 45%) won 32%.${conf.missing ? " Some data missing for this game." : ""}</div>`;
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
    ${tile("Were our chances right? — by fair price", calibChart(calRows))}
    ${tile("Were our chances right? — by win chance", calibChart(calC))}
    ${tile("Injuries", (inj.length ? inj.map(injTile).join("") : "") + (curInj.length ? curInj.map(i => `<span class="chipf">${esc(i.pos)} ${esc(i.short)} ${esc(i.status)}</span>`).join("") : (inj.length ? "" : `<div class="small muted">No key injuries</div>`)), true)}
    ${tile("Weather by hour", g.indoor ? `<div class="small">Indoors — weather not used</div>` : g.weather?.hours ? wxChart(g.weather.hours) : `<div class="small muted">Weather unavailable</div>`, true)}
    ${tile("Matchups (nflverse)", matchupBars(g), true)}
    ${tile("Score by quarter", timeline(g))}
    ${tile("Turnovers · QB", g.turnovers ? `<div class="kv"><span>${esc(g.away)}</span><span>${g.turnovers[g.away] ?? 0} TO · ${esc(g.qb?.[g.away]?.starter || "")}${g.qb?.[g.away]?.change ? " → " + esc(g.qb[g.away].change.to) : ""}</span><span>${esc(g.home)}</span><span>${g.turnovers[g.home] ?? 0} TO · ${esc(g.qb?.[g.home]?.starter || "")}${g.qb?.[g.home]?.change ? " → " + esc(g.qb[g.home].change.to) : ""}</span></div>` : `<div class="small muted">Not started</div>`)}
    ${combos.length ? tile("Combo legs", combos.map(({ k, cat, r }) => `<div class="small"><b>${k}-leg ${cat === "combined" ? "combined" : ""}</b> · hits ${pct(r.combo.hit)} · cost ${ct1(r.combo.cost)}<br>${r.combo.legs.map(l => `${l.team} ${ct(l.price)} (${pct(l.fair)})`).join(" · ")}</div>`).join(""), true) : ""}
   </div>`);
};

// ---------- share the app (Rick 2026-11-25) ----------
const APP_URL = "https://rcarrier1995.github.io/nfl-bets/";
function shareCard() {
  return `<div class="card"><h3>Share the app</h3>
   <div class="small">Send the link to a friend. It works on any phone or computer, nothing to sign up for. Their bet log stays on their phone, and your alerts stay yours.</div>
   <button class="btn pri" style="margin-top:10px;width:100%" onclick="shareApp()">Share app</button>
   <div id="shareRes" class="small"></div></div>`;
}
window.shareApp = async () => {
  const data = { title: "NFL Bets", text: "NFL picks helper (suggestions only):", url: APP_URL };
  if (navigator.share) { try { await navigator.share(data); return; } catch (e) { if (e && e.name === "AbortError") return; } }
  let ok = false;
  try { await navigator.clipboard.writeText(APP_URL); ok = true; } catch (e) {}
  openModal(`<h2>Share the app</h2><div class="small">${ok ? `<span class="ok">Link copied.</span> Paste it in a text or email.` : `Copy this link and send it:`}</div>
   <input readonly value="${APP_URL}" style="width:100%;margin-top:8px" onclick="this.select()">
   <div class="row" style="margin-top:12px"><span class="sp"></span><button class="btn pri" onclick="closeModal()">Done</button></div>`);
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
  const topic = localGet("topic") || "";   // never show the owner's server topic (app is shared)
  const h = S.B.health || {};
  return `<div class="ptitle">Setup</div><h2>Setup & Edge</h2>
  ${shareCard()}
  ${installCard()}
  <div class="card"><h3>Phone alerts</h3>
   <div class="small">Status: ${(p.hasTopic || p.topic) ? `<span class="ok">on — server alerts go only to the app owner's phone</span>` : `<span class="bad">no topic on server</span>`}${p.lastNote ? `<br>${esc(p.lastNote)}` : ""}</div>
   <div class="row" style="margin-top:8px"><input id="topic" placeholder="ntfy topic" value="${esc(topic)}" style="flex:1"><button class="btn pri" onclick="testPush()">Test</button></div>
   <div id="testRes" class="small"></div>
   <div class="small" style="margin:8px 0">Buzzes for: <b>game-day summary</b> (Thu &amp; Sun 11 AM) · Buy now · Wait prices hit · slow prices · sportsbook gaps (8¢+, needs the Odds API key) · live dips · <b>big swings</b> (ESPN win % moves 15+ pts, info only) · <b>injury news</b> (starter ruled out, confirmed out in-game, QB change).</div>
   <ol class="small"><li>Install the free <b>ntfy</b> app (App Store / Google Play).</li><li>Tap <b>+</b>, type the topic above, Subscribe.</li><li>Tap <b>Test</b> here — your phone should buzz.</li></ol>
   <div class="small"><a href="https://github.com/${REPO}/settings/secrets/actions" target="_blank" rel="noopener">Change the server topic</a> (it's the private <code>NTFY_TOPIC</code> secret: tap it, paste the new name, Update secret).</div>
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
   <p>Grade = the chance the team wins the game (from the line). A+ 85%+, A 75–85%, B 60–75%, C 45–60%, F under 45%. In testing A+ picks won 92%, A 80%, B 67%, C 54%, F 32%. It is not a price rating: Buy / Wait / Pass is. Combos are graded by their hit chance: A 1 in 3 or better, B 1 in 7, C 1 in 14, F rarer.</p>
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
  <div class="card"><h3>"I bought this" button</h3><div class="small">A folded line on each pick and combo that saves the bet to your log.</div><div class="row" style="margin-top:8px">${[["on", "Show"], ["off", "Hide"]].map(([k, l]) => `<button class="btn${(showBought() ? "on" : "off") === k ? " pri" : ""}" onclick="localSet('bought','${k}');render()">${l}</button>`).join("")}</div></div>
  <div class="card"><h3>Display</h3><div class="row">${[["light","Light"],["dark","Dark"],["auto","Auto"]].map(([k,l]) => `<button class="btn${(document.documentElement.dataset.theme || "dark") === k ? " pri" : ""}" onclick="theme('${k}')">${l}</button>`).join("")}</div></div>`;
}
function healthTable(h) {
  return `<div class="kv small">${Object.entries(h).map(([k, v]) => `<span><b>${esc(k)}</b></span><span>${v.ok ? `<span class="ok">ok</span>` : `<span class="bad">down</span>`} · last ok ${ago(v.lastOk)}${v.error && !v.ok ? " · " + esc(v.error) : ""}</span>`).join("")}</div>`;
}
window.theme = t => { document.documentElement.dataset.theme = t || "auto"; localSet("theme", t || "auto"); render(); };
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
  S.buy = {}; S.buyN = 0;
  settleBets();
  $("#weekLabel").textContent = `NFL Bets · Week ${S.B.week}`;
  const age = (Date.now() - Date.parse(S.B.generatedAt)) / 60000;
  $("#updated").textContent = `Updated ${ago(S.B.generatedAt)}`;
  $("#dot").classList.toggle("stale", age > 12);
  S.stale = age > 12 ? Math.round(age) : 0;
  const nLive = S.B.games.filter(g => g.state === "in").length;
  const bdg = document.querySelector('[data-tab=live] .badge'); bdg.hidden = !nLive; bdg.textContent = nLive;
  $("#gear").classList.toggle("on", S.tab === "setup");
  const fn = (S.stale ? [`Prices are ${S.stale} min old — calls may be out of date. Check the price in Robinhood.`] : []).concat(S.B.feedNotes || []);
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

// score, clock and ball straight from ESPN on the phone (prices and calls still come from the
// cloud check, every 6 minutes during games: Kalshi blocks price requests from a browser)
async function liveScores() {
  try {
    const sb = await fetch("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?t=" + Date.now()).then(r => r.json());
    for (const ev of sb.events || []) {
      const g = S.B.games.find(x => x.id === ev.id);
      const comp = ev.competitions?.[0];
      if (!g || !comp || g.state === "post") continue;
      const by = {}, ids = {};
      for (const c of comp.competitors || []) { by[c.homeAway] = c; ids[c.team?.id] = c.team?.abbreviation; }
      const st = ev.status || comp.status || {};
      if (st.type?.state === "pre") continue;
      g.score = { away: +(by.away?.score ?? g.score?.away ?? 0), home: +(by.home?.score ?? g.score?.home ?? 0) };
      if (st.type?.completed) { g.state = "post"; g.detail = "Final"; continue; }
      g.state = "in";
      g.period = st.period ?? g.period; g.clock = st.displayClock ?? g.clock;
      const sit = comp.situation || {};
      g.possession = ids[sit.possession] || null;
      g.downDist = sit.shortDownDistanceText || sit.downDistanceText || "";
      if (sit.homeTimeouts != null) { g.toH = sit.homeTimeouts; g.toA = sit.awayTimeouts; }
    }
    S.scoreAt = Date.now();
  } catch (e) { S.scoreAt = null; }
}
async function refreshNow(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Refreshing…"; }
  await load();
}
async function load() {
  try {
    const [b, l] = await Promise.all([
      fetch("data/board.json?t=" + Date.now()).then(r => r.json()),
      fetch("data/learning.json?t=" + Date.now()).then(r => r.json()).catch(() => null)]);
    S.B = b; S.L = l;
    if (b.games.some(g => g.state === "in")) await liveScores();
    render();
    if (b.games.some(g => g.state === "in") && (!S.drvAt || Date.now() - S.drvAt > 10000)) { S.drvAt = Date.now(); pollDrives(); }
  } catch (e) {
    if (!S.B) $("#view").innerHTML = `<div class="empty">Couldn't load data. Pull to refresh.</div>`;
  }
}
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; localSet("tab", S.tab); window.scrollTo(0, 0); render(); pollDrives(); });
$("#gear").onclick = () => { S.tab = "setup"; document.querySelectorAll("#tabs button").forEach(b => b.classList.remove("on")); window.scrollTo(0, 0); render(); };
$("#modalClose").onclick = closeModal;
$("#modal").onclick = e => { if (e.target.id === "modal") closeModal(); };
const th = localGet("theme"); if (th) document.documentElement.dataset.theme = th;   // default: dark
load();
setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
setInterval(() => pollDrives(), 15000);
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
