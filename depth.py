"""
How thorough the AI test is.

standard   what a weekly check uses: the hotel's core market prompts asked a few times each. Cheaper and quicker, enough to see change from week to week.
deep       what a manual or demo audit uses: more prompts, of more kinds (short searches, conversational requests, occasion-based ones), each asked more times, so the coverage figure rests on many answers and one
           lucky or unlucky answer matters less.

The same prompts are asked every time within a depth, and a hotel's benchmark prompts (frozen at its first audit) are always asked again word for word, so a later audit stays comparable.
"""

DEPTHS = {
    "standard": {"generic_questions": 8, "repeats": 2, "core": 14, "secondary": 8, "proposals": 8, "core_extra": 1, "core_cap": 4, "variants": 0, "budget_generic": 1.6, "budget_niche": 3.0, "workers": 3,
                 "reserve_millidollars": 4000},
    "deep": {"generic_questions": 12, "repeats": 3, "core": 20, "secondary": 18, "proposals": 14, "core_extra": 2, "core_cap": 5, "variants": 8, "budget_generic": 3.0, "budget_niche": 9.0, "workers": 6,
             "reserve_millidollars": 12000},
}
DEFAULT = "standard"


def limits(name):
    return DEPTHS.get(name) or DEPTHS[DEFAULT]


def clean(name):
    return name if name in DEPTHS else DEFAULT
