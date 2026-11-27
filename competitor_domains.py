"""
One answer, for every recommendation module, to: "is this website a hotel's own site, so nothing can be got onto it?"

Before this, three modules each had their own idea. strategy_actions knew only the rivals whose website the rival research had already found; source_actions added a list of hotel groups; commercial
had a looser check on the words of a rival's name. A competing hotel the research never reached was still eligible for an "get listed here" or "pitch a story to" action. This module is the shared process:

  1. A hotel group's or brand's own website (the chain list).
  2. A website the audit already knows belongs to a rival: the rival research, the comparison of facilities, the competitor look.
  3. A website whose address IS a rival's name, wherever the rival was named (the AI answers' rankings, the markets, the pages the assistants cited): 'northcotemanor.co.uk' for Northcote Manor,
     'thewatersmeethotel.co.uk' for Watersmeet Hotel. Exact: the address must be the name (with 'the' and 'hotel' words), not merely contain a word of it, so a tourism board called visitdevon is never taken
     for 'Devon Hotel'.
  4. A source that the research named after a rival ('The Headland Hotel & Spa') whatever its address.

`excluded(rep)` -> an Exclusions object for one report; `.reason(domain, name="")` -> '' (allowed) or why not. Nothing here fetches anything.
"""

import re

import evidence
import hotel_identity

# hotel groups' and brands' own websites: not a place another hotel can be listed
CHAIN_DOMAINS = ("marriott.com", "hilton.com", "ihg.com", "hyatt.com", "accor.com", "all.accor.com", "wyndhamhotels.com", "choicehotels.com", "bestwestern.com", "radissonhotels.com", "melia.com",
                 "nh-hotels.com", "scandichotels.com", "scandichotels.se", "strawberry.se", "nordicchoicehotels.com", "premierinn.com", "travelodge.co.uk", "kempinski.com", "fourseasons.com",
                 "ritzcarlton.com", "mandarinoriental.com", "shangri-la.com", "peninsula.com", "rosewoodhotels.com", "belmond.com", "minorhotels.com", "barcelo.com", "iberostar.com", "riu.com",
                 "omnihotels.com", "loewshotels.com", "sonesta.com", "ihg.co.uk", "holidayinn.com", "crowneplaza.com", "hamptoninn.com", "doubletree.com", "sheraton.com", "westin.com", "novotel.com",
                 "ibis.com", "mercure.com", "sofitel.com", "pullmanhotels.com", "fairmont.com", "raffles.com", "swissotel.com", "movenpick.com", "leonardo-hotels.com", "motel-one.com", "citizenm.com")

# words that may stand around a hotel's name in its own address without being part of it
_AROUND = {"the", "hotel", "hotels", "spa", "resort", "resorts", "inn", "lodge", "house", "uk", "group", "guesthouse", "bnb", "suites"}      # no short words ('and', 'at'): they end real names ('headland')
_SECOND_LEVEL = {"co", "com", "org", "ac", "gov", "net", "ltd", "plc"}


def dom(url_or_domain):
    d = re.sub(r"^https?://", "", str(url_or_domain or "")).split("/")[0].split("?")[0].lower()
    return d[4:] if d.startswith("www.") else d


def is_chain_site(domain):
    d = dom(domain)
    return any(d == c or d.endswith("." + c) for c in CHAIN_DOMAINS)


def _label(domain):
    """The name part of an address: 'www.thewatersmeethotel.co.uk' -> 'thewatersmeethotel'."""
    parts = [p for p in dom(domain).split(".") if p]
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def _strip_around(s):
    """Take the generic words off both ends of a run-together label."""
    changed = True
    while changed and s:
        changed = False
        for w in sorted(_AROUND, key=len, reverse=True):
            if s.startswith(w) and len(s) > len(w):
                s, changed = s[len(w):], True
                break
            if s.endswith(w) and len(s) > len(w):
                s, changed = s[:-len(w)], True
                break
    return s


def name_matches_domain(name, domain):
    """Is this address a hotel's own site under this name? True when the address is the name run together (a leading 'the', a trailing 'hotel', 'spa'... allowed) or is its first distinctive words
    (northcote.co.uk for Northcote Manor) with at least seven letters. A single word that is also a place ('Devon', 'Newquay') is too short to count."""
    import rivals
    toks = [t.replace("-", "") for t in rivals.tokens(name or "")]
    if not toks:
        return False
    lab = _label(domain).replace("-", "")
    if len(lab) < 6:
        return False
    # the name as written, every word ('The Cliff House' -> cliffhouse.co.uk, 'Royal Hotel' -> royalhotel.com)
    written = "".join(re.findall(r"[a-z0-9]+", evidence.fold(hotel_identity.base_name(name))))
    if len(written) >= 8 and lab in (written, written[3:] if written.startswith("the") else written):
        return True
    core = _strip_around(lab)
    if len(core) < 6:
        return False
    full = "".join(toks)
    if len(full) >= 7 and core == full:
        return True
    # the first distinctive words only ('northcote.co.uk' for Northcote Manor): long enough that it cannot be a town or county ('newquay', 'devon', 'boundary')
    for k in range(len(toks) - 1, 0, -1):
        run = "".join(toks[:k])
        if len(run) >= 9 and core == run:
            return True
    return False


class Exclusions:
    """The rival hotels a report knows, and the websites that are theirs or a hotel group's."""

    def __init__(self, rep):
        rep = rep or {}
        self.urls = {}          # domain -> rival name (a rival whose website was found)
        self.names = set()      # every rival name the report has anywhere
        gap = rep.get("ai_gap") or {}
        for r in gap.get("rivals") or []:
            self._rival(r.get("name"), r.get("url"))
        for r in (gap.get("comparison") or {}).get("rivals") or []:
            self._rival(r.get("name"), r.get("url"))
        for r in (rep.get("competitors") or {}).get("competitors") or []:
            self._rival(r.get("name"), r.get("url"))
        for m in gap.get("markets") or []:
            for r in m.get("rivals") or []:
                self._rival(r.get("name"), r.get("url"))
        for a in gap.get("articles") or []:
            for n in a.get("rivals_in") or []:
                self._rival(n, None)
        ins = rep.get("ai_insights") or {}
        for lb in (ins.get("leaderboard"), (ins.get("niche") or {}).get("leaderboard"), ins.get("brand_ranking")):
            for r in (lb or {}).get("rows", []) + (lb or {}).get("all", []):
                if not r.get("is_target"):
                    self._rival(r.get("name"), None)
        own = ((rep.get("identity") or {}).get("aliases") or [])
        self.own_names = {hotel_identity.collapse(a.get("name", "")) for a in own} | {hotel_identity.collapse((rep.get("meta") or {}).get("hotel") or "")}
        self.own_domain = dom(((rep.get("meta") or {}).get("base")) or "")

    def _rival(self, name, url):
        if name:
            self.names.add(str(name))
        if url:
            self.urls[dom(url)] = name or ""

    def reason(self, domain, name=""):
        """'' when the site may be recommended; otherwise why it may not."""
        d = dom(domain)
        if not d:
            return ""
        if self.own_domain and (d == self.own_domain or d.endswith("." + self.own_domain)):
            return ""                                   # the hotel's own site is handled by the callers; it is not a competitor
        if is_chain_site(d):
            return "a hotel group's own website"
        if d in self.urls:
            return f"the website of {self.urls[d] or 'a rival hotel'}"
        for n in sorted(self.names):
            if name_matches_domain(n, d):
                return f"the website of {n}"
        if name:
            import rivals
            nf = "".join(rivals.tokens(name))
            for n in self.names:
                if len(nf) >= 8 and nf == "".join(rivals.tokens(n)):
                    return f"a source named after a rival hotel ({n})"
        return ""

    def rival_domains(self, domains=()):
        """Of these domains (and every rival URL known), which are a rival's own site? -> set"""
        out = set(self.urls)
        for d in domains or ():
            if self.reason(d):
                out.add(dom(d))
        return out


def excluded(rep):
    return Exclusions(rep)
