(function () {
  "use strict";
  var cfg = window.PP || {};
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // Sends a form to the form service named in site.json (Web3Forms or Formspree), so the visitor never leaves the page. Resolves once it was accepted.
  window.PPsend = function (data, subject) {
    if (cfg.FORM_KEY) { data.append("access_key", cfg.FORM_KEY); data.append("subject", subject); data.append("from_name", "Presence Pro website"); }
    return fetch(cfg.FORM_ENDPOINT, { method: "POST", headers: { Accept: "application/json" }, body: data })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok || j.success === false) throw new Error(j.message || r.status); }); });
  };

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

  // billing: monthly / yearly switch and the buy buttons. Subscribe opens Stripe through our own checkout; a Payment Link from site.json
  // (if one is set) or the contact page is the fallback.
  var interval = "monthly";
  function link(id) { var l = cfg.LINKS && cfg.LINKS[id]; if (!l) return ""; return l[interval] || (interval === "annual" ? l.monthly || "" : ""); }
  function paint() {
    var key = interval === "annual" ? "a" : "m";
    $$("[data-m]").forEach(function (e) { var v = e.getAttribute("data-" + key); if (v !== null) e.textContent = v; });
    $$("[data-buy]").forEach(function (a) {
      var id = a.getAttribute("data-buy"), url = link(id);
      if (url) { a.href = url; a.target = "_blank"; a.rel = "noopener"; }
      else { a.href = "/contact.html?plan=" + id + "&billing=" + (id === "single" ? interval : "monthly"); a.removeAttribute("target"); }
    });
    $$(".toggle button").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-interval") === interval ? "true" : "false"); });
    calcs();
  }
  // price for one hotel at this number: Portfolio has volume tiers, the tier price applying to every hotel
  function unit(c, n, yearly) {
    var t = c.getAttribute("data-tiers");
    if (t && !yearly) {
      try { var a = JSON.parse(t); for (var i = 0; i < a.length; i++) { if (n >= a[i].from && n <= a[i].to) return a[i].price; } return a[a.length - 1].price; } catch (e) { /* fall through */ }
    }
    return parseFloat(c.getAttribute(yearly ? "data-pa" : "data-pm"));
  }
  function bounds(c) { return { lo: parseInt(c.getAttribute("data-min"), 10) || 1, hi: parseInt(c.getAttribute("data-max"), 10) || 99 }; }
  // "How many hotels?" totals on the pricing cards
  function calcs() {
    $$("[data-calc]").forEach(function (c) {
      var inp = $("input", c), bd = bounds(c);
      var n = Math.max(bd.lo, Math.min(bd.hi, parseInt(inp.value, 10) || bd.lo));
      var yearly = interval === "annual" && c.getAttribute("data-pa");
      var each = unit(c, n, yearly);
      var money = function (x) { return "\u00a3" + x.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
      $(".total", c).textContent = n + (n === 1 ? " hotel" : " hotels") + (n > 1 ? " at " + money(each) + " each" : "") + ": " + money(n * each) + (yearly ? " a year" : " a month") + " plus VAT";
      var q = $(".qtyn", c); if (q) q.textContent = n;
      var x = $(".cross[data-from]", c); if (x) x.hidden = n < (parseInt(x.getAttribute("data-from"), 10) || 5);
    });
  }
  $$("[data-calc] .step-btn").forEach(function (b) {
    b.addEventListener("click", function () {
      var c = b.closest("[data-calc]"), i = $("input", c), bd = bounds(c);
      i.value = Math.max(bd.lo, Math.min(bd.hi, (parseInt(i.value, 10) || bd.lo) + parseInt(b.getAttribute("data-dir"), 10)));
      calcs();
    });
  });
  $$("[data-calc] input").forEach(function (i) {
    i.addEventListener("input", calcs);
    i.addEventListener("change", function () { var c = i.closest("[data-calc]"), bd = bounds(c), v = parseInt(i.value, 10) || 0; if (v < bd.lo) i.value = bd.lo; if (v > bd.hi) i.value = bd.hi; calcs(); });
  });
  // open Stripe with the number of hotels already chosen. If our checkout cannot be reached, fall back to `go` (a Payment Link or the contact page).
  function openCheckout(a, body, go, failText) {
    var label = a.textContent;
    a.textContent = "Opening checkout\u2026"; a.setAttribute("aria-busy", "true");
    var ctl = new AbortController(), t = setTimeout(function () { ctl.abort(); }, 70000);   // the free host can take a minute to wake
    var back = function () { a.textContent = label; a.removeAttribute("aria-busy"); };
    fetch(cfg.CHECKOUT_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal })
      .then(function (r) { clearTimeout(t); return r.json().catch(function () { return {}; }).then(function (j) { if (r.ok && j.ok && j.url) { window.location.href = j.url; return; } if (r.status === 400 && j.error) { throw new Error(j.error); } throw new Error("fallback"); }); })
      .catch(function (err) {
        clearTimeout(t); back();
        if (err && err.message && err.message !== "fallback" && err.name !== "AbortError" && err.message !== "Failed to fetch") { alert(err.message); }
        else if (go) { window.location.href = go; }
        else { alert(failText || ("Sorry, checkout could not be opened just now. Please email " + (cfg.EMAIL || "us") + ".")); }
      });
  }
  $$("[data-buy]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (!cfg.CHECKOUT_ON || !cfg.CHECKOUT_URL) return;
      var card = a.closest(".plan"), box = card && $("[data-calc] input", card);
      if (!box) return;
      e.preventDefault();
      var plan = a.getAttribute("data-buy");
      openCheckout(a, { plan: plan, interval: plan === "single" ? interval : "monthly", quantity: parseInt(box.value, 10) || 1 }, a.getAttribute("href"));
    });
  });
  // Founding Hotel: an approved hotel continues to checkout and enters the code it was given
  $$("[data-founding-buy]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (!cfg.CHECKOUT_ON || !cfg.CHECKOUT_URL) return;
      e.preventDefault();
      openCheckout(a, { founding: true, plan: "single", interval: "monthly", quantity: 1 }, "", "Sorry, checkout could not be opened just now. Please email " + (cfg.EMAIL || "us") + " and we will help.");
    });
  });
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
        var label = form.topic ? form.topic.options[form.topic.selectedIndex].text : "";
        d.set("topic", label);
        var btn = form.querySelector("button[type=submit]"); btn.disabled = true;
        window.PPsend(d, "Presence Pro enquiry: " + label)
          .then(function () { form.reset(); say("ok", "Thanks, your message has been sent. We'll reply to " + email + "."); })
          .catch(function () { say("err", "Sorry, that didn't send. Please email " + cfg.EMAIL + " instead."); })
          .then(function () { btn.disabled = false; });
      } else {
        var topic = form.topic ? form.topic.options[form.topic.selectedIndex].text : "";
        var body = "Name: " + d.get("name") + "\nEmail: " + email + "\nHotel website: " + (d.get("website") || "") + "\nAbout: " + topic + "\n\n" + d.get("message");
        window.location.href = "mailto:" + cfg.EMAIL + "?subject=" + encodeURIComponent("Presence Pro: " + topic) + "&body=" + encodeURIComponent(body);
        say("ok", "Your email app should open with your message ready to send. If it doesn't, write to " + cfg.EMAIL + ".");
      }
    });
  }
})();

/* welcome page: hotel details (one row per hotel). Posts to the form service in site.json if there is one, otherwise opens an email to us. */
(function () {
  "use strict";
  var form = document.getElementById("hotelForm");
  if (!form) return;
  var cfg = window.PP || {};
  var rows = document.getElementById("hotelRows"), msg = document.getElementById("hotelMsg");
  var say = function (kind, text) { msg.className = "msg " + kind; msg.textContent = text; };
  document.getElementById("addHotel").addEventListener("click", function () {
    var first = rows.querySelector(".hrow"), row = first.cloneNode(true);
    Array.prototype.forEach.call(row.querySelectorAll("input"), function (i) { i.value = ""; });
    var rm = document.createElement("button");
    rm.type = "button"; rm.className = "rm"; rm.setAttribute("aria-label", "Remove this hotel"); rm.textContent = "×";
    rm.addEventListener("click", function () { row.remove(); });
    row.appendChild(rm);
    rows.appendChild(row);
    row.querySelector("input").focus();
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = new FormData(form);
    if (d.get("company")) { say("ok", "Thanks, we have your details."); return; }
    var email = String(d.get("email") || "").trim();
    var hotels = Array.prototype.map.call(rows.querySelectorAll(".hrow"), function (r) {
      var v = function (n) { return String(r.querySelector("[name=" + n + "]").value || "").trim(); };
      return { name: v("hotel_name"), city: v("hotel_city"), url: v("hotel_url") };
    });
    var complete = hotels.every(function (h) { return h.name && h.city && h.url; });
    if (!String(d.get("name") || "").trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || !hotels.length || !complete) {
      say("err", "Please add your name, the email you paid with, and the name, town or city and website of each hotel."); return;
    }
    var list = hotels.map(function (h, i) { return (i + 1) + ". " + h.name + " | " + h.city + " | " + h.url; }).join("\n");
    var text = "Name: " + d.get("name") + "\nEmail: " + email + "\n\nHotels (name | town or city | website):\n" + list + "\n\nNotes: " + (d.get("message") || "");
    if (cfg.FORM_ENDPOINT) {
      var out = new FormData(); out.append("name", d.get("name")); out.append("email", email); out.append("hotels", list); out.append("message", d.get("message") || "");
      var sendBtn = form.querySelector("button[type=submit]"); sendBtn.disabled = true;
      window.PPsend(out, "Presence Pro: hotel details from " + email)
        .then(function () { say("ok", "Thanks, we have your hotel details. We'll be in touch at " + email + "."); })
        .catch(function () { say("err", "Sorry, that didn't send. Please email " + cfg.EMAIL + " instead."); })
        .then(function () { sendBtn.disabled = false; });
    } else {
      window.location.href = "mailto:" + cfg.EMAIL + "?subject=" + encodeURIComponent("Presence Pro: my hotel details") + "&body=" + encodeURIComponent(text);
      say("ok", "Your email app should open with your details ready to send. If it doesn't, email them to " + cfg.EMAIL + ".");
    }
  });
})();


/* pricing page: break-even calculator. A sum the visitor controls, not a forecast. */
(function () {
  "use strict";
  var root = document.getElementById("be");
  if (!root) return;
  var cfg = window.PP || {}, plans = {};
  (cfg.PLANS || []).forEach(function (p) { plans[p.id] = p; });
  var q = function (s) { return root.querySelector(s); };
  var gbp = function (n) { return "\u00a3" + n.toLocaleString("en-GB", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 }); };
  function run() {
    var hotels = Math.max(1, Math.min(999, parseInt(q("[name=hotels]").value, 10) || 1));
    var value = Math.max(1, parseFloat(q("[name=value]").value) || 0);
    var pct = Math.max(1, Math.min(60, parseFloat(q("[name=pct]").value) || 0));
    var saving = value * pct / 100;
    var out = [];
    var single = plans.single, port = plans.portfolio;
    if (single && hotels <= 99) out.push({ name: "Single hotel", cost: hotels * single.monthly });
    if (port && port.tiers && hotels >= (port.min_hotels || 1) && hotels <= (port.max_hotels || 999)) {
      var tier = port.tiers.filter(function (t) { return hotels >= t.from && hotels <= t.to; })[0] || port.tiers[port.tiers.length - 1];
      out.push({ name: "Portfolio", cost: hotels * tier.price });
    }
    q(".be-out").innerHTML = "";
    out.forEach(function (o) {
      var n = Math.ceil(o.cost / saving);
      var c = document.createElement("div"); c.className = "be-card";
      c.innerHTML = "<small>" + o.name + " for " + hotels + (hotels === 1 ? " hotel" : " hotels") + "</small><b>" + gbp(o.cost) + " a month</b><p>Covered if <b style=\"display:inline;font-size:inherit\">" + n + (n === 1 ? " booking" : " bookings") + "</b> a month " + (n === 1 ? "moves" : "move") + " from a booking site to your own website, saving about " + gbp(saving) + " each.</p>";
      q(".be-out").appendChild(c);
    });
    if (hotels >= 50) { var e = document.createElement("div"); e.className = "be-card"; e.innerHTML = "<small>" + hotels + " hotels</small><b>Custom quotation</b><p>For 50 or more hotels we quote individually. <a href=\"/contact.html?plan=enterprise\">Contact us</a>.</p>"; q(".be-out").appendChild(e); }
  }
  Array.prototype.forEach.call(root.querySelectorAll("input"), function (i) { i.addEventListener("input", run); });
  run();
})();

/* free snapshot request. Sends from the page through the form service; falls back to an email if none is set. */
(function () {
  "use strict";
  var form = document.getElementById("snapshotForm");
  if (!form) return;
  var cfg = window.PP || {}, msg = document.getElementById("snapMsg");
  var say = function (kind, text) { msg.className = "msg " + kind; msg.textContent = text; };
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = new FormData(form);
    if (d.get("company")) { say("ok", "Thanks, we'll be in touch."); return; }
    var email = String(d.get("email") || "").trim();
    var need = ["name", "hotel", "city", "website"].every(function (k) { return String(d.get(k) || "").trim(); });
    if (!need || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { say("err", "Please add your name, email, and your hotel's name, town or city and website."); return; }
    var hotel = String(d.get("hotel")).trim();
    if (cfg.FORM_ENDPOINT && window.PPsend) {
      var btn = form.querySelector("button[type=submit]"); btn.disabled = true;
      window.PPsend(d, "Presence Pro snapshot request: " + hotel)
        .then(function () { form.reset(); say("ok", "Thanks. We'll email your snapshot to " + email + "."); })
        .catch(function () { say("err", "Sorry, that didn't send. Please email " + cfg.EMAIL + " with your hotel's name, town and website."); })
        .then(function () { btn.disabled = false; });
    } else {
      var body = "Name: " + d.get("name") + "\nEmail: " + email + "\nHotel: " + hotel + "\nTown or city: " + d.get("city") + "\nWebsite: " + d.get("website");
      window.location.href = "mailto:" + cfg.EMAIL + "?subject=" + encodeURIComponent("Presence Pro snapshot request: " + hotel) + "&body=" + encodeURIComponent(body);
      say("ok", "Your email app should open with your request ready to send.");
    }
  });
})();

/* Founding Hotel application. Sends from the page through the form service; falls back to an email if none is set. */
(function () {
  "use strict";
  var form = document.getElementById("foundingForm");
  if (!form) return;
  var cfg = window.PP || {}, msg = document.getElementById("foundingMsg");
  var say = function (kind, text) { msg.className = "msg " + kind; msg.textContent = text; };
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = new FormData(form);
    if (d.get("company")) { say("ok", "Thanks, we'll be in touch."); return; }
    var email = String(d.get("email") || "").trim();
    var need = ["name", "hotel", "city", "website"].every(function (k) { return String(d.get(k) || "").trim(); });
    if (!need || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { say("err", "Please add your name, email, and your hotel's name, town or city and website."); return; }
    if (!d.get("agree")) { say("err", "Please tick the box to confirm you understand how the programme works."); return; }
    var hotel = String(d.get("hotel")).trim();
    if (cfg.FORM_ENDPOINT && window.PPsend) {
      var btn = form.querySelector("button[type=submit]"); btn.disabled = true;
      window.PPsend(d, "Presence Pro Founding Hotel application: " + hotel)
        .then(function () { form.reset(); say("ok", "Thanks, we have your application. We'll reply to " + email + " within a few working days, whether or not it's a yes."); })
        .catch(function () { say("err", "Sorry, that didn't send. Please email " + cfg.EMAIL + " with your hotel's name, town and website."); })
        .then(function () { btn.disabled = false; });
    } else {
      var body = "Name: " + d.get("name") + "\nEmail: " + email + "\nRole: " + (d.get("role") || "") + "\nHotel: " + hotel + "\nTown or city: " + d.get("city") + "\nWebsite: " + d.get("website") + "\n\n" + (d.get("message") || "");
      window.location.href = "mailto:" + cfg.EMAIL + "?subject=" + encodeURIComponent("Presence Pro Founding Hotel application: " + hotel) + "&body=" + encodeURIComponent(body);
      say("ok", "Your email app should open with your application ready to send.");
    }
  });
})();
