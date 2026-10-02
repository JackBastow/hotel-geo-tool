"""
Small, dependency-free language identification for article and review text.

Uses common function words, which are very distinctive per language and need
no model. It is deliberately conservative: it returns None for short or
ambiguous text rather than guess. It identifies the LANGUAGE OF THE TEXT
only - never anyone's nationality.
"""

import re

_WORDS = {
    "en": "the and of to in is that for it with as was on are this be at by from or have had not but they you we our your their which will can has".split(),
    "fr": "le la les des du de et en un une est que pour dans qui sur au aux avec ce cette pas par plus nous vous sont ses son sa il elle ou mais".split(),
    "de": "der die das und ist nicht mit den dem ein eine zu von auf für im sich auch es als wir sie wird sind aber nach bei oder aus".split(),
    "es": "el la los las de que y en un una es por con para su al lo como más pero sus le ya o este sí porque esta entre cuando muy".split(),
    "it": "il lo la i gli le di che e un una è per con non su sono del della dei alla come più ma anche si da nel nella al suo sua".split(),
    "nl": "de het een en van ik te dat die in is niet op aan met als voor zijn er maar om ook dan bij uit nog wel naar hebben wij".split(),
    "pt": "o a os as de que e do da em um uma para com não é por mais dos das como mas foi ao ele se na no seu sua ou ser".split(),
}
_SETS = {k: set(v) for k, v in _WORDS.items()}
NAMES = {"en": "English", "fr": "French", "de": "German", "es": "Spanish",
         "it": "Italian", "nl": "Dutch", "pt": "Portuguese"}


def detect(text, min_words=25):
    """-> (code or None, confidence 0..1). Confidence is the winner's share."""
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    if len(words) < min_words:
        return None, 0.0
    sample = words[:600]
    scores = {k: sum(1 for w in sample if w in s) for k, s in _SETS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, second = ranked[0], ranked[1]
    if top[1] < 6 or top[1] < second[1] * 1.3:
        return None, 0.0
    total = sum(scores.values()) or 1
    return top[0], round(top[1] / total, 2)


def name(code):
    return NAMES.get(code, code or "unknown")
