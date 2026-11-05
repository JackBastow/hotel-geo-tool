"""
Offline test: the defects found by reading a real report (Paris Marriott Opera Ambassador, 5 Nov 2026): the same hotel listed twice with a brand in brackets, an airport "a minute walk" away, a menu strip quoted as evidence,
a spa described as thin in one section and confirmed in another, an open-data match called both confirmed and uncertain, a famous place 4 km away treated as close, a forum search that failed without saying why, 'Likely'
findings under a 'Confirmed problems' heading, and a hotel never named shown as 'came 62 of 62'. No network. Run: python test_report_check.py
"""
import contextlib
import copy
import io
import json
import os
import re
import warnings
from types import SimpleNamespace as NS

warnings.filterwarnings("ignore")
import advice
import ai_insights
import anchors
import facility_depth as fd
import forums
import ranking
import report_check
import report_pdf
import textutil

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


print("1. the same hotel is one hotel")
a, b, c = (ai_insights.canon(x) for x in ("Hôtel du Louvre (Unbound Collection by Hyatt)", "Hôtel du Louvre (Hyatt Unbound Collection)", "Hôtel du Louvre"))
check("a brand in brackets does not make another hotel", a == b == c and a, (a, b, c))
check("two genuinely different hotels stay apart", ai_insights.canon("Hôtel Regina Louvre") != ai_insights.canon("Hôtel du Louvre"))

print("2. wording and evidence that make sense")
check("a menu strip of destination links is not a sentence", textutil.looks_like_nav("Traverse City Hotels Waikiki Hotels Mexico City Hotels For Guests Best Rate Guarantee Marriott Bonvoy"))
check("a real sentence about the location is not caught", not textutil.looks_like_nav("Parisian address on the legendary Boulevard Haussmann, close to Opera Garnier and the department stores."))
src = open("insight_content.py", encoding="utf8").read()
check("an airport is never described as a walk: the example says 'by taxi / train'", "by [taxi / train]" in src and re.search(r'"airports" else', src) is not None)

print("3. a place 4 km away is not close")


def fetch(url, **kw):
    class R:
        status_code = 200

        def json(self):
            return {"query": {"geosearch": [{"title": "Galeries Lafayette", "dist": 150}, {"title": "Louvre", "dist": 1900}, {"title": "Eiffel Tower", "dist": 4300}]}}
    return R()


t = anchors.wikipedia_titles(48.87, 2.33, fetch)
check("only places within about 3 km count", "Galeries Lafayette" in t and "Louvre" in t and "Eiffel Tower" not in t, t)

print("4. one finding, one story: the spa")
pages_ok = [("https://h.com/experiences/", "Wellness Offer. Our fully-equipped gym. Wellness Galeries Lafayette. The wellness area has a spa."),
            ("https://h.com/overview/", "The spa offers massages and facials, a sauna, a steam room and a pool. Open daily 10:00 - 20:00. Treatments from €95. Book in advance; day guests welcome.")]
site = NS(content_pages=[{"url": u, "text": tx * 3} for u, tx in pages_ok])
res = {f["key"]: f for f in fd.analyse(site)}
check("the spa's details are found on the page that has them, even when it is not the page about the spa", "spa" in res and len(res["spa"]["found"]) >= 4 and not res["spa"]["thin"], (len(res["spa"]["found"]) if "spa" in res else None))
thin = {"key": "spa", "label": "Spa and wellness", "short": "the spa", "found": [{"key": "facilities", "label": "x", "quote": "q", "url": "u", "match": "m"}], "missing": [{"key": "treatments", "label": "The treatments offered", "example": "e"}], "total": 6, "thin": True,
        "quote": "q", "url": "https://h.com/experiences/", "pages": ["https://h.com/experiences/"], "names": [], "pages_read": 8}
rec = advice._from_facility_depth([thin])[0]
ranking.annotate([rec], [])
check("alone, it is a confirmed problem", rec["confidence_label"] == "Confirmed", rec["confidence_label"])
travel = {"segments": [{"label": "Romantic and spa breaks", "requirements": [{"label": "Spa facilities and who can use them", "state": "confirmed", "found": [{"fact": "what the spa has (treatments, pool, sauna, steam room)"}]}]}]}
notes = report_check.reconcile([rec], [thin], travel, [], None)
check("when the traveller check read the spa as stated, the two are reconciled: the finding becomes a lead, marked disputed, and says so", rec["confidence_label"] == "Worth checking" and thin.get("disputed") and "disagree" in rec["finding"] and notes, (rec["confidence_label"], notes))

print("5. one story on the open-data match")
prof = [{"key": "entity", "label": "Entity clarity", "score": 75, "assessed": True, "drivers": ["+ matched in open map/knowledge data"], "evidence": {"level": "medium", "why": "8 of 8 pages read; open-data match confirmed"}}]
ext = {"rows": [{"source": "OpenStreetMap", "status": "unclear"}, {"source": "Wikidata", "status": "unclear"}]}
n2 = report_check.reconcile([], [], {}, prof, ext)
check("an uncertain match is not described as confirmed, and its 20 points come off", prof[0]["score"] == 55 and "not verified" in prof[0]["drivers"][0] and "not verified" in prof[0]["evidence"]["why"] and n2)
prof2 = [{"key": "entity", "label": "Entity clarity", "score": 75, "assessed": True, "drivers": ["+ matched in open map/knowledge data"], "evidence": {"why": "open-data match confirmed"}}]
report_check.reconcile([], [], {}, prof2, {"rows": [{"source": "OpenStreetMap", "status": "verified"}]})
check("a verified match is left alone", prof2[0]["score"] == 75)

print("6. the forum search says why it failed, and tries again without the site list")
calls = []


class Boom(Exception):
    pass


class Fake:
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        calls.append(kw["tools"][0])
        if "allowed_domains" in kw["tools"][0]:
            raise Boom("400 invalid_request_error: domain not allowed")
        return NS(content=[NS(type="web_search_tool_result", content=[NS(url="https://www.reddit.com/r/paris/comments/1abc/where_to_stay_near_opera/", title="Where to stay near the Opera?", page_age="1 week ago")]),
                           NS(type="text", text="x", citations=[])], stop_reason="end_turn", usage=NS(input_tokens=100, output_tokens=20, server_tool_use=NS(web_search_requests=1)))


r = forums.run("Paris Marriott Opera Ambassador Hotel", "Paris", ["Where to stay near the Opera?"], ["Opera"], client=Fake(), model="claude-haiku-5-5")
check("the request is retried without the list of forums, and the result is used", len(calls) == 2 and "allowed_domains" in calls[0] and "allowed_domains" not in calls[1] and r["status"] == "ok" and r["opportunities"], (len(calls), r["status"]))


class Always(Fake):
    def create(self, **kw):
        raise Boom("400 invalid_request_error: nope")


r2 = forums.run("H", "Paris", ["q"], [], client=Always(), model="claude-haiku-5-5")
check("when it still fails, the reason is given in words and with the error, not just 'rejected'", r2["status"] == "unavailable" and "Boom" in r2["reason"] and "nope" in r2["reason"], r2["reason"])

print("7. the management report")
src2 = open("test_ai_gap.py", encoding="utf8").read()
src2 = src2[:src2.index('print("5. recommendations")')]
ns = {"__name__": "t"}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(src2, "test_ai_gap.py", "exec"), ns)
REP = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
REP.pop("review_pack", None)
REP["ai_gap"], REP["ai_sample"] = ns["res"], ns["AI"]
rep = copy.deepcopy(REP)
for r_ in rep["consultant"]["recommendations"]:
    r_["track"] = advice.track_of(r_)          # a report made by the current code carries the kind of each action
for row in rep["ai_insights"]["brand_ranking"]["all"]:
    if row.get("is_target"):
        row["mentions"], row["coverage_pct"], row["avg_rank"] = 0, 0, None
import pymupdf
doc = pymupdf.open(stream=report_pdf.build_pdf(rep, "management"), filetype="pdf")
txt = " ".join(" ".join(p.get_text() for p in doc).split())
check("a hotel that was never named is said not to have been named, not 'came 5 of 5'", "did not name" in txt and " of 5, named in 0" not in txt)
check("each rival is shown with its category compared with the hotel", "Category compared with this hotel" in txt)
check("'Likely' findings are not under a 'Confirmed' heading, and the table says how sure each is", "Problems found: suggested implementation order" in txt and "Confirmed problems" not in txt and "How sure" in txt)

print("8. three kinds of action, and the sites that name rivals but not the hotel")
ins = {"pages": [{"url": "https://parisjetaime.com/best-hotels", "domain": "parisjetaime.com", "title": "Best hotels", "cited": 16, "answers": 16, "names_hotel": False, "names_competitor": "Hotel Regina Louvre", "own_site": False},
                 {"url": "https://letsgomylove.com/paris", "domain": "letsgomylove.com", "title": "Romantic Paris", "cited": 16, "answers": 16, "names_hotel": False, "names_competitor": "Hotel du Louvre", "own_site": False},
                 {"url": "https://tripadvisor.com/x", "domain": "tripadvisor.com", "title": "Reviews", "cited": 27, "answers": 27, "names_hotel": True, "names_competitor": "Hotel du Louvre", "own_site": False},
                 {"url": "https://marriott.com/", "domain": "marriott.com", "title": "Official", "cited": 3, "answers": 3, "names_hotel": True, "names_competitor": None, "own_site": True}]}
sg = advice._from_source_gaps(ins)
check("sites whose pages name rivals but not the hotel become one recommendation; a page that names the hotel, or is its own site, is left out", len(sg) == 1 and sg[0]["id"] == "SG1" and "parisjetaime.com" in sg[0]["title"] and "tripadvisor.com" not in sg[0]["finding"] and "marriott.com" not in sg[0]["finding"], sg[0]["title"] if sg else "")
check("it names each site, how often it was used and which rival it named, with a link", len(sg[0]["evidence"]) == 2 and all(e["url"].startswith("https://") and "naming" in e["snippet"] for e in sg[0]["evidence"]))
check("it says it is a lead from one assistant, and gives only honest routes (claim a listing, ask how hotels are included), never paying for or inventing coverage", "lead to check" in sg[0]["why"] and "Do not pay for, or invent, coverage" in sg[0]["action"])
rk = ranking.annotate([dict(sg[0])], [])[0]
check("it reaches the action plan as a lead worth checking", rk["value"] >= 28 and rk["confidence_label"] == "Worth checking" and rk["kind"] == "opportunity", (rk["value"], rk["confidence_label"]))
check("no sites that name rivals: no recommendation", advice._from_source_gaps({"pages": [{"names_hotel": True, "names_competitor": "x", "domain": "a.com", "url": "u"}]}) == [] and advice._from_source_gaps(None) == [])
tr = lambda **kw: advice.track_of({"id": kw.get("id", ""), "source": kw.get("source", ""), "tag": kw.get("tag", "")})      # noqa: E731
check("each recommendation is one of three kinds: visibility, website content, data accuracy", tr(source="sources", id="SG1") == "visibility" and tr(source="ai_gap", id="AG-1") == "visibility" and tr(source="forums", id="FM1") == "visibility"
      and tr(source="facility", id="FD-spa") == "content" and tr(source="questions", id="Q1") == "content" and tr(source="location", id="L1") == "content"
      and tr(source="consistency", id="C1", tag="phone") == "accuracy" and tr(source="listings", id="LC1") == "accuracy" and tr(source="intel", id="X-I1") == "accuracy" and tr(source="intel", id="X-M2") == "visibility")
check("the management report splits the plan into the three kinds and puts the kind on each action", "Where to focus: three kinds of action" in txt and "AI visibility opportunity" in txt and "type:" in txt)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
