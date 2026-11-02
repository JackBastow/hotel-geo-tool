(function () {
  "use strict";
  var cfg = window.PP || {};
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // nav: solid once scrolled, mobile menu
  var nav = $("#nav"), links = $("#links"), btn = $("#menuBtn");
  function stick() { nav.classList.toggle("stuck", window.scrollY > 24); }
  stick(); window.addEventListener("scroll", stick, { passive: true });
  btn.addEventListener("click", function () {
    var open = links.classList.toggle("open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    nav.classList.toggle("menu-open", open);
  });
  $$("a", links).forEach(function (a) { a.addEventListener("click", function () { links.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); nav.classList.remove("menu-open"); }); });

  // scroll reveal
  var rv = $$(".rv");
  if (reduce || !("IntersectionObserver" in window)) { rv.forEach(function (e) { e.classList.add("on"); }); }
  else {
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("on"); io.unobserve(e.target); } }); }, { threshold: .12, rootMargin: "0px 0px -6% 0px" });
    rv.forEach(function (e) { io.observe(e); });
  }

  // billing: monthly / yearly switch and the buy buttons (Stripe Payment Links from site.json; the contact page until a link exists)
  var interval = "monthly";
  function link(id) { var l = cfg.LINKS && cfg.LINKS[id]; return l && l[interval] ? l[interval] : ""; }
  function paint() {
    var key = interval === "annual" ? "a" : "m";
    $$("[data-m]").forEach(function (e) { var v = e.getAttribute("data-" + key); if (v !== null) e.textContent = v; });
    $$("[data-buy]").forEach(function (a) {
      var id = a.getAttribute("data-buy"), url = link(id);
      if (url) { a.href = url; a.textContent = "Subscribe"; a.target = "_blank"; a.rel = "noopener"; }
      else { a.href = "/contact.html?plan=" + id + "&billing=" + interval; a.textContent = "Get started"; a.removeAttribute("target"); }
    });
    $$(".toggle button").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-interval") === interval ? "true" : "false"); });
  }
  $$(".toggle button").forEach(function (b) { b.addEventListener("click", function () { interval = b.getAttribute("data-interval"); paint(); }); });
  if ($("[data-buy]")) paint();

  // home page only: type the question, then reveal the answer
  var typed = $("#typed");
  if (typed) {
    var txt = $(".txt", typed), full = typed.getAttribute("data-text"), rows = $$(".hotel-row"), srcs = $(".srcs"), ins = $(".insight");
    var reveal = function () {
      rows.forEach(function (r, i) { setTimeout(function () { r.classList.add("on"); }, 300 + i * 450); });
      setTimeout(function () { srcs.classList.add("on"); }, 300 + rows.length * 450);
      setTimeout(function () { ins.classList.add("on"); }, 700 + rows.length * 450);
    };
    if (reduce) { txt.textContent = full; reveal(); }
    else {
      var i = 0;
      setTimeout(function tick() { txt.textContent = full.slice(0, ++i); if (i < full.length) setTimeout(tick, 26 + Math.random() * 28); else setTimeout(reveal, 250); }, 700);
    }
  }

  // home page only: report tabs
  var tabs = $$(".tab"), panels = $$(".panel");
  if (tabs.length) {
    var animateBars = function () { $$("#p1 .track i").forEach(function (b) { b.style.width = "0"; setTimeout(function () { b.style.width = b.getAttribute("data-w") + "%"; }, 60); }); };
    var show = function (i, focus) {
      tabs.forEach(function (t, j) { t.setAttribute("aria-selected", j === i ? "true" : "false"); t.tabIndex = j === i ? 0 : -1; });
      panels.forEach(function (p, j) { p.classList.toggle("on", j === i); });
      if (i === 0) animateBars();
      if (focus) tabs[i].focus();
    };
    tabs.forEach(function (t, i) {
      t.tabIndex = i === 0 ? 0 : -1;
      t.addEventListener("click", function () { show(i); });
      t.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); show((i + 1) % tabs.length, true); }
        if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); show((i + tabs.length - 1) % tabs.length, true); }
      });
    });
    var rep = $("#report");
    if (rep && "IntersectionObserver" in window) {
      var once = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { animateBars(); once.disconnect(); } }, { threshold: .3 });
      once.observe(rep);
    } else { animateBars(); }
  }

  // contact form: posts to the form service in site.json if there is one, otherwise opens the visitor's email app addressed to us
  var form = $("#contactForm"), msg = $("#formMsg");
  if (form) {
    var qs = new URLSearchParams(window.location.search), want = qs.get("plan");
    if (want && form.topic) { var opt = $$("option", form.topic).filter(function (o) { return o.value === want; })[0]; if (opt) form.topic.value = want; }
    var say = function (kind, text) { msg.className = "msg " + kind; msg.textContent = text; };
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var d = new FormData(form);
      if (d.get("company")) { say("ok", "Thanks, we'll be in touch."); return; } // honeypot: a person never fills this
      var email = String(d.get("email") || "").trim();
      if (!String(d.get("name") || "").trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || !String(d.get("message") || "").trim()) { say("err", "Please add your name, a valid email and a message."); return; }
      if (cfg.FORM_ENDPOINT) {
        fetch(cfg.FORM_ENDPOINT, { method: "POST", headers: { Accept: "application/json" }, body: d })
          .then(function (r) { if (!r.ok) throw new Error(r.status); form.reset(); say("ok", "Thanks, your message has been sent."); })
          .catch(function () { say("err", "Sorry, that didn't send. Please email " + cfg.EMAIL + " instead."); });
      } else {
        var topic = form.topic ? form.topic.options[form.topic.selectedIndex].text : "";
        var body = "Name: " + d.get("name") + "\nEmail: " + email + "\nHotel website: " + (d.get("website") || "") + "\nAbout: " + topic + "\n\n" + d.get("message");
        window.location.href = "mailto:" + cfg.EMAIL + "?subject=" + encodeURIComponent("Presence Pro: " + topic) + "&body=" + encodeURIComponent(body);
        say("ok", "Your email app should open with your message ready to send. If it doesn't, write to " + cfg.EMAIL + ".");
      }
    });
  }
})();
