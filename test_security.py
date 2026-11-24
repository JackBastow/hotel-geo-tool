"""
Account security across the two admins and the hotel portal (code review, Nov 2026):
- an invite link to an email that already has a login never sets its password: the person proves who they are with their current password, and the hotel is added;
- the individual-hotels admin cannot reset the password of, or switch off, someone who also signs in to portfolio hotels;
- an invite link works once, even used twice.
Run: python test_security.py
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
import headline
import server

headline.attach = lambda r: None
fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


TMP = tempfile.mkdtemp()
URL = "sqlite:///" + os.path.join(TMP, "s.db")
cfg = audit_service.Config({"DATABASE_URL": URL, "ADMIN_PASSWORD": "adm-pass-1", "INDIVIDUAL_ADMIN_PASSWORD": "ind-pass-1", "SECRET_KEY": "k" * 32, "RENDER": "true"})
app = server.create_app(cfg, run_fn=lambda p, cb=None: None)
db = backend.open_store(URL)
pf_id = db.create_hotel("Westmont One", "westmont-one.example", "Leeds", "westmont-one.example")
solo_id = db.create_hotel("Solo Hotel", "solo-hotel.example", "York", "solo-hotel.example", grp="individual")
gm = db.create_user("gm@westmont-one.example", "GM", accounts.hash_password("the-real-password-1"))
db.link_user(gm, pf_id)


def csrf_of(client, path):
    m = re.search(r'name="csrf" value="([^"]+)"', client.get(path).get_data(as_text=True))
    return m.group(1) if m else ""


ind = app.test_client()
ind.post("/hotels-admin/login", data={"password": "ind-pass-1"})
tok = csrf_of(ind, f"/hotels-admin/hotel/{solo_id}")

print("1. an invite to an email that already has a login")
page = ind.post(f"/hotels-admin/hotel/{solo_id}/invite", data={"csrf": tok, "email": "gm@westmont-one.example"}).get_data(as_text=True)
link = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
v = app.test_client()
form = v.get(link).get_data(as_text=True)
check("the link asks for the CURRENT password, not a new one", "current password" in form.lower() and "Choose a password" not in form, form[:300])
ct = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
r = v.post(link, data={"csrf": ct, "password": "attacker-chosen-1", "password2": "attacker-chosen-1"})
u = db.user_by_email("gm@westmont-one.example")
check("whoever opens the link cannot set the password", accounts.check_password("the-real-password-1", u["pw_hash"]) and not accounts.check_password("attacker-chosen-1", u["pw_hash"]))
with v.session_transaction() as s_:
    check("and is not signed in as that person", not s_.get("uid"))
check("the portfolio hotel stays out of reach", v.get(f"/portal/hotel/{pf_id}").status_code in (302, 404))
r = v.post(link, data={"csrf": ct, "password": "the-real-password-1"})
with v.session_transaction() as s_:
    check("with the right current password the person is signed in", s_.get("uid") == gm)
check("and the new hotel is added to their login", solo_id in {h["id"] for h in db.hotels_for_user(gm)})
check("the link then works no more", app.test_client().get(link).status_code == 410)

print("2. the individual-hotels admin and people who also see portfolio hotels")
tok = csrf_of(ind, f"/hotels-admin/hotel/{solo_id}")
page = ind.post(f"/hotels-admin/hotel/{solo_id}/reset/{gm}", data={"csrf": tok}).get_data(as_text=True)
check("it cannot make a password-reset link for them", "/portal/invite/" not in page and "main admin" in page, page[-400:])
ind.post(f"/hotels-admin/hotel/{solo_id}/user/{gm}/off", data={"csrf": tok})
check("nor switch them off", db.user_by_id(gm)["active"])
only_solo = db.create_user("owner@solo-hotel.example", "Owner", accounts.hash_password("solo-password-1"))
db.link_user(only_solo, solo_id)
page = ind.post(f"/hotels-admin/hotel/{solo_id}/reset/{only_solo}", data={"csrf": tok}).get_data(as_text=True)
check("but can for someone who only sees its own hotels", "/portal/invite/" in page)

print("3. one link, one use")
page = ind.post(f"/hotels-admin/hotel/{solo_id}/invite", data={"csrf": tok, "email": "new@solo-hotel.example"}).get_data(as_text=True)
link2 = re.search(r"/portal/invite/[A-Za-z0-9_-]+", page).group(0)
inv = db.get_invite(accounts.token_hash(link2.split("/")[-1]))
check("a link claimed by one request cannot be claimed by a second", db.use_invite(inv["id"]) is True and db.use_invite(inv["id"]) is False)

print("4. a password change ends the sign-ins made before it")
old = app.test_client()
st = old.get("/portal/signin").get_data(as_text=True)
old.post("/portal/signin", data={"csrf": re.search(r'name="csrf" value="([^"]+)"', st).group(1), "email": "owner@solo-hotel.example", "password": "solo-password-1"})
check("(signed in on a first device)", old.get(f"/portal/hotel/{solo_id}").status_code == 200)
tok = csrf_of(ind, f"/hotels-admin/hotel/{solo_id}")
page = ind.post(f"/hotels-admin/hotel/{solo_id}/reset/{only_solo}", data={"csrf": tok}).get_data(as_text=True)
rlink = re.findall(r"/portal/invite/[A-Za-z0-9_-]+", page)[-1]
newc = app.test_client()
f2 = newc.get(rlink).get_data(as_text=True)
newc.post(rlink, data={"csrf": re.search(r'name="csrf" value="([^"]+)"', f2).group(1), "password": "a-brand-new-pass-1", "password2": "a-brand-new-pass-1"})
check("the device that reset the password stays signed in", newc.get(f"/portal/hotel/{solo_id}").status_code == 200)
check("the first device is signed out (a copied or stolen sign-in stops working)", old.get(f"/portal/hotel/{solo_id}").status_code in (302, 404))
db.set_user_active(only_solo, False)
db.set_user_active(only_solo, True)
check("switching a login off and on again ends its sign-ins too", newc.get(f"/portal/hotel/{solo_id}").status_code in (302, 404))

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
