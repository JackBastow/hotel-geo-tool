"""
Offline test for the tidied report layout: the AI visibility tab shows the answer first (one sentence with its range, four numbers, a bar per search, what stands out) and keeps everything else one click away in
titled sections; the Scorecard no longer carries the long old frame; the Action plan is a list of one-line rows; the Tools tab folds its long tables. Uses the sample report plus the Paris gap fixture. No network.
Run: python test_ai_tab.py
"""
import contextlib
import copy
import io
import json
import os
import re
import warnings

warnings.filterwarnings("ignore")
import report_view
import ui_theme
from htmlst import st, build

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "test_ai_gap.py"), encoding="utf8").read()
src = src[:src.index('print("5. recommendations")')]
ns = {"__name__": "t"}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(src, "test_ai_gap.py", "exec"), ns)
REP = json.load(open(os.path.join(HERE, "tests_data", "sample_report.json"), encoding="utf8"))
REP["ai_gap"], REP["custom_prompts"] = ns["res"], ["Which hotels near the Opera suit a conference weekend?"]
html = report_view.render(copy.deepcopy(REP), token="t" * 32)
panel = lambda k: re.search(rf'<div class="tab-panel[^"]*" id="tab-{k}">(.*?)(?=<div class="tab-panel|$)', html, re.S).group(1)      # noqa: E731
ai = panel("ai")

print("1. the AI tab answers first")
first_details = ai.index("<details")
glance = ai[:first_details]
check("it opens with the question and a one-sentence answer with the honest range", "Do AI assistants name this hotel?" in glance and "plausibly" in glance and "of 4 answers" in glance or "answers" in glance)
check("four numbers sit beside it", glance.count('class="metric"') == 4 and "Named in" in glance and "Most-named rival" in glance and "Own website cited" in glance)
check("a bar for every search says 'n of m' and who was named instead", "hk-bar wide" in glance and "0 of 2" in glance and "Named instead:" in glance)
check("what stands out is a short list, not a table", "What stands out" in glance and glance.count("<li>") <= 4)
check("the limits are one line: one assistant, a sample, other assistants not tested", "A sample, not a ranking or a score" in glance and "not tested" in glance)

print("2. everything else is one click away, in titled sections")
titles = re.findall(r"<details[^>]*>\s*<summary>(.*?)</summary>", ai, re.S)
top = [t for t in titles if not t.startswith(("▶",))][:12]
text = " | ".join(re.sub(r"<[^>]+>", "", t) for t in titles)
for want in ("Who was named instead, and what the evidence shows", "Your own prompts", "Where the assistant got its information", "What the assistant says about the hotel", "The hotels named most often",
             "Every question and answer", "How the questions were chosen", "Test it by hand"):
    check(f"a section: {want}", want in text, text[:300])
opens = re.findall(r"<details open[^>]*>\s*<summary>(.*?)</summary>", ai, re.S)
check("only the sections that matter most start open: the gap and the person's own prompts", all(("Who was named instead" in o or "Your own prompts" in o) for o in opens) and len(opens) <= 3, opens)
check("nothing was dropped: the long material is still on the page, inside the sections", "Brand ranking" in ai and "The exact pages the assistant used" in ai and "All the answers" in ai and "How the questions were chosen" in ai)
check("the tab is a fraction of its old length (the glance is under 5,000 characters of HTML; the old tab opened every table)", len(glance) < 5000, len(glance))

print("3. the other tabs")
score = panel("score")
check("the Scorecard no longer carries the 11,000-pixel frame of the old dashboard, but keeps the score breakdown and the categories", "<iframe" not in score and "How the readiness score is calculated" in score)
action = panel("action")
check("the Action plan is one line per recommendation, opened on demand", action.count('class="rec-d"') >= 10 and action.count('<details class="rec-d" open>') <= 3)
tools = panel("tools")
check("the Tools tab folds the 30-check table and the by-hand prompts", "Method: all 30 checks" in tools and "prompts to copy" in tools and re.search(r"<details[^>]*>\s*<summary>Method: all 30 checks", tools) is not None)
site = panel("site")
check("the website tab folds the crawler access card, groups with their problem counts, structured data and the old signals", "How AI crawlers can reach the site" in site and "problem" in site and "Structured data" in site and "How the website reads to an AI" in site)

print("4. the count bars")
buf = build(lambda: ui_theme.count_bars([{"label": "a", "named": 0, "of": 3, "note": "x"}, {"label": "b", "named": 2, "of": 3}, {"label": "c", "named": 3, "of": 3}, {"label": "d", "named": 0, "of": 0}]))
check("never named is red, sometimes amber, usually green, no answers is 'no answers' and never a zero bar", "#C0392B" in buf and "#D9822B" in buf and "#1B873F" in buf and "no answers" in buf and "2 of 3" in buf)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
