/* Presence Pro chat assistant. Common questions are answered here instantly (no server call); anything else goes to the assistant
   (POST CHAT_URL, see chat.py). If that is unavailable the visitor is pointed to email. Nothing is stored in the browser. */
(function () {
  "use strict";
  var cfg = window.PP || {};
  if (!cfg.CHAT_URL) return;
  var money = function (n) { return "£" + n; };

  var num = function (n) { return Number.isInteger(n) ? String(n) : n.toFixed(2); };
  var plans = (cfg.PLANS || []).map(function (p) {
    var t = p.name + " " + money(num(p.monthly)) + (p.per_hotel ? " per hotel a month" : " a month");
    if (p.tier_from) t += " (" + money(num(p.tier_monthly)) + " per hotel from " + p.tier_from + " hotels)";
    if (p.annual) t += ", or " + money(num(p.annual)) + " a year";
    return t;
  }).join("; ");
  var QUICK = [
    { q: "What do you check?", a: "We check three things for your hotel: whether your own website answers the questions guests ask, what an AI assistant says when travellers ask where to stay (and who it names instead), and where your hotel is listed across booking sites, maps and the press. You get a plain-English plan of what to fix first. There's more on the What we do page: /what-we-do.html" },
    { q: "How much does it cost?", a: "Monthly reports: " + plans + ", plus VAT where it applies. Details: /pricing.html" },
    { q: "Does it cover ChatGPT?", a: "Not directly, and we'd rather say so. The sampled answers come from one AI assistant with live web search, and the report labels them as a sample of one assistant on one day. For ChatGPT, Gemini and others the report gives you a checklist to test by hand. Nobody can honestly promise that an assistant will recommend your hotel." },
    { q: "How do I pay or cancel?", a: "You pay by card through Stripe, so we never see your card details. It's a monthly subscription you can cancel any time; it ends at the close of the period you've paid for. For anything about billing, email " + (cfg.EMAIL || "us") + "." }
  ];

  var fab, panel, log, input, send, busy = false, history = [], opened = false;
  var el = function (t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; };

  function linkify(node, text) {
    var re = /(\/[a-z-]+\.html|https?:\/\/[^\s]+|[\w.+-]+@[\w-]+\.[\w.-]+)/g, last = 0, m;
    while ((m = re.exec(text))) {
      node.appendChild(document.createTextNode(text.slice(last, m.index)));
      var raw = m[0].replace(/[.,;:)]+$/, ""), a = el("a", "", raw);
      a.href = raw.indexOf("@") > 0 && raw.indexOf("/") < 0 ? "mailto:" + raw : raw;
      if (/^https?:/.test(raw)) { a.target = "_blank"; a.rel = "noopener"; }
      node.appendChild(a);
      last = m.index + raw.length; re.lastIndex = last;
    }
    node.appendChild(document.createTextNode(text.slice(last)));
  }
  function add(role, text) {
    var b = el("div", "msg-b " + role);
    if (role === "bot") linkify(b, text); else b.textContent = text;
    log.appendChild(b); log.scrollTop = log.scrollHeight; return b;
  }

  function build() {
    fab = el("button", "chat-fab");
    fab.type = "button"; fab.setAttribute("aria-haspopup", "dialog");
    fab.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg><span>Ask us</span>';
    panel = el("div", "chat-panel"); panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Chat with the Presence Pro assistant");
    var top = el("div", "chat-top");
    var who = el("div"); who.innerHTML = "<b>Presence Pro assistant</b><small>AI assistant. Ask about the product or pricing.</small>";
    var close = el("button", "", "×"); close.type = "button"; close.setAttribute("aria-label", "Close chat");
    top.appendChild(el("div", "av")); top.appendChild(who); top.appendChild(close);
    log = el("div", "chat-log"); log.setAttribute("aria-live", "polite");
    var quick = el("div", "quick");
    QUICK.forEach(function (item) { var b = el("button", "", item.q); b.type = "button"; b.addEventListener("click", function () { if (busy) return; add("me", item.q); history.push({ role: "user", content: item.q }); history.push({ role: "assistant", content: item.a }); add("bot", item.a); }); quick.appendChild(b); });
    var form = el("form", "chat-form");
    input = el("input"); input.type = "text"; input.maxLength = 600; input.placeholder = "Type your question"; input.setAttribute("aria-label", "Your question"); input.autocomplete = "off";
    send = el("button", "", "Send"); send.type = "submit";
    form.appendChild(input); form.appendChild(send);
    var foot = el("div", "chat-foot"); foot.innerHTML = 'AI assistant, so check anything important with us. Messages go to an AI service to write a reply and are not stored by us. <a href="/privacy.html">Privacy</a>' + (cfg.EMAIL ? ' &middot; <a href="mailto:' + cfg.EMAIL + '">Email a person</a>' : "");
    [top, log, quick, form, foot].forEach(function (n) { panel.appendChild(n); });
    document.body.appendChild(fab); document.body.appendChild(panel);

    fab.addEventListener("click", open); close.addEventListener("click", shut);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel.classList.contains("open")) shut(); });
    form.addEventListener("submit", function (e) { e.preventDefault(); ask(input.value); });
  }
  function open() {
    panel.classList.add("open"); fab.style.display = "none";
    if (!opened) { opened = true; add("bot", "Hello. I'm the Presence Pro assistant, an AI. I can explain what we do, how the reports work and what the plans include. What would you like to know?"); }
    setTimeout(function () { input.focus(); }, 50);
  }
  function shut() { panel.classList.remove("open"); fab.style.display = ""; fab.focus(); }

  function ask(text) {
    text = (text || "").trim(); if (!text || busy) return;
    input.value = ""; add("me", text); history.push({ role: "user", content: text });
    busy = true; send.disabled = true;
    var wait = add("bot", ""); wait.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    var slow = setTimeout(function () { wait.textContent = "One moment. The assistant is waking up, which can take up to a minute the first time."; }, 6000);
    var ctl = new AbortController(), kill = setTimeout(function () { ctl.abort(); }, 75000);
    fetch(cfg.CHAT_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: history.slice(-16) }), signal: ctl.signal })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j.ok, j: j }; }); })
      .then(function (res) {
        wait.textContent = "";
        if (res.ok) { linkify(wait, res.j.reply); history.push({ role: "assistant", content: res.j.reply }); }
        else { linkify(wait, (res.j.error || "Sorry, I can't answer that just now.") + (cfg.EMAIL ? " You can email " + cfg.EMAIL + " and a person will reply." : "")); history.pop(); }
      })
      .catch(function () { wait.textContent = ""; linkify(wait, "Sorry, I can't reach the assistant just now." + (cfg.EMAIL ? " Please email " + cfg.EMAIL + " and a person will reply." : "")); history.pop(); })
      .then(function () { clearTimeout(slow); clearTimeout(kill); busy = false; send.disabled = false; log.scrollTop = log.scrollHeight; input.focus(); });
  }
  build();
})();
