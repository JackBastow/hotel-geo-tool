"""
Feedback about the tool: a hotel user sends it with the Feedback button; the Westmont portfolio hotels' feedback shows on the main admin's Feedback page, the individual hotels' on the hotels admin's.
Run: python test_tool_feedback.py
"""
import os
import re
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import accounts
import audit_service
import backend
import server

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "f.db")
app = server.create_app(audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm", "INDIVIDUAL_ADMIN_PASSWORD": "ind", "SECRET_KEY": "k" * 32, "RENDER": "true"}), run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
pf = db.create_hotel("Westmont One", "westmont-one.example", "Leeds", "westmont-one.example")
solo = db.create_hotel("Solo Hotel", "solo.example", "York", "solo.example", grp="individual")


def login(email, hid):
    uid = db.create_user(email, "N", accounts.hash_password("a-long-password-1"))
    db.link_user(uid, hid)
    c = app.test_client()
    c.post("/portal/signin", data={"email": email, "password": "a-long-password-1"})
    return c


up, us = login("gm@westmont-one.example", pf), login("owner@solo.example", solo)

print("1. the hotel's Feedback button")
page = up.get(f"/portal/hotel/{pf}").get_data(as_text=True)
check("every hotel dashboard page has a Feedback button with a short form", 'class="fb-float"' in page and 'name="kind"' in page and 'name="message"' in page)
check("on Settings too", 'class="fb-float"' in up.get(f"/portal/hotel/{pf}/settings").get_data(as_text=True))
tok = re.search(r'class="fb-form" data-csrf="([^"]+)"', page).group(1)
r = up.post("/portal/api/tool-feedback", json={"kind": "idea", "message": "Could the PDF include the prompts?", "page": f"/portal/hotel/{pf}#actions"}, headers={"X-CSRF": tok})
check("feedback is sent, with a thank-you", r.status_code == 200 and r.get_json()["ok"] and "Thank you" in r.get_json()["message"])
tok2 = re.search(r'class="fb-form" data-csrf="([^"]+)"', us.get(f"/portal/hotel/{solo}").get_data(as_text=True)).group(1)
us.post("/portal/api/tool-feedback", json={"kind": "problem", "message": "The map pin is in the wrong town.", "page": f"/portal/hotel/{solo}"}, headers={"X-CSRF": tok2})
check("an empty message or an unknown kind is refused", up.post("/portal/api/tool-feedback", json={"kind": "idea", "message": " "}, headers={"X-CSRF": tok}).status_code == 400
      and up.post("/portal/api/tool-feedback", json={"kind": "spam", "message": "hello there"}, headers={"X-CSRF": tok}).status_code == 400)
check("it needs the page's token and a sign-in", up.post("/portal/api/tool-feedback", json={"kind": "idea", "message": "hello there"}).status_code == 400
      and app.test_client().post("/portal/api/tool-feedback", json={"kind": "idea", "message": "hello there"}).status_code == 401)
check("a hotel cannot file feedback against another hotel", db.tool_feedback()[0]["hotel_id"] == solo and db.tool_feedback()[1]["hotel_id"] == pf)
for _i in range(25):
    last = up.post("/portal/api/tool-feedback", json={"kind": "idea", "message": "again and again"}, headers={"X-CSRF": tok})
check("a few an hour at most", last.status_code == 429)

print("2. in the right admin")
a = app.test_client()
a.post("/admin/login", data={"password": "adm"})
fp = a.get("/admin/feedback").get_data(as_text=True)
check("the main admin's Feedback page shows the portfolio hotels' feedback", "Feedback from hotels" in fp and "Could the PDF include the prompts?" in fp and "Westmont One" in fp and "gm@westmont-one.example" in fp)
check("and not the individual hotels'", "The map pin is in the wrong town." not in fp)
i = app.test_client()
i.post("/hotels-admin/login", data={"password": "ind"})
ip = i.get("/hotels-admin/feedback").get_data(as_text=True)
check("the hotels admin has a Feedback page with the individual hotels' feedback only", "The map pin is in the wrong town." in ip and "Solo Hotel" in ip and "Could the PDF" not in ip and 'href="/hotels-admin/feedback"' in ip)
csrf = re.search(r'name="csrf" value="([^"]+)"', fp).group(1)
fid = next(f["id"] for f in db.tool_feedback() if f["hotel_id"] == pf)
a.post(f"/admin/tool-feedback/{fid}/done", data={"csrf": csrf})
check("feedback can be marked done", db.get_tool_feedback(fid)["status"] == "done")
sid = next(f["id"] for f in db.tool_feedback() if f["hotel_id"] == solo)
check("but the main admin cannot change the individual hotels' feedback, nor the reverse", a.post(f"/admin/tool-feedback/{sid}/done", data={"csrf": csrf}).status_code == 404
      and i.post(f"/hotels-admin/feedback/{fid}/new", data={"csrf": re.search(r'name="csrf" value="([^"]+)"', ip).group(1)}).status_code == 404)
check("and nobody else can see it", app.test_client().get("/hotels-admin/feedback").status_code == 302 and up.get("/admin/feedback").status_code == 302)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
