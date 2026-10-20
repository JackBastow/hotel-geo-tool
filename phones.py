"""
Telephone numbers, read properly.

A string of digits is not automatically a telephone number, and two different numbers are not automatically a contradiction. This module (using the free `phonenumbers` library, the same rules phones use)
answers three questions that the audit used to answer with string tricks:

  parse(raw, region)      is this a real, valid number, and what kind (landline, mobile, freephone)?
  same(a, b)              are these two the same number written differently (spaces, +33 / 0033 / 0, a trailing extension or stray digits)?
  is_central_line(info)   is it a freephone or shared-cost line (a chain's central reservations number, such as a US 1-844 number on a Paris hotel's listing)? Such a line is normally NOT the hotel's own
                          number, so it never contradicts the number on the hotel's site.

If the library is missing the functions fall back to plain digit rules and say so (valid is None), so nothing breaks and nothing is claimed that cannot be.
"""

import re

try:
    import phonenumbers
    from phonenumbers import PhoneNumberType as _T
except ImportError:  # pragma: no cover - the library is in requirements
    phonenumbers = None
    _T = None

_TLD_REGION = {"uk": "GB", "fr": "FR", "de": "DE", "es": "ES", "it": "IT", "nl": "NL", "be": "BE", "ch": "CH", "at": "AT", "ie": "IE", "pt": "PT", "se": "SE", "no": "NO", "dk": "DK", "fi": "FI",
               "pl": "PL", "cz": "CZ", "gr": "GR", "tr": "TR", "ae": "AE", "au": "AU", "nz": "NZ", "jp": "JP", "sg": "SG", "hk": "HK", "za": "ZA", "in": "IN", "br": "BR", "mx": "MX", "ca": "CA"}
_CENTRAL = None if _T is None else {_T.TOLL_FREE, _T.SHARED_COST, _T.UAN}


def region_from_host(host):
    """A country code from a website's ending ('.co.uk' -> 'GB'), or None for .com and the like."""
    tld = (host or "").lower().rstrip("/").rsplit(".", 1)[-1]
    return _TLD_REGION.get(tld)


def parse(raw, region=None):
    """
    -> {"e164", "digits", "cc", "region", "valid", "central", "kind"} or None when it cannot be a number at all.
    A leading + or 00 is read as an international prefix; a string of 11 or more digits is tried as international first; otherwise `region` (a country code such as 'FR') is used.
    """
    s = re.sub(r"[^\d+]", "", str(raw or ""))
    if not s or len(re.sub(r"\D", "", s)) < 7:
        return None
    if s.startswith("00"):
        s = "+" + s[2:]
    if phonenumbers is None:
        d = re.sub(r"\D", "", s)
        return {"e164": "+" + d.lstrip("0"), "digits": d, "cc": None, "region": region, "valid": None, "central": False, "kind": "unknown"} if 9 <= len(d) <= 15 else None
    tries = []
    if s.startswith("+"):
        tries.append((s, None))
    else:
        if len(s) >= 11:
            tries.append(("+" + s, None))
        if region:
            tries.append((s, region))
    best = None
    for text, reg in tries:
        try:
            n = phonenumbers.parse(text, reg)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(n):
            best = n
            break
    if best is None:
        return None
    t = phonenumbers.number_type(best)
    return {"e164": phonenumbers.format_number(best, phonenumbers.PhoneNumberFormat.E164), "digits": re.sub(r"\D", "", phonenumbers.format_number(best, phonenumbers.PhoneNumberFormat.E164)),
            "cc": best.country_code, "region": phonenumbers.region_code_for_number(best), "valid": True, "central": t in _CENTRAL, "kind": {_T.MOBILE: "mobile", _T.FIXED_LINE: "landline"}.get(t, "other")}


def same(a, b):
    """Are two parsed numbers the same line? Equal, or one is the other with stray digits after it (an extension or a run-together neighbour)."""
    if not a or not b:
        return False
    x, y = a["digits"], b["digits"]
    return x == y or (min(len(x), len(y)) >= 10 and (x.startswith(y) or y.startswith(x)))


def compare(site_raw, listing_raw, region=None):
    """
    The hotel's own number against a number shown on another site. -> 'same' | 'different' | 'not_comparable' (with the reason in the second item).
    Not comparable when either is not a valid number, or when the listing shows a freephone / shared-cost line of another country or kind (a chain's central reservations number): that is a
    different line by design, not a contradiction.
    """
    a, b = parse(site_raw, region), parse(listing_raw, region)
    if b is None and listing_raw:
        # stray digits after a real number ('3314483404077'): try the longest valid prefix
        d = re.sub(r"\D", "", str(listing_raw))
        for cut in range(len(d) - 1, 9, -1):
            b = parse(d[:cut], region)
            if b:
                break
    if a is None or b is None:
        return "not_comparable", "one of the numbers is not a valid telephone number"
    if same(a, b):
        return "same", ""
    if b["central"] and not a["central"]:
        return "not_comparable", "the other site shows a freephone or central-reservations line, which is not the hotel's own number"
    if a["central"] and not b["central"]:
        return "not_comparable", "the hotel's site shows a freephone or central line; the other site shows a direct number"
    return "different", ""
