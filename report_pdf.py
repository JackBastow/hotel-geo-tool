"""
Full PDF report, generated from a COMPLETED audit (the dict run_full_audit
returns). It makes no network requests.

Selectable text, clickable links, page numbers ("Page 3 of 14") and
repeating table headers come from reportlab's platypus layout engine, so long
tables paginate properly instead of being clipped.

Fonts: the PDF standard fonts (Helvetica/Courier) are used, so text is limited
to the Western European character set; anything outside it is replaced with a
close equivalent or '?'. That is stated in the methodology.
"""

import datetime as dt
import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

PAGE = A4
MARGIN = 17 * mm
W = PAGE[0] - 2 * MARGIN

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#5b6770")
RULE = colors.HexColor("#d5dbe0")
ACCENT = colors.HexColor("#1b5e7a")
HEAD_BG = colors.HexColor("#e8eff3")
ZEBRA = colors.HexColor("#f6f8fa")
GOOD, WARN, BAD, GREY = "#1e7b45", "#9a6a00", "#b3261e", "#6b7780"

_MAP = {"→": "->", "←": "<-", "≥": ">=", "≤": "<=", "✓": "yes", "✗": "no",
        "•": "-", " ": " ", "​": "", "‑": "-", "−": "-", "✕": "x",
        "★": "*", "☆": "*", "●": "-", "…": "..."}


class Markup(str):
    """Text already safe for a reportlab Paragraph (escaped, may contain <b>, <link> ...).
    A plain str placed in a table cell is ALWAYS escaped, so data can never break the
    layout or be escaped twice."""


def cat(*parts):
    """Join parts into Markup: Markup parts as they are, plain str escaped."""
    return Markup("".join(p if isinstance(p, Markup) else escape(clean(p)) for p in parts))


def clean(s):
    s = "" if s is None else str(s)
    for k, v in _MAP.items():
        s = s.replace(k, v)
    return s.encode("cp1252", "replace").decode("cp1252")


def esc(s):
    return Markup(escape(clean(s)))


def link(url, label=None, maxlen=70):
    if not url or not str(url).startswith(("http://", "https://")):
        return esc(label or url or "")
    shown = label or (url if len(url) <= maxlen else url[: maxlen - 3] + "...")
    return Markup(f'<link href="{escape(clean(url), {chr(34): "&quot;"})}" color="#1b5e7a"><u>{esc(shown)}</u></link>')


def coloured(text, colour):
    return Markup(f'<font color="{colour}">{esc(text)}</font>')


STATUS_COLOUR = {"assessed": GOOD, "partial": WARN, "not_assessed": BAD,
                 "ok": GOOD, "unavailable": BAD, "no_results": WARN, "not_configured": GREY}
STATUS_LABEL = {"assessed": "Assessed", "partial": "Partial", "not_assessed": "Not assessed"}


def _styles():
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12.2, textColor=INK,
                          alignment=TA_LEFT)
    S = {"base": base}
    S["small"] = ParagraphStyle("small", parent=base, fontSize=7.6, leading=9.8)
    S["tiny"] = ParagraphStyle("tiny", parent=base, fontSize=6.9, leading=8.8, textColor=MUTED)
    S["muted"] = ParagraphStyle("muted", parent=base, textColor=MUTED, fontSize=8.4, leading=11)
    S["cell"] = ParagraphStyle("cell", parent=base, fontSize=7.4, leading=9.4)
    S["cellb"] = ParagraphStyle("cellb", parent=S["cell"], fontName="Helvetica-Bold")
    S["h1"] = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=20,
                             textColor=ACCENT, spaceBefore=4, spaceAfter=6, keepWithNext=1)
    S["h2"] = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14,
                             textColor=INK, spaceBefore=9, spaceAfter=3, keepWithNext=1)
    S["h3"] = ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12,
                             textColor=ACCENT, spaceBefore=6, spaceAfter=2, keepWithNext=1)
    S["title"] = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=24, leading=28,
                                textColor=ACCENT, spaceAfter=4)
    S["bullet"] = ParagraphStyle("bullet", parent=base, leftIndent=11, bulletIndent=2, spaceAfter=1.5)
    S["code"] = ParagraphStyle("code", fontName="Courier", fontSize=6.8, leading=8.4, textColor=INK,
                               backColor=ZEBRA, leftIndent=4, rightIndent=4, borderPadding=3)
    S["note"] = ParagraphStyle("note", parent=base, fontSize=8.2, leading=11, textColor=MUTED,
                               leftIndent=6, borderPadding=(3, 4, 3, 6), backColor=ZEBRA, spaceBefore=3, spaceAfter=5)
    return S


S = _styles()


def P(text, style="base"):
    return Paragraph(text, S[style])


def para(text, style="base"):
    return Paragraph(esc(text), S[style])


def bullets(items, style="bullet"):
    return [Paragraph(i if isinstance(i, Markup) else esc(i), S[style], bulletText="-") for i in items]


def table(rows, widths, header=True, zebra=True, font="cell"):
    """rows: list of lists of str (plain text, already-escaped markup allowed if it starts with '<')."""
    data = []
    for ri, row in enumerate(rows):
        cells = []
        for c in row:
            markup = c if isinstance(c, Markup) else esc("" if c is None else c)
            cells.append(Paragraph(markup, S["cellb"] if (header and ri == 0) else S[font]))
        data.append(cells)
    t = Table(data, colWidths=[w * W for w in widths], repeatRows=1 if header else 0, splitByRow=1)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
          ("LEFTPADDING", (0, 0), (-1, -1), 3.5), ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if (i % 2) == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(st))
    return t


def kv(rows, widths=(0.28, 0.72)):
    return table([[Markup(f"<b>{esc(k)}</b>"), v] for k, v in rows], list(widths), header=False)


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas so each footer can say 'Page x of N'."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []
        self.header_text = ""

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total):
        n = self._pageNumber
        self.setFont("Helvetica", 7.2)
        self.setFillColor(MUTED)
        if n > 1:
            self.drawString(MARGIN, PAGE[1] - 11 * mm, clean(self.header_text))
            self.setStrokeColor(RULE)
            self.line(MARGIN, PAGE[1] - 12.5 * mm, PAGE[0] - MARGIN, PAGE[1] - 12.5 * mm)
        self.line(MARGIN, 12 * mm, PAGE[0] - MARGIN, 12 * mm)
        self.drawString(MARGIN, 8 * mm, "Hotel discovery & reputation report - evidence-based, not a measure of AI recommendations")
        self.drawRightString(PAGE[0] - MARGIN, 8 * mm, f"Page {n} of {total}")


# ----------------------------------------------------------------- sections

def _date(s):
    return (s or "")[:10]


def _score_colour(v):
    return GOOD if v >= 75 else (WARN if v >= 50 else BAD)


def _appendix_story(rep):
    """The Technical & Evidence Appendix: every detailed finding, extract, URL and method, said once."""
    import headline as headline_mod
    import report_pdf_consult
    meta = rep.get("meta", {})
    intel = rep.get("intel") or {}
    has_intel = bool(intel) and "error" not in intel
    consult = rep.get("consultant") or {}
    has_consult = bool(consult) and "error" not in consult
    sc = rep.get("scorecard", {})
    hotel = meta.get("hotel", "")
    story = []

    # ---- cover
    story += [Spacer(1, 12 * mm), para("Technical & evidence appendix", "title"),
              para(hotel, "h1"),
              P(link(meta.get("base", ""), meta.get("website", "")) + " - " + esc(meta.get("city", "")), "base"),
              Spacer(1, 4),
              para(f"Audit run {_date(meta.get('run_at'))}. Generated from the completed audit; no further "
                   "requests were made to produce this document.", "muted"),
              Spacer(1, 8),
              P("<b>How to use this appendix.</b> The management report states each finding once and gives it a reference. This appendix "
                "holds the detail behind them: the quotes and URLs (each tied to an E-number in the evidence list at the end), the "
                "methodology, the structured-data examples, platform discovery, media coverage and technical checks. Findings are "
                "labelled <b>observed</b> (we read it), <b>inferred</b> (a conclusion drawn from observed evidence) or <b>not assessed</b> "
                "(we could not check it, with the reason). <b>Nothing here measures what any AI assistant recommends</b>; no assistant was asked.", "note")]

    # ---- scorecard, coverage and evidence strength (the summary lives in the management report)
    h = rep.get("headline") or headline_mod.build(rep)
    story += [Spacer(1, 4), H1("Scorecard, coverage and evidence strength"), para(h["explanation"], "note")]
    rows = [["Category", "Weight", "Score", "Evidence strength", "What it found"]]
    for c in sc.get("categories", []):
        sv = f"{c['score']}" if c.get("assessed") else "not assessed"
        ev = (c.get("evidence_level") or "") + (f" - {c.get('evidence_note')}" if c.get("evidence_note") else "")
        rows.append([c["label"], f"{c['weight']}%", sv, ev, (c.get("detail") or "")[:200]])
    story.append(table(rows, [0.17, 0.07, 0.1, 0.26, 0.4]))
    if sc.get("caveat"):
        story.append(para(sc["caveat"], "note"))
    if has_intel:
        cc = intel["methodology"]["check_counts"]
        md = intel["media"]["summary"]
        story += [Spacer(1, 3), kv([
            ("Checks", f"{cc.get('assessed', 0)} assessed, {cc.get('partial', 0)} partial, {cc.get('not_assessed', 0)} not assessed (of 30)"),
            ("Evidence records", str(len(intel["ledger"]))),
            ("Media coverage", f"{md['articles']} pages naming the hotel from {md['publishers']} publishers; "
                               f"{md['independent_publishers']} independent; {md['duplicates_removed']} duplicate copies collapsed"),
            ("Guest reviews", intel["reviews"]["sample"]["statement"])])]

    if has_consult:
        story += report_pdf_consult.sections(consult, H1, rep.get("web_signals"))
    elif not has_intel:
        story += [para("The analysis of what AI systems can understand about this hotel did not complete for this run"
                       + (f": {consult.get('error')}" if consult else "") + ".", "note")]
    if not has_intel:
        story += [para("The wider discovery and reputation analysis did not complete for this run"
                       + (f": {intel.get('error')}" if intel else "") + ". The sections below that depend on it "
                       "are therefore omitted.", "note")]
        story += _website_section(rep, intel)
        return story

    story += _identity_section(intel)
    story += _reviews_section(intel)
    story += _media_section(intel)
    story += _traveller_section(intel)
    story += _social_local_section(intel)
    story += _website_section(rep, intel)
    if not has_consult:
        story += _recommendations_section(intel)
    story += _gaps_section(intel)
    story += _evidence_appendix(intel)
    return story


_COUNTER = [0]


def H1(title):
    """Numbered top-level heading; the numbers follow whatever sections the report has."""
    _COUNTER[0] += 1
    return Paragraph(f"{_COUNTER[0]}. {esc(title)}", S["h1"])


def _hr():
    return Spacer(1, 3)


def _identity_section(intel):
    idn = intel["identity"]
    out = [PageBreak(), H1("Identity and distribution")]
    out += [para("Do the sources agree on who and where this hotel is, where is it listed, and does what is "
                 "listed match the website? 'Discovered' means a page exists in search results or open data; "
                 "'content assessed' means we were allowed to read it.", "muted")]
    out += [para("Cross-source identity (check 1)", "h2")]
    rows = [["Source", "Name seen", "Place / address", "Confidence"]]
    for s in idn["sources_compared"]:
        conf = {True: "location verified", False: "possible different hotel", None: ""}.get(s.get("confident"), "")
        rows.append([s["source"], s.get("name") or "", (s.get("place") or "")[:90], conf])
    out.append(table(rows, [0.22, 0.26, 0.38, 0.14]))
    if idn["name_variants"]:
        out += [para("Name forms in use", "h3"),
                table([["Form", "Mentions", "Seen in"]] + [[v["variant"], str(v["count"]), ", ".join(v["sources"])]
                                                        for v in idn["name_variants"]], [0.34, 0.1, 0.56])]
    if idn["namesakes"]:
        out += [para("Possible namesakes (not this hotel)", "h3"),
                table([["Name", "Where", "Why it was flagged"]] +
                      [[n["name"], n["where"], n["why"]] for n in idn["namesakes"]], [0.4, 0.15, 0.45])]
    if idn["former_names"]:
        out += [para("Possible former names (inference)", "h3"),
                table([["Name", "Basis", "Source"]] + [[f["name"], f["basis"], f["source"]] for f in idn["former_names"]],
                      [0.25, 0.55, 0.2])]
    else:
        out.append(para("No former name or rebrand was found in the sources read. That is not proof there was none.", "muted"))

    out += [para("Public listing footprint (check 2)", "h2")]
    rows = [["Platform", "Type", "Discovered", "Content assessed", "Page"]]
    for r in idn["footprint"]:
        rows.append([r["platform"], r["type"], "yes" if r["discovered"] else "not found by our searches",
                     "yes" if r["content_assessed"] else ("no - " + (r.get("note") or "not read")[:60] if r["discovered"] else ""),
                     P_link(r["url"]) if r["url"] else ""])
    out.append(table(rows, [0.17, 0.17, 0.17, 0.25, 0.24]))
    out.append(para("'Not found by our searches' never means 'not listed': a search index is not a platform directory. "
                    "TripAdvisor, Booking.com, Expedia and similar sites prohibit automated reading, so their content is "
                    "never assessed here.", "note"))
    out += [para("Listing consistency (check 3)", "h2")]
    cons = idn["consistency"]
    if cons["rows"]:
        out.append(table([["Field", "Website", "Listing says", "Source"]] +
                         [[r["field"], str(r["own"]), str(r["other"]), P_link(r["url"], r["source"])] for r in cons["rows"]],
                         [0.14, 0.3, 0.3, 0.26]))
    else:
        out.append(para(f"{cons['pages_compared']} listing page(s) could be read and compared; no contradictory "
                        "telephone, postcode or star rating was found." if cons["pages_compared"] else
                        "No listing page could lawfully be read, so descriptions and facilities were not compared.", "base"))
    out += [para("Destination organisation (check 4)", "h2")]
    d = idn["destination"]
    if d["body"]:
        out.append(P(f"<b>{esc(d['body']['name'])}</b> ({esc(d['body'].get('scope', ''))}) - " + link(d["body"]["url"]) + ". "
                     + ("A page naming the hotel exists: " + ", ".join(link(p["url"], p["title"][:60] or p["url"]) for p in d["pages_naming_hotel"][:2])
                        if d["listing_found"] else "No page naming the hotel was found on the pages read."), "base"))
        out.append(para(d["route"], "note"))
    else:
        out.append(para("No official destination site was identified by the searches.", "base"))
    out += [para("Booking and distribution (check 5)", "h2")]
    dist = idn["distribution"]
    out.append(P("Booking links on the hotel's own pages: " + (", ".join(f"{esc(b['engine'])} ({esc(b['domain'])})" for b in dist["booking_links_on_site"])
                                                                if dist["booking_links_on_site"] else "none recognised") + ".", "base"))
    out.append(P("Platforms discovered: " + (esc(", ".join(dist["platforms_discovered"])) or "none") + ".", "base"))
    out.append(para(dist["statement"], "note"))
    return out


def _summary_reason(c):
    out = esc(c["summary"])
    if c["reason"]:
        out = Markup(out + "<br/><font color='#6b7780'>" + esc(c["reason"]) + "</font>")
    return out


def P_link(url, label=None, maxlen=70):
    return link(url, label, maxlen)


def _reviews_section(intel):
    rv, md = intel["reviews"], intel["media"]
    out = [PageBreak(), H1("Reviews and reputation"),
           para(rv["why_no_reviews"], "note"),
           para("Available review sample (check 6)", "h2"),
           para(rv["sample"]["statement"], "base")]
    if rv["ratings"]:
        rows = [["Source", "Rating shown", "Based on", "Seen in", "Hotel match", "Page"]]
        for r in rv["ratings"]:
            rows.append([r["source"], f"{r['value']} / {r['scale']}", f"{r['count']} ratings" if r["count"] else "count not shown",
                         r["where"], "town named beside hotel" if r["verified_location"] else "UNVERIFIED - may be another hotel",
                         P_link(r["url"])])
        out += [para("Aggregate ratings third parties display", "h3"), table(rows, [0.13, 0.11, 0.13, 0.1, 0.23, 0.3]),
                para("These are numbers shown by third parties, not reviews we could read or analyse.", "tiny")]
    if rv["editorial_reviews"]:
        out += [para("Editorial review articles (a writer's account, not guest reviews)", "h3"),
                table([["Date", "Publisher", "Title", "Freshness"]] +
                      [[r["date"] or "undated", r["publisher"], P_link(r["url"], (r["title"] or r["url"])[:70]), r["freshness"]]
                       for r in rv["editorial_reviews"]], [0.12, 0.2, 0.55, 0.13])]
    fsa = [e for e in intel["ledger"] if e["source_type"] == "government_register"]
    if fsa:
        out += [para("Official register: food hygiene (UK FSA)", "h3"),
                table([["Evidence", "Record", "Page"]] + [[e["id"], e["extract"], P_link(e["url"])] for e in fsa], [0.1, 0.62, 0.28])]
    out += [para("What could not be assessed (checks 7-14)", "h2")]
    rows = [["#", "Check", "Status", "What we can say / why not"]]
    for c in intel["checks"]:
        if 7 <= c["n"] <= 14:
            rows.append([str(c["n"]), c["name"], coloured(STATUS_LABEL[c["status"]], STATUS_COLOUR[c["status"]]),
                         _summary_reason(c)])
    out.append(table(rows, [0.05, 0.19, 0.11, 0.65]))
    pos = rv["positioning"]
    out += [para("Reputation versus positioning (check 14, independent sources only)", "h2")]
    if pos["supported"]:
        out.append(table([["Theme the hotel claims", "Independent publishers", "Example"]] +
                         [[s["theme"], str(s["independent_publishers"]),
                           (s["extract"].get("text", "")[:170] + " - " + s["extract"].get("publisher", "")) if s["extract"] else ""]
                          for s in pos["supported"]], [0.25, 0.14, 0.61]))
    if pos["claimed_only_by_hotel"]:
        out.append(P("<b>Claimed only on the hotel's own pages:</b> " + esc(", ".join(pos["claimed_only_by_hotel"])) + ".", "base"))
    if pos["described_by_others_not_by_hotel"]:
        out.append(P("<b>Described by others but not by the hotel:</b> " + esc(", ".join(pos["described_by_others_not_by_hotel"])) + ".", "base"))
    out.append(para(pos["limit"], "note"))
    return out


def _media_section(intel):
    md = intel["media"]
    cov = md["summary"]
    out = [PageBreak(), H1("Media coverage and independent validation"),
           para("Only pages that name the hotel in full count as coverage of it. Look-alikes (a motor circuit, a college, "
                "another hotel with the same name) are rejected and listed below. Search results vary between runs, so "
                "absence of a piece here is not proof it does not exist.", "muted")]
    out.append(kv([
        ("Pages naming the hotel", f"{cov['articles']} ({cov['stories']} distinct stories after removing {cov['duplicates_removed']} duplicate copies)"),
        ("Publishers", f"{cov['publishers']} total; {cov['independent_publishers']} independent (publishing groups counted once; "
                       "sponsored, press-release, syndicated and destination-body pieces excluded)"),
        ("By type (inferred)", ", ".join(f"{k} {v}" for k, v in cov["by_type"].items()) or "none"),
        ("By freshness", ", ".join(f"{k} {v}" for k, v in cov["by_freshness"].items()) or "n/a"),
        ("Languages of the articles", ", ".join(f"{k} {v}" for k, v in cov["by_language"].items()) or "n/a"),
        ("GDELT news monitor", (md["gdelt"]["status"] + (": " + md["gdelt"]["reason"] if md["gdelt"]["reason"] else ""))),
    ]))
    out += [para("Named coverage (checks 15-18)", "h2")]
    if md["articles"]:
        rows = [["Date", "Publisher", "Type (inferred)", "Fresh", "How much", "Lang", "Piece", "Ev."]]
        for a in md["articles"]:
            t = a["type"] + (f" ({a['cue_text']})" if a.get("cue_text") else "")
            rows.append([(a["date"] or "undated") + (" *" if a.get("date_note") else ""), a["publisher"], t, a["freshness"],
                         a["substance"], a["lang"] or "?", P_link(a["url"], (a["title"] or a["url"])[:60]), a["id"]])
        out.append(table(rows, [0.09, 0.15, 0.13, 0.07, 0.12, 0.05, 0.31, 0.08]))
        notes = [a for a in md["articles"] if a.get("date_note")]
        if notes:
            out.append(para("* " + notes[0]["date_note"] + " (example).", "tiny"))
        syn = [c for c in md["clusters"] if c["size"] > 1]
        if syn:
            out.append(para("Duplicate / syndicated copies collapsed: " + "; ".join(
                f"{c['size']} copies ({'shared across publishers' if c.get('syndicated') else 'one publishing group'})" for c in syn), "muted"))
    else:
        out.append(para("No page naming the hotel could be read." + (" The wider search did not run." if not cov["articles"] else ""), "base"))
    if md["rejected"]:
        out += [para("Rejected as not about this hotel", "h3"),
                table([["Page", "Match", "Why"]] + [[P_link(r["url"], (r["title"] or r["url"])[:60]), r["level"], r["why"]]
                                                   for r in md["rejected"][:10]], [0.4, 0.1, 0.5])]
    if md["unread"]:
        out.append(para(f"{len(md['unread'])} further page(s) from the searches could not be read (robots.txt, paywall, "
                        "errors or limits), so they are not counted: " + "; ".join(
                            f"{u['domain']} ({u['why_unread'][:40]})" for u in md["unread"][:6]), "muted"))
    out += [para("Awards and accreditation (check 19)", "h2")]
    if md["awards"]:
        rows = [["Issuer", "Year(s)", "Status", "Evidence"]]
        for a in md["awards"]:
            ev = []
            for c in a["claims"][:1]:
                ev.append("hotel: " + c["text"][:110])
            for c in a["independent"][:1]:
                ev.append(f"{c['publisher']}: " + c["text"][:110])
            rows.append([a["issuer"], ", ".join(a["years"]) or "-", a["status"], " | ".join(ev)])
        out.append(table(rows, [0.18, 0.1, 0.27, 0.45]))
        out.append(para("'Confirmed' requires a page on the issuer's own site naming the hotel. A claim on the hotel's own site "
                        "remains the hotel's claim until then.", "tiny"))
    else:
        out.append(para("No award or accreditation wording was found on the hotel's pages or in the coverage read.", "base"))
    out += [para("Media narrative (check 20)", "h2")]
    th = md["themes"]
    if th["themes"]:
        rows = [["Theme", "Hotel's own pages", "Independent publishers", "What independent sources say"]]
        for t in th["themes"][:12]:
            ex = t["independent_extracts"][0] if t["independent_extracts"] else None
            rows.append([t["theme"], str(t["own_pages"]), str(t["independent_publishers"]),
                         cat(ex["text"][:200], " - ", Markup(f"<i>{esc(ex['publisher'])}</i> "), link(ex["url"], "link")) if ex else ""])
        out.append(table(rows, [0.17, 0.11, 0.13, 0.59]))
        if th["disagreements"]:
            out.append(P("<b>Where sources disagree:</b> " + esc("; ".join(" vs ".join(d["themes"]) for d in th["disagreements"])) + ".", "base"))
        out.append(para("Themes are read only from the text around the hotel's name, so a roundup's words about other hotels "
                        "are not attributed to this one. Matching is by wording, not meaning.", "tiny"))
    else:
        out.append(para("No theme could be extracted from independent coverage.", "base"))
    out += [para("Comparison hotels in guides (check 21)", "h2")]
    if md["comparison"]:
        out.append(table([["Comparable nearby hotel", "Guides featuring it", "Why it is a valid comparison"]] +
                         [[c["hotel"], "; ".join(f"{p['publisher']}" for p in c["featured_in"]), "named in a guide for the same area"]
                          for c in md["comparison"]], [0.34, 0.36, 0.3]))
    out.append(para("Fewer than three validated comparison hotels is too few to compare against. Hotels are only compared when "
                    "they are mapped nearby or named in a guide about the same area - never because they are famous.", "tiny"))
    out += [para("Media and organisation targets (checks 22-23)", "h2")]
    if md["targets"]:
        rows = [["Outlet / body", "Kind", "Supporting page", "Audience fit", "Why relevant", "Confidence"]]
        for t in md["targets"]:
            rows.append([Markup(f"<b>{esc(t['name'])}</b>"), t["kind"],
                         cat(P_link(t["url"], (t["page_title"] or t["url"])[:60]), Markup("<br/>") if t["date"] else "",
                             t["date"] or ""),
                         t["audience_fit"], t["why_relevant"], t["confidence"]])
        out.append(table(rows, [0.14, 0.12, 0.24, 0.12, 0.26, 0.12]))
        out.append(para("Each row is named because a real, relevant page supports it. Whether an outlet would cover the hotel is "
                        "not something this tool can know; no journalist names or contact details are produced.", "tiny"))
    else:
        out.append(para("Discovery coverage was insufficient to name outlets from evidence. These are research directions, "
                        "NOT a researched shortlist:", "base"))
        out.append(table([["Direction", "Why", "How to look"]] + [[d["category"], d["why"], d["how"]] for d in md["research_directions"]],
                         [0.25, 0.4, 0.35]))
    out += [para("Pitch angles grounded in the hotel's own pages", "h3")]
    if md["angles"]:
        out.append(table([["Angle", "Fact found", "Source", "Evidence still missing before pitching"]] +
                         [[a["angle"], a["fact"][:220], P_link(a["source_url"]), "; ".join(a["missing_evidence"])] for a in md["angles"]],
                         [0.15, 0.32, 0.15, 0.38]))
        out.append(para("These are candidates. Newsworthiness is not assumed; each needs the missing evidence, and independent "
                        "confirmation, before it is pitched.", "tiny"))
    else:
        out.append(para("No documented, pitch-worthy fact was found on the pages read, so no angle is suggested.", "base"))
    return out


def _traveller_section(intel):
    tr = intel["traveller"]
    out = [PageBreak(), H1("Traveller fit and positioning"),
           para("What evidence exists for each kind of traveller, across the hotel's own pages, independent coverage and "
                "open data. This assesses evidence; it does not measure any AI ranking.", "muted"),
           para("Traveller-need coverage (check 24)", "h2")]
    rows = [["Traveller", "Evidence", "Own pages", "Independent", "Gaps / notes"]]
    for n in tr["needs"]:
        rows.append([n["segment"], n["status"], str(n["own_pages"]), str(n["independent_publishers"]),
                     "; ".join(n["gaps"] + n["open_data"])[:240]])
    out.append(table(rows, [0.22, 0.24, 0.08, 0.1, 0.36]))
    out += [para("Recommendation opportunities (check 25)", "h2"),
            para("Realistic traveller questions the hotel has some evidence to fit. Opportunities, not measured AI rankings.", "muted")]
    if tr["opportunities"]:
        out.append(table([["Traveller question", "Supporting facts", "Missing evidence"]] +
                         [[o["question"], "; ".join(o["supporting_facts"])[:260], "; ".join(o["missing_evidence"])[:240] or "none identified"]
                          for o in tr["opportunities"]], [0.28, 0.4, 0.32]))
    pos = tr["positioning"]
    out += [para("Distinctive positioning (check 26)", "h2")]
    if pos["candidates"]:
        out.append(table([["Feature", "Independent publishers", "Assessment"]] +
                         [[c["feature"], str(c["independent_publishers"]), c["assessment"] + (f" ({c['comparison_share']})" if c["comparison_share"] else "")]
                          for c in pos["candidates"]], [0.3, 0.17, 0.53]))
    if pos["local_anchors"]:
        out.append(P("<b>Local anchors independent writers connect with the hotel:</b> " + esc("; ".join(
            f"{a['place']} ({a['km']} km straight line, named by {', '.join(a['named_by'][:2])})" for a in pos["local_anchors"])) + ".", "base"))
    if pos["generic_note"]:
        out.append(para(pos["generic_note"], "note"))
    if not pos["comparison_available"]:
        out.append(para("Fewer than three comparable hotels could be validated, so 'distinctive' rests on what independent "
                        "sources emphasise, not on a comparison with other hotels.", "tiny"))
    t = tr["terminology"]
    out += [para("Language and terminology (check 27)", "h2")]
    if t["labels"]:
        out.append(table([["Label in use", "Sources using it"]] +
                         [[l["term"], ", ".join(l["used_by"])] for l in t["labels"]], [0.25, 0.75]))
    for cfl in t["conflicts"]:
        out.append(P("<b>Conflict:</b> " + esc(cfl), "base"))
    if t["words_others_use"]:
        out.append(P("<b>Words independent writers use that the hotel's pages never do</b> (consider only where true and useful to a guest): "
                     + esc(", ".join(f"'{w['word']}' ({w['publisher']})" for w in t["words_others_use"][:8])) + ".", "base"))
    out.append(para(t["guest_wording"] + ". " + t["caution"], "note"))
    return out


def _social_local_section(intel):
    so, lo = intel["social"], intel["local"]
    out = [PageBreak(), H1("Social, video and local context"),
           para("Public social and video evidence (check 28)", "h2")]
    if so["profiles"]:
        out.append(table([["Platform", "Profile", "Evidence"]] +
                         [[p["platform"], P_link(p["url"]), p["evidence"] + "; " + p["note"]] for p in so["profiles"]], [0.15, 0.4, 0.45]))
    else:
        out.append(para("No official social profile was found linked from the website.", "base"))
    if so["videos"]:
        out.append(table([["Date", "Channel", "Video"]] + [[v.get("published") or "", v["channel"], P_link(v["url"], v["title"][:80])]
                                                         for v in so["videos"]], [0.12, 0.25, 0.63]))
    else:
        out.append(para("Video: " + (so.get("youtube_reason") or "none found"), "muted"))
    out.append(para(so["note"], "note"))
    out += [para("Location and local partnerships (check 29)", "h2")]
    if lo["available"]:
        for title, key in (("Transport", "stations"), ("Attractions", "attractions"), ("Event / meeting venues", "venues"),
                           ("Airports", "airports")):
            if lo[key]:
                out.append(P(f"<b>{title}:</b> " + esc("; ".join(f"{x['name']} {x['km']} km" for x in lo[key])) + ".", "base"))
        if lo["failed_parts"]:
            out.append(para("Not retrieved from the public map servers this run: " + ", ".join(lo["failed_parts"]) +
                            ". Absence here does not mean nothing is nearby.", "note"))
    else:
        out.append(para(lo["reason"] or "Local context was not assessed.", "base"))
    out.append(para(lo["label"], "tiny"))
    if lo["partnerships"]:
        out.append(table([["Partner", "Relationship", "Status", "Source"]] +
                         [[p["partner"], p["relationship"], p["status"], P_link(p["source_url"])] for p in lo["partnerships"]],
                         [0.22, 0.2, 0.3, 0.28]))
    else:
        out.append(para("No partnership or destination-link statement was found in the pages read.", "muted"))
    return out


def _website_section(rep, intel):
    ws = intel.get("website") if intel and "error" not in intel else None
    gq = rep.get("guest_questions", {})
    out = [PageBreak(), H1("Website support"),
           para("Does the website explain the strengths, policies and facts found elsewhere, and can public crawlers read it? "
                "This is one pillar of the report, not the whole audit.", "muted")]
    if ws:
        out += [para("Claims made elsewhere that the website does not back up (check 30)", "h2")]
        if ws["external_facts_missing_on_site"]:
            out.append(table([["Others say", "Hint"]] + [[r["item"], r["action_hint"]] for r in ws["external_facts_missing_on_site"]], [0.5, 0.5]))
        else:
            out.append(para("Nothing found in independent coverage that the website fails to say.", "base"))
        ca = ws["crawler_access"]
        out.append(kv([("robots.txt present", str(ca["robots_txt_present"])), ("Blocks all crawlers", str(ca["blocks_all"])),
                       ("AI crawlers blocked", ", ".join(ca["ai_crawlers_blocked"]) or "none"),
                       ("Sitemap", "yes" if ca["sitemap"] else "not found"),
                       ("Structured data (Hotel/LodgingBusiness)", "yes" if ca["structured_data_found"] else "not found"),
                       ("Press / awards page", "found" if ws["has_press_or_awards_page"] else "not found among pages read")]))
    out += [para("Guest questions the website answers", "h2")]
    qs = gq.get("questions", [])
    if qs:
        rows = [["Question", "State", "Evidence from the website", "Page"]]
        for q in qs:
            rows.append([q["short"], q.get("state_label") or q["state"], (q.get("snippet") or q.get("note") or "")[:200],
                         P_link(q["source_url"]) if q.get("source_url") else ""])
        out.append(table(rows, [0.14, 0.14, 0.52, 0.2]))
        out.append(para(f"{gq.get('pages_ok', 0)} of {gq.get('pages_attempted', 0)} pages were read. 'Not found on the pages checked' "
                        "means we looked and found no clear answer on those pages - it does not prove the information is absent.", "tiny"))
    if gq.get("fact_sheet"):
        out += [para("Fact sheet read from the website", "h3"),
                table([["Fact", "Value", "From"]] + [[f["fact"], str(f["value"])[:120], P_link(f.get("source_url"))] for f in gq["fact_sheet"]],
                      [0.18, 0.5, 0.32])]
    fixes = rep.get("top_fixes", [])
    consult_ok = bool(rep.get("consultant")) and "error" not in (rep.get("consultant") or {})
    if fixes and not consult_ok:       # with the consultant analysis these examples live once, in the recommendation register
        out += [para("Top website fixes with worked examples", "h2")]
        for f in fixes:
            out.append(P(f"<b>{esc(f['action'])}</b> - owner: {esc(f.get('owner', ''))}; page: " + link(f.get("page", "")), "base"))
            if f.get("why"):
                out.append(para(f["why"], "muted"))
            if f.get("example"):
                out.append(Preformatted(_wrap_code(clean(f["example"])), S["code"]))
            out.append(Spacer(1, 3))
    return out


def _wrap_code(text, width=118):
    lines = []
    for ln in text.splitlines():
        while len(ln) > width:
            lines.append(ln[:width])
            ln = "    " + ln[width:]
        lines.append(ln)
    return "\n".join(lines)


def _recommendations_section(intel):
    out = [PageBreak(), para("Detailed recommendations", "h1"),
           para("Each recommendation states the problem, its evidence, why it matters, the exact action, the responsible team, a "
                "priority with its rationale, and how to check success. 'Basis' separates documented platform/regulator guidance from "
                "hypotheses. None guarantees an AI recommendation.", "muted")]
    order = {s["id"]: i for i, s in enumerate(intel["sections"])}
    recs = sorted(intel["recommendations"], key=lambda r: (order.get(r["section"], 99), ))
    ledger = {e["id"]: e for e in intel["ledger"]}
    cur = None
    titles = {s["id"]: s["title"] for s in intel["sections"]}
    for r in recs:
        heading = None
        if r["section"] != cur:
            cur = r["section"]
            heading = para(titles.get(cur, cur), "h2")
        ev = ", ".join(r["evidence_ids"]) or "none (the finding is the absence of data, or a stated gap)"
        rows = [[Markup(f"<b>{esc(r['title'])}</b>"), f"{r['priority'].upper()} - {r['team']}"],
                ["Problem / opportunity", r["problem"]], ["Evidence", ev],
                ["Why it matters", r["why_it_matters"]], ["Action", r["action"]],
                ["Priority rationale", r["priority_why"]], ["Success check", r["success_check"]],
                ["Basis", r["basis"] + (": " + r["basis_note"] if r["basis_note"] else "")]]
        block = [table(rows, [0.2, 0.8], header=False, zebra=False)]
        if r.get("example"):
            block.append(Preformatted(_wrap_code(clean(r["example"])), S["code"]))
        block.append(Spacer(1, 5))
        # a group heading always travels with the first card, never alone at a page bottom
        out.append(KeepTogether(([heading] if heading else []) + block[:1]))
        out += block[1:]
    return out


def _gaps_section(intel):
    m = intel["methodology"]
    out = [PageBreak(), H1("Coverage gaps and methodology"),
           para("All 30 checks and their status", "h2")]
    rows = [["#", "Check", "Section", "Status", "Result / reason"]]
    titles = {s["id"]: s["title"].split(" and ")[0] for s in intel["sections"]}
    for c in intel["checks"]:
        rows.append([str(c["n"]), c["name"] + (" (inferred)" if c["inference"] else ""), titles.get(c["section"], c["section"]),
                     coloured(STATUS_LABEL[c["status"]], STATUS_COLOUR[c["status"]]), _summary_reason(c)])
    out.append(table(rows, [0.04, 0.2, 0.12, 0.1, 0.54]))
    out += [para("Sources used in this run", "h2")]
    rows = [["Source", "Status", "Items", "Note"]]
    for s in m["sources_this_run"]:
        rows.append([s["source"], coloured(s["status"].replace("_", " "), STATUS_COLOUR.get(s["status"], GREY)), str(s["items"]), s["reason"]])
    out.append(table(rows, [0.22, 0.13, 0.07, 0.58]))
    if m["queries"]:
        out += [para(f"Searches run ({m['tavily_credits_used']} Tavily free-plan credits)", "h3"),
                table([["Purpose", "Query", "Results"]] + [[q["role"], q["query"][:110] + (" - ERROR: " + q["error"] if q["error"] else ""), str(q["n_results"])]
                                                           for q in m["queries"]], [0.14, 0.76, 0.1])]
    r = m["reads"]
    if r:
        out.append(para(f"Pages read: {r.get('ok', 0)} read, {r.get('robots_blocked', 0)} declined by robots.txt, "
                        f"{r.get('failed', 0)} failed" + ("; the time budget was reached." if r.get("budget_hit") else "."), "muted"))
    for n in m["notes"]:
        out.append(para(n, "note"))
    out += [para("Principles", "h2")] + bullets(m["principles"])
    out += [para("What each source returns, its limits and cost", "h2")]
    out.append(table([["Source", "Cost", "Needs", "Returns", "Limits"]] +
                     [[s["name"], s["cost"], s["needs"], s["returns"], s["limits"]] for s in m["source_catalogue"]],
                     [0.16, 0.16, 0.1, 0.32, 0.26]))
    out += [para("Sources deliberately NOT used", "h3"),
            table([["Source", "Why not"]] + [[x["name"], x["why"]] for x in m["excluded_sources"]], [0.38, 0.62]),
            para("Text in this PDF uses standard PDF fonts, so characters outside the Western European set may appear as '?'.", "tiny")]
    return out


def _evidence_appendix(intel):
    out = [PageBreak(), para("Evidence appendix", "h1"),
           para("Every record the findings rest on. 'Observed' = we read it; 'inference' = a conclusion drawn from observed "
                "evidence; match confidence says how sure we are that the source is about THIS hotel.", "muted")]
    rows = [["ID", "Source (type)", "Published / collected", "Match", "Kind", "Extract", "URL"]]
    for e in intel["ledger"]:
        rows.append([e["id"], f"{e['source']} ({e['source_type'].replace('_', ' ')})",
                     f"{e['published'] or 'n/a'} / {_date(e['collected_at'])}", f"{e['match']}" + (f": {e['match_why'][:50]}" if e["match_why"] else ""),
                     e["kind"], e["extract"][:260], P_link(e["url"], maxlen=48) if e["url"] else ""])
    out.append(table(rows, [0.075, 0.15, 0.11, 0.13, 0.07, 0.295, 0.17]))
    return out


def build_story(rep, part="full"):
    """part: 'management' (short), 'appendix' (detail and evidence) or 'full' (both, in that order)."""
    import report_pdf_mgmt
    _COUNTER[0] = 0
    consult = rep.get("consultant") or {}
    has_consult = bool(consult) and "error" not in consult
    if part == "appendix" or not has_consult:
        return _appendix_story(rep)
    mgmt = report_pdf_mgmt.story(rep, H1)
    if part == "management":
        return mgmt
    _COUNTER[0] = 0
    return mgmt + [PageBreak()] + _appendix_story(rep)


TITLES = {"management": "management report", "appendix": "technical & evidence appendix", "full": "discovery & reputation report"}


def build_pdf(rep, part="full"):
    """-> bytes. Raises nothing for missing optional sections."""
    buf = io.BytesIO()
    hotel = rep.get("meta", {}).get("hotel", "Hotel")
    label = TITLES.get(part, TITLES["full"])
    header = f"{hotel} - {label} - {_date(rep.get('meta', {}).get('run_at'))}"

    class _Canvas(NumberedCanvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.header_text = header

    doc = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=17 * mm,
                            bottomMargin=17 * mm, title=clean(f"{hotel} - {label}"),
                            author="Hotel Discoverability Audit", subject="Hotel discovery and reputation report")
    doc.build(build_story(rep, part), canvasmaker=_Canvas)
    return buf.getvalue()


def filename(rep, part="full"):
    meta = rep.get("meta", {})
    slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("hotel") or "hotel").lower()).strip("-")
    kind = {"management": "management-report", "appendix": "technical-evidence-appendix", "full": "discovery-report"}.get(part, "discovery-report")
    return f"{slug}-{kind}-{_date(meta.get('run_at')) or dt.date.today().isoformat()}.pdf"
