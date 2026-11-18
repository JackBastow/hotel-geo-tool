"""On the live host the audit tool is never open to the public, even if SITE_PASSWORD was never set."""
import sys

import audit_service
import server

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def client(env):
    app = server.create_app(audit_service.Config(env), run_fn=lambda p, prog: {"hotel": "x"})
    return app.test_client()


# live host, no site password: closed
c = client({"RENDER": "true", "ADMIN_PASSWORD": "adm"})
r = c.get("/")
check("the audit form redirects an anonymous visitor to the hotel sign-in", r.status_code == 302 and "/portal/signin" in r.headers["Location"])
check("an anonymous audit request is refused", c.post("/api/audit", json={"website": "brooklandshotelsurrey.com"}).status_code == 401)
check("an anonymous report link is refused", c.get("/r/" + "A" * 30).status_code == 302)
check("the health check stays open", c.get("/healthz").status_code == 200)
check("the hotel portal is not caught by the gate (it has its own sign-in)", c.get("/portal/signin").status_code != 302)
check("/login does not loop", "/portal/signin" in c.get("/login").headers["Location"])
c.post("/admin/login", data={"password": "adm"})
r = c.get("/?website=a.example&hotel=A")
check("the bare address sends a signed-in admin to the admin Quick audit, keeping a re-run's details", r.status_code == 302 and r.headers["Location"].startswith("/admin/audit?") and "website=a.example" in r.headers["Location"])
check("a signed-in admin may use the audit form", c.get("/admin/audit").status_code == 200)
page = c.get("/admin/audit").get_data(as_text=True)
check("the form is in the admin look and has no link to a public page", "Public page" not in page and "wm-brand" in page and "Portfolio" in page)
check("the admin pages link to it as Quick audit and have no Public page link", "Quick audit" in c.get("/admin/runs").get_data(as_text=True) and "Public page" not in c.get("/admin/runs").get_data(as_text=True))
check("the sign-in page has no public page link", "Public page" not in client({"RENDER": "true", "ADMIN_PASSWORD": "adm"}).get("/admin/login").get_data(as_text=True))

check("an anonymous visitor cannot open the Quick audit page", client({"RENDER": "true", "ADMIN_PASSWORD": "adm"}).get("/admin/audit").status_code == 302)

# live host WITH a site password set: the shared password no longer opens anything
c = client({"RENDER": "true", "SITE_PASSWORD": "pw"})
c.post("/login", data={"password": "pw"})
check("a shared site password no longer opens the audit tool", c.get("/").status_code == 302 and c.post("/api/audit", json={"website": "brooklandshotelsurrey.com"}).status_code == 401)

# a developer's machine: open as before
check("on a developer's machine nothing changes", client({}).get("/").status_code == 200)

sys.exit(1 if fails else 0)
