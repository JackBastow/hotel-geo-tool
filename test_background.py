"""
A quick audit keeps running when nobody has its page open: while any audit is queued or running, the site visits its own address every few minutes so the free host does not put it to sleep
half way; the visits stop when the audits are done. Offline: the visit is faked.
Run: python test_background.py
"""
import os
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")
import jobs
import requests

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


visits = []
requests.get = lambda url, timeout=None: visits.append(url)
jobs.KEEPALIVE_S = 0.05
os.environ["RENDER_EXTERNAL_URL"] = "https://example-app.onrender.com"
release = threading.Event()


def run(params, progress):
    release.wait(5)
    return {"meta": {}}


m = jobs.Manager(run, lambda rep: "tok-123456789012345678901", workers=2)
job, why = m.submit({"website": "x.example"}, visitor="a")
check("an audit starts", job is not None and not why)
m.submit({"website": "y.example"}, visitor="b")
time.sleep(0.4)
n = len(visits)
check("while it runs, the site visits its own address to stay awake", n >= 3 and all(v == "https://example-app.onrender.com/healthz" for v in visits), visits[:3])
check("one visitor thread at a time, however many audits run", sum(1 for t in threading.enumerate() if t.name == "audit-keepalive") == 1)
release.set()
time.sleep(0.4)
check("the audits finish", job.status == "done" and job.token)
n2 = len(visits)
time.sleep(0.3)
check("and the visits stop once nothing is running", len(visits) == n2 and not m.awake)
release.clear()
j2, _ = m.submit({"website": "z.example"}, visitor="c")
time.sleep(0.3)
check("a later audit starts the visits again", len(visits) > n2 and m.awake)
release.set()
time.sleep(0.3)
del os.environ["RENDER_EXTERNAL_URL"]
v3 = len(visits)
release.clear()
m.submit({"website": "w.example"}, visitor="d")
time.sleep(0.3)
check("on a computer that is not the host, nothing is visited", len(visits) == v3)
release.set()

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
