"""
Classification knowledge: what kind of site is this, what kind of page is it,
who really owns the publisher, and which awards are real issuers.

Everything here is a heuristic over URLs, titles and wording. Page-type
results are therefore INFERENCES and are labelled that way in the report.
"""

import re

import evidence

# --------------------------------------------------------------- site classes

BOOKING_PLATFORMS = {
    "booking.com": "Booking.com", "expedia": "Expedia", "hotels.com": "Hotels.com",
    "agoda.com": "Agoda", "trip.com": "Trip.com", "kayak": "Kayak", "trivago": "Trivago",
    "tripadvisor": "TripAdvisor", "lastminute.com": "lastminute.com",
    "laterooms.com": "LateRooms", "hotelscombined": "HotelsCombined",
    "skyscanner": "Skyscanner", "secretescapes.com": "Secret Escapes",
    "guestreservations.com": "Guest Reservations", "ebookers": "Ebookers",
    "travelrepublic": "Travel Republic", "wowcher.co.uk": "Wowcher",
    "groupon": "Groupon", "hotelplanner": "HotelPlanner", "priceline": "Priceline",
    "orbitz": "Orbitz", "travelocity": "Travelocity", "hrs.com": "HRS",
    "mrandmrssmith.com": "Mr & Mrs Smith", "i-escape": "i-escape",
    "classic-british-hotels": "Classic British Hotels", "bedandbreakfast": "Bed and Breakfast",
    "airbnb": "Airbnb", "vrbo": "Vrbo", "snaptravel": "SnapTravel",
    "traveloka": "Traveloka", "makemytrip": "MakeMyTrip", "hostelworld": "Hostelworld",
    "cheaptickets": "CheapTickets", "ratestogo": "RatesToGo",
    # review platforms and deal sites: places a hotel is listed or rated, not editorial
    "trustpilot": "Trustpilot", "feefo": "Feefo", "reviews.io": "REVIEWS.io",
    "luxuryescapes": "Luxury Escapes", "britainsfinest": "Britain's Finest",
    "travelweekly.com": "Travel Weekly (hotel listing)", "hotels.uk.com": "Hotels.uk.com",
    "holidaycheck": "HolidayCheck", "otel.com": "Otel.com", "mrandmrs": "Mr & Mrs Smith",
    # experience / spa-day / deal marketplaces: they sell the hotel, they don't review it
    "spaseekers": "SpaSeekers", "spabreaks": "Spa Breaks", "buyagift": "Buyagift",
    "redletterdays": "Red Letter Days", "virginexperiencedays": "Virgin Experience Days",
    "activitysuperstore": "Activity Superstore", "itison": "itison", "treatwell": "Treatwell",
    "daysoutguide": "Days Out Guide",
}
# Review platforms we know prohibit automated collection - discovered, never read.
NO_READ_PLATFORMS = ("tripadvisor", "booking.com", "expedia", "hotels.com", "agoda",
                     "trip.com", "trivago", "kayak", "airbnb", "vrbo", "hostelworld",
                     "trustpilot", "travelocity", "orbitz", "priceline")

HOTEL_DIRECTORIES = (
    "hotelsone", "hotel-r.net", "hotelguides", "hotelmap", "hotelbye", "hotelscan",
    "hotelsguide", "thegoodhotelguide", "sawdays", "alastairsporting", "yell.com",
    "yelp.", "foursquare.com", "hotels-in-", "hotelplanner", "hotelsnearme",
    "bestday", "findhotel", "wanderlog", "tripomatic", "europa-hotels",
    "ukhotelsdirect", "hotelreservations", "hotelsplus", "hotel-mix", "hotelcheckin",
    "jetcost", "momondo", "cheapflights", "roomsurf", "trover", "cylex",
    "hotelguru", "thehotelguru", "ratedtrips", "travelagewest", "tripoffice", "hotelsnearby",
    # wedding / event supplier directories: listings you apply for, not editorial
    "hitched", "bridebook", "weddingwire", "theweddingsecret", "confetti.co.uk", "venuefinder",
    "mitmagazine", "meetings-conventions", "conferences-uk", "cvent", "venuedirectory",
)
HOTEL_GROUPS = ("marriott.com", "hilton.com", "ihg.com", "accor.com", "radissonhotels",
                "bestwestern", "premierinn", "travelodge", "whitbread", "dorchestercollection",
                "warnerleisure", "macdonaldhotels", "handpicked", "britanniahotels",
                "village-hotels", "thistlehotels", "qhotels", "hand-picked", "mandarinoriental",
                "relaischateaux", "preferredhotels", "slh.com", "historichouses",
                "pride-of-britain", "johansens")

SOCIAL = {"quora.com": "Quora", "instagram.com": "Instagram", "facebook.com": "Facebook", "tiktok.com": "TikTok",
          "twitter.com": "X", "x.com": "X", "pinterest.": "Pinterest", "linkedin.com": "LinkedIn",
          "threads.net": "Threads", "reddit.com": "Reddit", "flickr.com": "Flickr"}
VIDEO = {"youtube.com": "YouTube", "youtu.be": "YouTube", "vimeo.com": "Vimeo"}
MAPS = ("google.com/maps", "maps.google", "maps.apple.com", "openstreetmap.org",
        "bing.com/maps", "waze.com", "mapcarta", "wego.here", "what3words")
WIKI = ("wikipedia.org", "wikidata.org", "wikivoyage.org", "wikimedia.org", "dbpedia")
AWARDS_BODIES = ("worldtravelawards", "theaa.com", "aarosettes", "michelin.com", "guide.michelin",
                 "visitengland.com", "enjoyengland", "greentourism", "goodhotelguide",
                 "cntraveler", "condenasttraveller", "sawdays", "tripadvisor.co.uk/travelerschoice",
                 "awards.", "-awards", "hotelier-awards", "cateringawards", "bestofbritish")
GOV_REGISTERS = ("food.gov.uk", "ratings.food.gov.uk", "companieshouse", "gov.uk")
TOURISM_RE = re.compile(
    r"(^|\.)(visit[a-z0-9-]+|discover[a-z0-9-]+|experience[a-z0-9-]+|"
    r"[a-z0-9-]*tourism[a-z0-9-]*|enjoyengland|visitbritain|visitengland|"
    r"[a-z0-9-]+destination[a-z0-9-]*|[a-z0-9-]*tourist[a-z0-9-]*)\.[a-z.]+$")

AGGREGATORS = ("msn.com", "yahoo.com", "news.google", "flipboard.com", "newsnow.co.uk",
               "dailyhunt", "ground.news", "newsbreak", "smartnews", "pressreader.com",
               "apple.news", "news.yahoo", "allnews", "newsfeed")

# Publisher groups whose titles often run the same story. Distinct domains
# inside one group are counted as ONE independent publisher.
PUBLISHER_GROUPS = {
    "Reach plc": ("getsurrey.co.uk", "mirror.co.uk", "express.co.uk", "dailystar.co.uk",
                  "manchestereveningnews.co.uk", "liverpoolecho.co.uk", "birminghammail.co.uk",
                  "walesonline.co.uk", "chroniclelive.co.uk", "business-live.co.uk",
                  "getreading.co.uk", "getwestlondon.co.uk", "bristolpost.co.uk",
                  "devonlive.com", "cornwalllive.com", "kentlive.news", "mylondon.news",
                  "plymouthherald.co.uk", "dailyrecord.co.uk", "belfastlive.co.uk",
                  "hertfordshiremercury.co.uk", "nottinghampost.com", "leeds-live.co.uk",
                  "examinerlive.co.uk", "cambridge-news.co.uk", "stokesentinel.co.uk"),
    "Newsquest": ("surreycomet.co.uk", "yorkshirepost.co.uk", "thenorthernecho.co.uk",
                  "oxfordmail.co.uk", "bournemouthecho.co.uk", "theargus.co.uk",
                  "heraldscotland.com", "eadt.co.uk", "ekn.co.uk", "newsshopper.co.uk",
                  "bucksfreepress.co.uk", "basingstokegazette.co.uk", "hampshirechronicle.co.uk"),
    "National World": ("scotsman.com", "yorkshirepost.co.uk", "portsmouth.co.uk",
                       "nationalworld.com", "lancashirepost.co.uk", "newsletter.co.uk",
                       "edinburghnews.scotsman.com", "kentonline.co.uk"),
    "DMG Media": ("dailymail.co.uk", "metro.co.uk", "thisismoney.co.uk"),
    "News UK": ("thesun.co.uk", "thesun.ie", "thetimes.co.uk", "thetimes.com", "talksport.com"),
    "Telegraph Media Group": ("telegraph.co.uk",),
    "Future plc": ("timeout.com", "countryliving.com", "goodto.com", "womanandhome.com",
                   "tomsguide.com", "techradar.com", "livingetc.com"),
    "Hearst UK": ("harpersbazaar.com", "cosmopolitan.com", "elle.com", "esquire.com",
                  "countryliving.com", "housebeautiful.com"),
    "Condé Nast": ("cntraveler.com", "condenasttraveller.com", "vogue.co.uk", "tatler.com",
                   "wired.co.uk", "gq-magazine.co.uk"),
}


def _group_of(domain):
    for g, doms in PUBLISHER_GROUPS.items():
        for d in doms:
            if domain == d or domain.endswith("." + d):
                return g
    return None


def classify_domain(url, own_url=""):
    """
    -> (source_type, label). source_type is one of evidence.SOURCE_TYPES.
    Unknown domains are 'other' (a candidate publisher or blog) - they are
    NOT assumed to be news until a page has been read.
    """
    low = (url or "").lower()
    dom = evidence.domain_of(url)
    if own_url and evidence.same_site(url, own_url):
        return "own_website", dom
    for pat, label in SOCIAL.items():
        if pat in dom:
            return "social", label
    for pat, label in VIDEO.items():
        if pat in dom:
            return "video", label
    for pat in WIKI:
        if pat in dom:
            return "wiki", dom
    for pat in MAPS:
        if pat in low:
            return "map_or_open_data", dom
    for pat, label in BOOKING_PLATFORMS.items():
        if pat in dom:
            return "booking_platform", label
    for pat in GOV_REGISTERS:
        if pat in dom and "visit" not in dom:
            return "government_register", dom
    if TOURISM_RE.search(dom) or ".gov.uk" in dom or "tourism" in dom:
        return "destination_body", dom
    for pat in AWARDS_BODIES:
        if pat in low:
            return "awards_body", dom
    for pat in HOTEL_GROUPS:
        if pat in dom:
            return "hotel_group", dom
    for pat in HOTEL_DIRECTORIES:
        if pat in dom:
            return "hotel_directory", dom
    return "other", dom


def is_aggregator(domain):
    return any(a in domain for a in AGGREGATORS)


def publisher_key(domain):
    """The identity used to count independent publishers (group if known)."""
    d = domain[4:] if domain.startswith("www.") else domain
    return _group_of(d) or evidence.registrable(d)


def may_read(url):
    """False for platforms whose terms prohibit automated collection."""
    dom = evidence.domain_of(url)
    return not any(p in dom for p in NO_READ_PLATFORMS)


# ---------------------------------------------------------------- page types

_ROUNDUP = re.compile(r"\b(\d{1,2}\s+(?:of\s+the\s+)?(?:best|top|finest|greatest|loveliest|"
                      r"most\s+\w+)|best(?!\s+western)|top\s+\d+|finest|greatest|our\s+favourite|"
                      r"where\s+to\s+stay|hotels?\s+in|places\s+to\s+stay|round-?up)\b", re.I)
_GUIDE = re.compile(r"\b(guide\s+to|weekend\s+in|things\s+to\s+do|visit(?:ing)?|"
                    r"what\s+to\s+do|travel\s+guide|day\s+out|itinerary|local\s+guide)\b", re.I)
_REVIEW = re.compile(r"\b(review|reviewed|we\s+stayed|i\s+stayed|our\s+stay|checked\s+in|"
                     r"stay\s+at|a\s+night\s+at|sleeping\s+at|hotel\s+review|verdict)\b", re.I)
_INTERVIEW = re.compile(r"\b(interview|q\s*&\s*a|q&a|in\s+conversation|meets|talks\s+to|"
                        r"meet\s+the|profile)\b", re.I)
_NEWS = re.compile(r"\b(opens?|opening|launch(?:es|ed)?|reopen(?:s|ed)?|refurb\w*|renovat\w*|"
                   r"appoint\w*|acquir\w*|sold|sale|bought|planning|closure|closes|"
                   r"revamp\w*|unveil\w*|announce\w*|investment|expansion|new\s+owner|"
                   r"fire|police|council|investigation|plans)\b", re.I)


def classify_page(url, title, text="", cues=None, hotel_mentions=0):
    """
    -> {"type": one of review|roundup|destination_guide|news|interview|
                press_release|sponsored|listing|other,
        "basis": why, "confidence": low|medium}
    Sponsored and press-release cues win because they change what the piece
    means as independent validation.
    """
    cues = cues or {}
    t = (title or "")
    path = re.sub(r"[-_/]+", " ", evidence.domain_of(url) + " " + url.split("//", 1)[-1])
    if cues.get("sponsored_cue"):
        return {"type": "sponsored", "basis": "page carries sponsored/partner wording",
                "confidence": "medium"}
    if cues.get("press_release_cue") or re.search(r"press[- ]?release|/pr/|/press/", url, re.I):
        return {"type": "press_release",
                "basis": "wording or URL indicates a republished press release",
                "confidence": "medium"}
    if _INTERVIEW.search(t):
        return {"type": "interview", "basis": "title wording", "confidence": "medium"}
    if _REVIEW.search(t) or re.search(r"/reviews?/|hotel-review", url, re.I):
        return {"type": "review", "basis": "title/URL wording", "confidence": "medium"}
    if _ROUNDUP.search(t) and not _NEWS.search(t):
        return {"type": "roundup", "basis": "'best/top/where to stay' title wording",
                "confidence": "medium"}
    if _GUIDE.search(t) or re.search(r"/(guides?|destinations?|things-to-do)/", url, re.I):
        return {"type": "destination_guide", "basis": "guide wording in title/URL",
                "confidence": "medium"}
    if _NEWS.search(t) or re.search(r"/news/", url, re.I):
        return {"type": "news", "basis": "news-event wording in title/URL", "confidence": "low"}
    return {"type": "other", "basis": "no clear signal in title or URL", "confidence": "low"}


# ---------------------------------------------------------------- award issuers

AWARD_ISSUERS = [
    # (regex for the award wording, issuer, domains that would confirm it)
    (r"\bAA\s+(?:\d\s*)?(?:rosettes?|stars?|hotel|hospitality|inspected)|\b\d\s+rosettes?\b",
     "The AA", ("theaa.com",)),
    (r"\bvisit\s?england\b.{0,40}\b(?:award|quality|star|gold|silver)|\benjoy\s?england\b",
     "VisitEngland", ("visitengland.com", "visitbritain.org")),
    (r"\bmichelin\b", "Michelin Guide", ("michelin.com", "guide.michelin.com")),
    (r"\bcond[eé]\s*nast\b.{0,40}\b(?:gold\s+list|readers.? choice|award)",
     "Condé Nast Traveller", ("cntraveler.com", "condenasttraveller.com")),
    (r"\btravell?ers.? choice\b|\btripadvisor\b.{0,30}\b(?:award|certificate of excellence)",
     "TripAdvisor", ("tripadvisor.",)),
    (r"\bworld\s+travel\s+awards?\b", "World Travel Awards", ("worldtravelawards.com",)),
    (r"\bgood\s+hotel\s+guide\b", "The Good Hotel Guide", ("goodhotelguide.com",)),
    (r"\bgreen\s+tourism\b", "Green Tourism", ("green-tourism.com",)),
    (r"\bbooking\.com\b.{0,40}\b(?:award|traveller review)", "Booking.com", ("booking.com",)),
    (r"\bhotels\.com\b.{0,30}\bloved by guests", "Hotels.com", ("hotels.com",)),
    (r"\bsawday", "Sawday's", ("sawdays.co.uk",)),
    (r"\bgood\s+hotel\s+awards?\b|\bgold\s+seal\b", "Good Hotel Awards", ("goodhotelaward.com",)),
    (r"\bgood\s+spa\s+guide\b", "Good Spa Guide Awards", ("goodspaguide.co.uk",)),
    (r"\bsilver\s+award|\bgold\s+award|\bbronze\s+award|\bproud\s+winner|\bwinner\s+of\b|"
     r"\baward[- ]winning\b|\bshortlisted\b|\bfinalist\b", "(issuer not named)", ()),
]
AWARD_NOUN = re.compile(r"award|rosette|winner|finalist|shortlist|accredit|recogni[sz]ed|"
                        r"named\s+best|voted|ranked|certificate|gold list|stars?\b", re.I)

# --------------------------------------------------------------------- themes

THEMES = {
    "romantic": r"romantic|couples?|honeymoon|candle|intimate|getaway for two",
    "quiet / peaceful": r"quiet|peaceful|tranquil|serene|calm|secluded|retreat",
    "lively / social": r"lively|buzzing|vibrant|bustling|nightlife|party atmosphere|live music",
    "family-friendly": r"family|families|children|kids|child-friendly|cots?|connecting rooms?",
    "luxury": r"luxur\w+|opulent|five[- ]star|5[- ]star|indulgent|lavish|sumptuous|plush",
    "value / affordable": r"good value|great value|value for money|affordable|budget|bargain|inexpensive|cheap",
    "design-led / contemporary": r"design|contemporary|stylish|modern|chic|boutique|interior|sleek",
    "historic / heritage": r"histor\w+|heritage|listed|georgian|victorian|tudor|period|"
                           r"stately|manor|country house|centuries?[- ]old|built in \d{4}",
    "wellness / spa": r"spa|wellness|treatments?|massage|thermal|pool|sauna|steam room|"
                      r"hydrotherapy|health club",
    "food-focused": r"restaurant|dining|chef|menu|cuisine|tasting|afternoon tea|gastro|"
                    r"brasserie|breakfast|rosette|cocktail",
    "business / meetings": r"business|conference|meeting rooms?|corporate|work-?friendly|"
                           r"events? space|boardroom|networking",
    "weddings & events": r"wedding|ceremon\w+|bride|civil partnership|event venue",
    "countryside / gardens": r"garden|countryside|grounds|parkland|woodland|rural|walks?|"
                             r"riverside|lakeside",
    "dog-friendly": r"dog[- ]friendly|dogs? welcome|pet[- ]friendly|pets? welcome|bring your dog",
    "accessible": r"wheelchair|accessible|step[- ]free|mobility|lift access|disabled",
    "well connected": r"(?:near|close to|minutes from) (?:the )?(?:station|airport|motorway|m25|"
                      r"heathrow|gatwick)|transport links|easy access to|commut\w+",
}
OPPOSITES = [("quiet / peaceful", "lively / social"), ("luxury", "value / affordable"),
             ("historic / heritage", "design-led / contemporary")]

GENERIC_CLAIMS = re.compile(
    r"\b(friendly staff|great location|excellent location|comfortable|clean rooms?|"
    r"warm welcome|home from home|something for everyone|perfect (?:place|location|choice)|"
    r"hidden gem|well[- ]located|nice hotel|good value|helpful staff|lovely staff)\b", re.I)
