"""
ChatGPT, Gemini and Perplexity on the hotel's tracked prompts (assistants.py). Offline: replies shaped like each provider's documented API (Nov 2026), no network, no key.
Run: python test_assistants.py
"""
import copy
import json
import os
import sys
import types
import warnings

warnings.filterwarnings("ignore")
import assistants
import report_model

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   {detail}"))
    if not ok:
        fails.append(name)


class Resp:
    def __init__(self, code, data):
        self.status_code, self._d, self.text = code, data, json.dumps(data)

    def json(self):
        return self._d


sent = []
OPENAI = {"output": [{"type": "web_search_call", "id": "ws_1", "status": "completed", "action": {"type": "search", "query": "hotels weybridge"}},
                     {"type": "message", "content": [{"type": "output_text", "text": "1. Brooklands Hotel - stylish, near the station\n2. Oatlands Park Hotel",
                                                      "annotations": [{"type": "url_citation", "url": "https://www.tripadvisor.co.uk/x", "title": "TA", "start_index": 0, "end_index": 5},
                                                                      {"type": "url_citation", "url": "https://brooklandshotelsurrey.com/", "title": "Brooklands", "start_index": 0, "end_index": 5}]}]}],
          "usage": {"input_tokens": 3000, "output_tokens": 400}}
PPLX = {"status": "completed", "output": [{"type": "search_results", "queries": ["q"], "results": [{"id": 1, "url": "https://www.booking.com/h", "title": "B"}]},
                                          {"type": "message", "content": [{"type": "output_text", "text": "Try Oatlands Park Hotel or the Hand & Spear [1]."}]}],
        "usage": {"input_tokens": 2000, "output_tokens": 300, "cost": {"total_cost": 0.0042}, "tool_calls_details": {"search_web": {"invocation": 1}}}}


def post(url, json=None, headers=None, timeout=None):
    sent.append((url, json, headers))
    return Resp(200, OPENAI if "openai" in url else PPLX)


print("1. one question to each assistant, read from its documented reply")
a = assistants.ask_chatgpt("Best hotels in Weybridge?", "k", country="GB", post=post)
check("ChatGPT: the answer, its cited pages, one search, and a cost", a["answer"].startswith("1. Brooklands Hotel") and len(a["pages"]) == 2 and a["searches"] == 1 and a["cost_usd"] > 0.01, a)
body = sent[-1][1]
check("ChatGPT is asked with web search on and the UK as the searcher's country", body["tools"][0]["type"] == "web_search" and body["tools"][0]["user_location"]["country"] == "GB"
      and "United Kingdom" in body.get("instructions", ""))
p = assistants.ask_perplexity("Best hotels in Weybridge?", "k", country="GB", post=post)
check("Perplexity: the answer, its sources, and the cost it reports itself", "Oatlands" in p["answer"] and p["pages"][0]["url"].startswith("https://www.booking.com") and p["cost_usd"] == 0.0042, p)
check("Perplexity is asked at its Agent API with web search", sent[-1][0] == "https://api.perplexity.ai/v1/agent" and sent[-1][1]["tools"][0]["type"] == "web_search" and sent[-1][1]["model"] == "perplexity/sonar")


class FakeGemini:
    model = "gemini-test"

    def ask_grounded(self, q):
        return {"ok": True, "answer": "Brooklands Hotel is a good choice in Weybridge.", "citations": [{"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "visitsurrey.com"}],
                "search_queries": ["hotels weybridge"]}


g = assistants.ask_gemini("Best hotels in Weybridge?", "k", country="GB", client=FakeGemini())
check("Gemini: the answer, and the site behind Google's redirect link", "Brooklands" in g["answer"] and g["pages"][0]["url"] == "https://visitsurrey.com", g)

print("2. the tracked prompts, one assistant")
PROMPTS = [{"id": "t1", "text": "Which hotels in Weybridge are good for a business stay?"}, {"id": "t2", "text": "Which quiet hotels are near Weybridge station?"}]
r = assistants.run_engine("chatgpt", PROMPTS, "Brooklands Hotel", "Weybridge", own_domain="brooklandshotelsurrey.com", key="k",
                          ask=lambda q, key, country=None: assistants.ask_chatgpt(q, key, country, post=post))
check("each tracked prompt is asked twice and judged by the same rules as Claude", r["status"] == "ok" and len(r["items"]) == 4 and all(i["mentioned"] and i["position"] == 1 for i in r["items"]), r.get("reason"))
check("the hotel's own site is recognised among the sources", all(i["own_site_cited"] for i in r["items"]))
check("an assistant without a key is not asked, and says so", assistants.run_engine("perplexity", PROMPTS, "H", "W", key=None, ask=None)["status"] == "not_configured")
check("an assistant past its monthly budget is not asked", assistants.run_engine("chatgpt", PROMPTS, "H", "W", key="k", ask=lambda *a_, **k_: OPENAI, budget_left_milli=0)["status"] == "over_budget")


class Bad(Exception):
    status_code = 401


calls = {"n": 0}


def bad(q, key, country=None):
    calls["n"] += 1
    raise Bad("invalid key")


rb = assistants.run_engine("chatgpt", PROMPTS, "H", "W", key="k", ask=bad)
check("a rejected key stops at once and gives the reason (no more calls)", rb["status"] == "unavailable" and calls["n"] <= 3 and "did not answer" in rb["reason"], (calls, rb["reason"]))

print("3. in the report")
rep = json.load(open(os.path.join("tests_data", "sample_report.json"), encoding="utf8"))
base = copy.deepcopy(next(i for i in rep["ai_sample"]["items"] if i["kind"] == "niche"))
rep["ai_sample"]["items"] += [{**copy.deepcopy(base), "id": f"t{k}", "qid": f"t{k}", "source": "benchmark", "text": f"Tracked {k}", "mentioned": k < 1, "names_hotel": False} for k in range(2)]
rep["ai_engines"] = {"chatgpt": r, "perplexity": {"status": "not_configured", "reason": "No Perplexity API key is set on the host, so Perplexity was not asked.", "items": []}}
rows = {x["engine"]: x for x in report_model.engine_counts(rep)}
check("each assistant has its own count on the same tracked prompts", rows["claude"]["named"] == 1 and rows["claude"]["asked"] == 2 and rows["chatgpt"]["named"] == 4 and rows["chatgpt"]["asked"] == 4, rows)
check("an assistant not asked is 'not tested', never 0%", rows["perplexity"]["status"] == "not_configured" and "pct" not in rows["perplexity"] and rows["gemini"]["status"] == "not_configured")
import glance
h = glance.engines_html(rep)
check("the Overview lists every assistant: figures for those asked, the reason for those not", "ChatGPT" in h and "100%" in h and "Not tested" in h and "Perplexity" in h, h[:300])
import engines
er = {e["name"]: e for e in engines.rows(rep)}
check("the report names each assistant asked, through its official API", er["ChatGPT"]["tested"] and "official API" in er["ChatGPT"]["detail"] and not er["Gemini"]["tested"])
try:
    import pymupdf
    import report_pdf
    txt = " ".join(" ".join(p.get_text() for p in pymupdf.open(stream=report_pdf.build_pdf(copy.deepcopy(rep), "management"), filetype="pdf")).split())
    check("the management report lists the assistants asked, with each one's figure", "AI assistants asked" in txt and "ChatGPT" in txt, txt[:200])
except ImportError:
    print("  (PyMuPDF not installed: PDF text not read)")

print("4. Google AI Overviews, checked by hand")
import tempfile
import backend
import manual_checks
form = manual_checks.form_html(rep, [], "/x", "tok", "GB")
check("the form lists the tracked prompts, each opening its Google search", "Tracked 0" in form and "google.com/search?" in form and "gl=gb" in form, form[:200])
posted = {"n": "2", "p0": "Tracked 0", "s0": "1", "n0": "1", "c0": "tripadvisor.co.uk, visitsurrey.com", "p1": "Tracked 1", "s1": "0", "n1": "1", "c1": ""}
rows_ = manual_checks.rows_from_form(posted)
check("what was recorded is read back; 'named' only counts where an Overview appeared", rows_ == [{"prompt": "Tracked 0", "shown": 1, "named": 1, "sources": "tripadvisor.co.uk, visitsurrey.com"},
                                                                                                   {"prompt": "Tracked 1", "shown": 0, "named": 0, "sources": ""}], rows_)
db = backend.open_store("sqlite:///" + os.path.join(tempfile.mkdtemp(), "m.db"))
hid = db.create_hotel("Brooklands Hotel", "b.example", "Weybridge", "b.example")
db.save_manual_checks(hid, 7, manual_checks.ENGINE, rows_, "the operator")
saved = db.manual_checks(hid, manual_checks.ENGINE)
check("it is saved for the hotel's check and read back", len(saved) == 2 and saved[0]["checked_by"] == "the operator")
h2 = glance.engines_html({**rep, "manual_checks": saved})
check("the Overview shows it beside the assistants, labelled as checked by hand", "Google AI Overviews" in h2 and "checked by hand" in h2 and "1 of 1 Overviews shown (2 prompts checked)" in h2, h2[-600:])

print("FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
