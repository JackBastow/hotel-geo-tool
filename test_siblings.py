"""
Offline test: another property of the same brand ('Hampton by Hilton Düsseldorf City Centre') is never counted as the hotel ('Hilton Düsseldorf'): not as a mention in an answer, and not as a second line marked 'you' on the dashboard.
Run: python test_siblings.py
"""
import warnings

warnings.filterwarnings("ignore")
import ai_insights
import ai_sample

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


H = "Hilton Düsseldorf"
check("an answer that names only 'Hampton by Hilton Düsseldorf City Centre' does not name the hotel", not ai_sample.mentioned("Top picks: Hampton by Hilton Düsseldorf City Centre and the Hyatt Regency.", H))
check("an answer that names the hotel itself does", ai_sample.mentioned("I recommend the Hilton Düsseldorf near the Königsallee.", H) and ai_sample.mentioned("Hilton Dusseldorf is a solid choice", H))
check("an answer that names both is counted once, for the real one", ai_sample.mentioned("Hilton Düsseldorf or Hampton by Hilton Düsseldorf City Centre", H))
check("the ranking marks a sibling property as a rival, not as the hotel", ai_insights._sibling("Hampton by Hilton Düsseldorf City Centre", H) and ai_insights._sibling("Hilton Düsseldorf Airport", H) and not ai_insights._sibling("Hilton Düsseldorf", H) and not ai_insights._sibling("Hilton Düsseldorf Hotel", H))
check("a hotel whose own name has the word keeps it ('Hilton Düsseldorf Airport' for a hotel of that name)", not ai_insights._sibling("Hilton Düsseldorf Airport", "Hilton Düsseldorf Airport"))
print("2. one hotel, written three ways, is one line")
lb = {"questions": 10, "rows": [{"name": "Brooklands Hotel", "is_target": True, "mentions": 6, "avg_rank": 2.0, "positive": 5, "neutral": 1, "negative": 0},
                                {"name": "Brooklands Hotel & Spa, Weybridge", "is_target": True, "mentions": 4, "avg_rank": 1.0, "positive": 3, "neutral": 1, "negative": 0},
                                {"name": "Brooklands Hotel Surrey", "is_target": True, "mentions": 1, "avg_rank": 3.0, "positive": 1, "neutral": 0, "negative": 0},
                                {"name": "Oatlands Park Hotel", "is_target": False, "mentions": 7, "avg_rank": 1.0, "positive": 7, "neutral": 0, "negative": 0}]}
br = ai_insights.brand_ranking([lb], "Brooklands Hotel")
me = [r for r in br["all"] if r["is_target"]]
check("the three spellings become one row named after the hotel, counted once (the largest count, not the sum)", len(me) == 1 and me[0]["name"] == "Brooklands Hotel" and me[0]["mentions"] == 6, me)
check("the rival is untouched", [r for r in br["all"] if not r["is_target"]][0]["name"] == "Oatlands Park Hotel")
import backend
import os
import tempfile
st = backend.Store("sqlite:///" + os.path.join(tempfile.mkdtemp(), "s.db"))
st.init()
conn = st._connect()
rid1 = st._insert(conn, "runs", {"run_at": "2026-10-01T00:00:00", "hotel": "Brooklands Hotel", "hotel_key": "b.com"})
for nm, cov in (("Brooklands Hotel", 94), ("Brooklands Hotel & Spa, Weybridge", 6), ("Brooklands Hotel Surrey", 0)):
    st._insert(conn, "ai_competitors", {"run_id": rid1, "kind": "all", "competitor": nm, "is_target": 1, "mentions": cov, "asked": 100, "coverage_pct": cov, "sentiment": 50})
conn.commit()
ch = st.competitor_history("b.com")
mine = [r for r in ch["rows"] if r["is_target"]]
check("runs saved earlier are merged when read: one line for the hotel, with the strongest figure", len(mine) == 1 and mine[0]["name"] == "Brooklands Hotel" and mine[0]["points"][0]["coverage_pct"] == 94, mine)

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
