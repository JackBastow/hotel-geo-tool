"""
The management report: short, decision-oriented, and built from the highest-value
findings across the WHOLE audit (not section by section).

It says each thing once and points to the Technical & Evidence Appendix for the
quotes, URLs and method. Aim: roughly 6-10 pages.

  1 Executive summary            5 Important information gaps
  2 Readiness score + coverage   6 Reputation and distribution risks
  3 Top actions (5-7)            7 What the hotel is already doing well
  4 What AI/search can clearly   8 30 / 60 / 90-day plan
    understand

Imported lazily by report_pdf.build_story (it uses report_pdf's helpers).
"""

from reportlab.platypus import KeepTogether, PageBreak, Spacer

import headline as headline_mod
import report_pdf as R
from report_pdf import Markup, cat, esc, link, para, table

PRI_COL = {"critical": R.BAD, "high": "#c2570c", "medium": R.WARN, "low": R.GREY}
LEVEL_COL = {"high": R.GOOD, "medium": R.WARN, "low": R.BAD}
STATUS_COL = {"assessed": R.GOOD, "provisional": R.WARN, "withheld": R.BAD}


def short(text, n):
    """Trim to a sentence or word boundary, never mid-word."""
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    for sep in (". ", "; ", ", ", " "):
        i = cut.rfind(sep)
        if i > n * 0.55:
            return cut[: i + (1 if sep == ". " else 0)].rstrip(" ;,") + ("" if sep == ". " else "...")
    return cut.rstrip() + "..."


def _path(u):
    from urllib.parse import urlparse
    return urlparse(u or "").path or "/"


def _ev1(r):
    e = (r.get("evidence") or [{}])[0]
    q = short(e.get("snippet", ""), 150)
    lead = link(e["url"], _path(e["url"])) if e.get("url") else Markup("")
    return cat(lead, ": " if lead and q else "", f"“{q}”" if q else "")


def action_card(i, r):
    head = R.Paragraph(f"{i}. {esc(short(r['title'], 120))}", R.S["h3"])
    meta = R.P(cat(R.coloured(r["priority"].upper() + " priority", PRI_COL[r["priority"]]),
                   f" - effort {r['effort']} - confidence: {r['confidence'].lower()} - owner: {r['team']}"), "small")
    rows = [["Issue", short(r["finding"], 250)],
            ["Why it matters", short(r["why"], 230)],
            ["Evidence", _ev1(r)],
            ["Exact action", short(r["action"], 280)],
            ["Owner", r["team"]],
            ["Expected outcome", short(r["expected_outcome"], 210)],
            ["Detail", f"Appendix reference {r['ref']}"]]
    return [KeepTogether([head, meta, table(rows, [0.17, 0.83], header=False, zebra=False), Spacer(1, 5)])]


def _sentences(c, h, recs, top, hotel):
    score, cov = h["score"], h["coverage_pct"]
    if h["status"] == "withheld":
        s1 = (f"Too little of the full model could be assessed ({cov:.0f}%) to give {hotel} a single readiness score, so the category "
              "results are shown on their own.")
    else:
        lvl = "well" if score >= 75 else ("partly" if score >= 50 else "weakly")
        s1 = (f"On the factors we could measure, {hotel} is {lvl} set up to be found and understood (readiness {score}/100"
              f"{', provisional' if h['status'] == 'provisional' else ''} - {cov:.0f}% of the full model measured).")
    u = c["understanding"]
    s2 = ("What search and AI tools can clearly pick up from the website: " + ", ".join(u["strong_signals"][:4]) + ".") if u["strong_signals"] else ""
    titles = [short(r.get("short_title") or r["title"], 75) for r in top[:3]]
    s3 = ("The most worthwhile fixes are: " + "; ".join(titles) + ".") if titles else "No required fixes stood out."
    risk = [r for r in top if r["source"] == "intel" and r["category"] == "authority"]
    s4 = (f"One of them is a reputation risk, not a website issue: {short(risk[0]['title'], 80)}." if risk else "")
    s5 = ("Not measured: " + "; ".join(f"{u_['label']} ({u_['weight']:g}%)" for u_ in h["unassessed"]) + ". This report does not show what "
          "any AI assistant actually says about the hotel.") if h["unassessed"] else ""
    s6 = c["coverage"]["note"] if c.get("coverage", {}).get("limited") else ""
    return [x for x in (s1, s2, s3, s4, s5, s6) if x]


def story(rep, H1):
    c = rep["consultant"]
    meta = rep.get("meta", {})
    hotel = meta.get("hotel", "the hotel")
    h = rep.get("headline") or headline_mod.build(rep)
    recs = {r["id"]: r for r in c["recommendations"]}
    top = [recs[i] for i in c["top_actions"]]
    out = [R.Spacer(1, 6 * R.mm), para("Management report", "title"), para(hotel, "h1"),
           R.P(link(meta.get("base", ""), meta.get("website", "")) + " - " + esc(meta.get("city", "")) +
               " - audit run " + esc(R._date(meta.get("run_at"))), "base"), Spacer(1, 4),
           para("What AI and search systems can understand about this hotel, what they may struggle with, and the few things most worth "
                "doing. Quotes, URLs and method are in the Technical & Evidence Appendix; each action below gives its reference.", "muted")]

    cov = c.get("coverage") or {}
    if cov.get("limited"):
        why = "; ".join(f"{n} x {r}" for r, n in (cov.get("failure_reasons") or {}).items())
        out.append(para(f"Read {cov['pages_read']} of {cov['pages_attempted']} pages. {cov['note']}" + (f" Why pages failed: {why}." if why else ""), "note"))

    # 1 -------------------------------------------------------------- executive summary
    out.append(H1("Executive summary"))
    for s in _sentences(c, h, recs, top, hotel):
        out.append(para(s, "base"))
        out.append(Spacer(1, 2))

    # 2 -------------------------------------------------------------- readiness + coverage
    out.append(H1("Readiness score and coverage"))
    num = "-" if h["score"] is None else f"{h['score']} / 100"
    box = table([[Markup(f"<font size=22><b>{esc(num)}</b></font>"),
                  cat(R.coloured(h["badge"].upper(), STATUS_COL[h["status"]]), Markup("<br/>"),
                      f"Measurement coverage: {h['coverage_pct']:.0f}% of the full model", Markup("<br/>"),
                      h["title"])]], [0.22, 0.78], header=False, zebra=False)
    out += [box, Spacer(1, 3), para(h["explanation"], "note")]
    rows = [["Measure", "Score", "Evidence strength", "What drove it"]]
    for p in c["profile"]:
        ev = p.get("evidence") or {}
        sc = f"{p['score']} / 100" if p["assessed"] else "not assessed"
        rows.append([p["label"], sc, R.coloured((ev.get("level") or "-") + " evidence", LEVEL_COL.get(ev.get("level"), R.GREY)),
                     short("; ".join(p["drivers"][:2]), 120) + (f" ({ev['why']})" if ev.get("why") else "")])
    out.append(table(rows, [0.2, 0.12, 0.16, 0.52]))
    out.append(para("A score and the evidence behind it are different things: 100/100 on thin evidence is shown as such. The measures are "
                    "kept separate and are not blended into one GEO score.", "tiny"))
    if h["unassessed"]:
        out.append(para("Not measured", "h3"))
        out += R.bullets([f"{u['label']} ({u['weight']:g}% of the model): {short(u['why'], 170)}" for u in h["unassessed"]])

    # 3 -------------------------------------------------------------- top actions
    out.append(R.PageBreak())
    out.append(H1(f"The {len(top)} things most worth doing" if top else "Top actions"))
    out.append(para("Chosen from the whole audit by one ranking model: business and reputation risk, how much travellers care, how much it "
                    "affects discoverability, and how sure we are - moderated by effort. Required fixes only; commercial opportunities are "
                    "separate (section 4).", "muted"))
    if not top:
        out.append(para("Nothing in this audit met the bar for a required fix.", "base"))
    for i, r in enumerate(top, 1):
        out += action_card(i, r)

    # 4 -------------------------------------------------------------- what is clearly understood
    out.append(H1("What AI and search can clearly understand"))
    u = c["understanding"]
    if u["summary"]:
        out.append(para(u["summary"], "note"))
    strong = [r for r in c["intents"] if r["level"] == "strong"]
    some = [r for r in c["intents"] if r["level"] == "some"]
    if strong or some:
        rows = [["Traveller type", "Evidence", "Why"]]
        for r in strong + some:
            rows.append([r["label"], "Strongly supported" if r["level"] == "strong" else "Some evidence", short(r["reason"], 150)])
        out.append(table(rows, [0.22, 0.18, 0.6]))
    else:
        out.append(para("No traveller type is strongly supported by the pages read.", "base"))
    if c.get("opportunities"):
        out.append(para("Commercial opportunities", "h3"))
        out.append(para("Not defects. Weak signals matter only if the segment is one the hotel wants to attract.", "tiny"))
        out += R.bullets([o["statement"] for o in c["opportunities"][:3]])

    # 5 -------------------------------------------------------------- information gaps
    out.append(H1("Important information gaps"))
    gaps = [r for r in c["recommendations"] if r["source"] in ("questions", "location") and r["kind"] == "fix"]
    if gaps:
        rows = [["Page", "What is not clearly stated", "Priority", "Ref"]]
        for r in gaps:
            pg = (r.get("page") or {})
            what = r.get("summary") or "; ".join(short(a, 70) for a in r["additions"][:4]) or short(r["finding"], 140)
            rows.append([link(pg["url"], pg["label"]) if pg.get("url") else (pg.get("label") or "-"), what,
                         R.coloured(r["priority"], PRI_COL[r["priority"]]), r["ref"]])
        out.append(table(rows, [0.22, 0.58, 0.1, 0.1]))
        out.append(para("Each gap is listed once here; the quotes, example wording and where each answer belongs are in the appendix.", "tiny"))
    else:
        out.append(para("The common traveller questions are answered on the pages read.", "base"))

    # 6 -------------------------------------------------------------- reputation and distribution
    out.append(H1("Reputation and distribution risks"))
    risks = [r for r in c["recommendations"] if r["source"] == "intel" and r["kind"] == "fix"]
    if risks:
        rows = [["Risk", "What we found", "Priority", "Ref"]]
        for r in risks:
            rows.append([short(r["title"], 80), short(r["finding"], 190), R.coloured(r["priority"], PRI_COL[r["priority"]]), r["ref"]])
        out.append(table(rows, [0.28, 0.5, 0.1, 0.12]))
    else:
        out.append(para("No reputation or distribution risk was found in the sources checked.", "base"))
    out.append(para("Guest reviews could not be assessed (no lawful, free source), so the absence of a finding here is not evidence of a healthy "
                    "review profile.", "tiny"))

    # 7 -------------------------------------------------------------- doing well
    out.append(H1("What the hotel is already doing well"))
    out += R.bullets([w["point"] for w in c["working"]] or ["Nothing specific stood out in the pages read."])

    # 8 -------------------------------------------------------------- 30 / 60 / 90
    out.append(H1("30 / 60 / 90-day plan"))

    def col(ids):
        if not ids:
            return "-"
        out_ = Markup("")
        for k, rid in enumerate(ids):
            r = recs[rid]
            tag = " (opportunity)" if r["kind"] == "opportunity" else ""
            out_ = cat(out_, Markup("<br/>") if k else "", f"- {short(r.get('short_title') or r['title'], 70)}{tag} [{r['team']}, {r['ref']}]")
        return out_
    plan = c["plan"]
    out.append(table([["First 30 days", "Days 31-60", "Days 61-90"], [col(plan["30"]), col(plan["60"]), col(plan["90"])]],
                     [0.36, 0.32, 0.32]))
    out.append(para("30 days: serious and quick items. 60 days: medium-effort required fixes. 90 days: opportunities and larger pieces of work. "
                    "Re-run the audit afterwards to check what changed.", "tiny"))
    out.append(para("Limits of this report", "h3"))
    out += R.bullets([
        "It does not show what any AI assistant actually says about the hotel; nothing was asked of an assistant.",
        f"The readiness score rests on {h['coverage_pct']:.0f}% of the full model and is a set-up indicator, not a measure of AI visibility.",
        "Findings come from the hotel's own pages and public sources read during the audit; search results vary between runs.",
        "Recommendations are labelled by confidence. None guarantees that any AI assistant will recommend the hotel."])
    return out
