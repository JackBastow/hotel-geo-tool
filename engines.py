"""
Which AI assistants a report actually tested, and which it did not. Only an assistant that was really asked is shown as tested; the rest are listed as NOT tested, so nobody reads the report as saying what
ChatGPT, Gemini or Google AI Overviews recommend when nothing was asked of them. When another assistant is added later (through its own API, with web search), it is added here and its row turns to 'tested'.
"""

import ai_sample

# name, maker, how the audit could ask it, and why it is not tested today
OTHERS = [("ChatGPT", "OpenAI", "Not tested. The audit has not asked ChatGPT anything. Test it by hand with the checklist in the appendix."),
          ("Gemini", "Google", "Not tested. The audit has not asked Gemini anything. Test it by hand with the checklist in the appendix."),
          ("Google AI Overviews", "Google Search", "Not tested. Google offers no way to ask for these, so they can only be checked by searching Google yourself."),
          ("Microsoft Copilot", "Microsoft", "Not tested. Test it by hand with the checklist in the appendix."),
          ("Perplexity", "Perplexity", "Not tested. Test it by hand with the checklist in the appendix.")]


def rows(rep):
    """-> [{"name", "maker", "tested" (bool), "detail"}], the tested assistant(s) first."""
    ai = (rep or {}).get("ai_sample") or {}
    out = []
    if ai.get("status") == "ok":
        log = ai_sample.test_log(ai) or {}
        sm = log.get("summary") or {}
        where = f", searching as if from {ai['search_country']}" if ai.get("search_country") else ""
        n_all = len(ai.get("items") or [])
        out.append({"name": "Claude", "maker": "Anthropic", "tested": True,
                    "detail": f"Tested: {ai.get('model', 'Claude')} with live web search{where}, on {log.get('date') or 'the audit date'}. {sm.get('prompts', 0)} different prompts, {n_all} answers in all."})
    else:
        out.append({"name": "Claude", "maker": "Anthropic", "tested": False, "detail": "Not tested in this audit: " + (ai.get("reason") or "the AI sample was not run.")})
    out += [{"name": n, "maker": m, "tested": False, "detail": d} for n, m, d in OTHERS]
    return out
