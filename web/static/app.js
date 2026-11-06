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

/* copy the suggested reply */
document.addEventListener("click", function (ev) {
  var b = ev.target.closest("[data-copy]");
  if (!b) { return; }
  var pre = b.closest(".th-reply").querySelector("pre");
  var done = function () { var t = b.textContent; b.textContent = "Copied"; setTimeout(function () { b.textContent = t; }, 1500); };
  if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(pre.innerText).then(done, function () {}); }
});

/* hotel portal: mark an action */
document.addEventListener("click", function (ev) {
  var b = ev.target.closest(".act-set");
  if (!b) { return; }
  var card = b.closest(".act"), root = b.closest(".pt");
  if (!card || !root) { return; }
  b.disabled = true;
  fetch("/portal/api/action", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": root.getAttribute("data-csrf") }, body: JSON.stringify({ id: card.getAttribute("data-id"), status: b.getAttribute("data-v") }) })
    .then(function (r) { return r.json(); })
    .then(function (j) {
      b.disabled = false;
      if (j && j.ok) {      /* update the buttons in place: no page reload, so it feels instant; the lists and counts regroup the next time the page is opened */
        card.querySelectorAll(".act-set").forEach(function (x) { x.classList.toggle("on", x === b); });
        card.setAttribute("data-kind", b.getAttribute("data-v") === "done" ? "completed" : b.getAttribute("data-v"));
      } else { alert((j && j.error) || "That did not save. Please try again."); }
    })
    .catch(function () { b.disabled = false; alert("That did not save. Please check your connection and try again."); });
});

/* a check in progress: show its messages, and reload the page when it finishes */
(function () {
  var box = document.querySelector(".live[data-url]");
  if (!box) { return; }
  var url = box.getAttribute("data-url");
  function tick() {
    fetch(url, { headers: { "Accept": "application/json" } }).then(function (r) { return r.json(); }).then(function (j) {
      if (!j || !j.ok) { setTimeout(tick, 6000); return; }
      if (j.state === "done" || j.state === "error" || j.state === "idle") { window.location.reload(); return; }
      var ul = box.querySelector(".live-m");
      if (ul) { ul.innerHTML = ""; (j.messages || []).slice(-6).forEach(function (m) { var li = document.createElement("li"); li.textContent = m; ul.appendChild(li); }); }
      setTimeout(tick, 3000);
    }).catch(function () { setTimeout(tick, 6000); });
  }
  setTimeout(tick, 2500);
})();

/* the portfolio page: while any check is running, refresh the page every few seconds so the status column stays current */
(function () { if (document.querySelector("[data-pf-active]")) { setTimeout(function () { window.location.reload(); }, 5000); } })();

/* the Prompts tab: edit, add, remove, save a draft, confirm */
(function () {
  var box = document.querySelector(".prompts[data-url]");
  var root = document.querySelector(".pt");
  if (!box || !root) { return; }
  var url = box.getAttribute("data-url"), min = +box.getAttribute("data-min"), max = +box.getAttribute("data-max"), rec = +box.getAttribute("data-rec");
  var list = box.querySelector("#prow-list"), count = box.querySelector(".pcount"), msg = box.querySelector(".pmsg");
  function say(t, ok) { if (msg) { msg.textContent = t || ""; msg.className = "pmsg " + (t ? (ok ? "good" : "bad") : ""); } }
  function post(body, cb) {
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": root.getAttribute("data-csrf") }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); }).then(cb).catch(function () { say("That did not save. Please check your connection and try again.", false); });
  }
  function rows() { return Array.prototype.slice.call(list ? list.querySelectorAll(".prow") : []); }
  function collect() { return rows().map(function (r) { return { id: r.getAttribute("data-id") || "", text: r.querySelector("textarea").value, source: r.getAttribute("data-source") || "own", angle: r.getAttribute("data-angle") || "", style: r.getAttribute("data-style") || "" }; }); }
  function refresh() {
    if (!count) { return; }
    var n = rows().length;
    rows().forEach(function (r, i) { var d = r.querySelector(".prow-n"); if (d) { d.textContent = i + 1; } });
    count.textContent = n + " prompt" + (n === 1 ? "" : "s") + " (recommended " + rec + "; " + min + " to " + max + " allowed)";
    count.className = "pcount" + (n < min || n > max ? " bad" : "");
    var a = box.querySelector("#agree"), a2 = box.querySelector("#agree-change"), b = box.querySelector("#pconfirm");
    if (b) { b.disabled = !(a && a.checked) || (a2 && !a2.checked) || n < min || n > max; }
  }
  function showErrors(errors) {
    rows().forEach(function (r) { r.classList.remove("err"); var e = r.querySelector(".prow-err"); if (e) { e.hidden = true; } });
    (errors || []).forEach(function (er) { var r = rows()[er.i]; if (r) { r.classList.add("err"); var e = r.querySelector(".prow-err"); e.textContent = er.msg; e.hidden = false; } });
  }
  box.addEventListener("click", function (ev) {
    var t = ev.target;
    if (t.classList.contains("pdel")) { t.closest(".prow").remove(); refresh(); return; }
    if (t.id === "padd") {
      if (rows().length >= max) { say("You can have at most " + max + " prompts.", false); return; }
      var d = document.createElement("div"); d.className = "prow"; d.setAttribute("data-source", "own"); d.setAttribute("data-id", "");
      d.innerHTML = '<div class="prow-n"></div><div class="prow-main"><textarea rows="2" maxlength="220" placeholder="For example: Which hotels near the airport have a shuttle and an early breakfast?"></textarea><div class="prow-err" hidden></div></div><button type="button" class="btn small pdel">Remove</button>';
      list.appendChild(d); d.querySelector("textarea").focus(); refresh(); return;
    }
    if (t.id === "psave") { post({ action: "save", prompts: collect() }, function (j) { showErrors(j.errors); say(j.ok ? j.message : (j.error || "Not saved."), !!j.ok); }); return; }
    if (t.id === "pconfirm") {
      post({ action: "confirm", prompts: collect(), agree: !!box.querySelector("#agree").checked, agree_change: !!(box.querySelector("#agree-change") && box.querySelector("#agree-change").checked) }, function (j) {
        showErrors(j.errors); if (j.ok) { window.location.reload(); } else { say(j.error || "Not confirmed.", false); }
      }); return;
    }
    if (t.id === "pchange") { post({ action: "start_change" }, function (j) { if (j.ok) { window.location.reload(); } else { say(j.error, false); } }); return; }
    if (t.id === "pdiscard") { post({ action: "discard" }, function (j) { if (j.ok) { window.location.reload(); } else { say(j.error, false); } }); return; }
  });
  box.addEventListener("input", function () { refresh(); });
  box.addEventListener("change", function () { refresh(); });
  refresh();
})();

/* the actions on the dashboard: filter by kind (AI visibility, website content, data accuracy) */
document.addEventListener("click", function (ev) {
  var b = ev.target.closest(".fchip[data-t]");
  if (!b) { return; }
  var box = b.closest("#act-list");
  if (!box) { return; }
  box.querySelectorAll(".fchip[data-t]").forEach(function (x) { x.classList.toggle("on", x === b); });
  var want = b.getAttribute("data-t");
  box.querySelectorAll(".act").forEach(function (a) { a.hidden = !(want === "all" || a.getAttribute("data-track") === want); });
  box.querySelectorAll("h3.grp").forEach(function (h) { var n = h.nextElementSibling, any = false; while (n && n.classList && n.classList.contains("act")) { if (!n.hidden) { any = true; } n = n.nextElementSibling; } h.hidden = !any; });
});

/* the Prompts tab: add one of the suggested prompts to the editor */
document.addEventListener("click", function (ev) {
  var b = ev.target.closest(".psugadd");
  if (!b) { return; }
  var box = document.querySelector(".prompts[data-url]");
  var list = box && box.querySelector("#prow-list");
  if (!list) { return; }
  var max = +box.getAttribute("data-max");
  if (list.querySelectorAll(".prow").length >= max) { alert("You can have at most " + max + " prompts."); return; }
  var d = document.createElement("div"); d.className = "prow"; d.setAttribute("data-source", "suggested"); d.setAttribute("data-id", ""); d.setAttribute("data-angle", "Suggested"); d.setAttribute("data-style", "");
  d.innerHTML = '<div class="prow-n"></div><div class="prow-main"><textarea rows="2" maxlength="220"></textarea><div class="prow-meta"><span class="hk-chip brand">Suggested</span></div><div class="prow-why"></div><div class="prow-err" hidden></div></div><button type="button" class="btn small pdel">Remove</button>';
  d.querySelector("textarea").value = b.getAttribute("data-text");
  d.querySelector(".prow-why").textContent = b.getAttribute("data-why") || "";
  list.appendChild(d);
  b.disabled = true; b.textContent = "Added";
  box.dispatchEvent(new Event("input", { bubbles: true }));
  d.scrollIntoView({ behavior: "smooth", block: "center" });
});
