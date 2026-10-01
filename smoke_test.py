#!/usr/bin/env python3
"""
Live API smoke test - run this before trusting any audit numbers.

The point of this script is to answer, against a real key and a real call:

  1. Does /v1beta/interactions work, and with which model?
  2. Does the legacy :generateContent + google_search fallback still work?
  3. Does the answer text parse out?
  4. Do citations parse out?
  5. Do the search queries the model issued parse out?
  6. Does the Search Suggestions HTML actually come back? (Google's grounding
     terms require it to be displayed alongside grounded results.)

It makes 1-2 grounded calls, not 40, so it costs almost nothing to run.

Usage:
  set GEMINI_API_KEY=...          (Windows)
  export GEMINI_API_KEY=...       (bash)
  python smoke_test.py
  python smoke_test.py --model gemini-3.5-flash --raw
"""

import argparse
import json
import os
import sys

import gemini_client
from gemini_client import GeminiClient, GeminiError, find_search_suggestions

PROBE = "What are the best hotels in Weybridge, Surrey?"


def _mark(ok):
    return "PASS" if ok else "FAIL"


def try_transport(client, mode, query, show_raw=False):
    """Force one specific transport and report exactly what came back."""
    print(f"\n{'=' * 66}\n  {mode}  (model: {client.model})\n{'=' * 66}")
    client.mode = mode
    try:
        res = client.ask_grounded(query)
    except Exception as e:  # noqa: BLE001 - we want the real error visible
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        return None

    if not res["ok"]:
        print(f"  FAILED: {res.get('error')}")
        return None

    raw = res.get("raw", {})
    answer = res.get("answer", "")
    cites = res.get("citations", [])
    queries = res.get("search_queries", [])
    sugg = res.get("search_suggestions_html", "")

    print(f"  transport works ............ PASS")
    print(f"  answer text parsed ......... {_mark(bool(answer.strip()))} "
          f"({len(answer)} chars)")
    print(f"  citations parsed ........... {_mark(bool(cites))} ({len(cites)})")
    print(f"  search queries parsed ...... {_mark(bool(queries))} ({len(queries)})")
    print(f"  search suggestions HTML .... {_mark(bool(sugg))} ({len(sugg)} chars)")

    if isinstance(raw, dict):
        print(f"  raw top-level keys ......... {sorted(raw.keys())}")
        if "steps" in raw:
            print(f"  step types ................. "
                  f"{[s.get('type') for s in raw['steps'] if isinstance(s, dict)]}")

    print(f"\n  --- answer (first 400 chars) ---\n  {answer[:400]!r}")
    if queries:
        print(f"\n  --- search queries issued ---")
        for q in queries:
            print(f"    - {q}")
    if cites:
        print(f"\n  --- citations (first 8) ---")
        for c in cites[:8]:
            print(f"    - {c.get('title', '')!r} {c.get('url', '')}")
    if sugg:
        print(f"\n  --- search suggestions HTML (first 200 chars) ---\n"
              f"  {sugg[:200]!r}")
    else:
        print("\n  WARNING: no Search Suggestions HTML found. Google's grounding "
              "terms\n  require these to be shown with grounded results - if this "
              "stays empty,\n  find out why before shipping any report.")

    if show_raw:
        print(f"\n  --- FULL RAW RESPONSE ---")
        print(json.dumps(raw, indent=2)[:12000])

    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=gemini_client.DEFAULT_MODEL)
    p.add_argument("--query", default=PROBE)
    p.add_argument("--raw", action="store_true", help="dump the full JSON response")
    p.add_argument("--mode", choices=["interactions", "generate", "both"],
                   default="both")
    a = p.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("No GEMINI_API_KEY set in the environment.")
        return 2

    print(f"Query: {a.query}")
    results = {}
    modes = ["interactions", "generate"] if a.mode == "both" else [a.mode]
    for mode in modes:
        client = GeminiClient(model=a.model, pause=0.5, verbose=True)
        results[mode] = try_transport(client, mode, a.query, show_raw=a.raw)

    print(f"\n{'=' * 66}\n  VERDICT\n{'=' * 66}")
    working = [m for m, r in results.items() if r]
    for mode in modes:
        r = results.get(mode)
        if not r:
            print(f"  {mode:<14} does not work")
        else:
            print(f"  {mode:<14} works | answer={_mark(bool(r['answer'].strip()))} "
                  f"cites={len(r['citations'])} "
                  f"queries={len(r['search_queries'])} "
                  f"suggestions={_mark(bool(r['search_suggestions_html']))}")
    if not working:
        print("\n  Neither transport works. Do not run a full audit.")
        return 1
    print(f"\n  Use: {working[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
