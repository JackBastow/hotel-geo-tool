#!/usr/bin/env python3
"""
Hotel AI discoverability audit - AI visibility measurement module.

Runs a fixed query set through Gemini with Google Search grounding and
records, for every query: the answer text, the sources cited, and the
search queries the model actually issued.

Everything downstream is computed from that stored evidence. Nothing is
asserted that the raw log does not support. Failed calls are recorded as
failures and excluded from rates, never counted as a negative result.

Usage:
  export GEMINI_API_KEY=...
  python3 audit.py --hotel "Brooklands Hotel" \
                   --website brooklandshotelsurrey.com \
                   --city "Weybridge, Surrey" \
                   --landmarks "Brooklands Museum,Mercedes-Benz World" \
                   --out brooklands.json
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from gemini_client import GeminiClient, resolve_domain
import queryset


# ---------------------------------------------------------------- extraction

DISCOVERY_EXTRACT = """You are extracting structured data from an AI assistant's answer. \
Do not add information. Do not use outside knowledge. Only describe what the answer below says.

QUESTION ASKED: {query}

ANSWER:
\"\"\"
{answer}
\"\"\"

TARGET HOTEL: {hotel}

Return ONLY a JSON object:
{{
  "hotels_named": ["exact hotel names in the order they first appear in the answer"],
  "target_present": true or false,
  "target_position": integer 1-based index into hotels_named, or null,
  "target_treatment": "recommended" or "mentioned" or "absent",
  "target_reasons": ["short reasons the answer gives for the target hotel, if any"]
}}

Rules:
- "recommended" means the answer puts it forward as a suggestion or pick.
- "mentioned" means it appears only in passing, as context, or unfavourably.
- Count the target as present if the answer names it, allowing for minor
  wording differences in the hotel's name.
- Do not list hotels that are not named in the answer.
"""

BRANDED_EXTRACT = """You are extracting structured data from an AI assistant's answer. \
Do not add information. Do not use outside knowledge. Only describe what the answer below says.

QUESTION ASKED: {query}

ANSWER:
\"\"\"
{answer}
\"\"\"

Return ONLY a JSON object:
{{
  "answered": true or false,
  "confidence": "confident" or "hedged" or "unable",
  "key_fact": "the specific factual answer given, in one short line, or empty string",
  "caveats": ["any hedging the answer uses, e.g. 'check with the hotel'"]
}}

Rules:
- "confident" = a specific, usable factual answer with no significant hedging.
- "hedged" = an answer is given but qualified, vague, or tells the reader to verify.
- "unable" = the answer says it does not know or cannot find the information.
- "answered" is false only when confidence is "unable".
"""


# ------------------------------------------------------------------- running

def _run_one(client, q, kind, hotel, domain, verbose):
    """One query end to end: grounded search + structured extraction."""
    print(f"  [{kind}] {q}")
    res = client.ask_grounded(q)
    row = {
        "kind": kind,
        "query": q,
        "ok": res["ok"],
        "error": res.get("error"),
        "answer": res.get("answer", ""),
        "citations": res.get("citations", []),
        "search_queries": res.get("search_queries", []),
        "search_suggestions_html": res.get("search_suggestions_html", ""),
    }
    if not res["ok"]:
        print(f"      FAILED: {res.get('error')}")
        return row

    row["cited_domains"] = sorted(
        {resolve_domain(c["url"]) for c in row["citations"] if c.get("url")}
    )
    row["first_party_cited"] = any(
        domain and (d == domain or d.endswith("." + domain))
        for d in row["cited_domains"]
    )
    row["literal_name_hit"] = _literal_hit(row["answer"], hotel)

    prompt = (
        DISCOVERY_EXTRACT.format(query=q, answer=row["answer"], hotel=hotel)
        if kind == "discovery"
        else BRANDED_EXTRACT.format(query=q, answer=row["answer"])
    )
    row["extract"] = client.extract_json(prompt)
    if row["extract"] is None:
        print("      (extraction failed - row kept, excluded from rates)")

    if kind == "discovery" and row["extract"]:
        mp = row["extract"].get("target_present")
        if isinstance(mp, bool) and mp != row["literal_name_hit"]:
            row["extraction_disagreement"] = True
            print(
                f"      note: model says present={mp}, "
                f"literal match={row['literal_name_hit']} - flagged"
            )
    return row


def run_set(client, queries, kind, hotel, domain, verbose=True, progress=None,
            offset=0, total=None, checkpoint=None, workers=3):
    """
    Runs `queries` with up to `workers` concurrent in flight. This is the
    single biggest lever on wall-clock time: each query is dominated by
    model latency (real search + generation, commonly 10-30s), not by
    anything CPU-bound, so a handful of threads waiting on network I/O in
    parallel cuts total time roughly in proportion to `workers` without
    hitting free-tier limits any harder than the existing retry/backoff
    logic already handles.

    Order of completion is not the order of submission with concurrency>1,
    so results are re-sorted back into query order at the end - this keeps
    output deterministic and comparable run to run.
    """
    total = total or len(queries)
    done_count = [0]  # mutable cell, threads increment under lock
    lock = threading.Lock()
    results = {}

    def worker(i, q):
        row = _run_one(client, q, kind, hotel, domain, verbose)
        with lock:
            results[i] = row
            done_count[0] += 1
            n = done_count[0]
            if progress:
                progress(offset + n, total, f"{kind}: {q}")
            if checkpoint:
                # ordered snapshot of everything completed so far, across
                # both sets - checkpoint doesn't need to be gap-free.
                checkpoint([results[k] for k in sorted(results)])
        return row

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = [ex.submit(worker, i, q) for i, q in enumerate(queries)]
        for f in as_completed(futures):
            f.result()  # re-raise any worker exception now, not silently

    return [results[i] for i in sorted(results)]


def _literal_hit(answer, hotel):
    """Loose literal check: all significant words of the hotel name present."""
    if not answer:
        return False
    a = answer.lower()
    stop = {"the", "hotel", "and", "&", "spa", "resort", "inn", "house"}
    words = [w for w in re.findall(r"[a-z0-9]+", hotel.lower()) if w not in stop]
    if not words:
        return hotel.lower() in a
    return all(w in a for w in words)


# ------------------------------------------------------------------- metrics

def compute_metrics(rows, hotel):
    disc = [r for r in rows if r["kind"] == "discovery" and r["ok"] and r.get("extract")]
    brand = [r for r in rows if r["kind"] == "branded" and r["ok"] and r.get("extract")]
    all_ok = [r for r in rows if r["ok"]]

    m = {
        "queries_attempted": len(rows),
        "queries_succeeded": len(all_ok),
        "queries_failed": len(rows) - len(all_ok),
        "discovery_analysed": len(disc),
        "branded_analysed": len(brand),
    }

    # --- discovery / visibility
    if disc:
        present = [r for r in disc if r["extract"].get("target_present")]
        top3 = [
            r for r in present
            if isinstance(r["extract"].get("target_position"), int)
            and r["extract"]["target_position"] <= 3
        ]
        rec = [r for r in present if r["extract"].get("target_treatment") == "recommended"]
        m["mention_rate"] = round(len(present) / len(disc), 3)
        m["top3_rate"] = round(len(top3) / len(disc), 3)
        m["recommendation_rate"] = round(len(rec) / len(disc), 3)
        m["mention_count"] = len(present)

        # share of voice across every hotel named in the discovery answers
        names = Counter()
        for r in disc:
            for n in r["extract"].get("hotels_named", []) or []:
                names[_norm(n)] += 1
        total = sum(names.values())
        tgt = names.get(_norm(hotel), 0)
        m["share_of_voice"] = round(tgt / total, 3) if total else 0.0
        m["total_hotel_mentions_in_set"] = total
        m["competitor_frequency"] = [
            {"hotel": n, "appearances": c}
            for n, c in names.most_common(20)
            if _norm(n) != _norm(hotel)
        ]
        m["reasons_given"] = [
            reason
            for r in present
            for reason in (r["extract"].get("target_reasons") or [])
        ]

    # --- branded / answerability
    if brand:
        answered = [r for r in brand if r["extract"].get("answered")]
        confident = [r for r in brand if r["extract"].get("confidence") == "confident"]
        m["branded_answered_rate"] = round(len(answered) / len(brand), 3)
        m["branded_confident_rate"] = round(len(confident) / len(brand), 3)
        m["branded_unanswered"] = [
            {"query": r["query"], "confidence": r["extract"].get("confidence")}
            for r in brand
            if not r["extract"].get("answered")
            or r["extract"].get("confidence") != "confident"
        ]

    # --- citations
    if all_ok:
        fp = [r for r in all_ok if r.get("first_party_cited")]
        m["first_party_citation_rate"] = round(len(fp) / len(all_ok), 3)
        dom = Counter()
        for r in all_ok:
            for d in r.get("cited_domains", []):
                dom[d] += 1
        m["top_cited_domains"] = [
            {"domain": d, "queries_citing": c} for d, c in dom.most_common(25)
        ]
        # the interesting gap: answered about this hotel, without its own site
        brand_ok = [r for r in all_ok if r["kind"] == "branded"]
        if brand_ok:
            m["branded_first_party_citation_rate"] = round(
                sum(1 for r in brand_ok if r.get("first_party_cited")) / len(brand_ok), 3
            )
    return m


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# -------------------------------------------------------------------- output

def write_markdown(payload, path):
    m = payload["metrics"]
    meta = payload["meta"]
    L = []
    A = L.append
    A(f"# AI visibility test log - {meta['hotel']}")
    A("")
    A(f"- **Hotel:** {meta['hotel']}")
    A(f"- **City:** {meta['city']}")
    A(f"- **Website:** {meta['website']} (domain matched: `{meta['domain']}`)")
    A(f"- **Tested:** {meta['run_at']}")
    A(f"- **Engine:** Gemini `{meta['model']}` with Google Search grounding, "
      f"via `{meta['api_mode']}`")
    A("")
    A("> **Scope of this measurement.** These are OBSERVED results from a "
      "controlled test set run against one grounded AI engine on the date "
      "above. They are not a measure of consumer traffic on ChatGPT, Gemini, "
      "Copilot or any other assistant, and an API answer is not identical to "
      "what a consumer sees in those apps. Treat as a directional indicator.")
    A("")
    A("## Coverage")
    A("")
    A(f"- Queries attempted: **{m['queries_attempted']}**")
    A(f"- Succeeded: **{m['queries_succeeded']}** | Failed: **{m['queries_failed']}**")
    A(f"- Discovery queries analysed: **{m.get('discovery_analysed', 0)}**")
    A(f"- Branded queries analysed: **{m.get('branded_analysed', 0)}**")
    A("")
    if "mention_rate" in m:
        A("## AI visibility (unbranded discovery queries)")
        A("")
        A("| Metric | Value |")
        A("|---|---|")
        A(f"| Mention rate | {_pct(m['mention_rate'])} |")
        A(f"| Top-3 rate | {_pct(m['top3_rate'])} |")
        A(f"| Recommendation rate | {_pct(m['recommendation_rate'])} |")
        A(f"| Share of voice | {_pct(m['share_of_voice'])} |")
        A("")
        if m.get("competitor_frequency"):
            A("### Hotels appearing most often in the same answers")
            A("")
            A("| Hotel | Answers naming it |")
            A("|---|---|")
            for c in m["competitor_frequency"][:15]:
                A(f"| {c['hotel']} | {c['appearances']} |")
            A("")
    if "branded_confident_rate" in m:
        A("## AI answerability (branded questions)")
        A("")
        A(f"- Answered at all: **{_pct(m['branded_answered_rate'])}**")
        A(f"- Answered confidently: **{_pct(m['branded_confident_rate'])}**")
        if "branded_first_party_citation_rate" in m:
            A(f"- Answered citing the hotel's own site: "
              f"**{_pct(m['branded_first_party_citation_rate'])}**")
        A("")
        if m.get("branded_unanswered"):
            A("### Questions not confidently answered")
            A("")
            for u in m["branded_unanswered"]:
                A(f"- {u['query']}  _({u['confidence']})_")
            A("")
    if m.get("top_cited_domains"):
        A("## Sources the engine actually cited")
        A("")
        A(f"First-party citation rate across all queries: "
          f"**{_pct(m.get('first_party_citation_rate', 0))}**")
        A("")
        A("| Domain | Queries citing it |")
        A("|---|---|")
        for d in m["top_cited_domains"][:20]:
            mark = " **(first-party)**" if d["domain"] == meta["domain"] else ""
            A(f"| {d['domain']}{mark} | {d['queries_citing']} |")
        A("")
    A("## Evidence")
    A("")
    A(f"Full answer text, citation URLs and the search queries the engine "
      f"issued are stored for every query in `{os.path.basename(payload['meta']['json_path'])}`.")
    with open(path, "w") as f:
        f.write("\n".join(L))


def _pct(v):
    return f"{round(v * 100)}%"



# --------------------------------------------------------------- orchestrator

def run_full(hotel, website, city, brand="", landmarks=None, extra_discovery=None,
             model="gemini-3.8-flash", pause=1.0, workers=3, api_key=None, limit=0,
             progress=None, verbose=True, on_checkpoint=None):
    """
    Importable entry point used by the Streamlit app and the background
    thread it starts.
    `progress(done, total, label)` is called as each query completes.
    `on_checkpoint(partial_payload)` is called after every query completes,
    so a long run can be saved incrementally rather than losing everything
    if the process is interrupted. verbose defaults True: print() is the
    only place retry/error diagnostics are visible when this runs behind a
    GUI, so it must not be silenced by default.
    `workers` queries run concurrently - see run_set() for why this is the
    main lever on wall-clock time.
    Returns the same payload structure the CLI writes to JSON.
    """
    domain = resolve_domain(website)
    disc_q = queryset.build_discovery(city, landmarks or [], extra_discovery or [])
    brand_q = queryset.build_branded(hotel, city)
    if limit:
        disc_q, brand_q = disc_q[:limit], brand_q[:limit]
    total = len(disc_q) + len(brand_q)

    client = GeminiClient(api_key=api_key, model=model, pause=pause, verbose=verbose)

    prior_rows = []  # completed sets, so checkpoints during set 2 still include set 1

    def _checkpoint(current_set_rows):
        if on_checkpoint:
            on_checkpoint(_build_payload(
                hotel, brand, city, website, domain, model, client.mode,
                prior_rows + current_set_rows, partial=True,
            ))

    disc_rows = run_set(client, disc_q, "discovery", hotel, domain, verbose=verbose,
                        progress=progress, offset=0, total=total,
                        checkpoint=_checkpoint, workers=workers)
    prior_rows = disc_rows
    brand_rows = run_set(client, brand_q, "branded", hotel, domain, verbose=verbose,
                         progress=progress, offset=len(disc_q), total=total,
                         checkpoint=_checkpoint, workers=workers)
    rows = disc_rows + brand_rows

    metrics = compute_metrics(rows, hotel)
    suggestions = next(
        (r["search_suggestions_html"] for r in rows
         if r.get("search_suggestions_html")), ""
    )
    payload = _build_payload(hotel, brand, city, website, domain, model,
                              client.mode, rows, partial=False)
    payload["metrics"] = metrics
    payload["search_suggestions_html"] = suggestions
    return payload


def _build_payload(hotel, brand, city, website, domain, model, api_mode, rows,
                    partial=False):
    ok_rows = [r for r in rows if r.get("ok")]
    return {
        "meta": {
            "hotel": hotel, "brand": brand, "city": city, "website": website,
            "domain": domain,
            "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "model": model, "api_mode": api_mode,
            "grounded_calls": len(ok_rows),
            # Gemini 3 bills per search query the model CHOOSES to run, not per
            # request - one question can trigger several. Counting requests
            # therefore undercounts the billed figure, sometimes badly. This is
            # the number to track quota against.
            "search_queries_executed": sum(
                len(r.get("search_queries") or []) for r in ok_rows
            ),
            "partial": partial,
            "json_path": "",
            "engine_note": (
                "Gemini with Google Search grounding. One engine, one point in "
                "time. Not a measure of consumer AI assistant traffic."
            ),
        },
        "metrics": compute_metrics(rows, hotel) if rows else {},
        "search_suggestions_html": "",
        "results": [{k: v for k, v in r.items() if k != "raw"} for r in rows],
    }


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hotel", required=True)
    p.add_argument("--website", required=True)
    p.add_argument("--city", required=True)
    p.add_argument("--brand", default="")
    p.add_argument("--landmarks", default="", help="comma separated")
    p.add_argument("--extra-discovery", default="", help="comma separated")
    p.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"))
    p.add_argument("--pause", type=float, default=1.0)
    p.add_argument("--workers", type=int, default=3,
                   help="concurrent queries in flight - the main lever on runtime")
    p.add_argument("--out", default="audit_results.json")
    p.add_argument("--limit", type=int, default=0, help="cap queries per set (testing)")
    a = p.parse_args()

    domain = resolve_domain(a.website)
    landmarks = [s.strip() for s in a.landmarks.split(",") if s.strip()]
    extra = [s.strip() for s in a.extra_discovery.split(",") if s.strip()]

    disc_q = queryset.build_discovery(a.city, landmarks, extra)
    brand_q = queryset.build_branded(a.hotel, a.city)
    if a.limit:
        disc_q, brand_q = disc_q[: a.limit], brand_q[: a.limit]

    print(f"Hotel:  {a.hotel}")
    print(f"Domain: {domain}")
    print(f"Queries: {len(disc_q)} discovery + {len(brand_q)} branded "
          f"= {len(disc_q) + len(brand_q)} grounded calls, {a.workers} concurrent\n")

    client = GeminiClient(model=a.model, pause=a.pause)

    rows = run_set(client, disc_q, "discovery", a.hotel, domain, workers=a.workers)
    rows += run_set(client, brand_q, "branded", a.hotel, domain, workers=a.workers)

    metrics = compute_metrics(rows, a.hotel)
    payload = {
        "meta": {
            "hotel": a.hotel,
            "brand": a.brand,
            "city": a.city,
            "website": a.website,
            "domain": domain,
            "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "model": a.model,
            "api_mode": client.mode,
            "json_path": a.out,
            "engine_note": (
                "Gemini with Google Search grounding. One engine, one point in "
                "time. Not a measure of consumer AI assistant traffic."
            ),
        },
        "metrics": metrics,
        "results": [{k: v for k, v in r.items() if k != "raw"} for r in rows],
    }

    with open(a.out, "w") as f:
        json.dump(payload, f, indent=2)
    md = a.out.rsplit(".", 1)[0] + ".md"
    write_markdown(payload, md)

    print(f"\nAPI calls made: {client.calls_made}")
    print(f"Evidence log:   {a.out}")
    print(f"Summary:        {md}")
    if metrics.get("queries_failed"):
        print(f"WARNING: {metrics['queries_failed']} queries failed and are "
              f"excluded from all rates.")


if __name__ == "__main__":
    sys.exit(main())
