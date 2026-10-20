"""
Who counts as a competitor, and who is the same hotel written two ways.

The assistant names hotels in every answer. Two problems make a raw count misleading:

  * THE SAME HOTEL UNDER SEVERAL NAMES ('Hôtel de Crillon' / 'Crillon', 'Astor House' / 'Maison Astor'). resolve() groups names that are one hotel. Names that appear TOGETHER in one answer are different hotels
    (an assistant does not list one hotel twice), so they are never merged. A merge on a single shared distinctive word is flagged 'possibly the same hotel' and both names are shown.
  * HOTELS IN ANOTHER CATEGORY. A four-star business hotel is not competing with a palace hotel, however often the assistant names it. tier_of() places every named hotel on one ladder
    (budget, mid-range, upscale, luxury, palace) from the evidence available, in this order: the stars the assistant itself gave, the stars on the hotel's own site, the brand or a known palace name. relation()
    then says whether it is the same category, one step up (a stretch competitor), above (not comparable), below, or unknown. Only comparable rivals make a 'gap'.

Everything here is a rule on text the audit already holds: no extra requests and no cost. The reason for each placement is kept so the report can show it.
"""

import re

import ai_niche
import evidence

LADDER = {"budget": 1, "midscale": 2, "upscale": 3, "luxury": 4, "palace": 5}
LADDER_LABEL = {"budget": "budget", "midscale": "mid-range", "upscale": "upscale (4-star)", "luxury": "luxury (5-star)", "palace": "palace / ultra-luxury"}
# houses the market treats as palace or ultra-luxury, whatever the star rating says: a four-star hotel is not competing with them
PALACE = ("cheval blanc", "crillon", "le bristol", "plaza athenee", "shangri-la", "george v", "ritz", "le meurice", "meurice", "peninsula", "mandarin oriental", "royal monceau", "raffles", "lutetia",
          "four seasons", "aman", "bulgari", "rosewood", "st regis", "waldorf astoria", "claridge", "savoy", "dorchester", "connaught", "langham", "badrutt", "grand hotel du cap", "burj al arab", "belmond")
PALACE_FOLDED = tuple(" ".join(re.findall(r"[a-z0-9]+", p)) for p in PALACE)
_FLAVOUR = {"maison", "house", "residence", "residences", "suites", "palace", "lodge", "apartments", "boutique", "grand"}
_PARTICLES = {"de", "du", "des", "la", "le", "les", "the", "by", "and", "&", "at", "of", "hotel", "hotels", "hotel", "spa", "resort", "inn", "suites", "collection", "maison", "house", "residence", "residences",
              "grand", "palace", "boutique", "lodge", "apartments", "by", "autograph", "curio", "tapestry", "a", "an", "el", "il", "der", "die", "das", "von"}


def tokens(name, city=""):
    """The distinctive words of a hotel name: accents folded, generic and town words dropped ('Hôtel de Crillon, Paris' -> {'crillon'})."""
    place = {t for t in re.split(r"[^a-z0-9]+", evidence.fold((city or "").split(",")[0])) if t}
    return [t for t in re.split(r"[^a-z0-9]+", evidence.fold(name)) if t and t not in _PARTICLES and t not in place]


def resolve(by_answer, city=""):
    """
    by_answer: [(answer_id, [hotel names named in that answer])]. -> [{"key", "name", "names", "answers": set, "uncertain": bool}] one per hotel.
    Same distinctive words = same hotel; a name whose words are inside another's ('Crillon' in 'Hôtel de Crillon Paris') joins it; a merge on ONE shared word is kept but flagged; names that
    ever appear together in one answer are never merged.
    """
    groups = {}
    together = set()
    # two different names with the same distinctive words in ONE answer ('Maison Astor' and 'Astor House' listed side by side) are two hotels: they get separate groups from the start
    split = set()
    for _aid, names in by_answer:
        seen_k = {}
        for n in names:
            k = tuple(sorted(tokens(n, city)))
            fl = frozenset(t for t in re.split(r"[^a-z0-9]+", evidence.fold(n)) if t in _FLAVOUR)
            if k and k in seen_k and evidence.fold(n) != seen_k[k][0] and fl != seen_k[k][1]:
                split.add(k)
            seen_k.setdefault(k, (evidence.fold(n), fl))

    def ek(n):
        k = tuple(sorted(tokens(n, city)))
        return k + (("#" + evidence.fold(n),) if k in split else ())

    for aid, names in by_answer:
        keys = {ek(n) for n in names}
        keys.discard(())
        for a in keys:
            for b in keys:
                if a != b:
                    together.add((a, b))
        for n in names:
            k = ek(n)
            if not tuple(sorted(tokens(n, city))):
                continue
            g = groups.setdefault(k, {"key": " ".join(k), "names": {}, "answers": set(), "uncertain": False, "members": {k}, "flavours": set()})
            g["names"][n] = g["names"].get(n, 0) + 1
            fl = frozenset(t for t in re.split(r"[^a-z0-9]+", evidence.fold(n)) if t in _FLAVOUR)
            if fl:
                g["flavours"].add(fl)
            g["uncertain"] = len(g["flavours"]) > 1          # 'Maison Astor' and 'Astor House' share every distinctive word but not the kind of house: probably one hotel, not certain
            g["answers"].add(aid)
    merged = True
    while merged:
        merged = False
        ks = sorted(groups, key=lambda k: (-len(k), k))
        for a in ks:
            if a not in groups:
                continue
            for b in ks:
                if b == a or b not in groups or a not in groups:
                    continue
                if any((x, y) in together for x in groups[a]["members"] for y in groups[b]["members"]):
                    continue
                sa, sb = {t for t in a if not t.startswith("#")}, {t for t in b if not t.startswith("#")}
                inside = sb <= sa and (len(sb) >= 2 or (len(sb) == 1 and len(next(iter(sb))) >= 5))
                shared_one = len(sa & sb) == 1 and len(sa) <= 2 and len(sb) <= 2 and len(next(iter(sa & sb))) >= 5 and not inside
                if inside or shared_one:
                    hi, lo = groups[a], groups.pop(b)
                    for n, c in lo["names"].items():
                        hi["names"][n] = hi["names"].get(n, 0) + c
                    hi["answers"] |= lo["answers"]
                    hi["members"] |= lo["members"]
                    hi["flavours"] |= lo["flavours"]
                    hi["uncertain"] = hi["uncertain"] or shared_one or lo["uncertain"] or len(hi["flavours"]) > 1
                    merged = True
    out = []
    for g in groups.values():
        names = sorted(g["names"], key=lambda n: (-g["names"][n], -len(n), n))
        out.append({"key": g["key"], "name": names[0], "names": names, "answers": g["answers"], "uncertain": g["uncertain"]})
    return out


def _key_for(name, city=""):
    return " ".join(sorted(tokens(name, city)))


def tier_of(name, stars_said=None, site_stars=None):
    """
    -> {"key": ladder key | None, "label", "source", "why"}. The stars the assistant gave, then the stars on the hotel's own site, then a known palace house or the brand's usual level; otherwise unknown.
    A five-star hotel is 'luxury' unless it is a known palace house.
    """
    fold = " " + " ".join(re.findall(r"[a-z0-9]+", evidence.fold(name))) + " "
    palace = next((p for p in PALACE_FOLDED if f" {p} " in fold), None)
    for stars, src in ((stars_said, "the assistant called it"), (site_stars, "its own site says")):
        if stars:
            key = "luxury" if stars >= 5 else "upscale" if stars == 4 else "midscale" if stars == 3 else "budget"
            if key == "luxury" and palace:
                return {"key": "palace", "label": LADDER_LABEL["palace"], "source": src, "why": f"{src} {stars}-star, and {palace.title()} is a palace-category house"}
            return {"key": key, "label": LADDER_LABEL[key], "source": src, "why": f"{src} {stars}-star"}
    if palace:
        return {"key": "palace", "label": LADDER_LABEL["palace"], "source": "a known palace house", "why": f"{palace.title()} is a palace-category house"}
    hay = " " + ai_niche._fold_words(name) + " "
    for key, brands in ai_niche.BRAND_TIERS:
        hit = next((b for b in brands if f" {b} " in hay), None)
        if hit:
            k = {"luxury": "luxury"}.get(key, key)
            return {"key": k, "label": LADDER_LABEL[k], "source": "its brand", "why": f"{hit} is usually {LADDER_LABEL[k]} (an inference from the brand)"}
    return {"key": None, "label": "category not known", "source": "", "why": "no star rating or brand level was available"}


def relation(hotel_tier_key, rival_tier_key):
    """'same', 'one_up' (a stretch competitor), 'above' (not comparable), 'one_down', 'below' (not comparable) or 'unknown'."""
    if hotel_tier_key not in LADDER or rival_tier_key not in LADDER:
        return "unknown"
    d = LADDER[rival_tier_key] - LADDER[hotel_tier_key]
    return "same" if d == 0 else "one_up" if d == 1 else "above" if d > 1 else "one_down" if d == -1 else "below"


COMPARABLE = ("same", "one_up", "one_down", "unknown")
RELATION_LABEL = {"same": "same category", "one_up": "one step up (a stretch competitor)", "above": "a higher category (not comparable)", "one_down": "one step down", "below": "a lower category (not comparable)",
                  "unknown": "category not known"}
