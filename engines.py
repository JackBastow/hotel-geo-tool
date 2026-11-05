"""
Which AI assistant a report actually asked, and how much. Only an assistant that was really asked appears; nothing is said about assistants that were not asked. When another assistant is added later (through its
own API, with web search) it is added here and gets its own row.
"""

import ai_sample


def rows(rep):
    """-> [{"name", "maker", "tested" (bool), "detail"}]: the assistant(s) asked in this audit."""
    ai = (rep or {}).get("ai_sample") or {}
    if ai.get("status") != "ok":
        return [{"name": "Claude", "maker": "Anthropic", "tested": False, "detail": "Not asked in this audit: " + (ai.get("reason") or "the AI sample was not run.")}]
    log = ai_sample.test_log(ai) or {}
    where = f", searching as if from {ai['search_country']}" if ai.get("search_country") else ""
    items = ai.get("items") or []
    by_q = {}
    for i in items:
        k = i.get("qid") or i.get("id")
        by_q[k] = by_q.get(k, 0) + 1
    top = max(by_q.values()) if by_q else 0
    return [{"name": "Claude", "maker": "Anthropic", "tested": True,
             "detail": f"Tested: {ai.get('model', 'Claude')} with live web search{where}, on {log.get('date') or 'the audit date'}. {len(by_q)} different prompts, {len(items)} answers in all"
                       + (f"; the most important prompts were each asked {top} times." if top > 1 else ".")}]
