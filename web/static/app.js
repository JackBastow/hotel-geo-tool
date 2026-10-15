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
      var body = { website: fd.get("website"), hotel: fd.get("hotel"), city: fd.get("city"), tier: fd.get("tier"), wider: fd.get("wider") ? "1" : "0", audiences: fd.getAll("audiences") };
      fetch("/api/audit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
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
  var rp = $("#review-pack"), cmp = $("#compare");
  if (rp) { upload("#rp-go", "#rp-file", "#rp-status", "#rp-result", "/api/r/" + rp.getAttribute("data-token") + "/review-pack", function (fd) { fd.append("platform", $("#rp-platform").value); }); }
  if (cmp) { upload("#cmp-go", "#cmp-file", "#cmp-status", "#cmp-result", "/api/r/" + cmp.getAttribute("data-token") + "/compare"); }
})();
