"""
Offline tests for dashboard.py. The point is the escaping: a lot of the text
shown here comes from third-party pages (review excerpts, text lifted from a
hotel's own site, article judgments), and the page is rendered as raw HTML.
Run: python test_dashboard.py
"""
import re

import dashboard

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


EVIL = '<img src=x onerror=alert(1)>'
EVIL2 = '</div><script>alert("pwned")</script>'

sc = {"overall": 61, "coverage_pct": 60.0, "caveat": "c", "categories": [
    {"key": "website", "label": EVIL, "weight": 12.5, "assessed": True, "partial": False,
     "score": 50},
    {"key": "ai_visibility", "label": "AI Visibility", "weight": 25.0, "assessed": False,
     "partial": False, "score": None},
    {"key": "social", "label": "Social", "weight": 7.5, "assessed": True, "partial": True,
     "score": 36}]}
rest = [{"priority": "medium", "action": EVIL, "why": EVIL2, "category": EVIL}]
top = [{"priority": "critical", "action": EVIL, "why": EVIL2, "owner": EVIL, "effort": "quick",
        "page": "javascript:alert(1)", "example": '<script>alert("x")</script>\n' + EVIL2,
        "category": "c", "code": "x"},
       {"priority": "high", "action": "Second", "why": "w", "owner": "Web developer",
        "effort": "moderate", "page": "https://good.example/p", "example": "", "code": "y"}]
guest = {"pages_ok": 3, "pages_attempted": 4, "sitemap_total": 50, "questions": [
    {"id": "parking", "label": EVIL, "short": "P", "state": "partial", "state_label": "x",
     "missing": [EVIL2], "snippet": EVIL2, "source_url": "javascript:alert(1)", "note": EVIL},
    {"id": "wifi", "label": "Wi-Fi?", "short": "W", "state": "answered", "state_label": "x",
     "missing": [], "snippet": "Free Wi-Fi.", "source_url": "https://good.example/wifi",
     "note": ""}]}

html, height = dashboard.build(EVIL, EVIL2, sc, rest, guest, top)

print("1. hostile text from third parties cannot become markup")
check("no raw <img> tag from injected text", "<img src=x" not in html)
check("no injected </div><script> sequence", "</div><script>alert" not in html)
check("the injected script text is present only as escaped text",
      "&lt;script&gt;alert(" in html)
scripts = re.findall(r"<script\b", html)
check("exactly ONE <script> in the document - our own resize helper", len(scripts) == 1,
      len(scripts))
check("that one script is the constant resize helper",
      "frameElement" in html.split("<script>")[1])
from html.parser import HTMLParser


class _Tags(HTMLParser):
    """Collects every REAL tag and attribute, ignoring text content."""
    def __init__(self):
        super().__init__()
        self.tags, self.attrs = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs += [(tag, k, v) for k, v in attrs]


parsed = _Tags()
parsed.feed(html)
check("no real tag carries an on* event handler attribute",
      not [a for a in parsed.attrs if a[1].startswith("on")],
      [a for a in parsed.attrs if a[1].startswith("on")])
check("no img / iframe / object / embed / form tag exists",
      not {"img", "iframe", "object", "embed", "form"} & set(parsed.tags),
      sorted(set(parsed.tags)))

print("2. links")
check("no href or src attribute starts with javascript:",
      not [a for a in parsed.attrs if a[1] in ("href", "src")
           and str(a[2]).strip().lower().startswith("javascript")],
      [a for a in parsed.attrs if a[1] in ("href", "src")])
check("every link that exists is http(s)",
      all(str(a[2]).startswith(("http://", "https://"))
          for a in parsed.attrs if a[0] == "a" and a[1] == "href"))
check("an https link is rendered with noopener",
      'href="https://good.example/p"' in html and "noopener" in html)
check("links open in a new tab", 'target="_blank"' in html)

print("3. content")
check("score shown", ">61<" in html)
check("fix heading matches the count", "Fix these two things first" in html)
check("owner chip shown", "Web developer" in html)
check("example is inside a collapsed <details>", "<details>" in html and "<pre>" in html)
check("guest section present with both states", "Partly answered" in html and "Answered" in html)
check("'not assessed' card is muted", "not assessed" in html)

print("4. degenerate inputs do not crash")
h, _ = dashboard.build("", "x.com", sc, [], None, None)
check("no fixes, no guest, no recs", "No recommendations" in h)
h, _ = dashboard.build("H", "x.com", sc, rest, guest, top[:1])
check("single fix heading", "Fix this first" in h)
h, _ = dashboard.build("H", "x.com", sc, [], guest, top)
check("fixes but nothing else: no empty 'everything else' heading",
      "Everything else" not in h)
check("height estimate is a sane positive number", 300 < height < 6000, height)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
