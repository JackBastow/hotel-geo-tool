"""
The hotel dashboard's layout: Prompt analysis, Competitors and Join the conversation tabs; prompts and history in Settings; the detailed analysis (the report) with a way back to the dashboard.
Run: python test_dashboard_tabs.py
"""
import copy
import json
import os
import re
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import accounts
import audit_service
import backend
import competitors_view
import headline
import hotel_profile
import prompt_analysis
import server

headline.attach = lambda r: None
fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


BASE = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
H = "Paris Marriott Opera Ambassador Hotel"


def rival(name, answers, of, reasons, themes, rank=2):
    return {"name": name, "answers": answers, "of": of, "best_rank": rank, "ratings": [], "reasons": reasons, "themes": themes, "relation": "same", "tier": {"label": "upscale"}, "aliases": []}


def market(qid, q, named, of, rivals, angle="Neighbourhood"):
    status = "named" if named == of else "sometimes" if named else "not_named"
    return {"qid": qid, "kind": "niche", "question": q, "angle": angle, "named": named, "of": of, "status": status, "rivals": rivals, "other_category": [], "gap": status != "named" and bool(rivals)}


def report():
    r = copy.deepcopy(BASE)
    r["meta"].update(base="https://www.marriott-opera.example/", website="marriott-opera.example", hotel=H, city="Paris")
    base_items = [i for i in BASE["ai_sample"]["items"] if i.get("kind") != "direct"]
    qs = [("q1", "Which 4-star hotels near the Palais Garnier are best for a business trip?", "benchmark", False),
          ("q2", "Which hotels near Galeries Lafayette have a good restaurant?", "new", True),
          ("q3", "Which hotels in Paris are good value for a city break?", "new", False)]
    items = [{**copy.deepcopy(base_items[k % len(base_items)]), "id": q, "qid": q, "kind": "niche", "text": t, "source": src, "mentioned": m} for k, (q, t, src, m) in enumerate(qs)]
    import ai_sample
    r["ai_sample"] = {**r["ai_sample"], "status": "ok", "items": items, "summary": ai_sample.summarise(items)}
    r["ai_gap"] = {"status": "ok", "markets": [
        market("q1", "Which 4-star hotels near the Palais Garnier are best for a business trip?", 0, 2,
               [rival("Hilton Paris Opéra", 2, 2, ["Close to Saint-Lazare with big meeting rooms"], {"meetings_events": 2, "transport_access": 1}), rival("Hôtel Scribe Paris Opéra", 1, 2, ["Historic, steps from the Opéra"], {"meetings_events": 1})],
               "Business travel"),
        market("q2", "Which hotels near Galeries Lafayette have a good restaurant?", 2, 2, [], "Dining"),
        market("q3", "Which hotels in Paris are good value for a city break?", 1, 2, [rival("Hôtel La Conversation", 2, 2, ["Budget pick that Time Out calls the best"], {"value": 2})], "City breaks")],
        "criteria": {"q1": [{"theme": "meetings_events", "label": "meeting rooms, conferences or events", "rivals": ["Hilton Paris Opéra", "Hôtel Scribe Paris Opéra"], "count": 3, "quotes": [],
                             "hotel": {"state": "not_found", "url": "", "snippet": ""}}],
                     "q3": [{"theme": "value", "label": "price, value or affordability", "rivals": ["Hôtel La Conversation"], "count": 2, "quotes": [],
                             "hotel": {"state": "strong", "url": "https://x/", "snippet": "Traverse City Hotels Waikiki Hotels Mexico City Hotels For Guests Best Rate Guarantee Marriott Bonvoy Moments"}}]},
        "observations": {"q1": [{"kind": "source", "text": "1 of the 1 editorial page(s) the assistant cited name Hilton Paris Opéra and do not mention the hotel.", "urls": ["https://www.timeout.example/paris/hotels"]}]},
        "investigate": {}, "articles": [{"url": "https://www.timeout.example/paris/hotels", "domain": "timeout.example", "title": "Best hotels in Paris", "kind": "editorial", "cited": 2, "read": "ok",
                                         "hotel_in": False, "rivals_in": ["Hilton Paris Opéra"], "questions": ["q1"], "opportunity": True}],
        "comparison": {"rivals": [{"name": "Hilton Paris Opéra"}], "rows": [{"facility": "Meeting rooms", "hotel": None, "rivals": {"Hilton Paris Opéra": "strong"}}]}}
    return r


print("1. the Prompt analysis tab")
rep = report()
pa = prompt_analysis.panel(rep)
txt = re.sub(r"<[^>]+>", " ", pa)
check("one line per prompt, grouped by kind, tracked ones marked", pa.count("<tr><td><b>") == 3 and "Who it is for" in txt and "tracked" in txt and "Where the hotel is" in txt)
check("each says if the hotel was named, who instead, and why", "No" in txt and "0 of 2" in txt and "Hilton Paris Opéra (2/2)" in txt and "meeting rooms, conferences or events" in txt)
check("with one thing to do, in plain words", "State meeting rooms, conferences or events clearly on your website" in txt)
check("a prompt where the hotel is always named needs nothing", "Nothing to do: named every time" in txt)
check("a menu or footer strip is never treated as the hotel stating something", "Waikiki" not in txt and "State price, value or affordability clearly on your website" in txt, txt[txt.find("good value"):][:400])
check("the evidence is one click away, not on the page", pa.count("<details") == 2 and "Evidence" in txt)
check("the figures at the top count prompts to fix on the site and on other sites", "Fix on your website" in txt and "Fix on other sites" in txt)
check("and it points to the Recommendations to mark things done", 'data-goto="actions"' in pa)
check("a check without the analysis says so", "not analysed" in prompt_analysis.panel({**rep, "ai_gap": {}}) and "after the first check" in prompt_analysis.panel(None))

print("2. the Competitors tab")
h = {"profile_json": json.dumps({**hotel_profile.empty(), "status": "confirmed", "competitors": ["Hilton Paris Opera", "InterContinental Paris Le Grand"]})}
cv = competitors_view.panel(rep, h)
ct = re.sub(r"<[^>]+>", " ", cv)
check("who AI recommends instead, in how many prompts", "Comparable hotels AI recommends instead of you" in ct and "Hilton Paris Opéra" in ct and "1 of 3" in ct)
check("the hotel's chosen competitors, matched however they are spelled, and the ones AI never named", "your competitor" in ct and "InterContinental Paris Le Grand" in ct and "Not named in this check" in ct)
check("why rivals are recommended, their websites beside the hotel's, and where to get listed", "Why rivals are recommended instead" in ct and "What their websites say, beside yours" in ct and "Where to get listed" in ct)
check("and the articles that list rivals but not the hotel", "Articles the assistant read that list rivals but not you" in ct and "timeout.example" in ct)
check("without a profile it asks for competitors in Settings", "Add the hotels you compete with to your profile" in competitors_view.panel(rep, {}))

print("3. on the dashboard, and Settings")
URL = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm", "SECRET_KEY": "k" * 32})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
hid = db.create_hotel(H, "marriott-opera.example", "Paris", backend.hotel_key(rep))
token = app.extensions["reports"].save(rep)
uid = db.create_user("gm@marriott-opera.example", "GM", accounts.hash_password("a-long-password-1"))
db.link_user(uid, hid)
u = app.test_client()
u.post("/portal/signin", data={"email": "gm@marriott-opera.example", "password": "a-long-password-1"})
dash = u.get(f"/portal/hotel/{hid}").get_data(as_text=True)
names = re.findall(r'data-name="([a-z]+)"', dash)
check("the dashboard has Prompt analysis, Competitors and Join the conversation tabs", all(n in names for n in ("analysis", "competitors", "talk")), names)
check("and no Prompts or History tab: those are in Settings", "prompts" not in names and "history" not in names, names)
check("the report button is called Detailed analysis", "Detailed analysis" in dash and "full report" not in dash.lower())
st = u.get(f"/portal/hotel/{hid}/settings").get_data(as_text=True)
check("Settings has the profile, the prompts, the history and the login", all(f'data-name="{n}"' in st for n in ("profile", "prompts", "history", "login")) and "The prompts we ask AI" in st and "Detailed analysis" in st,
      ([n for n in ("profile", "prompts", "history", "login") if f'data-name="{n}"' not in st], 'class="prompts' in st, "Detailed analysis" in st, st[:300]))
check("and the prompts there can be edited (the page carries its form token)", 'class="pt" data-csrf="' in st and f'data-url="/portal/api/prompts/{hid}"' in st)
db.insert_prompt_set(hid, "draft", [{"id": "p1", "text": "Which hotels in Paris are near the Opéra?", "angle": "Neighbourhood", "source": "recommended"}], "recommended")
dash = u.get(f"/portal/hotel/{hid}").get_data(as_text=True)
check("'Review the prompts' on the dashboard goes to Settings", f'href="/portal/hotel/{hid}/settings#prompts"' in dash)
a = app.test_client()
a.post("/admin/login", data={"password": "adm"})
adm = a.get(f"/admin/hotel/{hid}").get_data(as_text=True)
an = re.findall(r'data-name="([a-z]+)"', adm)
check("the operator's view of the hotel looks the same: the new tabs, and no Prompts or History tab", all(n in an for n in ("analysis", "competitors", "talk")) and "prompts" not in an and "history" not in an, an)
check("its Settings button opens the profile, prompts and history, editable by the operator", f'href="/admin/hotel/{hid}/settings"' in adm)
ast = a.get(f"/admin/hotel/{hid}/settings").get_data(as_text=True)
check("there", all(f'data-name="{n}"' in ast for n in ("profile", "prompts", "history")) and f'data-url="/admin/hotel/{hid}/prompts"' in ast and 'class="pt" data-csrf="' in ast)
check("and nobody else can open it", app.test_client().get(f"/admin/hotel/{hid}/settings").status_code == 302 and u.get(f"/admin/hotel/{hid}/settings").status_code == 302)

print("3b. ticking steps, and the research button")
aid = db.insert_action(hid, {"title": "Get listed with Visit Example", "source": "strategy", "akey": "strategy|x|get listed", "status": "todo", "state": "open", "priority": "high", "team": "marketing",
                             "rec_json": json.dumps({"steps": [{"title": "Open it"}, {"title": "Send the email"}], "kind_label": "Tourism board"}), "reopened": 0, "resolution": "", "note": "", "first_run_id": 0, "last_run_id": 0})
dash = u.get(f"/portal/hotel/{hid}").get_data(as_text=True)
cu = re.search(r'data-csrf="([^"]+)"', dash).group(1)
r = u.post("/portal/api/action-step", json={"id": aid, "step": 1, "done": True}, headers={"X-CSRF": cu})
check("a step can be ticked, and is remembered", r.get_json()["ok"] and db.get_action(aid)["steps_done"] == "1" and "1 of 2 steps" in u.get(f"/portal/hotel/{hid}").get_data(as_text=True))
u.post("/portal/api/action-step", json={"id": aid, "step": 1, "done": False}, headers={"X-CSRF": cu})
check("and unticked", db.get_action(aid)["steps_done"] == "")
check("not without the page's token, nor on another hotel's action", u.post("/portal/api/action-step", json={"id": aid, "step": 0, "done": True}).status_code == 400
      and app.test_client().post("/portal/api/action-step", json={"id": aid, "step": 0, "done": True}).status_code == 401)
check("the Strategy section has the research line (its button shows only when the host can search: no Claude key here)", "research-box" in dash and f'action="/portal/hotel/{hid}/research"' not in dash)
check("the button needs the page's token", u.post(f"/portal/hotel/{hid}/research", data={}).status_code == 400 and u.post(f"/portal/hotel/{hid}/research", data={"csrf": cu}).status_code == 302)
adm2 = a.get(f"/admin/hotel/{hid}").get_data(as_text=True)
check("the operator sees the same, with the step boxes read-only", "research-box" in adm2 and 'data-step="0" disabled' in adm2)

print("4. the detailed analysis")
r = u.get(f"/r/{token}").get_data(as_text=True)
check("it is called Detailed analysis and has a way back to the hotel's dashboard", "Detailed analysis" in r and f'href="/portal/hotel/{hid}"' in r and "Back to the dashboard" in r)
r = a.get(f"/r/{token}").get_data(as_text=True)
check("for the operator it goes back to the hotel's admin page", f'href="/admin/hotel/{hid}"' in r)

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
