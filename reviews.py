"""
Reviews and reputation (checks 6-14).

The honest position: there is no lawful, free, automated source of guest
review TEXT for a hotel.
  * TripAdvisor, Booking.com, Expedia, Agoda, Trip.com, Trustpilot and others
    prohibit automated collection in their terms (and/or robots.txt).
  * Google reviews need the Places API, which needs a billing-enabled account.
  * The hotel's own "testimonials" are marketing, not independent evidence,
    and are never used as a stand-in.

So checks 7-13 are reported as NOT ASSESSED, each with its specific reason,
rather than dressed up from thin data. What IS available is reported as what
it is: aggregate ratings that third parties display, and editorial review
ARTICLES (a journalist's or blogger's write-up - not guest reviews).
"""

import media

NO_TEXT = ("No lawful, free, automated source of guest review text exists for this tool: the review "
           "platforms' terms prohibit automated collection, Google reviews need a billing-enabled "
           "account, and the hotel's own testimonials are marketing rather than independent evidence.")


def assess(ratings, arts, theme_info, own_theme_counts, summary):
    """-> dict with per-check results for checks 6-14."""
    editorial_reviews = [a for a in arts if a["type"] == "review"]
    dated = [a for a in editorial_reviews if a["date"]]
    verified_ratings = [r for r in ratings if r["verified_location"]]
    unverified_ratings = [r for r in ratings if not r["verified_location"]]

    # ---- check 6: the sample, stated before anything is analysed
    sample = {
        "guest_reviews_accessible": 0,
        "aggregate_ratings_seen": len(ratings),
        "editorial_reviews_found": len(editorial_reviews),
        "date_range_of_editorial_reviews": (
            [min(a["date"] for a in dated), max(a["date"] for a in dated)] if dated else None),
        "statement": (
            "0 guest reviews were accessible. " +
            (f"{len(ratings)} aggregate rating(s) shown by third parties were captured "
             f"({len(verified_ratings)} with the town named alongside the hotel). "
             if ratings else "No aggregate ratings were captured. ") +
            (f"{len(editorial_reviews)} editorial review article(s) were found - a writer's "
             "account of a stay, not guest reviews." if editorial_reviews else
             "No editorial review articles were found.")),
    }

    # ---- check 7: freshness - only of what exists (editorial reviews), labelled as such
    fresh = None
    if dated:
        newest = max(a["date"] for a in dated)
        fresh = {"newest_editorial_review": newest,
                 "recent_12m": sum(1 for a in dated if a["freshness"] == "recent"),
                 "older_than_3y": sum(1 for a in dated if a["freshness"] == "old"),
                 "note": "This is the age of editorial write-ups, NOT of guest reviews."}

    # ---- check 14: claims vs evidence - independent sources only, no guest evidence
    both = [t for t in theme_info["themes"] if t["own_pages"] and t["independent_publishers"]]
    own_only = [t for t in theme_info["themes"] if t["own_pages"] and not t["independent_publishers"]]
    ind_only = [t for t in theme_info["themes"] if t["independent_publishers"] and not t["own_pages"]]
    positioning = {
        "supported": [{"theme": t["theme"], "independent_publishers": t["independent_publishers"],
                       "extract": (t["independent_extracts"] or [{}])[0]} for t in both],
        "claimed_only_by_hotel": [t["theme"] for t in own_only],
        "described_by_others_not_by_hotel": [t["theme"] for t in ind_only],
        "disagreements": theme_info["disagreements"],
        "limit": ("This compares the hotel's own wording with what independent writers say. It cannot "
                  "show a gap between marketing and GUEST experience, because guest reviews were not "
                  "available. Do not read 'no independent support' as 'guests disagree'."),
    }
    checks = {
        6: {"status": "partial", "summary": sample["statement"]},
        7: {"status": "not_assessed" if not fresh else "partial",
            "summary": (f"Guest-review freshness could not be measured. {fresh['note']} Newest editorial "
                        f"review: {fresh['newest_editorial_review']}." if fresh else
                        "Guest-review freshness could not be measured, and no dated editorial reviews were found."),
            "reason": NO_TEXT},
        8: {"status": "not_assessed", "summary": "Recurring praise was not assessed.", "reason": NO_TEXT},
        9: {"status": "not_assessed", "summary": "Recurring complaints were not assessed.", "reason": NO_TEXT},
        10: {"status": "not_assessed", "summary": "Management-reply coverage was not assessed.",
             "reason": "It needs review/reply pairs, which are only available on the review platforms "
                       "whose terms prohibit automated collection. " + NO_TEXT},
        11: {"status": "not_assessed", "summary": "Reply speed was not assessed.",
             "reason": "It needs both the review date and the reply date from the review platforms. " + NO_TEXT},
        12: {"status": "not_assessed", "summary": "Reply language was not assessed.",
             "reason": "It needs the text of management replies. " + NO_TEXT},
        13: {"status": "not_assessed",
             "summary": "Review languages were not assessed (no guest reviews were accessible).",
             "reason": NO_TEXT + " The languages of independent ARTICLES are reported under media coverage; "
                                 "they say nothing about the languages of guests."},
        14: {"status": "partial" if (both or own_only or ind_only) else "not_assessed",
             "summary": (f"{len(both)} of the hotel's themes are echoed by independent writers; "
                         f"{len(own_only)} are claimed only on the hotel's own pages; "
                         f"{len(ind_only)} are used by others but not by the hotel. "
                         "No guest evidence was available.") if (both or own_only or ind_only)
            else "Not enough independent coverage to compare with the hotel's positioning.",
             "reason": positioning["limit"]},
    }
    return {"sample": sample, "freshness": fresh, "positioning": positioning,
            "ratings": ratings, "editorial_reviews": [
                {"id": a["id"], "publisher": a["publisher"], "date": a["date"], "url": a["url"],
                 "title": a["title"], "freshness": a["freshness"]} for a in editorial_reviews],
            "checks": checks, "why_no_reviews": NO_TEXT}
