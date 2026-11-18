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
check("the audit form redirects an anonymous visitor to the admin sign-in", r.status_code == 302 and "/admin/login" in r.headers["Location"])
check("an anonymous audit request is refused", c.post("/api/audit", json={"website": "brooklandshotelsurrey.com"}).status_code == 401)
check("an anonymous report link is refused", c.get("/r/" + "A" * 30).status_code == 302)
check("the health check stays open", c.get("/healthz").status_code == 200)
check("the hotel portal is not caught by the gate (it has its own sign-in)", c.get("/portal/signin").status_code != 302)
check("/login does not loop", "/admin/login" in c.get("/login").headers["Location"])
c.post("/admin/login", data={"password": "adm"})
check("a signed-in admin may use the audit form", c.get("/").status_code == 200)

# live host with a site password: unchanged
c = client({"RENDER": "true", "SITE_PASSWORD": "pw"})
check("with a site password the form still asks for it", c.get("/").status_code == 302 and "/login" in c.get("/").headers["Location"])
c.post("/login", data={"password": "pw"})
check("and works after it", c.get("/").status_code == 200)

# a developer's machine: open as before
check("on a developer's machine nothing changes", client({}).get("/").status_code == 200)

sys.exit(1 if fails else 0)
