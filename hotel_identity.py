"""
One identity per hotel, for the whole application.

Why this exists (Saunton Sands, Nov 2026): the hotel was registered as 'sauntonsands hotel', the assistant called it 'Saunton Sands Hotel' (85 times, and 25 other spellings), and every part
of the tool that decided 'is this name the hotel?' compared the assistant's words with the registered words. The hotel scored 0%, while the same hotel written 'Saunton Sands Hotel, North Devon'
(55%) and 'Saunton Sands Hotel Source Spa and Wellness' (39%) appeared as its competitors. The same fault doubled 'Watersmeet Hotel' and 'Watersmeet Hotel, Woolacombe' among the rivals.

There are now two things, used by everything that counts, ranks, recommends or charts hotels:

  identity   the hotel under audit: ONE canonical name, the verified alternative names (each with the evidence that verified it), its official domain, its town. build() makes it from what the
             audit already holds (the name typed, the hotel's own page titles, open map data, the names the assistant used, names verified in earlier checks). A name typed as a run-together
             version of the real name ('sauntonsands hotel') is replaced by the real spelling, because the real spelling is on the hotel's own website and in every assistant answer.
  Resolver   one decision per audit about every name an assistant used: which names are the hotel (is_target), which are the same other hotel written two ways (key, display), and which only
             look similar and are NOT merged (a self-catering block, a villa, a restaurant, 'Terminal 5', a sister brand). Used for the hotel and for its competitors alike.

Rules that stop two different properties being merged because their names are alike:
  * a name that carries a kind of property the hotel's own names do not ('apartments', 'villas', 'chalet', 'self-catering', 'terminal', 'express'...) is another property;
  * names listed side by side in ONE answer are different hotels (an assistant does not list one hotel twice);
  * a name that adds an identifying word is another hotel; only the hotel's own name plus a place, a bracketed note, or its own spa/wellness is the same hotel;
  * a name that is only a big chain's brand is never matched on that alone.

Everything here is a rule on text the audit already holds: no requests and no cost.
"""

import html
import re
import urllib.parse

import evidence
import hotelname

# registrable domains that are two labels deep ('co.uk'): the hotel's own name is the label in front
_TWO_PART = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "co.nz", "com.br", "co.za", "co.jp", "com.mx", "com.ar", "co.in", "com.sg", "com.tr", "com.es", "com.pt", "co.il",
             "com.hk", "com.tw", "co.kr", "com.my", "com.ph", "co.id", "com.vn", "com.cn"}

# a word that makes a name ANOTHER KIND of property or an outlet inside one: never the hotel itself unless the hotel's own names carry it
UNIT_WORDS = frozenset({
    "apartment", "apartments", "aparthotel", "villa", "villas", "chalet", "chalets", "cottage", "cottages", "bungalow", "bungalows", "lodge", "lodges", "residence", "residences",
    "holiday", "camping", "campsite", "glamping", "caravan", "hostel", "restaurant", "grill", "bistro", "brasserie", "cafe", "bar", "pub", "kitchen", "terminal", "airport", "express",
    "centre", "center", "city", "garden", "gardens", "hampton", "doubletree", "conrad", "embassy", "curio", "tapestry", "homewood", "canopy", "beach", "villas", "penthouse"})
_UNIT_PHRASES = ("selfcatering", "self catering", "holiday park", "bed and breakfast", "guest house", "guesthouse")
# what may follow the hotel's own name without making it another hotel: its spa and leisure side, a star rating, 'main building'
FACILITY_TAIL = frozenset({"spa", "wellness", "health", "leisure", "club", "pool", "resort", "golf", "retreat", "hydro", "thermal", "thermae"})
SAFE_REMAINDER = frozenset({"and", "the", "at", "by", "in", "of", "with", "a", "hotel", "hotels", "main", "building", "star", "stars", "luxury", "boutique", "near", "on", "for", "or", "its"})
_NUMBER_WORDS = frozenset({"one", "two", "three", "four", "five", "3", "4", "5", "1", "2"})
_LODGING = re.compile(r"\b(?:hotel|hotels|hotell|hotelli|inn|resort|lodge|guest ?house|b ?(?:&|and) ?b|motel|manor|house|arms|spa)\b", re.I)
# a brand-new generic label is not a hotel's own name
_GENERIC_LABELS = {"hotel", "hotels", "booking", "reservations", "stay", "stays", "holiday", "holidays", "rooms", "resort", "resorts", "inn", "travel"}


def fold(s):
    return evidence.fold(s or "")


def tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", fold(s)) if t]


def collapse(s):
    """Letters and digits only, folded: 'Saunton Sands' and 'sauntonsands' are the same string."""
    return re.sub(r"[^a-z0-9]", "", fold(s))


def domain_key(website):
    """The hotel's own name as its domain writes it, collapsed: 'https://www.sauntonsands.co.uk/' -> 'sauntonsands'. '' when there is none."""
    host = urllib.parse.urlparse(website if "//" in (website or "") else "https://" + (website or "")).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    parts = [p for p in host.split(".") if p]
    if not parts:
        return ""
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_PART:
        label = parts[-3]
    elif len(parts) >= 2:
        label = parts[-2]
    else:
        label = parts[0]
    label = collapse(label)
    return "" if label in _GENERIC_LABELS else label


def base_name(name):
    """The name without a bracketed note or a ', place' / ' - note' tail: 'Watersmeet Hotel, Woolacombe' -> 'Watersmeet Hotel'; 'Saunton Sands Hotel (Source Spa)' -> 'Saunton Sands Hotel'.
    A name that is only a big chain's brand before the comma keeps its tail ('Marriott, Paris Opera' is not 'Marriott')."""
    s = re.sub(r"\s*\([^)]*\)", " ", name or "")
    cut = re.split(r"\s*,\s*|\s+[-–—|]\s+", s)[0].strip()
    toks = tokens(cut)
    core = [t for t in toks if t not in hotelname.GENERIC]
    if core and all(t in hotelname.BRANDS or " ".join(core) in hotelname.BRANDS for t in core):
        return re.sub(r"\s+", " ", s).strip(" ,")
    return re.sub(r"\s+", " ", cut)


def _qual(name):
    """The place or note after the first top-level comma or dash: 'The Hoxton, Shoreditch' -> ['shoreditch']."""
    s = re.sub(r"\s*\([^)]*\)", " ", name or "")
    parts = re.split(r"\s*,\s*|\s+[-–—|]\s+", s, maxsplit=1)
    return tokens(parts[1]) if len(parts) > 1 else []


def unit_words(name):
    """The kind-of-property words in a name (the WHOLE name, brackets and tails included: 'Saunton Sands Hotel (4-star), via its self-catering apartments' is the apartments)."""
    f = fold(name)
    out = {t for t in tokens(f) if t in UNIT_WORDS}
    flat = " ".join(tokens(f))
    out |= {p for p in _UNIT_PHRASES if p in flat or p.replace(" ", "") in collapse(f)}
    return out


def _core(s):
    return [t for t in tokens(s) if t not in hotelname.GENERIC]


def _site_candidates(titles):
    """Names the hotel's own page titles repeat: 'Living Suites | Saunton Sands Hotel | North Devon' -> 'Saunton Sands Hotel' (it is in many titles and has a hotel word; 'North Devon' has none)."""
    seen = {}
    for t in titles or []:
        t = html.unescape(str(t or ""))
        for seg in re.split(r"\s*[|•·–—]\s*|\s+-\s+|:\s+", t):
            seg = seg.strip()
            if 3 <= len(seg) <= 70 and _LODGING.search(seg):
                seen[seg] = seen.get(seg, 0) + 1
    return [n for n, c in sorted(seen.items(), key=lambda kv: (-kv[1], len(kv[0]))) if c >= 2 or len(seen) == 1][:6]


def _respelling(entered, cands):
    """A candidate that is the typed name with its spaces put in ('sauntonsands hotel' -> 'Saunton Sands Hotel'): same letters, more words. -> (name, source) or None."""
    ec = collapse(" ".join(_core(entered)))
    if not ec:
        return None
    en = len(_core(entered))
    best = None
    for name, src in cands:
        cc = collapse(" ".join(_core(name)))
        if cc == ec and len(_core(name)) > en:
            rank = (src, len(name) if src == 4 else 0)         # the names verified earlier: the shortest ('Saunton Sands Hotel', not 'Saunton Sands Hotel & Spa'); others: in the order given
            if best is None or rank < best[2]:
                best = (name, src, rank)
    return best[:2] if best else None


def build(entered, city="", website="", *, site_titles=(), site_names=(), entity_names=(), observed=None, known=None, brand_site=False, towns=()):
    """
    The hotel's identity. entered: the name as typed or registered. site_titles: the page titles of the hotel's own website. site_names: names its structured data / headings give.
    entity_names: names open map data and Wikidata give. observed: {name: count} the assistants used. known: aliases verified in earlier checks ([{"name","basis"}] or [str]).
    brand_site: the website is a hotel group's (the domain says nothing about this hotel). -> dict (see module doc); never raises.
    """
    entered = re.sub(r"\s+", " ", (entered or "")).strip()
    dk = "" if brand_site else domain_key(website)
    observed = {k: v for k, v in (observed or {}).items() if k}
    titles = list(site_titles or [])
    sitec = _site_candidates(titles) + [n for n in (site_names or []) if n]
    cands = [(n, 1) for n in sitec] + [(n, 2) for n in (entity_names or []) if n] + [(n, 4) for n in _known_names(known)]
    # the names the assistant used count as evidence of how people write the name, in order of use, when they match the domain (or the typed letters)
    obs_ok = []
    for n, c in sorted(observed.items(), key=lambda kv: (-kv[1], len(kv[0]))):
        b = base_name(n)
        if unit_words(n) or not _LODGING.search(b):
            continue
        if (dk and len(dk) >= 6 and dk in collapse(b)) or (collapse(" ".join(_core(entered))) and collapse(" ".join(_core(entered))) == collapse(" ".join(_core(b)))):
            obs_ok.append(n)
    cands += [(n, 3) for n in obs_ok[:8]]
    canonical, changed, why = entered, False, "the name as entered"
    swap = _respelling(entered, cands) if entered else None
    if swap:
        canonical, changed = swap[0].strip(), True
        why = {1: "the spelling on the hotel's own website", 2: "the spelling in open map data", 3: "the spelling every assistant used", 4: "the spelling verified in an earlier check"}[swap[1]]
        why = f"the name was typed run together ('{entered}'); {why} is '{canonical}'"
    elif not entered:
        pick = (sitec or list(entity_names or []) or obs_ok[:1] or [""])[0]
        canonical, changed, why = pick.strip(), bool(pick), "taken from the website" if pick else "no name"
    town = (city or "").split(",")[0].strip()
    ident = {"canonical": canonical, "entered": entered, "town": town, "domain_key": dk, "brand_site": bool(brand_site), "website": website or "", "changed": changed, "basis": why,
             "aliases": [], "related": [], "own_units": [], "own_words": [], "towns": [], "needs_review": "",
             "site_titles": [str(t) for t in titles][:40], "site_names": [str(n) for n in (site_names or [])][:10], "entity_names": [str(n) for n in (entity_names or [])][:10]}
    # own words: what the hotel's own pages call things (a name's extra words are verified by being on its own pages)
    words = set()
    for t in titles + list(site_names or []) + list(entity_names or []):
        words |= {w for w in tokens(t) if len(w) >= 3}
    ident["own_words"] = sorted(w for w in words if w not in UNIT_WORDS)[:300]
    ident["towns"] = sorted({w for t in ([town] + list(towns or [])) for w in tokens(t) if len(w) >= 3})
    own_units = set()
    for n in [canonical, entered] + [c[0] for c in cands if c[1] in (1, 2, 4)]:
        own_units |= unit_words(n)
    ident["own_units"] = sorted(own_units)
    aliases, seen = [], set()

    def add(name, basis):
        k = collapse(name)
        if name and k and k not in seen:
            seen.add(k)
            aliases.append({"name": name.strip(), "basis": basis})
    add(canonical, "canonical name")
    if entered:
        add(entered, "entered by you")
    for n in sitec:
        add(n, "the hotel's own website")
    for n in (entity_names or []):
        add(n, "open map data / Wikidata")
    for n in _known_names(known):
        add(n, "verified in an earlier check")
    ident["aliases"] = aliases
    if entered and not changed and dk and len(dk) >= 8 and collapse(" ".join(_core(entered))) == dk and " " not in " ".join(_core(entered)).strip():
        ident["needs_review"] = (f"The name '{entered}' looks like the website address, not the hotel's name, and no better spelling was found. Rename the hotel to the name guests use: every question "
                                 "asked about it and every comparison uses it.")
    # the names the assistants used: verified aliases (with the evidence) and the related properties kept separate
    for n, c in sorted(observed.items(), key=lambda kv: (-kv[1], len(kv[0]))):
        own, basis = is_own(ident, n)
        if own:
            if collapse(base_name(n)) not in seen:
                add(n, basis)
        elif _looks_related(ident, n):
            ident["related"].append({"name": n, "why": _why_not(ident, n), "answers": c})
    ident["aliases"] = aliases[:60]
    ident["related"] = ident["related"][:40]
    # a name a group shares among several hotels ('The Hoxton, Shoreditch'): the bare group name does not say which one
    cq = _qual(canonical)
    if cq and not set(cq) <= (set(ident["towns"]) | set(tokens(town))):
        base_t = [t for t in tokens(base_name(canonical)) if t != "the"]
        sibs = sorted({n for n in observed if _qual(n) and set(_qual(n)).isdisjoint(cq) and [t for t in tokens(base_name(n)) if t != "the"] == base_t})
        if brand_site or sibs:
            ident["group"] = {"qualifier": cq, "base": base_t, "siblings": sibs[:6],
                              "why": ("the website is the group's, covering several hotels" if brand_site else "") + ("; " if brand_site and sibs else "") + (("the assistants also named " + ", ".join(sibs[:3])) if sibs else "")}
    return ident


def matcher_name(ident):
    """The hotel's name for the text matcher: a GroupName when its name is shared by several hotels of a group, else the plain canonical name."""
    g = (ident or {}).get("group")
    name = (ident or {}).get("canonical") or ""
    return hotelname.GroupName(name, g["qualifier"]) if g and name else name


def is_ambiguous(ident, name):
    """Is this name only the group's name ('The Hoxton'), with nothing saying which of the group's hotels? Never true for a hotel that has no group."""
    g = (ident or {}).get("group")
    if not g or not name or _qual(name):
        return False
    bt = [t for t in tokens(base_name(name)) if t != "the"]
    base = g["base"]
    if bt[:len(base)] != base:
        return False
    rem = bt[len(base):]
    return not (set(rem) & set(g["qualifier"])) and _remainder_ok(rem, ident)


def refine(ident, *, observed=None, entity_names=(), known=None, towns=(), city=""):
    """The identity again with more evidence: the names the assistants used and the names open map data gives. Same inputs as before, plus these. -> dict"""
    ident = ident or {}
    return build(ident.get("entered") or ident.get("canonical") or "", city or ident.get("town") or "", ident.get("website") or "", site_titles=ident.get("site_titles") or (),
                 site_names=ident.get("site_names") or (), entity_names=list(ident.get("entity_names") or []) + [n for n in (entity_names or []) if n], observed=observed,
                 known=list(_known_names(known)) + [a["name"] for a in ident.get("aliases") or []], brand_site=ident.get("brand_site"), towns=towns)


def _known_names(known):
    out = []
    for k in known or []:
        n = k.get("name") if isinstance(k, dict) else k
        if n:
            out.append(str(n))
    return out


def _alias_names(ident):
    return [a["name"] for a in ident.get("aliases") or []] or [ident.get("canonical") or ""]


def _remainder_ok(rem, ident):
    if not rem:
        return True
    allowed = SAFE_REMAINDER | set(ident.get("towns") or []) | set(ident.get("own_words") or []) | _NUMBER_WORDS
    rem = [t for t in rem if t != "s"]
    if all(t in allowed for t in rem):
        return True
    return rem[-1] in FACILITY_TAIL                 # '<hotel> Source Spa', '<hotel> & Wellness'


def is_own(ident, name):
    """
    Is this name THE hotel? -> (bool, basis). The hotel's own names, its names with a place or a bracketed note added, its names with its spa and wellness side added, a respelling of its
    domain; never another kind of property (a self-catering block, a villa, a restaurant, a terminal, a sister brand), never a place of the same name on its own.
    """
    f = fold(name)
    if not f or not ident:
        return False, ""
    if is_ambiguous(ident, name):
        return False, ""                  # the group's name alone: not confirmed as this hotel (it is not a rival either: see Resolver.is_ambiguous)
    extra_units = unit_words(name) - set(ident.get("own_units") or [])
    if extra_units:
        return False, ""
    aliases = _alias_names(ident)
    if any(hotelname.sister_brand(name, a) for a in aliases[:3]):
        return False, ""
    # a group's hotels told apart by the place after the name ('The Hoxton, Shoreditch' and 'The Hoxton, Holborn'): a different place is a different hotel
    cq, nq = _qual(ident.get("canonical")), _qual(name)
    if cq and nq and set(cq).isdisjoint(nq) and tokens(base_name(name)) == tokens(base_name(ident.get("canonical"))):
        return False, ""
    bt = tokens(base_name(name))
    bt_nothe = bt[1:] if bt[:1] == ["the"] else bt
    for a in aliases:
        at = tokens(a)
        at_nothe = at[1:] if at[:1] == ["the"] else at
        if not at_nothe:
            continue
        if bt_nothe == at_nothe or tokens(name) == at:
            return True, "the hotel's own name"
        if bt_nothe[:len(at_nothe)] == at_nothe and _remainder_ok(bt_nothe[len(at_nothe):], ident):
            return True, "the hotel's own name with " + ("its spa or wellness side" if bt_nothe[len(at_nothe):] and bt_nothe[-1] in FACILITY_TAIL else "a place or note added")
    # the shorter forms the name is known by ('The Nici' for 'THE NICI Newquay')
    town = ident.get("town") or ""
    for a in aliases[:6]:
        forms = {" ".join(tokens(v)) for v in hotelname.variants(a, town)}
        forms |= {" ".join(tokens(v)[1:]) for v in forms if v.startswith("the ")}
        if " ".join(bt) in forms or " ".join(bt_nothe) in forms:
            return True, "a shorter form of the hotel's name"
    dk = ident.get("domain_key") or ""
    if dk and len(dk) >= 6 and dk in collapse(base_name(name)) and _LODGING.search(base_name(name)):
        return True, f"the name contains the hotel's website name ('{dk}')"
    return False, ""


def _looks_related(ident, name):
    """A name that shares the hotel's distinctive words but is NOT the hotel: shown as related, never merged."""
    own_core = set(_core(ident.get("canonical") or "")) - hotelname.PLACE_WORDS
    nt = set(_core(name))
    return bool(own_core) and bool(own_core & nt)


def _why_not(ident, name):
    u = unit_words(name) - set(ident.get("own_units") or [])
    if u:
        return "another kind of property (" + ", ".join(sorted(u)) + ")"
    return "a different name: it adds words the hotel's own names do not carry"


def mentioned_in(ident, text, city=""):
    """Is the hotel named in this text, under any verified name? (the one text matcher, hotelname.py, on each verified name.)"""
    for a in _alias_names(ident)[:8]:
        if hotelname.mentioned(text, a, city or (ident or {}).get("town") or ""):
            return True
    return False


# --------------------------------------------------------------------------- the resolver

class Resolver:
    """
    One decision, for a whole audit, about every hotel name an assistant used. names: [(answer id, [names listed in that answer])].
      is_target(name) -> bool          the hotel itself
      key(name)       -> '__self__' or the group key of the same other hotel
      display(name)   -> the name to show ('Saunton Sands Hotel'; 'Watersmeet Hotel' for 'Watersmeet Hotel, Woolacombe')
      aliases(name)   -> the other spellings of that hotel the assistants used
    """
    SELF = "__self__"

    def __init__(self, ident, by_answer, city=""):
        import rivals
        self.ident, self.city = ident or {}, city or (ident or {}).get("town") or ""
        self._own = {}
        self._amb = {}
        for _aid, ns in by_answer:
            for n in ns:
                if n not in self._own:
                    self._own[n] = is_own(self.ident, n)[0] if self.ident else False
                    self._amb[n] = bool(self.ident) and is_ambiguous(self.ident, n)
        rest = [(aid, [n for n in ns if not self._own.get(n) and not self._amb.get(n)]) for aid, ns in by_answer]
        self._group = {}
        for g in rivals.resolve(rest, self.city, strict=True):
            clean = [n for n in g["names"] if base_name(n) == n.strip()] or g["names"]
            disp = max(clean, key=lambda n: (g["names"].index(n) * -1, -len(n)))
            for n in g["names"]:
                self._group[n] = {"key": g["key"], "name": disp, "names": g["names"], "uncertain": g["uncertain"]}

    def is_ambiguous(self, name):
        """The group's name alone ('The Hoxton'): neither the hotel nor a rival; counted apart as a possible mention."""
        if name not in self._amb:
            self._amb[name] = bool(self.ident) and is_ambiguous(self.ident, name)
        return self._amb[name]

    def is_target(self, name):
        if name not in self._own:
            self._own[name] = is_own(self.ident, name)[0] if self.ident else False
        return bool(self._own[name])

    def key(self, name):
        if self.is_target(name):
            return self.SELF
        g = self._group.get(name)
        return g["key"] if g else " ".join(sorted(rivals_tokens(name, self.city))) or fold(name)

    def display(self, name):
        if self.is_target(name):
            return (self.ident or {}).get("canonical") or name
        g = self._group.get(name)
        return g["name"] if g else name

    def aliases(self, name):
        g = self._group.get(name)
        return [n for n in (g["names"] if g else []) if n != self.display(name)]

    def uncertain(self, name):
        g = self._group.get(name)
        return bool(g and g["uncertain"])


def rivals_tokens(name, city=""):
    import rivals
    return rivals.tokens(name, city)


def by_answer_of(extracted_answers):
    """[(answer id, [names])] from the hotels each answer was read as listing ({answer id: [{"name": ...}]})."""
    return [(aid, [h.get("name") for h in hs if h.get("name")]) for aid, hs in (extracted_answers or {}).items()]


def resolver_for(hotel, city, extracted_answers, ident=None, website=""):
    """A Resolver for an audit: the identity given, or one made from the name and website alone."""
    ident = ident or build(hotel, city, website)
    return Resolver(ident, by_answer_of(extracted_answers), city)


def normal_key(name, city=""):
    """A key from one name alone (no other answers), for merging the same hotel across checks over time: 'Watersmeet Hotel, Woolacombe' = 'Watersmeet Hotel'."""
    toks = rivals_tokens(name, city)
    return " ".join(sorted(toks)) or fold(name)
