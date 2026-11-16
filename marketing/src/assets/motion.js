/* Presence Pro: the movement layer. Everything here is decoration: the site reads and works the same without it, and it is switched off
   for visitors who ask their device for reduced motion. No libraries, nothing loaded from other sites. */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) return;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  root.classList.add("motion");

  // 1. headline: words rise in one after another
  $$(".hero h1, .page-hero h1").forEach(function (h) {
    var i = 0;
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (c) {
        if (c.nodeType === 3) {
          var frag = document.createDocumentFragment();
          c.nodeValue.split(/(\s+)/).forEach(function (part) {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
            var s = document.createElement("span"); s.className = "wd"; s.style.setProperty("--i", i++); s.textContent = part; frag.appendChild(s);
          });
          node.replaceChild(frag, c);
        } else if (c.nodeType === 1) { walk(c); }
      });
    })(h);
    void h.offsetWidth;                         // settle the hidden start state, then let the words rise
    h.classList.add("go");
  });

  // 2. staggered reveals, and a "settled" state so hover effects are quick after the entrance
  var groups = new Map();
  $$(".rv").forEach(function (e) {
    if (/\bd[123]\b/.test(e.className) || e.classList.contains("ph")) return;
    var p = e.parentNode; var n = groups.get(p) || 0; groups.set(p, n + 1);
    if (n > 0) e.style.transitionDelay = Math.min(n, 5) * 70 + "ms";
  });
  if ("IntersectionObserver" in window) {
    var settle = new IntersectionObserver(function (es) {
      es.forEach(function (en) { if (en.isIntersecting) { var t = en.target; setTimeout(function () { t.classList.add("done"); t.style.transitionDelay = ""; }, 1300); settle.unobserve(t); } });
    }, { threshold: .12 });
    $$(".rv").forEach(function (e) { settle.observe(e); });

    // 3. numbers count up once, when they come into view
    var count = new IntersectionObserver(function (es) {
      es.forEach(function (en) {
        if (!en.isIntersecting) return;
        count.unobserve(en.target);
        var el = en.target, txt = el.getAttribute("data-final"), m = /^(\D*)(\d+(?:\.\d+)?)(.*)$/.exec(txt);
        if (!m) return;
        var to = parseFloat(m[2]), dec = (m[2].split(".")[1] || "").length, t0 = null;
        (function tick(t) {
          if (t0 === null) t0 = t;
          var k = Math.min(1, (t - t0) / 1400), e = 1 - Math.pow(1 - k, 3);
          el.textContent = m[1] + (to * e).toFixed(dec) + m[3];
          if (k < 1) requestAnimationFrame(tick); else el.textContent = txt;
        })(performance.now());
      });
    }, { threshold: .6 });
    $$(".big").forEach(function (el) {
      var txt = el.textContent.trim();
      if (!/^\D*\d/.test(txt) || /[×x]$/.test(txt)) return;   // leave "2×" alone
      el.setAttribute("data-final", txt); el.textContent = txt.replace(/\d+(\.\d+)?/, "0"); count.observe(el);
    });
  }

  // 4. scroll progress bar, header that steps aside while reading, parallax street and photos
  var bar = document.createElement("div"); bar.className = "progress"; bar.setAttribute("aria-hidden", "true"); document.body.appendChild(bar);
  var nav = $("#nav"), hero = $(".hero, .page-hero"), photos = $$(".ph img"), lastY = window.scrollY, ticking = false;
  function frame() {
    ticking = false;
    var y = window.scrollY, max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    bar.style.setProperty("--p", Math.min(1, y / max).toFixed(4));
    if (nav && !nav.classList.contains("menu-open")) {
      if (y > 220 && y - lastY > 6) nav.classList.add("hide"); else if (y < lastY - 6 || y < 120) nav.classList.remove("hide");
    }
    lastY = y;
    if (hero && y < 900) { hero.style.setProperty("--py", Math.min(y * .22, 56).toFixed(1) + "px"); hero.style.setProperty("--cy", (-y * .06).toFixed(1) + "px"); }
    var vh = window.innerHeight;
    photos.forEach(function (img) {
      var r = img.parentNode.getBoundingClientRect();
      if (r.bottom < -50 || r.top > vh + 50) return;
      var k = ((r.top + r.height / 2) - vh / 2) / vh;                 // -0.5 .. 0.5 across the screen
      img.style.setProperty("--ty", (k * -34).toFixed(1) + "px");
    });
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(frame); } }
  window.addEventListener("scroll", onScroll, { passive: true }); window.addEventListener("resize", onScroll); frame();
  if (nav) { nav.addEventListener("focusin", function () { nav.classList.remove("hide"); }); }

  // 5. the example AI answer leans gently towards the pointer
  var chat = $(".hero .chat");
  if (chat && window.matchMedia("(hover: hover)").matches) {
    var wrap = chat.parentNode;
    wrap.addEventListener("pointermove", function (e) {
      var r = chat.getBoundingClientRect(), x = (e.clientX - (r.left + r.width / 2)) / r.width, y = (e.clientY - (r.top + r.height / 2)) / r.height;
      chat.style.setProperty("--ry", (x * 5).toFixed(2) + "deg"); chat.style.setProperty("--rx", (-y * 4).toFixed(2) + "deg");
    });
    wrap.addEventListener("pointerleave", function () { chat.style.setProperty("--ry", "0deg"); chat.style.setProperty("--rx", "0deg"); });
  }
})();
