/* Presence Pro sample dashboard: an interactive demonstration with a fictional hotel and invented figures.
   Nothing here is real data. The page is plain HTML underneath: if this script is off, the text above the demo still explains it. */
(function () {
  "use strict";
  var root = document.getElementById("dm");
  if (!root) return;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  var MONTHS = ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"];
  var NAMED = [1, 2, 3, 3, 4, 5];            // answers (of 14) that named the hotel, per month: invented
  var TOTAL = 14;
  var QUESTIONS = [
    { q: "Which hotel near the conference centre is best for a business trip?", n: 0, t: 4, who: ["Cathedral Close Inn", "Marlow & Finch Hotel", "The Quayside"] },
    { q: "Is there a hotel with free parking near the cathedral?", n: 1, t: 3, who: ["The Lantern House", "The Quayside"] },
    { q: "Where should we stay in Brightmouth with young children?", n: 0, t: 3, who: ["The Lantern House", "Marlow & Finch Hotel"] },
    { q: "A quiet boutique hotel for a weekend away?", n: 4, t: 4, who: ["Marlow & Finch Hotel"] }
  ];
  var COMPETITORS = [["The Lantern House", 64], ["Marlow & Finch Hotel", 43], ["Cathedral Close Inn", 29], ["The Quayside", 21]];
  var SOURCES = [
    { name: "Brightmouth Business Travel Guide", type: "Guide", names: "Cathedral Close Inn, Marlow & Finch", you: false },
    { name: "Conference centre: where to stay", type: "Venue page", names: "Cathedral Close Inn, Marlow & Finch", you: false },
    { name: "Family Days Out in Brightmouth", type: "Blog", names: "The Lantern House", you: false },
    { name: "Booking site listing", type: "Booking site", names: "All four hotels", you: true },
    { name: "Brightmouth Tourism: places to stay", type: "Tourism page", names: "Six hotels, including yours", you: true }
  ];
  var ACTIONS = [
    { t: "Get onto the two pages the assistant cited", why: "Both name your rivals and not you. Seek honest inclusion, never paid editorial.", tag: "ck", tagText: "Worth checking", done: false },
    { t: "Add the walking distance and meeting facilities as text", why: "On a page guests open. Evidence: the meeting rooms appear only in a PDF.", tag: "lk", tagText: "Likely", done: false },
    { t: "Answer the family-friendly questions you are missing", why: "Named in 0 of 3 answers; rivals are named in all three.", tag: "lk", tagText: "Likely", done: false },
    { t: "State the parking price on the parking page", why: "Evidence: the price appears only in the footer of the booking page.", tag: "ok", tagText: "Confirmed", done: true },
    { t: "Reply to the three unanswered critical reviews", why: "Evidence: three critical reviews from the last quarter have no reply.", tag: "ok", tagText: "Confirmed", done: false }
  ];
  var HOTELS = [
    { name: "The Harbour Lane Hotel", you: true, spark: [1, 2, 3, 3, 4, 5], note: "" },
    { name: "Riverside Suites", spark: [3, 4, 5, 6, 8, 9], ch: 6, named: 9, done: 5, of: 6 },
    { name: "The Orchard House", spark: [1, 1, 2, 3, 3, 5], ch: 4, named: 5, done: 3, of: 8 },
    { name: "Cathedral View Hotel", spark: [4, 4, 5, 4, 4, 4], ch: 0, named: 4, done: 2, of: 6 },
    { name: "Old Town Lodge", spark: [4, 4, 3, 5, 3, 2], ch: -3, named: 2, done: 1, of: 7 },
    { name: "Station Road Inn", spark: [1, 1, 1, 2, 1, 1], ch: 0, named: 1, done: 0, of: 6 }
  ];

  var S = { view: "hotel", tab: "overview", month: 5, onlyMissed: false, msg: "" };

  function doneCount() { return ACTIONS.filter(function (a) { return a.done; }).length; }
  function pct(n) { return Math.round(n / TOTAL * 100); }
  function ring(p, label) { return '<div class="dm-ring" style="--p:' + p + '"><b>' + esc(label) + "</b></div>"; }
  function statusOf(h) { return h.named <= 2 || h.ch < 0 ? ["hi", "Needs attention"] : h.ch > 0 ? ["ok", "Improving"] : ["ck", "Steady"]; }
  function hotelRow(h) {
    if (h.you) { h.named = NAMED[5]; h.ch = NAMED[5] - NAMED[4]; h.done = doneCount(); h.of = ACTIONS.length; }
    return h;
  }
  function spark(a) {
    var max = Math.max.apply(null, a), min = Math.min.apply(null, a), w = 92, h = 26, span = Math.max(1, max - min);
    var pts = a.map(function (v, i) { return (i * (w / (a.length - 1))).toFixed(1) + "," + (h - 3 - (v - min) / span * (h - 8)).toFixed(1); }).join(" ");
    return '<svg class="dm-spark" viewBox="0 0 ' + w + " " + h + '" aria-hidden="true"><polyline points="' + pts + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  // ---------- views ----------
  function chart() {
    var W = 560, H = 150, pad = 18, n = NAMED.length, xs = [], ys = [];
    NAMED.forEach(function (v, i) { xs.push(pad + i * ((W - pad * 2) / (n - 1))); ys.push(H - 26 - v / TOTAL * (H - 50)); });
    var line = xs.map(function (x, i) { return x.toFixed(1) + "," + ys[i].toFixed(1); }).join(" ");
    var area = "M" + xs[0].toFixed(1) + "," + (H - 26) + " L" + line.replace(/ /g, " L") + " L" + xs[n - 1].toFixed(1) + "," + (H - 26) + " Z";
    var dots = xs.map(function (x, i) {
      var sel = i === S.month;
      return '<g><circle cx="' + x.toFixed(1) + '" cy="' + ys[i].toFixed(1) + '" r="' + (sel ? 7 : 4) + '" fill="' + (sel ? "#b98a35" : "#fff") + '" stroke="#b98a35" stroke-width="2.5"/>' +
        '<text x="' + x.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" class="dm-axis' + (sel ? " sel" : "") + '">' + MONTHS[i] + "</text></g>";
    }).join("");
    return '<svg class="dm-chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Line chart of how many of 14 answers named the hotel each month, from ' + NAMED[0] + " in June to " + NAMED[n - 1] + ' in November. Invented figures.">' +
      '<defs><linearGradient id="dmg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3ab63" stop-opacity=".45"/><stop offset="1" stop-color="#d3ab63" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="' + area + '" fill="url(#dmg)"/><polyline points="' + line + '" fill="none" stroke="#b98a35" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>' + dots + "</svg>";
  }
  function overview() {
    var n = NAMED[S.month], prev = S.month > 0 ? NAMED[S.month - 1] : n, d = n - prev, nextA = ACTIONS.filter(function (a) { return !a.done; })[0];
    var bars = QUESTIONS.map(function (q) {
      var p = Math.round(q.n / q.t * 100);
      return '<div class="dm-qb"><span>' + esc(q.q) + '</span><div class="dm-tr"><i style="width:' + p + '%"></i></div><em>' + q.n + " of " + q.t + "</em></div>";
    }).join("");
    var mb = MONTHS.map(function (m, i) { return '<button type="button" data-month="' + i + '" aria-pressed="' + (i === S.month ? "true" : "false") + '">' + m + "</button>"; }).join("");
    return '<div class="dm-head"><div><h3>The Harbour Lane Hotel</h3><p>Brightmouth &middot; 4-star city hotel</p></div><div class="dm-months" role="group" aria-label="Choose a month">' + mb + "</div></div>" +
      '<div class="dm-tiles">' +
      '<div class="dm-tile"><small>AI visibility, ' + MONTHS[S.month] + "</small>" + ring(pct(n), pct(n) + "%") + "<span>named in " + n + " of " + TOTAL + " answers" + (S.month > 0 ? (d === 0 ? ", no change" : (d > 0 ? ", up " : ", down ") + Math.abs(d)) : "") + "</span></div>" +
      '<div class="dm-tile warn"><small>Missed recommendations</small><b class="dm-big">' + (TOTAL - n) + "</b><span>answers named rivals only</span></div>" +
      '<div class="dm-tile"><small>Top competitor</small><b class="dm-big">' + COMPETITORS[0][1] + "%</b><span>" + esc(COMPETITORS[0][0]) + "</span></div>" +
      '<div class="dm-tile"><small>Actions done</small>' + ring(Math.round(doneCount() / ACTIONS.length * 100), doneCount() + "/" + ACTIONS.length) + "<span>" + (ACTIONS.length - doneCount()) + " still open</span></div></div>" +
      '<div class="dm-two"><section class="dm-card"><h4>Named by AI, month by month</h4>' + chart() + '<p class="dm-note">The same questions are asked each month, so changes are comparable. Progress is not proof that one action caused a change.</p></section>' +
      '<section class="dm-card"><h4>Who is named instead</h4>' + COMPETITORS.map(function (c) { return '<div class="dm-qb"><span>' + esc(c[0]) + '</span><div class="dm-tr"><i class="rv" style="width:' + c[1] + '%"></i></div><em>' + c[1] + "%</em></div>"; }).join("") + "</section></div>" +
      '<div class="dm-two"><section class="dm-card"><h4>By question (' + MONTHS[5] + ")</h4>" + bars + "</section>" +
      '<section class="dm-card dm-next"><h4>Next best action</h4>' + (nextA ? '<p class="dm-na"><b>' + esc(nextA.t) + "</b><span>" + esc(nextA.why) + '</span></p><button type="button" class="dm-link" data-go="actions">See all actions &rarr;</button>' : '<p class="dm-na"><b>All actions done.</b><span>The same questions are asked again next month, so you can see what moved.</span></p>') + "</section></div>";
  }
  function questions() {
    var rows = QUESTIONS.filter(function (q) { return !S.onlyMissed || q.n < q.t; }).map(function (q) {
      var p = Math.round(q.n / q.t * 100);
      return '<tr><td>' + esc(q.q) + '</td><td class="n">' + q.n + " of " + q.t + '</td><td><div class="dm-tr"><i style="width:' + p + '%"></i></div></td><td>' + q.who.map(function (w) { return '<span class="dm-chip">' + esc(w) + "</span>"; }).join("") + "</td></tr>";
    }).join("");
    return '<div class="dm-head"><div><h3>Guest questions</h3><p>Written the way guests ask, without the hotel\'s name. Each asked more than once.</p></div><label class="dm-toggle"><input type="checkbox" id="dm-missed"' + (S.onlyMissed ? " checked" : "") + '> Show questions we were missed on</label></div>' +
      '<div class="dm-card dm-tablecard"><div class="dm-scroll"><table class="dm-table"><thead><tr><th>Question</th><th>Named</th><th></th><th>Named instead</th></tr></thead><tbody>' + rows + "</tbody></table></div></div>";
  }
  function sources() {
    var yes = SOURCES.filter(function (s) { return s.you; }).length;
    return '<div class="dm-head"><div><h3>Pages the assistant relied on</h3><p>' + yes + " of " + SOURCES.length + " cited pages include your hotel.</p></div></div>" +
      '<div class="dm-list">' + SOURCES.map(function (s) {
        return '<div class="dm-src"><span class="dm-type">' + esc(s.type) + "</span><div><b>" + esc(s.name) + "</b><small>Names: " + esc(s.names) + '</small></div><span class="dm-pill ' + (s.you ? "ok" : "hi") + '">' + (s.you ? "You: listed" : "You: not listed") + "</span></div>";
      }).join("") + "</div>";
  }
  function actions() {
    var n = doneCount();
    return '<div class="dm-head"><div><h3>Actions</h3><p>Tick one off as you complete it. Each shows its evidence and how sure we are.</p></div><div class="dm-prog" aria-label="' + n + " of " + ACTIONS.length + ' actions done"><i style="width:' + Math.round(n / ACTIONS.length * 100) + '%"></i><span>' + n + " of " + ACTIONS.length + " done</span></div></div>" +
      '<div class="dm-list">' + ACTIONS.map(function (a, i) {
        return '<div class="dm-act' + (a.done ? " done" : "") + '"><button type="button" class="dm-check" role="checkbox" aria-checked="' + (a.done ? "true" : "false") + '" data-act="' + i + '" aria-label="Mark done: ' + esc(a.t) + '"></button><div><b>' + esc(a.t) + "</b><small>" + esc(a.why) + '</small></div><span class="dm-pill ' + a.tag + '">' + a.tagText + "</span></div>";
      }).join("") + "</div>";
  }
  function reports() {
    var months = ["November 2026", "October 2026", "September 2026", "August 2026"];
    return '<div class="dm-head"><div><h3>Reports</h3><p>Pull a report from the dashboard whenever you need one: for the owner, the board or your team.</p></div></div>' +
      '<div class="dm-list">' + months.map(function (m, i) {
        return '<div class="dm-src"><span class="dm-type">PDF</span><div><b>' + m + ' report</b><small>' + (i === 0 ? "Latest check" : "Earlier check") + ' &middot; The Harbour Lane Hotel</small></div><button type="button" class="dm-btn" data-report="1">Pull report</button></div>';
      }).join("") + "</div>" + (S.msg ? '<p class="dm-msg" role="status">' + esc(S.msg) + "</p>" : "");
  }
  function group() {
    var rows = HOTELS.map(hotelRow);
    var imp = rows.filter(function (h) { return statusOf(h)[0] === "ok"; }).length, need = rows.filter(function (h) { return statusOf(h)[0] === "hi"; }).length;
    var avg = Math.round(rows.reduce(function (s, h) { return s + h.named; }, 0) / rows.length / TOTAL * 100);
    return '<div class="dm-head"><div><h3>Portfolio overview</h3><p>Every hotel in the group, with the same questions asked of each. Each hotel sees only itself.</p></div></div>' +
      '<div class="dm-tiles"><div class="dm-tile"><small>Hotels</small><b class="dm-big">' + rows.length + '</b><span>in this group</span></div><div class="dm-tile"><small>Average named by AI</small><b class="dm-big">' + avg + '%</b><span>across all hotels</span></div><div class="dm-tile"><small>Improving</small><b class="dm-big up">' + imp + '</b><span>since last month</span></div><div class="dm-tile warn"><small>Need attention</small><b class="dm-big">' + need + "</b><span>hotels</span></div></div>" +
      '<div class="dm-card dm-tablecard"><div class="dm-scroll"><table class="dm-table"><thead><tr><th>Hotel</th><th>Named by AI</th><th>Trend</th><th>Since last month</th><th>Actions done</th><th>Status</th></tr></thead><tbody>' +
      rows.map(function (h, i) {
        var st = statusOf(h);
        return '<tr class="dm-hrow' + (h.you ? " you" : "") + '" data-hotel="' + i + '" tabindex="0"><td><b>' + esc(h.name) + "</b>" + (h.you ? '<small>Open the detailed view</small>' : "") + '</td><td class="n">' + h.named + ' of 14</td><td class="dm-sp">' + spark(h.spark) + '</td><td class="n ' + (h.ch > 0 ? "up" : h.ch < 0 ? "down" : "") + '">' + (h.ch > 0 ? "+" : h.ch < 0 ? "−" : "") + Math.abs(h.ch) + '</td><td class="n">' + h.done + " of " + h.of + '</td><td><span class="dm-pill ' + st[0] + '">' + st[1] + "</span></td></tr>";
      }).join("") + "</tbody></table></div></div>" + (S.msg ? '<p class="dm-msg" role="status">' + esc(S.msg) + "</p>" : "") +
      '<p class="dm-note" style="margin-top:12px">Progress shown is progress, not proof that one action caused a change.</p>';
  }

  var TABS = { hotel: [["overview", "Overview"], ["questions", "Questions"], ["sources", "Sources"], ["actions", "Actions"], ["reports", "Reports"]], group: [["portfolio", "Portfolio"]] };
  function draw() {
    root.setAttribute("data-view", S.view);
    $$(".dm-switch button", root).forEach(function (b) { b.setAttribute("aria-selected", b.getAttribute("data-view") === S.view ? "true" : "false"); });
    $("#dm-side", root).innerHTML = TABS[S.view].map(function (t) { return '<button type="button" data-tab="' + t[0] + '" aria-current="' + (t[0] === S.tab ? "page" : "false") + '">' + t[1] + (t[0] === "actions" ? ' <u>' + (ACTIONS.length - doneCount()) + "</u>" : "") + "</button>"; }).join("");
    var html = S.view === "group" ? group() : S.tab === "questions" ? questions() : S.tab === "sources" ? sources() : S.tab === "actions" ? actions() : S.tab === "reports" ? reports() : overview();
    $("#dm-main", root).innerHTML = html;
    requestAnimationFrame(function () { $$(".dm-tr i.rv", root).forEach(function (i) { i.classList.remove("rv"); }); });
  }

  root.addEventListener("click", function (e) {
    var t = e.target.closest("button, tr[data-hotel]");
    if (!t) return;
    if (t.hasAttribute("data-view")) { S.view = t.getAttribute("data-view"); S.tab = S.view === "group" ? "portfolio" : "overview"; S.msg = ""; draw(); return; }
    if (t.hasAttribute("data-tab")) { S.tab = t.getAttribute("data-tab"); S.msg = ""; draw(); return; }
    if (t.hasAttribute("data-go")) { S.tab = t.getAttribute("data-go"); draw(); return; }
    if (t.hasAttribute("data-month")) { S.month = +t.getAttribute("data-month"); draw(); return; }
    if (t.hasAttribute("data-act")) { var a = ACTIONS[+t.getAttribute("data-act")]; a.done = !a.done; draw(); var again = $('[data-act="' + t.getAttribute("data-act") + '"]', root); if (again) again.focus(); return; }
    if (t.hasAttribute("data-report")) { S.msg = "In the real dashboard this downloads the report as a PDF. This demo has no real file."; draw(); return; }
    if (t.hasAttribute("data-hotel")) {
      var h = HOTELS[+t.getAttribute("data-hotel")];
      if (h.you) { S.view = "hotel"; S.tab = "overview"; S.msg = ""; } else { S.msg = h.name + " has its own dashboard in the real thing. This demo shows one hotel in detail: The Harbour Lane Hotel."; }
      draw();
    }
  });
  root.addEventListener("keydown", function (e) { if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr[data-hotel]")) { e.preventDefault(); e.target.click(); } });
  root.addEventListener("change", function (e) { if (e.target.id === "dm-missed") { S.onlyMissed = e.target.checked; draw(); var c = $("#dm-missed", root); if (c) c.focus(); } });
  draw();
})();
