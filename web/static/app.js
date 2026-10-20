/* Hotel AI Discoverability Audit: tabs, charts, the audit form and its progress, and the two upload boxes on the report. No framework. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---- charts: Vega-Lite specs written into the page by the server, drawn once their tab is visible */
  function drawCharts(root) {
    if (!window.vegaEmbed) { return; }
    $$(".vega:not([data-done])", root).forEach(function (el) {
      if (el.offsetParent === null) { return; }
      el.setAttribute("data-done", "1");
      try { window.vegaEmbed(el, JSON.parse(el.getAttribute("data-spec")), { actions: false, renderer: "svg" }); } catch (e) { el.textContent = ""; }
    });
  }
  function sizeFrames(root) {
    $$("iframe.dash", root).forEach(function (f) {
      if (f.offsetParent === null) { return; }
      try { var h = f.contentDocument.documentElement.scrollHeight; if (h > 100) { f.style.height = (h + 8) + "px"; } } catch (e) { /* cross-origin: leave the default height */ }
    });
  }
  function refresh(root) { drawCharts(root); sizeFrames(root); }

  /* ---- tabs (nested tabs work the same way) */
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest(".tab");
    if (!t) { return; }
    var box = t.closest(".tabs");
    var bar = $(":scope > .tab-bar", box);
    $$(":scope > .tab", bar).forEach(function (b) { b.classList.toggle("active", b === t); });
    var id = t.getAttribute("data-tab");
    $$(":scope > .tab-panel", box).forEach(function (p) { p.classList.toggle("active", p.id === id); });
    refresh($("#" + id));
  });
  /* ---- the top tabs: jump from a card to a tab, keep the tab in the address, and filter the recommendations */
  function openTab(name) {
    var b = $('.tabs.top > .tab-bar .tab[data-name="' + name + '"]');
    if (b) { b.click(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  }
  document.addEventListener("click", function (ev) {
    var g = ev.target.closest("[data-goto]");
    if (g) { openTab(g.getAttribute("data-goto")); return; }
    var top = ev.target.closest(".tabs.top > .tab-bar .tab");
    if (top && window.history && history.replaceState) { history.replaceState(null, "", "#" + top.getAttribute("data-name")); }
    var f = ev.target.closest(".fchip");
    if (f) {
      $$(".fchip").forEach(function (x) { x.classList.toggle("on", x === f); });
      var want = f.getAttribute("data-f");
      $$("#rec-list .rec").forEach(function (card) {
        var show = want === "all" || (want === "start" && card.getAttribute("data-start") === "1") || (want.indexOf("kind:") === 0 && card.getAttribute("data-kind") === want.slice(5)) || (want.indexOf("team:") === 0 && card.getAttribute("data-team") === want.slice(5));
        card.hidden = !show;
      });
      $$("#rec-list .grp").forEach(function (h) { var n = h.nextElementSibling, any = false; while (n && n.classList && n.classList.contains("rec")) { if (!n.hidden) { any = true; } n = n.nextElementSibling; } h.hidden = !any; });
    }
  });
  document.addEventListener("DOMContentLoaded", function () { var h = (location.hash || "").slice(1); var b = h && $('.tabs.top > .tab-bar .tab[data-name="' + h + '"]'); if (b) { b.click(); } });
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest('a[href^="#rec-"]');
    if (!a) { return; }
    ev.preventDefault();
    openTab("action");
    setTimeout(function () { var el = document.getElementById(a.getAttribute("href").slice(1)); if (el) { el.hidden = false; el.scrollIntoView({ behavior: "smooth", block: "start" }); } }, 60);
  });
  window.addEventListener("load", function () { refresh(document); setTimeout(function () { refresh(document); }, 400); });
  document.addEventListener("DOMContentLoaded", function () {
    refresh(document);
    $$("iframe.dash").forEach(function (f) {
      f.addEventListener("load", function () {
        sizeFrames(document);
        try { if (window.ResizeObserver) { new ResizeObserver(function () { sizeFrames(document); }).observe(f.contentDocument.body); } f.contentDocument.addEventListener("toggle", function () { sizeFrames(document); }, true); } catch (e) { /* leave it */ }
      });
    });
  });
  window.addEventListener("resize", function () { sizeFrames(document); });

  /* ---- the audit form */
  var form = $("#audit-form");
  if (form) {
    var errBox = $("#form-error"), prog = $("#progress"), go = $("#go");
    var fail = function (msg) { errBox.textContent = msg; errBox.hidden = false; go.disabled = false; prog.classList.remove("on"); form.style.display = ""; };
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      errBox.hidden = true;
      go.disabled = true;
      var fd = new FormData(form);
      var file = $("#f-reviews") && $("#f-reviews").files[0];
      var req;
      if (file) {
        var mf = new FormData();      /* with a review file the form goes as multipart; the file is read by the server for this run only */
        ["website", "hotel", "city", "tier", "platform", "prompts"].forEach(function (k) { mf.append(k, fd.get(k) || ""); });
        mf.append("wider", fd.get("wider") ? "1" : "0");
        fd.getAll("audiences").forEach(function (a) { mf.append("audiences", a); });
        mf.append("reviews", file);
        req = { method: "POST", body: mf };
      } else {
        var body = { website: fd.get("website"), hotel: fd.get("hotel"), city: fd.get("city"), tier: fd.get("tier"), prompts: fd.get("prompts") || "", wider: fd.get("wider") ? "1" : "0", audiences: fd.getAll("audiences") };
        req = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
      }
      fetch("/api/audit", req)
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok || !res.j.ok) { fail(res.j.error || "Something went wrong. Please try again."); return; }
          form.style.display = "none";
          prog.classList.add("on");
          prog.scrollIntoView({ behavior: "smooth", block: "center" });
          poll(res.j.job);
        })
        .catch(function () { fail("Could not reach the service. Check your connection and try again."); });
    });
    var poll = function (job) {
      var started = Date.now();
      var tick = function () {
        fetch("/api/job/" + job).then(function (r) { return r.json(); }).then(function (j) {
          if (!j.ok) { fail(j.error || "That audit is no longer available."); return; }
          var log = $("#run-log"), now = $("#run-now"), q = $("#run-queue");
          if (j.messages && j.messages.length) { now.textContent = j.messages[j.messages.length - 1]; log.textContent = j.messages.slice(-12).join("\n"); }
          if (j.status === "queued" && j.position) { q.hidden = false; q.textContent = "Waiting for a free place: " + j.position + (j.position === 1 ? " audit is" : " audits are") + " ahead of yours."; } else { q.hidden = true; }
          if (j.status === "done") { window.location.href = "/r/" + j.token; return; }
          if (j.status === "error") { fail("The audit failed: " + j.error); return; }
          setTimeout(tick, 2500);
        }).catch(function () { if (Date.now() - started < 15 * 60 * 1000) { setTimeout(tick, 4000); } else { fail("Lost contact with the audit. Please try again."); } });
      };
      tick();
    };
  }

  /* ---- uploads on the report: the review export and the earlier report */
  function upload(btnId, fileId, statusId, resultId, url, extra) {
    var btn = $(btnId);
    if (!btn) { return; }
    btn.addEventListener("click", function () {
      var f = $(fileId).files[0], status = $(statusId), out = $(resultId);
      if (!f) { status.textContent = "Choose a file first."; return; }
      var fd = new FormData();
      fd.append("file", f);
      if (extra) { extra(fd); }
      btn.disabled = true;
      status.textContent = "Analysing...";
      fetch(url, { method: "POST", body: fd }).then(function (r) { return r.json().catch(function () { return { ok: false, error: "The service could not read that file." }; }); }).then(function (j) {
        btn.disabled = false;
        if (!j.ok) { status.textContent = j.error || "That did not work."; return; }
        status.textContent = "";
        out.innerHTML = j.html;
        refresh(out);
      }).catch(function () { btn.disabled = false; status.textContent = "Could not reach the service."; });
    });
  }
  /* a link to a recommendation (quick wins, the 30/60/90 plan) opens it */
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest('a[href^="#rec-"]');
    if (!a) { return; }
    var art = document.getElementById(a.getAttribute("href").slice(1)), d = art && art.querySelector("details.rec-d");
    if (d) { d.open = true; }
  });
  /* ---- 'useful' / 'wrong' on a recommendation: one tap, and for 'wrong' an optional word on what is wrong */
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest(".fb button");
    if (!b) { return; }
    var box = b.closest(".fb"), m = location.pathname.match(/^\/r\/([A-Za-z0-9_-]+)/);
    if (!box || !m) { return; }
    var note = "";
    if (b.getAttribute("data-v") === "wrong") {
      note = window.prompt("What is wrong or not relevant? (optional, a few words help us fix it)", "");
      if (note === null) { return; }
    }
    box.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
    fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: m[1], ref: box.getAttribute("data-ref"), verdict: b.getAttribute("data-v"), note: note }) })
      .then(function (r) { return r.json(); })
      .then(function (j) { var d = box.querySelector(".fb-done"); d.textContent = j.ok ? "Thank you, noted." : (j.error || "That did not save."); d.hidden = false; })
      .catch(function () { box.querySelectorAll("button").forEach(function (x) { x.disabled = false; }); });
  });
  var rp = $("#review-pack"), cmp = $("#compare");
  if (rp) { upload("#rp-go", "#rp-file", "#rp-status", "#rp-result", "/api/r/" + rp.getAttribute("data-token") + "/review-pack", function (fd) { fd.append("platform", $("#rp-platform").value); }); }
  if (cmp) { upload("#cmp-go", "#cmp-file", "#cmp-status", "#cmp-result", "/api/r/" + cmp.getAttribute("data-token") + "/compare"); }
})();
