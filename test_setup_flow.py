"""
Setting up a hotel by its profile: the operator adds it, the hotel opens its invite and confirms its profile (which hotel exactly, how guests find it, what it is, its competitors), prompts are
written from the profile, the hotel confirms them, and that starts its first check. Nothing is checked weekly before that. Hotels set up before profiles keep running and are asked to review one.
The profile then feeds every check. Offline: web, map and Claude are faked.
Run: python test_setup_flow.py
"""
import json
import os
import re
import sys
import tempfile
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import ai_questions
import audit_service
import backend
import hotel_profile
import prompt_sets
import server

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


GEO = {"address": "Eriksberg 1, 374 96 Trensum, Blekinge, Sweden", "map_name": "Eriksberg Hotell & Naturreservat, Trensum, Karlshamn, Blekinge, Sweden", "lat": 56.21, "lon": 14.73}
looked_up = []
hotel_profile.geocode = lambda name, town, fetch=None: (looked_up.append((name, town)), dict(GEO))[1]

URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "s.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "INDIVIDUAL_ADMIN_PASSWORD": "ind-pass-1", "SECRET_KEY": "k" * 32, "RENDER": "true"})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
W = app.extensions["weekly"]
started = []
W.start = lambda force_ids=None: (started.append(set(force_ids or ())), (True, len(force_ids or ())))[1]
H = "Eriksberg Hotel & Nature Reserve"

print("1. the operator adds the hotel: it waits for its profile")
adm = app.test_client()
adm.post("/hotels-admin/login", data={"password": "ind-pass-1"})
csrf = re.search(r'name="csrf" value="([^"]+)"', adm.get("/hotels-admin").get_data(as_text=True)).group(1)
adm.post("/hotels-admin/add", data={"csrf": csrf, "name": H, "website": "eriksberg.example", "city": "Eriksberg"})
h = db.hotel_by_key("eriksberg.example")
check("a new hotel is 'pending' until it is set up", h["setup"] == "pending")
check("the list shows where it is in setting up", "Not invited yet" in adm.get("/hotels-admin").get_data(as_text=True))
check("it is not due for a weekly check", h["id"] not in {x["id"] for x in W.due(db)})
adm.post("/hotels-admin/run-all", data={"csrf": csrf})
check("and 'run every hotel now' leaves it out", not started or h["id"] not in started[-1], started)
hp = adm.get(f"/hotels-admin/hotel/{h['id']}").get_data(as_text=True)
check("its page shows the set-up and a link to fill in the profile", "Set-up:</b> Not invited yet" in hp and f"/hotels-admin/hotel/{h['id']}/profile" in hp and "Not checked weekly until its prompts are confirmed" in hp)
page = adm.post(f"/hotels-admin/hotel/{h['id']}/invite", data={"csrf": csrf, "email": "kristoffer@eriksberg.example"}).get_data(as_text=True)
link = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
check("once invited, the list says so", "Invited" in adm.get("/hotels-admin").get_data(as_text=True))

print("2. the hotel opens its invite and lands on 'Set up your hotel'")
u = app.test_client()
c2 = re.search(r'name="csrf" value="([^"]+)"', u.get(link).get_data(as_text=True)).group(1)
u.post(link, data={"csrf": c2, "name": "Kristoffer", "password": "a-long-password-1", "password2": "a-long-password-1"})
check("creating the login does not start a check for a new hotel", not any(h["id"] in s_ for s_ in started), started)
r = u.get("/portal")
check("the dashboard sends a new hotel to its profile first", r.status_code == 302 and r.headers["Location"].endswith(f"/portal/hotel/{h['id']}/profile"))
form = u.get(f"/portal/hotel/{h['id']}/profile").get_data(as_text=True)
check("the form asks which hotel exactly, where guests search, what it is, its guests, price and competitors",
      all(x in form for x in ("Set up your hotel", "Step 1 of 3", 'name="address"', 'name="town"', 'name="region"', 'name="area"', 'name="attractions"', 'name="kinds"', 'name="reasons"',
                              'name="audiences"', 'name="origins"', 'name="languages"', 'name="price"', 'name="competitors"')))
check("starting from the town the operator entered", 'name="town" value="Eriksberg"' in form)
cp = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
bad = u.post(f"/portal/hotel/{h['id']}/profile", data={"csrf": cp, "address": "x", "town": "Sweden"}).get_data(as_text=True)
check("a country is refused as the town", "is a country" in bad and not hotel_profile.confirmed(db.get_hotel(h["id"])))
check("the form needs its token", u.post(f"/portal/hotel/{h['id']}/profile", data={"address": "x", "town": "Karlshamn"}).status_code == 400)
data = {"csrf": cp, "address": "Eriksberg 1, Trensum", "town": "Karlshamn", "region": "Blekinge", "area": "southern Sweden",
        "attractions": "Eriksberg nature reserve\nTärnö", "kinds": ["destination", "countryside"], "reasons": "wildlife safaris\naward-winning game restaurant\nconferences in nature",
        "audiences": ["couples", "meetings", "food"], "origins": "Sweden, Germany, Denmark", "languages": ["English", "Swedish", "German"], "price": "upscale",
        "competitors": "Hooks Herrgård\nSkåne Tranås Hotel"}
r = u.post(f"/portal/hotel/{h['id']}/profile", data=data)
h = db.get_hotel(h["id"])
prof = hotel_profile.confirmed(h)
check("saving confirms the profile, by that person", prof and prof["confirmed_by"] == "kristoffer@eriksberg.example" and prof["region"] == "Blekinge" and prof["competitors"] == ["Hooks Herrgård", "Skåne Tranås Hotel"])
check("the map is looked up from the address", prof["lat"] == 56.21 and looked_up)
check("the hotel's record takes its town, price level and guests", h["city"] == "Karlshamn" and h["tier"] == "upscale" and h["audiences"] == "couples,meetings,food")
check("it goes on to its prompts", r.status_code == 302 and r.headers["Location"].endswith("#prompts"))
st = prompt_sets.state(db, h)
texts = [p["text"] for p in st["draft"]["prompts"]] if st["draft"] else []
check("a recommended set is written from the profile", st["draft"] and st["draft"]["created_by"] == "profile" and len(texts) >= 8, texts)
check("at every level guests search at: area, region, town and the places they come for",
      any("southern Sweden" in t for t in texts) and any("Blekinge" in t for t in texts) and any("Karlshamn" in t for t in texts) and any("Tärnö" in t for t in texts), texts)
check("a place that carries the hotel's own name (the reserve IS the hotel) is never asked about: that would name the hotel", not any("Eriksberg nature reserve" in t for t in texts))
check("about why guests come and who they are", any("wildlife safaris" in t for t in texts) and any("romantic getaway" in t or "conference" in t for t in texts), texts)
check("and none names the hotel", not any("Eriksberg Hotel" in t for t in texts))
check("every prompt passes the prompt rules", not prompt_sets.check_set(st["draft"]["prompts"], h["name"], h["city"], [{"name": x} for x in hotel_profile.places(prof)])[1])
check("the status moves on", "Profile done" in adm.get("/hotels-admin").get_data(as_text=True))
check("still nothing is checked", h["id"] not in {x["id"] for x in W.due(db)} and not any(h["id"] in s_ for s_ in started))

print("3. confirming the prompts starts the first check")
dash = u.get(f"/portal/hotel/{h['id']}")
check("the dashboard now opens, asking for the prompts to be confirmed", dash.status_code == 200 and "Confirm the prompts" in dash.get_data(as_text=True))
cu = re.search(r'data-csrf="([^"]+)"', dash.get_data(as_text=True)).group(1)
r = u.post(f"/portal/api/prompts/{h['id']}", json={"action": "confirm", "prompts": st["draft"]["prompts"], "agree": True}, headers={"X-CSRF": cu})
h = db.get_hotel(h["id"])
check("the prompts are confirmed", r.status_code == 200 and prompt_sets.state(db, h)["active"], r.get_data(as_text=True)[:300])
check("set-up is finished and the first check starts, and the hotel is told", h["setup"] == "done" and started and started[-1] == {h["id"]} and "first check has started" in r.get_json().get("message", ""))
check("from now on it is checked weekly like any hotel", h["id"] in {x["id"] for x in W.due(db)})
check("the status says so", "Prompts confirmed" in adm.get("/hotels-admin").get_data(as_text=True))

print("4. the profile feeds every check")
params = W.params_for(h, manual=True)
check("the check is run for the confirmed town, price level and guests, with the profile", params["city"] == "Karlshamn" and params["tier"] == "upscale" and params["audiences"] == ["couples", "meetings", "food"]
      and params["profile"]["competitors"] == ["Hooks Herrgård", "Skåne Tranås Hotel"])
facts = hotel_profile.facts_for_audit(params["profile"])
check("its owner-stated facts are labelled as stated by the hotel", facts and all("stated by the hotel" in f["text"] for f in facts) and any("wildlife safaris" in f["text"] for f in facts))


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="text", text=self.replies.pop(0) if self.replies else "{}")], usage=NS(input_tokens=500, output_tokens=200))


props = json.dumps({"prompts": [{"text": "Where can I go on a wildlife safari in southern Sweden for a weekend?", "facts": ["f2"]},
                                {"text": "Which hotels in Blekinge have a great game restaurant?", "facts": ["f3"]},
                                {"text": "Which hotels in Karlshamn have a rooftop pool?", "facts": ["f2"]}]})
fk = Fake([props])
b = ai_questions.build({"features": [], "strong_features": [], "tier": None, "classes": [], "audiences": [], "segments": []}, H, "Karlshamn", [], client=fk, model="m", pages=[], profile=params["profile"])
qs = [q["text"] for q in b["questions"]]
check("the question engine's AI proposals may rest on the profile and mention its region and area", any("southern Sweden" in q for q in qs) and any("Blekinge" in q for q in qs), (qs, b["rejected"]))
check("but still not on a facility nobody stated", not any("rooftop pool" in q for q in qs))
check("the hotel's own facts are not re-read from its pages when the profile gives enough", len(fk.calls) == 1)
check("a check's report records the profile it was run with", hotel_profile.for_report(params["profile"])["region"] == "Blekinge")

print("5. writing the profile draft from the website")
site = {"https://eriksberg.example": '<html><body><h1>Eriksberg</h1><p>Följ med på en guidad safari bland visenter. Restaurang Havsörnen serverar vilt.</p>'
                                     '<a href="/konferens/">Konferens</a><a href="/om-oss/">Om oss</a><a href="https://other.example/x">x</a></body></html>',
        "https://eriksberg.example/konferens/": "<p>Mötesrum för 60 personer.</p>", "https://eriksberg.example/om-oss/": "<p>Ett naturreservat i Blekinge strax väster om Karlshamn.</p>"}
fetched = []


def fetch(url):
    fetched.append(url)
    return NS(status_code=200, text=site.get(url.rstrip("/") if url.rstrip("/") in site else url, ""), url=url) if (url in site or url.rstrip("/") in site) else NS(status_code=404, text="", url=url)


draft = json.dumps({"town": "Karlshamn", "region": "Blekinge", "area": "southern Sweden", "attractions": ["Eriksberg nature reserve"], "kinds": ["destination", "spaceship"],
                    "reasons": [{"text": "guided bison safaris", "quote": "guidad safari bland visenter"}, {"text": "helicopter tours", "quote": "helikopterturer varje dag"}],
                    "audiences": ["couples", "astronauts"], "origins": "Sweden, Germany", "languages": ["Swedish", "English"], "price": "upscale", "competitors": ["Hooks Herrgård"]})
d = hotel_profile.draft_from_site({"name": H, "website": "eriksberg.example", "city": "Eriksberg"}, NS(anthropic="x", anthropic_model="m"), fetch=fetch, client=Fake([draft]))
check("the website is read: the home page and the pages that say what it is, only on its own site", "https://eriksberg.example/konferens/" in fetched and "https://eriksberg.example/om-oss/" in fetched and not any("other.example" in f for f in fetched))
check("the town the operator entered is corrected from the pages", d["town"] == "Karlshamn" and d["region"] == "Blekinge")
check("a reason is kept only when its quote is on the pages", d["reasons"] == ["guided bison safaris"], d["reasons"])
check("only known kinds and guest types are kept", d["kinds"] == ["destination"] and d["audiences"] == ["couples"])
check("competitors from the AI are kept as suggestions to check, not as the hotel's competitors", d["suggested"] == ["Hooks Herrgård"] and d["competitors"] == [])
check("and it stays a draft until someone confirms it", d["status"] == "draft")
d2 = hotel_profile.draft_from_site({"name": H, "website": "eriksberg.example", "city": "Eriksberg"}, NS(anthropic=None), fetch=fetch)
check("with no Claude key the draft is the town entered and the map", d2["town"] == "Eriksberg" and d2["lat"] == 56.21 and not d2["reasons"])
fp = hotel_profile.form_html(d, "/x", "t")
check("the form shows the AI's competitor suggestions, labelled as suggestions", "Suggested by the AI" in fp and "Hooks Herrgård" in fp)

print("6. hotels set up before profiles")
old_id = db.create_hotel("Old Town Hotel", "old-town.example", "York", "old-town.example")
o = app.test_client()
inv = adm.post(f"/hotels-admin/hotel/{old_id}/invite", data={"csrf": csrf, "email": "o@old-town.example"})
check("(an older hotel is in the main admin, not here)", inv.status_code == 404)
a2 = app.test_client()
a2.post("/admin/login", data={"password": "adm-pass-1"})
ac = re.search(r'name="csrf" value="([^"]+)"', a2.get("/admin/portfolio").get_data(as_text=True)).group(1)
lk = re.search(r"/portal/invite/[A-Za-z0-9_-]+", a2.post(f"/admin/hotel/{old_id}/invite", data={"csrf": ac, "email": "o@old-town.example"}).get_data(as_text=True)).group(0)
oc = re.search(r'name="csrf" value="([^"]+)"', o.get(lk).get_data(as_text=True)).group(1)
o.post(lk, data={"csrf": oc, "name": "O", "password": "a-long-password-1", "password2": "a-long-password-1"})
od = o.get("/portal")
check("keep their dashboard and weekly checks", od.status_code == 200 and old_id in {x["id"] for x in W.due(db)})
check("and are asked to check their profile", "Check your hotel profile" in od.get_data(as_text=True) and f"/portal/hotel/{old_id}/profile" in od.get_data(as_text=True))
check("the admin list says they run as before", "Running (set up before profiles); profile to review" in a2.get("/admin/portfolio").get_data(as_text=True))
pf = a2.get(f"/admin/hotel/{old_id}/profile").get_data(as_text=True)
pc = re.search(r'name="csrf" value="([^"]+)"', pf).group(1)
r = a2.post(f"/admin/hotel/{old_id}/profile", data={"csrf": pc, "address": "1 High St, York", "town": "York", "region": "North Yorkshire", "kinds": ["town", "historic"],
                                                     "reasons": "walk to York Minster", "audiences": ["city_break"], "price": "midscale"})
ho = db.get_hotel(old_id)
check("the operator can fill in a profile on the hotel's behalf", hotel_profile.confirmed(ho) and hotel_profile.confirmed(ho)["confirmed_by"] == "the operator" and r.status_code == 302)
check("which writes a new recommended set but leaves the hotel's set-up and checks alone", prompt_sets.state(db, ho)["draft"] and ho["setup"] == "" and old_id in {x["id"] for x in W.due(db)})
check("and the banner goes once the profile is confirmed", "Check your hotel profile" not in o.get("/portal").get_data(as_text=True))
check("nobody else's hotel profile can be opened", o.get(f"/portal/hotel/{h['id']}/profile").status_code == 404 and adm.get(f"/hotels-admin/hotel/{old_id}/profile").status_code == 404)

print("7. every hotel can open its profile from Settings")
for client_, hid_, who_ in ((u, h["id"], "individual"), (o, old_id, "portfolio")):
    dash_ = client_.get(f"/portal/hotel/{hid_}").get_data(as_text=True)
    check(f"a {who_} hotel's dashboard has a Settings link in the top bar", 'href="/portal/settings"' in dash_)
    check(f"Settings goes to its own settings", client_.get("/portal/settings").headers.get("Location", "").endswith(f"/portal/hotel/{hid_}/settings"))
    sp = client_.get(f"/portal/hotel/{hid_}/settings").get_data(as_text=True)
    check(f"which shows its profile and an Edit button ({who_})", "Hotel profile" in sp and f'href="/portal/hotel/{hid_}/profile"' in sp and "Edit the profile" in sp and "Confirmed" in sp)
check("the individual hotel's settings show what it confirmed", "Blekinge" in u.get(f"/portal/hotel/{h['id']}/settings").get_data(as_text=True)
      and "Hooks Herrgård" in u.get(f"/portal/hotel/{h['id']}/settings").get_data(as_text=True))
check("the edit page links back to settings", f'href="/portal/hotel/{h["id"]}/settings"' in u.get(f"/portal/hotel/{h['id']}/profile").get_data(as_text=True))
check("another hotel's settings cannot be opened", u.get(f"/portal/hotel/{old_id}/settings").status_code == 404 and o.get(f"/portal/hotel/{h['id']}/settings").status_code == 404)
check("settings needs a sign-in", app.test_client().get("/portal/settings").status_code == 302)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
