/* Presence Pro homepage: drives the sticky demonstration stage. Everything here is illustrative and decorative-in-service-of-the-story:
   the captions carry the full explanation in plain text, so the page reads the same with this script off or with reduced motion. */
(function () {
  "use strict";
  var story = document.getElementById("story");
  if (!story) return;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var stage = $(".story-stage", story), steps = $$(".chap", story), panels = {}, dots = $$(".stage-dots li", story);
  $$(".pn", stage).forEach(function (p) { panels[p.getAttribute("data-p")] = p; });
  var SHOW = [["answer"], ["answer", "sources"], ["site"], ["actions"], ["dash"]];
  var cur = -1;

  // ---- which scene is the reader on? The caption nearest the reading line decides. ----
  function focusY() {
    var vh = window.innerHeight;
    if (window.innerWidth >= 960) return vh * 0.5;
    var b = stage.getBoundingClientRect().bottom;         // phones: the stage is stuck at the top, the captions read below it
    return b + (vh - b) / 2;
  }
  function setScene(i) {
    if (i === cur) return;
    cur = i; stage.setAttribute("data-s", i);
    Object.keys(panels).forEach(function (k) { panels[k].classList.toggle("on", SHOW[i].indexOf(k) > -1); });
    steps.forEach(function (s, n) { s.classList.toggle("cur", n === i); });
    dots.forEach(function (d, n) { d.classList.toggle("on", n === i); });
    if (i === 4) animateDash();
  }
  var ticking = false;
  function pick() {
    ticking = false;
    var fy = focusY(), best = 0, bd = 1e9;
    steps.forEach(function (s, n) {
      var r = s.getBoundingClientRect(), d = Math.abs(r.top + r.height / 2 - fy);
      if (n === 0 && r.bottom > fy) d = Math.min(d, 0);     // while the hero copy is still on the reading line, stay on scene 0
      if (d < bd) { bd = d; best = n; }
    });
    setScene(best);
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(pick); } }
  window.addEventListener("scroll", onScroll, { passive: true }); window.addEventListener("resize", onScroll);

  // ---- scene 0: a guest asks, the assistant answers, your hotel is missing ----
  var q = $(".chat-q", stage), qt = $(".t", q), full = q.getAttribute("data-text"), recs = $$(".rec", stage), played = false;
  function playDemo() {
    if (played) return; played = true;
    if (reduce) { qt.textContent = full; recs.forEach(function (r) { r.classList.add("show"); }); var c = $(".caret", q); if (c) c.style.display = "none"; return; }
    var i = 0;
    setTimeout(function tick() {
      qt.textContent = full.slice(0, ++i);
      if (i < full.length) setTimeout(tick, 22 + Math.random() * 26);
      else recs.forEach(function (r, n) { setTimeout(function () { r.classList.add("show"); }, 380 + n * 520); });
    }, 700);
  }
  // start when the stage is on screen: straight away on desktop (it is beside the headline), on first view on phones
  function maybePlay() { if (!played && stage.getBoundingClientRect().top < window.innerHeight * 0.75) playDemo(); }
  window.addEventListener("scroll", maybePlay, { passive: true }); window.addEventListener("resize", maybePlay);
  setTimeout(maybePlay, 500); maybePlay();

  // ---- scene 4: the interactive dashboard (illustrative data) ----
  var DATA = {
    all:  { pct: 36, named: "named in 5 of 14 answers", miss: 9,  top: "64%",  topN: "The Lantern House", bars: [["The Lantern House", 64, "9 of 14"], ["Marlow & Finch", 43, "6 of 14"], ["Your hotel", 36, "5 of 14", 1], ["Cathedral Close Inn", 29, "4 of 14"], ["The Quayside", 21, "3 of 14"]] },
    conf: { pct: 0,  named: "named in 0 of 5 answers", miss: 5,  top: "100%", topN: "Cathedral Close Inn", bars: [["Cathedral Close Inn", 100, "5 of 5"], ["Marlow & Finch", 80, "4 of 5"], ["The Quayside", 40, "2 of 5"], ["Your hotel", 0, "0 of 5", 1]] },
    park: { pct: 33, named: "named in 1 of 3 answers", miss: 2,  top: "67%",  topN: "The Lantern House", bars: [["The Lantern House", 67, "2 of 3"], ["The Quayside", 67, "2 of 3"], ["Your hotel", 33, "1 of 3", 1], ["Marlow & Finch", 33, "1 of 3"]] },
    fam:  { pct: 0,  named: "named in 0 of 3 answers", miss: 3,  top: "100%", topN: "The Lantern House", bars: [["The Lantern House", 100, "3 of 3"], ["The Quayside", 67, "2 of 3"], ["Marlow & Finch", 33, "1 of 3"], ["Your hotel", 0, "0 of 3", 1]] }
  };
  var dRing = $("#dRing"), dPct = $("#dPct"), dNamed = $("#dNamed"), dMiss = $("#dMiss"), dTop = $("#dTop"), dTopN = $("#dTopN"), dBars = $("#dBars"), tabs = $$(".dsh-tabs button", stage);
  var shown = 0, dashKey = "all";
  function tween(from, to, ms, fn) {
    if (reduce) { fn(to); return; }
    setTimeout(function () { fn(to); }, ms + 80);            // land on the true value even if animation frames are paused
    var t0 = null; (function f(t) { if (t0 === null) t0 = t; var k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3); fn(from + (to - from) * e); if (k < 1) requestAnimationFrame(f); })(performance.now());
  }
  function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
  function renderDash(key) {
    var d = DATA[key]; dashKey = key;
    tween(shown, d.pct, 800, function (v) { v = Math.round(v); dRing.style.setProperty("--p", v); dPct.textContent = v + "%"; });
    shown = d.pct;
    dNamed.textContent = d.named; dMiss.textContent = d.miss; dTop.textContent = d.top; dTopN.textContent = d.topN;
    dBars.innerHTML = d.bars.map(function (b) {
      return '<div class="db' + (b[3] ? " you" : "") + '"><span>' + esc(b[0]) + '</span><div class="tr"><i data-w="' + b[1] + '"></i></div><em>' + b[1] + '%<small>' + b[2] + '</small></em></div>';
    }).join("");
    requestAnimationFrame(function () { requestAnimationFrame(function () { $$("i", dBars).forEach(function (i) { i.style.width = i.getAttribute("data-w") + "%"; }); }); });
    tabs.forEach(function (t) { t.setAttribute("aria-selected", t.getAttribute("data-k") === key ? "true" : "false"); });
  }
  var dashPlayed = false;
  function animateDash() { if (dashPlayed) return; dashPlayed = true; shown = 0; renderDash("all"); }
  tabs.forEach(function (t) { t.addEventListener("click", function () { dashPlayed = true; renderDash(t.getAttribute("data-k")); }); });
  renderDash("all"); dashPlayed = false;           // pre-render so there is real text in the page before the scene is reached
  dBars.innerHTML = dBars.innerHTML;

  // ---- depth and light: the stage leans towards the pointer, a soft spotlight follows it ----
  if (!reduce && window.matchMedia("(hover: hover)").matches) {
    var inner = $(".stage-inner", stage);
    story.addEventListener("pointermove", function (e) {
      var r = story.getBoundingClientRect(); story.style.setProperty("--mx", (e.clientX - r.left) + "px"); story.style.setProperty("--my", (e.clientY - r.top) + "px");
      var s = stage.getBoundingClientRect(), x = (e.clientX - (s.left + s.width / 2)) / s.width, y = (e.clientY - (s.top + s.height / 2)) / s.height;
      inner.style.setProperty("--ry", (-3 + x * 5).toFixed(2) + "deg"); inner.style.setProperty("--rx", (2 - y * 4).toFixed(2) + "deg");
      inner.style.setProperty("--gx", ((e.clientX - s.left) / s.width * 100).toFixed(0) + "%"); inner.style.setProperty("--gy", ((e.clientY - s.top) / s.height * 100).toFixed(0) + "%");
    });
  }

  // ---- "Today / With the gaps fixed" ----
  var flip = $(".flip-viz"), sw = $$(".flip-sw button");
  sw.forEach(function (b) { b.addEventListener("click", function () { flip.setAttribute("data-st", b.getAttribute("data-st")); sw.forEach(function (x) { x.setAttribute("aria-selected", x === b ? "true" : "false"); }); }); });

  pick();
})();
