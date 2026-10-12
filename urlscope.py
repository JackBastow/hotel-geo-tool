"""
What the visitor typed, turned into something the audit can use.

People paste whatever is in their address bar: tracking parameters (?msockid=...), a language
folder, or - for chain hotels - a page inside the brand's website
(hilton.com/en/hotels/xyz-doubletree-luxembourg/). Treating that as "the hotel's website" gave
a malformed address and then audited the whole brand site.

  normalise(text)  -> (start_url, scope)
      start_url: scheme + host + path, no query or fragment, always ending in "/"
      scope:     None for an ordinary site (an inner page like /rooms/ starts from the site's front page); for a
                 chain page, the path prefix that belongs to this one hotel, e.g. "/en/hotels/xyz-doubletree-luxembourg/"
  in_scope(url, scope) -> True when the URL is inside that prefix (always True when scope is None)
"""

import re
import urllib.parse

# folders that name a place's own section on a multi-property website
_PROPERTY_FOLDERS = {"hotels", "hotel", "properties", "property", "resorts", "resort", "locations", "destinations", "rooms-and-suites-hotels"}
_LANG = re.compile(r"^[a-z]{2}([-_][a-z]{2,4})?$", re.I)


def normalise(text):
    raw = (text or "").strip()
    if "//" not in raw:
        raw = "https://" + raw
    p = urllib.parse.urlparse(raw)
    host = p.netloc.lower()
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    segs = [s for s in path.split("/") if s]
    if segs and "." in segs[-1]:                      # a file such as /index.html: the page's folder is the unit
        segs = segs[:-1]
    start = urllib.parse.urlunparse((p.scheme or "https", host, "/" + "/".join(segs) + ("/" if segs else ""), "", "", ""))
    content = [s for s in segs if not _LANG.match(s)]
    if not content:
        return start, None
    # a chain page: keep everything up to and including the folder that names this hotel
    for i, s in enumerate(segs):
        if s.lower() in _PROPERTY_FOLDERS and i + 1 < len(segs):
            return start, "/" + "/".join(segs[: i + 2]) + "/"
    # an ordinary site and the visitor pasted an inner page (/rooms/): they mean the hotel's whole website
    return urllib.parse.urlunparse((p.scheme or "https", host, "/", "", "", "")), None


def in_scope(url, scope):
    if not scope:
        return True
    return urllib.parse.urlparse(url).path.lower().startswith(scope.lower())


def origin(url):
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def scope_note(start_url, scope):
    if not scope:
        return ""
    host = urllib.parse.urlparse(start_url).netloc
    return (f"You entered a page inside a larger website ({host}), so only this hotel's own pages were read. robots.txt, the sitemap and "
            f"other site-wide settings belong to the whole {host} website, which the hotel usually can't change itself; "
            "raise those with the brand's web team.")
