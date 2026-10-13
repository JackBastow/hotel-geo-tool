"""
Offline tests for claude_reader.py (the fallback page reader). A fake client stands in for the Anthropic SDK:
no network, no credit. Run: python test_claude_reader.py
"""
from types import SimpleNamespace as NS

import claude_reader as cr

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


START = "https://www.hilton.com/en/hotels/lxmhidi-doubletree-luxembourg/"
HOME = ("---\ncanonical: " + START + "\nmeta-description: Book direct\ntitle: Luxembourg Hotels - DoubleTree\n---\n"
        "# DoubleTree by Hilton Luxembourg\n\n![logo](https://www.hilton.com/logo.svg)\n\n"
        "Welcome to our hotel at [12 Rue Jean Engling](https://maps.example/x). Check-in is at 3 pm and check-out at 12 pm. "
        "Call +352 4378 or write to Reception@doubletree-luxembourg.com. Pets are allowed up to 10 kg. Breakfast is a buffet for a fee.\n\n"
        "- [Rooms](" + START + "rooms/?numRooms=1)\n- [Dining](" + START + "dining/)\n- [Another hotel](https://www.hilton.com/en/hotels/parhi-hilton-paris/rooms/)\n"
        "- [Events](" + START + "events/)\n- [Cookies](" + START + "privacy/)\n" +("Padding sentence about the hotel. " * 20))


def doc(url, text, title="t"):
    return NS(type="web_fetch_tool_result", content=NS(type="web_fetch_result", url=url, content=NS(title=title, source=NS(data=text, media_type="text/plain"))))


def err(code="url_not_accessible"):
    return NS(type="web_fetch_tool_result", content=NS(type="web_fetch_tool_result_error", error_code=code))


def resp(blocks, stop="end_turn"):
    return NS(content=blocks + [NS(type="text", text="done", citations=None)], stop_reason=stop,
              usage=NS(input_tokens=20000, output_tokens=200, server_tool_use=NS(web_fetch_requests=len(blocks))))


class Fake:
    def __init__(self, answers, boom=None):
        self.answers, self.calls, self.boom = list(answers), [], boom
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom
        return self.answers.pop(0)


print("1. turning a fetched document into a page")
meta, body = cr.split_front_matter(HOME)
check("the reader's '--- key: value ---' header is separated from the page", meta["title"] == "Luxembourg Hotels - DoubleTree" and body.lstrip().startswith("# DoubleTree"))
p = cr.to_page(START, HOME)
check("it becomes the page dict the audit already understands, flagged text-only with no HTML signals", p["ok"] and p["text_only"] and p["signals"] == {} and p["status"] == 200)
check("markdown is stripped from the text (no link syntax, no image, no heading marks)", "](" not in p["text"] and "![" not in p["text"] and "#" not in p["text"] and "12 Rue Jean Engling" in p["text"])
check("the facts a guest wants survive: times, pets, breakfast", all(w in p["text"] for w in ("3 pm", "12 pm", "Pets are allowed", "Breakfast is a buffet")))
check("title, heading, phone and email are picked out", p["title"] == "Luxembourg Hotels - DoubleTree" and p["h1"] == ["DoubleTree by Hilton Luxembourg"]
      and any("+352 4378" in t for t in p["tels"]) and "Reception@doubletree-luxembourg.com" in p["mails"])
check("links are kept for choosing the next pages", START + "dining/" in p["links"])
check("a page with almost no text is not 'ok'", not cr.to_page(START, "---\n---\nhi")["ok"])

print("2. reading the hotel's pages")
sub = [doc(START + "rooms/", "---\n---\n# Rooms\n" + "A comfortable room with a view. " * 20, "Rooms"), doc(START + "dining/", "---\n---\n# Dining\n" + "Modern European cuisine. " * 20, "Dining"),
       err()]
fake = Fake([resp([doc(START, HOME, "Home")]), resp(sub)])
r = cr.read_hotel_pages(START, client=fake, progress=lambda m: None)
check("two requests: the hotel's page first, then its sub-pages", len(fake.calls) == 2 and r["status"] == "ok")
check("each request uses the fetch tool, allowing exactly as many fetches as URLs asked for",
      all(c["tools"][0]["type"] == "web_fetch_20250910" and c["tools"][0]["max_uses"] == len([ln for ln in c["messages"][0]["content"].splitlines() if ln.startswith("http")]) for c in fake.calls))
asked = [ln for ln in fake.calls[1]["messages"][0]["content"].splitlines() if ln.startswith("http")]
check("it stays inside this hotel's own folder: no other hotel, no booking or privacy pages",
      asked and all(u.startswith(START) for u in asked) and not any("paris" in u or "privacy" in u or "numRooms" in u for u in asked), asked)
check("the RAW fetched text is what is kept (from the result blocks), not the model's reply", all(p["text_only"] for p in r["pages"]) and "done" not in r["pages"][0]["text"])
ok = [p for p in r["pages"] if p["ok"]]
check("a page the reader could not fetch is recorded as failed, with the reason, not dropped", any((not p["ok"]) and "could not fetch" in p["reason"] for p in r["pages"]) and len(ok) >= 2)
check("cost is tiny and reported", 0 < r["cost_usd"] < 0.01 and r["model"] == "claude-haiku-5-5")

print("3. when it cannot help")
check("no key: not configured, with the reason", cr.read_hotel_pages(START)["status"] == "not_configured")
r = cr.read_hotel_pages(START, client=Fake([resp([err()])]))
check("if the home page cannot be fetched either, it says so and the site stays unread", r["status"] == "unavailable" and "could not read the page either" in r["reason"])


class E(Exception):
    status_code = 429


r = cr.read_hotel_pages(START, client=Fake([], boom=E()))
check("an API failure becomes a stated reason and never raises", r["status"] == "unavailable" and "rate limit" in r["reason"])

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
