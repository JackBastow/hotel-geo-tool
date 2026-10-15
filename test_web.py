"""
Offline tests for the Flask site: the HTML layer, the fetch guard, the audit job flow, the report pages and downloads, the uploads, and the admin pages. No network, no keys.
Run: python test_web.py
"""
import copy
import io
import json
import os
import tempfile
import threading
import time
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import requests

import audit_service
import htmlst
import jobs
import netguard
import server
from htmlst import st

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)

print("1. the HTML layer")
html1 = htmlst.build(lambda: (st.markdown("**bold** <script>alert(1)</script> [x](javascript:alert(1)) ![p](http://t.example/p.gif)"), st.caption("a *note*")))
check("text is escaped, javascript: links neutralised and images dropped (no tracking pixels)", "&lt;script&gt;" in html1 and "javascript:" not in html1 and "<img" not in html1 and "<strong>bold</strong>" in html1, html1)
check("a normal link opens safely in a new tab", 'target="_blank"' in htmlst.render_md("[a](https://example.com/x)") and 'rel="noopener noreferrer nofollow"' in htmlst.render_md("[a](https://example.com/x)"))
check("our own HTML passes only when asked, and even then scripts and handlers are removed",
      "<b>ok</b>" in htmlst.render_md("<b>ok</b><script>x()</script><i onclick=\"y()\">i</i>", unsafe=True) and "<script" not in htmlst.render_md("<b>ok</b><script>x()</script>", unsafe=True)
      and "onclick" not in htmlst.render_md("<i onclick=\"y()\">i</i>", unsafe=True))


def layout():
    a, b = st.columns([2, 1])
    a.metric("Coverage", "50%", delta=5)
    with b:
        with st.container(border=True):
            st.info("hello")
    t1, t2 = st.tabs(["One", "Two"])
    with t1:
        st.dataframe([{"Page": "https://e.com/x", "Note": "<b>x</b>", "Bad": "javascript:alert(1)"}], column_config={"Page": st.column_config.LinkColumn("Page", display_text="open"),
                                                                                                                  "Bad": st.column_config.LinkColumn("Bad", display_text="open")})
    with t2:
        with st.expander("More"):
            st.code("<x>")
    st.progress(0.4, text="Coverage: 40%")


out = htmlst.build(layout)
check("columns, metrics, cards, alerts, tabs, tables, expanders, code and progress all draw", all(w in out for w in ('class="cols"', 'class="metric"', 'class="card"', 'class="alert info"', 'class="tabs"', "<details", "pre class=\"code\"", "p-fill")))
check("only the first tab is showing, and each tab has a button", out.count('tab-panel active') == 1 and out.count('<button type="button" class="tab') == 2)
check("table cells are escaped, a link column links only http(s) addresses", "&lt;b&gt;x&lt;/b&gt;" in out and 'href="https://e.com/x"' in out and 'href="javascript' not in out)
res = []


def worker(i):
    res.append(htmlst.build(lambda: st.markdown(f"**item {i}**")))


ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
[t.start() for t in ts]
[t.join() for t in ts]
check("pages built at the same time in different threads do not mix", sorted(res) == sorted(f'<div class="md"><p><strong>item {i}</strong></p></div>' for i in range(12)))

print("2. the fetch guard")
check("only public web addresses are allowed: localhost, private ranges, the cloud metadata address, odd ports and other schemes are not",
      not netguard.url_ok("http://localhost/") and not netguard.url_ok("http://127.0.0.1/") and not netguard.url_ok("http://10.0.0.5/") and not netguard.url_ok("http://169.254.169.254/latest/meta-data/")
      and not netguard.url_ok("http://192.168.1.1/") and not netguard.url_ok("http://[::1]/") and not netguard.url_ok("https://example.com:8080/") and not netguard.url_ok("file:///etc/passwd")
      and not netguard.url_ok("ftp://example.com/") and not netguard.url_ok("http://printer.local/") and netguard.url_ok("https://8.8.8.8/") and not netguard.url_ok(""))
calls = []
orig_get, orig_gai = requests.get, netguard.socket.getaddrinfo


def fake_gai(host, *a, **k):
    return [(2, 1, 6, "", ({"public.example": "93.184.216.34", "sneaky.example": "10.1.2.3"}.get(host, "93.184.216.34"), 0))]


def fake_get(url, **kw):
    calls.append(url)
    if url == "https://public.example/start":
        return NS(status_code=302, headers={"Location": "http://sneaky.example/admin"}, close=lambda: None, url=url)
    return NS(status_code=200, headers={}, close=lambda: None, url=url, text="ok")


netguard.socket.getaddrinfo, requests.get = fake_gai, fake_get
try:
    r = netguard.get("https://public.example/page")
    blocked = False
    try:
        netguard.get("https://public.example/start")
    except netguard.Blocked:
        blocked = True
    check("a public address is fetched, and a redirect from a public address to a private one is stopped before it is followed", r.status_code == 200 and blocked and "http://sneaky.example/admin" not in calls, calls)
    check("a name that RESOLVES to a private address is refused", not netguard.url_ok("https://sneaky.example/"))
finally:
    netguard.socket.getaddrinfo, requests.get = orig_gai, orig_get

print("3. the audit job flow")


def fake_run(params, progress):
    progress("Reading the website...")
    progress("Working out the market...")
    r = copy.deepcopy(REP)
    r["meta"]["website"], r["meta"]["hotel"] = params["website"], params.get("hotel") or "Brooklands Hotel"
    return r


cfg = audit_service.Config({"ADMIN_PASSWORD": "open-sesame", "AUDITS_PER_HOUR_PER_VISITOR": "3", "MAX_QUEUED_AUDITS": "4"})
app = server.create_app(cfg, run_fn=fake_run)
c = app.test_client()
home = c.get("/")
check("the form page renders, with the audience choices and no claim about saving when no database is set", home.status_code == 200 and b"Run audit" in home.data and b"Business travellers" in home.data and b"saved by the operator" not in home.data)
check("security headers are on every page (CSP limits scripts to ours and the chart library; no framing; no sniffing)",
      "script-src 'self' https://cdn.jsdelivr.net" in home.headers["Content-Security-Policy"] and home.headers["X-Frame-Options"] == "DENY" and home.headers["X-Content-Type-Options"] == "nosniff")
check("an empty or malformed website is refused with a plain message", c.post("/api/audit", json={"website": ""}).status_code == 400 and c.post("/api/audit", json={"website": "not a site"}).status_code == 400
      and c.post("/api/audit", json={"website": "a" * 400 + ".com"}).status_code == 400)
check("a private address cannot be audited", c.post("/api/audit", json={"website": "http://127.0.0.1:8000/"}).status_code == 400 and c.post("/api/audit", json={"website": "localhost"}).status_code == 400)
r = c.post("/api/audit", json={"website": "brooklandshotelsurrey.com", "hotel": "Brooklands Hotel", "city": "Weybridge", "tier": "upscale", "audiences": ["business", "nonsense"], "wider": "1"})
jid = r.get_json()["job"]
check("a valid audit starts a job", r.status_code == 200 and jid)
token = None
for _ in range(100):
    j = c.get(f"/api/job/{jid}").get_json()
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.1)
check("the job reports its progress messages and finishes with a private link to the report", j["status"] == "done" and j["token"] and "Reading the website..." in j["messages"], j)
token = j["token"]
check("an unknown job gives a clear message", c.get("/api/job/doesnotexist").status_code == 404)
for k in range(2):
    c.post("/api/audit", json={"website": f"hotel{k}.example.com"})
check("a visitor is limited to a few audits an hour, with a plain message (3 allowed here)", c.post("/api/audit", json={"website": "another.example.com"}).status_code == 429)

print("4. the report and its downloads")
page = c.get(f"/r/{token}")
body = page.get_data(as_text=True)
check("the report page renders the hotel, the six tabs, the readiness ring and the AI view", page.status_code == 200 and "Brooklands Hotel" in body and all(t in body for t in ("Overview", "How AI sees your hotel", "Fix your website", "Beyond your website", "Scorecard", "Tools &amp; method"))
      and 'class="hk-ring"' in body and "Brand ranking: the hotel and the hotels named most" in body and "How we read this hotel" in body)
check("it carries the honesty wording: a sample, not the market; not assessed; hypotheses not causes", all(w in body for w in ("not the market", "Not assessed", "not as causes")))
check("it is private: not indexed, not cached", page.headers["X-Robots-Tag"].startswith("noindex") and page.headers["Cache-Control"] == "no-store" and 'name="robots" content="noindex' in body)
check("an unknown link and a malformed one are both a plain 404 (a guessed address finds nothing)", c.get("/r/" + "a" * 32).status_code == 404 and c.get("/r/short").status_code == 404 and c.get("/r/%2e%2e%2f").status_code == 404)
check("the charts are written as data for the browser to draw, and the scorecard is a sandboxed frame without scripts", 'class="vega"' in body and 'sandbox="allow-same-origin"' in body and "ResizeObserver" not in body.split('<iframe class="dash"')[1].split("</iframe>")[0])
pdf = c.get(f"/r/{token}/management.pdf")
check("the management report downloads as a PDF", pdf.status_code == 200 and pdf.data[:4] == b"%PDF" and "attachment" in pdf.headers["Content-Disposition"])
check("so does the appendix, and the data file", c.get(f"/r/{token}/appendix.pdf").data[:4] == b"%PDF" and json.loads(c.get(f"/r/{token}/data.json").data)["meta"]["hotel"] == "Brooklands Hotel" and c.get(f"/r/{token}/other.pdf").status_code == 404)

pdf_before = c.get(f"/r/{token}/appendix.pdf").data
print("5. the uploads on a report")
csvdata = ("Review date,Review score,Positive review,Negative review,Response,Response date,Guest name\n"
           "2026-09-20,9.0,Lovely breakfast,,Thank you for the breakfast. Kind regards Maria Guest Relations,2026-09-21,Anna Smith\n"
           "2026-09-02,4.0,,The room was noisy at night,,,Bob Jones\n"
           "2026-07-30,2.0,,Dirty bathroom,,,Di White\n")
up = c.post(f"/api/r/{token}/review-pack", data={"file": (io.BytesIO(csvdata.encode()), "export.csv"), "platform": "Booking.com"}, content_type="multipart/form-data")
uj = up.get_json()
check("a review export is analysed: figures, the unanswered critical reviews with drafts, and the privacy line", up.status_code == 200 and uj["ok"] and "Reviews analysed" in uj["html"] and "Critical reviews still unanswered" in uj["html"]
      and "Draft reply to finish" in uj["html"] and "noisy at night" in uj["html"], uj.get("error"))
rep2 = app.extensions["reports"].load(token)
check("the report now holds only the aggregates (the review text and names are nowhere in it)", rep2["review_pack"]["reviews"] == 3 and "noisy at night" not in json.dumps(rep2, default=str) and "Smith" not in json.dumps(rep2, default=str))
check("the scorecard now has Reviews & Reputation assessed from the file, the page shows the saved analysis, and the appendix is rebuilt (different from before)",
      next(x for x in rep2["scorecard"]["categories"] if x["key"] == "reviews").get("from_review_pack") and "Upload the file again" in c.get(f"/r/{token}").get_data(as_text=True)
      and c.get(f"/r/{token}/appendix.pdf").data != pdf_before)
check("a file that is not a review export is refused with the columns it found", c.post(f"/api/r/{token}/review-pack", data={"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")}, content_type="multipart/form-data").status_code == 400)
check("no file is a plain message", c.post(f"/api/r/{token}/review-pack", data={}, content_type="multipart/form-data").status_code == 400)
cmpr = c.post(f"/api/r/{token}/compare", data={"file": (io.BytesIO(json.dumps(REP).encode()), "earlier.json")}, content_type="multipart/form-data").get_json()
check("an earlier report can be compared, and the result is drawn", cmpr["ok"] and "Things that improved" in cmpr["html"])
check("a file that is not JSON is refused", c.post(f"/api/r/{token}/compare", data={"file": (io.BytesIO(b"not json"), "x.json")}, content_type="multipart/form-data").status_code == 400)
check("the upload endpoints do not work on an unknown report", c.post("/api/r/" + "b" * 30 + "/review-pack", data={"file": (io.BytesIO(csvdata.encode()), "x.csv")}, content_type="multipart/form-data").status_code == 404)

print("6. a busy service")
mgr = jobs.Manager(lambda p, prog: (time.sleep(0.4), {"meta": {}})[1], lambda r: "tok", workers=1, max_queue=2, per_hour=100)
j1, _ = mgr.submit({"website": "a.example.com"}, "v1")
j2, _ = mgr.submit({"website": "b.example.com"}, "v2")
j3, why = mgr.submit({"website": "c.example.com"}, "v3")
check("when too many audits are waiting the next is refused as busy, not queued without limit", j3 is None and why == "busy")
check("the second job is told its place in the queue", mgr.position(j2) == 1 and mgr.position(j1) == 0)

print("7. a report survives a restart when there is a database")
DB = os.path.join(tempfile.gettempdir(), "hotel_web_test.db")
if os.path.exists(DB):
    os.remove(DB)
url = "sqlite:///" + DB.replace("\\", "/")
cfg2 = audit_service.Config({"DATABASE_URL": url, "ADMIN_PASSWORD": "open-sesame"})
app2 = server.create_app(cfg2, run_fn=fake_run)
c2 = app2.test_client()
jid2 = c2.post("/api/audit", json={"website": "brooklandshotelsurrey.com"}).get_json()["job"]
for _ in range(100):
    j = c2.get(f"/api/job/{jid2}").get_json()
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.1)
tok2 = j["token"]
check("the landing page now says every run is saved and not shown to others", b"saved by the operator" in c2.get("/").data and j["status"] == "done")
app3 = server.create_app(cfg2, run_fn=fake_run)       # a fresh process: nothing in memory
check("after a restart the same private link still opens the report", app3.test_client().get(f"/r/{tok2}").status_code == 200)
import backend
st_ = backend.open_store(url)
check("the link is not part of any list or export the operator pulls", all("access_token" not in r for r in st_.export_rows()) and "access_token" not in backend.to_csv(st_.export_rows()))
up2 = app3.test_client().post(f"/api/r/{tok2}/review-pack", data={"file": (io.BytesIO(csvdata.encode()), "export.csv"), "platform": "Booking.com"}, content_type="multipart/form-data")
check("a review export applied after a restart updates the saved run in place", up2.status_code == 200 and st_.list_runs()[0]["pack_reviews"] == 3)

print("8. the admin pages")
ca = app2.test_client()
check("admin without a password set is switched off, not open", server.create_app(audit_service.Config({}), run_fn=fake_run).test_client().get("/admin").status_code == 403)
check("admin needs a sign-in: pages redirect to it", ca.get("/admin/runs").status_code == 302 and "/admin/login" in ca.get("/admin/runs").headers["Location"])
bad = ca.post("/admin/login", data={"password": "wrong"})
check("a wrong password is refused", b"Wrong password" in bad.data and ca.get("/admin/runs").status_code == 302)
ok = ca.post("/admin/login", data={"password": "open-sesame"})
check("the right password signs in", ok.status_code == 302 and ca.get("/admin/runs").status_code == 200)
ov = ca.get("/admin/overview").get_data(as_text=True)
check("the overview shows the saved audits and totals", "Audits saved" in ov and "Brooklands Hotel" in ov)
check("runs can be filtered, a run opened, and its report, data and PDFs downloaded", "Brooklands" in ca.get("/admin/runs?q=brooklands").get_data(as_text=True) and "Open the full report" in ca.get("/admin/run/1").get_data(as_text=True)
      and "Brand ranking" in ca.get("/admin/run/1/report").get_data(as_text=True) and ca.get("/admin/run/1/management.pdf").data[:4] == b"%PDF" and json.loads(ca.get("/admin/run/1/data.json").data)["meta"]["hotel"])
check("the hotels, markets and usage pages render", all(ca.get(p).status_code == 200 for p in ("/admin/hotels", "/admin/markets", "/admin/usage", "/admin/export")) and "Free-tier guards" in ca.get("/admin/usage").get_data(as_text=True))
check("the exports download: summary, competitors, pages, sources, the monthly pack and the zip",
      all(ca.get(f"/admin/export/{n}").status_code == 200 for n in ("runs.csv", "competitors.csv", "pages.csv", "sources.csv", "reports.zip"))
      and ca.get("/admin/export/pack.xlsx?from=2000-01&to=2099-12").data[:2] == b"PK" and ca.get("/admin/export/pack.xlsx?from=2099-01&to=2000-01").status_code == 400)
check("access_token is not in the CSV export", b"access_token" not in ca.get("/admin/export/runs.csv").data)
check("deleting needs the confirmation box and the page's own token", ca.post("/admin/run/1/delete", data={"confirm": "yes", "csrf": "wrong"}).status_code == 400 and st_.count() >= 1)
csrf = ca.get("/admin/run/1").get_data(as_text=True).split('name="csrf" value="')[1].split('"')[0]
ca.post("/admin/run/1/delete", data={"confirm": "yes", "csrf": csrf})
check("with both, the run is deleted", st_.get_report(1) is None)
ca.post("/admin/logout")
check("signing out closes the pages again", ca.get("/admin/runs").status_code == 302)
for _ in range(5):
    app2.test_client().post("/admin/login", data={"password": "nope"})

print("8b. the site password")
gcfg = audit_service.Config({"SITE_PASSWORD": "Westmont-test", "ADMIN_PASSWORD": "open-sesame", "AUDITS_PER_HOUR_PER_VISITOR": "9"})
gapp = server.create_app(gcfg, run_fn=fake_run)
g = gapp.test_client()
home_r = g.get("/")
check("with a site password, the home page sends a visitor to the sign-in page, remembering where they were going", home_r.status_code == 302 and home_r.headers["Location"].startswith("/login"))
check("the sign-in page shows no report and no form, and is not indexed", b"Run audit" not in g.get("/login").data and b"noindex" in g.get("/login").data)
check("reports, downloads, uploads, the audit API and the admin pages are all closed too", g.get("/r/" + "a" * 30).status_code == 302 and g.get("/admin").status_code == 302 and g.post("/api/audit", json={"website": "x.com"}).status_code == 401
      and g.get("/api/job/abc").status_code == 401 and g.post("/api/r/" + "a" * 30 + "/review-pack").status_code == 401)
check("the uptime monitor and the sign-in page's own files stay open", g.get("/healthz").status_code == 200 and g.get("/static/app.css").status_code == 200)
time.sleep(0)
bad_login = g.post("/login", data={"password": "westmont"})
check("a wrong password (even a different capital) is refused and nothing opens", b"not right" in bad_login.data and g.get("/").status_code == 302)
good = g.post("/login", data={"password": "Westmont-test", "next": "/r/" + "a" * 30})
check("the right password signs in and goes where the visitor was heading", good.status_code == 302 and good.headers["Location"].endswith("/r/" + "a" * 30) and g.get("/").status_code == 200)
check("a sign-in cannot be used to redirect to another site", g.post("/login", data={"password": "Westmont-test", "next": "//evil.example.com"}).headers["Location"] == "/" and g.post("/login", data={"password": "Westmont-test", "next": "https://evil.example.com"}).headers["Location"] == "/")
check("once in, the audit works as before, and the admin pages still need the admin password", g.post("/api/audit", json={"website": "brooklandshotelsurrey.com"}).status_code == 200 and g.get("/admin/runs").status_code == 302 and "/admin/login" in g.get("/admin/runs").headers["Location"])
g.post("/logout")
check("signing out closes it again", g.get("/").status_code == 302)
spam = gapp.test_client()
for _ in range(6):
    spam.post("/login", data={"password": "no"})
check("after six wrong passwords further tries are refused for a while, even the right one", spam.post("/login", data={"password": "Westmont-test"}).status_code == 429)
check("no password set means no gate (as it was)", c.get("/").status_code == 200)
check("the password is nowhere in the code or the blueprint", "Westmont" not in open(os.path.join(HERE, "render.yaml"), encoding="utf8").read() and "SITE_PASSWORD" in open(os.path.join(HERE, "render.yaml"), encoding="utf8").read())

print("9. deployment")
import subprocess
import sys
r = subprocess.run([sys.executable, "-c", "import sys; sys.modules['streamlit']=None; import report_view, server, admin, wsgi; print('ok')"], capture_output=True, text=True, cwd=HERE)
check("the site imports and builds without Streamlit installed (the host does not need it)", r.stdout.strip().endswith("ok"), r.stderr[-300:])
req = chr(10).join(l for l in open(os.path.join(HERE, "requirements-web.txt"), encoding="utf8").read().lower().splitlines() if not l.startswith("#"))
check("the web requirements list what the site imports and not Streamlit", all(w in req for w in ("flask", "waitress", "markdown", "altair", "pandas", "reportlab", "openpyxl", "psycopg", "anthropic")) and "streamlit" not in req)
yml = open(os.path.join(HERE, "render.yaml"), encoding="utf8").read()
check("render.yaml starts the site, checks /healthz, and holds no secret values", "python wsgi.py" in yml and "/healthz" in yml and "sk-ant" not in yml and "postgresql://" not in yml and yml.count("sync: false") >= 5)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
