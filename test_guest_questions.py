"""
Offline tests for guest_questions.py - no network. Run:  python test_guest_questions.py

These pin the behaviour that matters most: the five states mean different
things, and in particular a site we could not read must never be reported as
a site that lacks the information.
"""
import guest_questions as gq


def page(url, text, title="", h1=None, ok=True, reason="", tels=None, mails=None):
    return {"url": url, "ok": ok, "reason": reason, "title": title, "h1": h1 or [],
            "text": text, "footer_text": "", "tels": tels or [], "mails": mails or [],
            "links": []}


def q_by_id(results, qid):
    return next(r for r in results if r["id"] == qid)


fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


PAD = " Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6

print("1. states")
pages = [
    page("https://h.com/", "Welcome to the hotel." + PAD),
    page("https://h.com/parking/",
         "Parking. We have an on-site car park. It costs £10 per night. Spaces cannot "
         "be reserved in advance, they are first come first served." + PAD,
         title="Parking"),
    page("https://h.com/getting-here/",
         "Getting here. Parking is available for guests. Our station is Weybridge, "
         "10 minutes by taxi. Leave the M25 at junction 11." + PAD,
         title="Getting here"),
    page("https://h.com/about/",
         "Our history. Dogs are mentioned once in passing here, that is all." + PAD),
]
res = gq.evaluate(pages, sufficient=True)
check("parking answered (price, on-site, reservation all present)",
      q_by_id(res, "parking")["state"] == "answered", q_by_id(res, "parking"))
check("parking snippet shows real text", "£10" in q_by_id(res, "parking")["snippet"]
      or "car park" in q_by_id(res, "parking")["snippet"])
check("parking source is the parking page",
      q_by_id(res, "parking")["source_url"].endswith("/parking/"))
check("transport answered", q_by_id(res, "transport")["state"] == "answered",
      q_by_id(res, "transport"))
check("pets = needs_checking (passing mention on an unrelated page)",
      q_by_id(res, "pets")["state"] == "needs_checking", q_by_id(res, "pets"))
check("EV charging = not_found when nothing mentions it",
      q_by_id(res, "ev")["state"] == "not_found")

print("2. partial lists exactly what is missing")
pages = [page("https://h.com/", PAD),
         page("https://h.com/parking/", "Parking is available." + PAD, title="Parking"),
         page("https://h.com/a/", PAD), page("https://h.com/b/", PAD)]
r = q_by_id(gq.evaluate(pages, True), "parking")
check("partial", r["state"] == "partial", r)
check("missing lists price and on-site and reservation",
      set(r["missing"]) == {"the price", "whether it is on-site",
                            "whether you can or must reserve"}, r["missing"])

print("3. a site we could not read is never 'missing'")
res = gq.evaluate([page("https://h.com/", "", ok=False, reason="HTTP 403")], sufficient=False)
check("every unanswered question is couldnt_check, not not_found",
      all(r["state"] == "couldnt_check" for r in res), [r["state"] for r in res])
check("couldnt_check is excluded from the coverage score",
      gq.coverage_fraction({"questions": res}) is None)

print("4. coverage score")
guest = {"questions": [{"state": "answered"}, {"state": "partial"},
                       {"state": "not_found"}, {"state": "couldnt_check"}]}
check("(1 + 0.5 + 0) / 3 judged, couldnt_check ignored",
      abs(gq.coverage_fraction(guest) - 0.5) < 1e-9, gq.coverage_fraction(guest))

print("5. time parsing - the traps")
check("3pm -> 15:00", gq.parse_time("3pm") == "15:00")
check("3.30 pm -> 15:30", gq.parse_time("3.30 pm") == "15:30")
check("12am -> 00:00", gq.parse_time("12am") == "00:00")
check("15:00 -> 15:00", gq.parse_time("15:00") == "15:00")
check("bare '3.00' is rejected, not guessed", gq.parse_time("3.00") is None)
check("garbage rejected", gq.parse_time("soon") is None)

print("6. check-in / check-out are not confused with each other")
pg = [page("https://h.com/faq/",
           "Check-in is from 3pm. Check-out is by 11am." + PAD, title="FAQ")]
ci = gq._times_for(pg, gq._CI)
co = gq._times_for(pg, gq._CO)
check("check-in = 15:00", [t for t, _, _ in ci] == ["15:00"], ci)
check("check-out = 11:00", [t for t, _, _ in co] == ["11:00"], co)
pg = [page("https://h.com/faq/",
           "Check-in is flexible, check-out 11am." + PAD, title="FAQ")]
check("'check-in is flexible, check-out 11am' gives NO check-in time",
      gq._times_for(pg, gq._CI) == [], gq._times_for(pg, gq._CI))
pg = [page("https://h.com/faq/", "Breakfast costs £10.00 per person." + PAD)]
check("a price is not read as a time of day",
      gq._times_for(pg, [rf"breakfast(?:(?!check)[^.\n]){{0,60}}?(?P<t>{gq._TIME})"]) == [])

print("7. conflicts between pages are surfaced")
pages = [page("https://h.com/", "Check-in is from 3pm." + PAD),
         page("https://h.com/faq/", "Check-in from 2pm. Check-out 11am." + PAD, title="FAQ"),
         page("https://h.com/x/", PAD), page("https://h.com/y/", PAD)]
res = gq.evaluate(pages, True)
rows, conflicts, node = gq.build_fact_sheet(
    [p for p in pages if p["ok"]], res, "The Hotel", "https://h.com/")
check("check-in conflict detected", any(c["fact"] == "Check-in time" for c in conflicts),
      conflicts)
check("check-out has no conflict", not any(c["fact"] == "Check-out time" for c in conflicts))

print("8. fact sheet + own-facts node for the consistency check")
pages = [page("https://h.com/", "Welcome." + PAD, tels=["+44 1932 335700"],
              mails=["hello@h.com"]),
         page("https://h.com/c/", PAD, tels=["+44 1932 335700"]),
         page("https://h.com/d/", PAD), page("https://h.com/e/", PAD)]
res = gq.evaluate(pages, True)
rows, conflicts, node = gq.build_fact_sheet(pages, res, "The Hotel", "https://h.com/")
check("telephone taken from the tel: link", node.get("telephone") == "+44 1932 335700", node)
check("every fact row carries a source link", all(r["source_url"] for r in rows), rows)
check("email found", any(r["fact"] == "Email" for r in rows))

print("9. page selection never guesses URLs and respects the cap")
sitemap = [f"https://h.com/page-{i}/" for i in range(200)] + [
    "https://h.com/parking/", "https://h.com/faq/", "https://h.com/blog/parking-news/",
    "https://other.com/parking/", "https://h.com/photo.jpg"]
chosen = gq.select_pages("https://h.com/", [], sitemap, max_pages=25)
check("homepage first", chosen[0] == "https://h.com/")
check("capped at 25", len(chosen) <= 25, len(chosen))
check("parking and faq are chosen", "https://h.com/parking/" in chosen
      and "https://h.com/faq/" in chosen)
check("blog posts, other domains and images excluded",
      not any(("blog" in u or "other.com" in u or u.endswith(".jpg")) for u in chosen))

print("10. regressions from the first live run (real Brooklands FAQ wording)")
FAQ = (
    "Is breakfast included in the room rate? Breakfast is included in selected rates. "
    "If it's not included in your rate, you can add breakfast to your booking for £21.95 "
    "per person. Do you offer room service? Yes, room service is available 24 hours a day. "
    "Is Wi-Fi available? Yes, complimentary Wi-Fi is available throughout the hotel. "
    "Do you have accessible facilities? Yes, the hotel is equipped with accessible "
    "facilities, including accessible bedrooms. Please let us know your requirements "
    "when booking. Is parking available at the hotel? Overnight parking is available at "
    "£14 per vehicle, per night. Please ensure you register your vehicle at Reception. "
    "Do you have gift vouchers available? Yes, gift vouchers are available and can be "
    "purchased on our website for £50. Is the hotel dog-friendly? We love dogs, but "
    "unfortunately, we can't accommodate them at the hotel. Assistance dogs are, of "
    "course, welcome. What time is check-in and check-out? Check-in is from 15:00, and "
    "check-out is by 11:00. If you require an early check-in or late check-out, please "
    "contact us in advance." + PAD)
faq_pages = [page("https://h.com/", PAD), page("https://h.com/faqs/", FAQ, title="FAQs"),
             page("https://h.com/a/", PAD), page("https://h.com/b/", PAD)]
res = gq.evaluate(faq_pages, True)
ci = [t for t, _, _ in gq._times_for(faq_pages, gq._CI)]
co = [t for t, _, _ in gq._times_for(faq_pages, gq._CO)]
check("check-in is 15:00", ci == ["15:00"], ci)
check("check-out is 11:00, NOT 15:00 (the bug)", co == ["11:00"], co)
pk = q_by_id(res, "parking")
check("parking price £14 found", "£14" in pk["snippet"], pk["snippet"])
check("parking snippet is the Q&A, not the neighbouring accessibility answer",
      "accessible" not in pk["snippet"].lower(), pk["snippet"])
check("'booking' from the accessibility answer does NOT satisfy 'reserve'",
      "whether you can or must reserve" not in pk["found"], pk["found"])
pt = q_by_id(res, "pets")
check("pets: a refusal answers the question", pt["state"] == "answered", pt)
check("pets: no fee demanded when the site refuses pets",
      pt["missing"] == [], pt["missing"])
check("pets: the £50 gift voucher price is not used as a pet fee",
      "voucher" not in pt["snippet"].lower(), pt["snippet"])
check("pets: flagged for a human to check the wording", "check the wording" in pt["note"])
bf = q_by_id(res, "breakfast")
check("breakfast: partial, and the missing part is serving times",
      bf["state"] == "partial" and bf["missing"] == ["serving times"], bf)
check("wifi answered (complimentary)", q_by_id(res, "wifi")["state"] == "answered")
check("breakfast snippet quotes the ANSWER, not just the question",
      "included in selected rates" in bf["snippet"] or "£21.95" in bf["snippet"], bf["snippet"])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
