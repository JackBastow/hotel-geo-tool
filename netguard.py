"""
Outbound fetches of addresses a visitor can influence (the website they type, the pages it links to, redirects) may only go to the public web.

Without this, a public form that says "type a website and we will read it" could be pointed at the server's own network (localhost, a cloud metadata address, an internal
service) and show what is there. get() checks the address before every request and before every redirect: only http and https, only ports 80 and 443, and every address the
name resolves to must be a public one. A blocked address raises a requests exception, which the callers already treat as "could not be fetched".

Limits, stated: a name could change what it resolves to between our check and the request (DNS rebinding); the callers are read-only and only ever show page text, which keeps
the exposure small. Set ALLOW_PRIVATE_FETCH=1 to switch the check off on a private machine.
"""

import ipaddress
import os
import socket
import urllib.parse

import requests


class Blocked(requests.RequestException):
    """The address is not a public web address."""


def host_ok(host):
    if os.environ.get("ALLOW_PRIVATE_FETCH") == "1":
        return True
    if not host or host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return ip.is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True                    # it does not resolve, so it cannot reach anything; the request itself fails as it always did
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
                return False
        except ValueError:
            return False
    return True


def url_ok(url):
    p = urllib.parse.urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        port = p.port
    except ValueError:
        return False
    if os.environ.get("ALLOW_PRIVATE_FETCH") != "1" and port not in (None, 80, 443):
        return False
    return host_ok(p.hostname)


def get(url, headers=None, timeout=25, stream=False, max_redirects=5, **kw):
    """requests.get that checks every hop. Same return value as requests.get."""
    cur = url
    for _ in range(max_redirects + 1):
        if not url_ok(cur):
            raise Blocked("blocked: not a public web address")
        r = requests.get(cur, headers=headers, timeout=timeout, stream=stream, allow_redirects=False, **kw)
        loc = r.headers.get("Location") if hasattr(r, "headers") else None
        if loc and getattr(r, "status_code", 200) in (301, 302, 303, 307, 308):
            cur = urllib.parse.urljoin(cur, loc)
            r.close()
            continue
        return r
    raise requests.TooManyRedirects("too many redirects")
