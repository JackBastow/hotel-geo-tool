"""
Query set generator.

Two separate sets, because they measure different things:

  DISCOVERY  - unbranded, commercial-intent queries. The hotel name never
               appears. Measures: would an AI surface this hotel to someone
               who has not heard of it? -> AI Visibility.

  BRANDED    - natural-language questions about this specific hotel.
               Measures: can an AI answer factual questions about it, and
               does it use the hotel's OWN site to do so?
               -> AI Answerability + first-party citation.

Templates are deterministic so the same hotel scores comparably over time
and different hotels score comparably against each other. Extra queries can
be layered on per hotel without breaking the benchmark, as long as the core
set is always run.
"""

# ---------------------------------------------------------------- discovery

DISCOVERY_CORE = [
    "Best hotels in {city}",
    "Best luxury hotels in {city}",
    "Best value upscale hotels in {city}",
    "Best hotels in {city} for couples",
    "Best hotels in {city} for a romantic weekend",
    "Best hotels in {city} for families",
    "Best hotels in {city} for business travellers",
    "Hotels with parking in {city}",
    "Hotels with a spa in {city}",
    "Hotels with a pool in {city}",
    "Hotels with a good gym in {city}",
    "Best hotel restaurants in {city}",
    "Where should I stay in {city} for a weekend?",
    "Dog friendly hotels in {city}",
    "Hotels in {city} with meeting and conference facilities",
    "Wedding venues with accommodation in {city}",
]

DISCOVERY_PROXIMITY = [
    "Hotels near {landmark}",
    "Where to stay near {landmark}",
]


def build_discovery(city, landmarks=None, extra=None):
    qs = [t.format(city=city) for t in DISCOVERY_CORE]
    for lm in landmarks or []:
        qs += [t.format(landmark=lm) for t in DISCOVERY_PROXIMITY]
    qs += list(extra or [])
    return _dedupe(qs)


# ------------------------------------------------------------------ branded

BRANDED_CORE = [
    # location & transport
    "Where is {hotel} and how do I get there?",
    "How far is {hotel} from the nearest railway station?",
    "Does {hotel} have parking, and does it cost anything?",
    "Does {hotel} have EV charging?",
    # food & drink
    "What time is breakfast at {hotel}?",
    "Is breakfast included in the room rate at {hotel}?",
    "What restaurants and bars are there at {hotel}?",
    "Can non-guests eat at the restaurant at {hotel}?",
    # facilities
    "Does {hotel} have a gym, and what equipment does it have?",
    "Does {hotel} have a swimming pool?",
    "Does {hotel} have a spa, and can non-residents book treatments?",
    "Does {hotel} have free Wi-Fi?",
    # rooms & policies
    "What types of room does {hotel} have?",
    "Does {hotel} have family rooms or connecting rooms?",
    "What are the check-in and check-out times at {hotel}?",
    "Does {hotel} allow dogs?",
    "Is {hotel} wheelchair accessible?",
    # commercial
    "Does {hotel} have facilities for meetings or conferences?",
    "Can you get married at {hotel}?",
    "Is {hotel} a good place for a romantic break?",
]


def build_branded(hotel, city=None, extra=None):
    label = f"{hotel}, {city}" if city else hotel
    qs = [t.format(hotel=label) for t in BRANDED_CORE]
    qs += list(extra or [])
    return _dedupe(qs)


def _dedupe(items):
    seen, out = set(), []
    for i in items:
        k = i.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(i.strip())
    return out
