#!/usr/bin/env python3
"""
Free, UNGROUNDED Gemini text-judging - reads text already fetched by
tavily_check.py and judges it properly, instead of crude keyword rules.

CRITICAL DISTINCTION FROM gemini_client.py / AI VISIBILITY - READ THIS FIRST
-----------------------------------------------------------------------------
This module NEVER uses Google Search grounding. It makes a plain
`generateContent` call with no `tools` field at all - just "here is some text,
judge it." That is the free-tier-friendly path: verified live (2026-10) that
ordinary ungrounded Gemini calls return 200 on a free-tier project, while
EVERY grounded call (the one AI Visibility uses, via gemini_client.py) returns
429 without a billing-enabled project. Those are two different API calls with
two different cost profiles, not two settings on the same one.

Do not add a `tools` field here. Do not import anything from gemini_client.py
that constructs a grounded request. If this module's cost profile ever needs
reconsidering, that is a sign something has been wired together that
shouldn't be - the whole reason this exists as a separate module is so the
free reading layer and the paid grounding layer can never accidentally merge.

WHAT THIS BUYS
--------------
tavily_check.py's rule-based `_judge()` can tell you a domain appeared and
count words near the hotel's name. It cannot tell you that an article is
glowing but mentions a tired-looking spa, or that a "mention" is actually a
different hotel with a similar name. A live test of this exact call,
real article text, genuinely answered that in one request, for free:

    {"confirmed": true, "substance": "feature", "sentiment": "positive",
     "one_line_summary": "A highly recommended, modern hotel with excellent
     dining and service, despite a slightly tired-looking spa area."}

No key -> "not configured". Never raises for a missing key - the caller
(tavily_check.py) falls back to its own rule-based judgment instead.

Usage:
  export GEMINI_API_KEY=...
  python gemini_reader.py --hotel "Brooklands Hotel" --text "..."
"""

import argparse
import json
import os
import re
import sys
import time

import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

# Deliberately NOT gemini_client.DEFAULT_MODEL (gemini-3.8-flash) - that model
# returned intermittent 503 "high demand" errors during testing this session.
# This is a background judging call where reliability matters more than
# having the newest model, so a steadier one is the better default.
DEFAULT_READER_MODEL = "gemini-3.5-flash"

JUDGE_PROMPT = """You are judging whether a piece of text is genuine editorial \
or social coverage of a specific hotel. Do not add information. Only describe \
what the text actually says.

HOTEL: {hotel}

TEXT:
\"\"\"
{text}
\"\"\"

Return ONLY a JSON object:
{{
  "confirmed": true or false,
  "substance": "feature" or "substantial mention" or "passing mention",
  "sentiment": "positive" or "neutral" or "negative",
  "one_line_summary": "one short sentence summarising what this source says about the hotel"
}}

Rules:
- "confirmed" is false if the text is clearly about a different hotel, or
  does not mention this hotel at all (allowing for minor name variation).
- "feature" = a substantial piece largely about this hotel.
- "substantial mention" = several sentences of real content about it.
- "passing mention" = named once in a list or aside, nothing more.
- Judge sentiment only from what the text actually says, not from assumption.
"""


class ReaderError(RuntimeError):
    pass


def has_key(api_key=None):
    return bool(api_key or os.environ.get("GEMINI_API_KEY"))


def _find_json(text):
    """Pull the first JSON object out of a model response. Same approach as
    gemini_client.py's helper of the same name, kept separate on purpose -
    see the module docstring for why this file imports nothing from there."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def judge(text, hotel, api_key=None, model=None, timeout=30, attempts=3):
    """
    Returns a dict in the same shape as tavily_check.py's rule-based
    `_judge()`, or None if the call failed - the caller falls back to the
    rule-based version in that case, never raises.

    Retries on 429/500/502/503/504 with a short backoff - verified live that
    gemini-3.5-flash returns genuine 503 "currently experiencing high demand"
    under ordinary load, the same transient overload seen on other Gemini
    models elsewhere in this project (gemini_client.py retries the same set
    of codes for exactly this reason). Without a retry here, a single
    transient 503 silently downgrades a read to the weaker rule-based
    fallback for no real reason.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key or not text:
        return None
    model = model or DEFAULT_READER_MODEL
    prompt = JUDGE_PROMPT.format(hotel=hotel, text=text[:6000])

    r = None
    delay = 3
    for attempt in range(attempts):
        try:
            r = requests.post(
                f"{API_ROOT}/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                # No "tools" field - this is the plain, ungrounded, free-tier call.
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=timeout,
            )
        except requests.RequestException:
            return None
        if r.status_code == 200:
            break
        if r.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
            time.sleep(delay)
            delay *= 2
            continue
        return None
    else:
        return None
    if r is None or r.status_code != 200:
        return None

    try:
        data = r.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        return None
    parsed = _find_json(raw_text)
    if not parsed:
        return None
    return {
        "confirmed": parsed.get("confirmed"),
        "substance": parsed.get("substance", "unknown"),
        "sentiment": parsed.get("sentiment", "unknown"),
        "excerpt": parsed.get("one_line_summary", ""),
        "via": "llm",
    }


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hotel", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--model", default=DEFAULT_READER_MODEL)
    a = p.parse_args()
    if not has_key():
        print("No GEMINI_API_KEY set.")
        return 2
    result = judge(a.text, a.hotel, model=a.model)
    print(json.dumps(result, indent=2) if result else "call failed")
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
