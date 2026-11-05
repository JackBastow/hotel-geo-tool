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
print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
