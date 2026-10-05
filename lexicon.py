"""
Vocabulary for the consultant layer: hotel features, traveller intents and
the patterns that show a place is described with a distance.

These are wording patterns, not understanding. Every finding built on them
quotes the page text it matched, so a reader can see why - and a wrong match
is visible and dismissible, never hidden.
"""

import re


def rx(p):
    return re.compile(p, re.I)


# key -> (label, pattern)
FEATURES = {
    "restaurant": ("Restaurant / dining", rx(r"restaurant|brasserie|\bgrill\b|fine dining|a la carte|à la carte|tasting menu")),
    "bar": ("Bar / lounge", rx(r"\bbar\b|lounge|cocktails?")),
    "afternoon_tea": ("Afternoon tea", rx(r"afternoon tea")),
    "spa": ("Spa", rx(r"\bspa\b|massage|sauna|steam room|hydrotherapy|treatment rooms?")),
    "pool": ("Swimming pool", rx(r"swimming pool|\bpool\b")),
    "gym": ("Gym / fitness", rx(r"\bgym\b|fitness (?:suite|centre|center|room)")),
    "meeting_rooms": ("Meeting rooms", rx(r"meeting rooms?|conference (?:rooms?|facilit|suite|centre)|boardroom|function rooms?|delegates?")),
    "weddings": ("Weddings", rx(r"wedding|civil ceremon|marriage")),
    "parking": ("Parking", rx(r"\bparking\b|car[- ]park")),
    "ev": ("EV charging", rx(r"\bEV\b|electric vehicle|charging points?|charge points?|chargers?")),
    "pets": ("Dog / pet friendly", rx(r"dog[- ]friendly|pet[- ]friendly|dogs? (?:are )?(?:welcome|allowed)|pets? (?:are )?(?:welcome|allowed)|bring your dog")),
    "family": ("Family rooms", rx(r"family (?:rooms?|suites?|friendly)|connecting rooms?|interconnecting|adjoining rooms?|\bcots?\b|travel cots?|children'?s menu|kids")),
    "accessible": ("Accessible rooms", rx(r"wheelchair|accessible (?:rooms?|bedrooms?|bathrooms?)|step[- ]free|hearing loop|mobility|lift access|disabled")),
    "wifi": ("Wi-Fi", rx(r"wi-?fi|wireless internet")),
    "garden": ("Gardens / grounds", rx(r"\bgardens?\b|grounds|terrace|parkland")),
    "airport_transfer": ("Airport transfers", rx(r"airport (?:transfers?|shuttle)|shuttle (?:bus|service)")),
    "room_service": ("Room service", rx(r"room service")),
    "reception_24h": ("24-hour reception", rx(r"24[- ]hour reception|24/7 reception|reception is open 24")),
    "heritage": ("Historic building", rx(r"grade (?:i|ii)\*? listed|listed building|built in \d{4}|dating (?:back )?to|history of the (?:hotel|building)")),
}

# key -> (label, pattern, slug hints that indicate a dedicated page)
INTENTS = {
    "luxury": ("Luxury", rx(r"luxur\w+|five[- ]star|5[- ]star|opulent|indulg\w+|sumptuous|prestigious"), ("luxury",)),
    "budget": ("Budget / value", rx(r"budget|affordable|great value|good value|value for money|low[- ]cost|economy|best price|cheap"), ("offers", "deals")),
    "business": ("Business travel", rx(r"business (?:travel|guests?|travellers?|centre|stays?|meetings?|facilities)|corporate (?:rates?|events?|bookings?|guests?|travel|meetings?)|work[- ]?friendly|workspace"), ("business", "corporate")),
    "family": ("Families", rx(r"famil(?:y|ies)[- ](?:rooms?|friendly|suites?|stays?|breaks?|welcome|activities)|family[- ]run|child(?:ren)?[- ]friendly|children'?s? (?:menu|club|room|pool|activities|area)|kids'? (?:menu|club)|\bcots?\b|connecting rooms?|interconnecting|high chairs?|babysit\w*"), ("family", "families", "kids", "children")),
    "couples": ("Couples / romantic", rx(r"romantic|couples?|honeymoon|anniversar\w+|valentine|romance"), ("romantic", "couples")),
    "groups": ("Groups", rx(r"group (?:bookings?|stays?|rates?)|coach parties|large parties|party bookings|groups? of \d+"), ("groups",)),
    "meetings": ("Meetings and events", rx(r"meeting rooms?|conference|function rooms?|boardroom|delegates?|private dining|events? (?:space|venue|team)"), ("meeting", "conference", "events", "business")),
    "weddings": ("Weddings", rx(r"wedding|civil ceremon|marriage|bridal"), ("wedding",)),
    "spa": ("Spa and wellness", rx(r"\bspa\b|wellness|massage|sauna|health club|treatments?"), ("spa", "wellness")),
    "food": ("Food and dining", rx(r"restaurant|dining|chef|tasting menu|afternoon tea|brasserie|fine dining|rosettes?|cocktails?"), ("dining", "restaurant", "eat", "menu", "food")),
    "beach": ("Beach / seaside", rx(r"beach|seafront|seaside|coastal|sea views?|promenade"), ("beach",)),
    "airport": ("Airport stays", rx(r"airport|heathrow|gatwick|stansted|luton|terminal [1-5]|park (?:and|&) fly"), ("airport",)),
    "city_break": ("City breaks", rx(r"city breaks?|city[- ]centre|sightseeing|weekend (?:away|break)|short breaks?|nearby attractions"), ("city", "visit", "explore", "things to do")),
    "pet": ("Dog / pet friendly", rx(r"dog[- ]friendly|pet[- ]friendly|dogs? (?:are )?(?:welcome|allowed)|pets? (?:are )?(?:welcome|allowed)|bring your dog"), ("dog", "pet")),
    "sustainable": ("Sustainability", rx(r"sustainab\w+|eco[- ]friendly|green tourism|carbon (?:neutral|footprint|reduction|emissions)|net[- ]zero|renewable|plastic[- ]free"), ("sustainab", "green", "environment")),
    "accessible": ("Accessibility", rx(r"wheelchair|accessible (?:rooms?|bedrooms?|bathrooms?)|step[- ]free|hearing loop|mobility|lift access|disabled access"), ("access",)),
    "long_stay": ("Long stays", rx(r"long[- ]stay|extended stay|weekly rates?|monthly rates?|serviced apartments?|kitchenette|self[- ]catering"), ("apartment", "long-stay")),
}

# Intents a hotel may simply not have; shown as 'unclear to a machine', never as a failure.
CORE_UNCLEAR = ("family", "couples", "accessible", "sustainable", "pet", "city_break")

# --- distances ---------------------------------------------------------------
TIME_DIST = rx(
    r"\b(\d{1,3})[- ]?(?:min(?:ute)?s?)\b[^.\n]{0,30}?(?:walk|drive|taxi|cab|train|transfer|away|from|by (?:car|foot))"
    r"|(?:walk|drive|taxi|journey|ride)[^.\n]{0,30}?\b(\d{1,3})[- ]?(?:min(?:ute)?s?)\b")
LENGTH_DIST = rx(r"\b(\d+(?:\.\d+)?)\s*(?:miles?|km|kilomet(?:re|er)s?)\b")
HAS_DISTANCE = lambda s: bool(TIME_DIST.search(s) or LENGTH_DIST.search(s))  # noqa: E731
# A sentence only counts as describing the hotel's SURROUNDINGS if it carries a place cue; the
# word "beach" in a menu item or "shopping" in a gift-voucher line says nothing about location.
LOCATION_CUE = rx(r"\b(?:near|nearby|close to|minutes?|walk|drive|from the hotel|located|just|opposite|next to|adjacent|within|"
                  r"away|steps from|doorstep|surrounded|moments)\b")
BOOKING_PAGE = rx(r"book|reserv|checkout|basket|availability|enquir")
# pages that are legal/policy boilerplate: not evidence of what the hotel offers, and they carry the
# operating company's address and phone numbers rather than the hotel's
LEGAL_PAGE = rx(r"terms|privacy|cookie|gdpr|data-protection|modern-slavery|complaints?|legal|disclaimer|accessibility-statement|t-?and-?cs?\b")

LOCATION_CATEGORIES = {
    "transport": ("Rail and public transport", rx(r"\b(?:railway |train |tube |underground |metro |bus )?station\b|\btrain(?:s)?\b|\btube\b|\bmetro\b|\btram\b|bus (?:stop|route|service)")),
    "airports": ("Airports", rx(r"airport|heathrow|gatwick|stansted|luton|southend|manchester airport|terminal")),
    "city_centre": ("City / town centre", rx(r"city[- ]centre|town[- ]centre|high street|heart of")),
    "business": ("Business district / offices", rx(r"business (?:park|district)|financial district|office park|industrial estate|trading estate")),
    "venues": ("Conference and event venues", rx(r"exhibition centre|conference centre|arena|stadium|racecourse|expo\b|convention")),
    "beach": ("Beach / seafront", rx(r"beach|seafront|promenade|\bcoast\b")),
    "nightlife": ("Nightlife", rx(r"nightlife|nightclubs?|\bpubs?\b|\bbars? and (?:restaurants|clubs)")),
    "restaurants": ("Restaurants nearby", rx(r"restaurants? (?:nearby|within|close|around)|local restaurants|places to eat")),
    "shopping": ("Shopping", rx(r"shopping|shops\b|retail park|outlet|mall\b")),
}
