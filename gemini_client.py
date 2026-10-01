"""
Gemini grounded-search client for the hotel AI discoverability audit.

Purpose: send a natural-language query to Gemini WITH Google Search grounding
and capture (a) the answer text and (b) the source URLs the model actually
cited. Both are stored verbatim as the audit's evidence trail.

Design notes:
- Targets the current /v1beta/interactions endpoint.
- Falls back to the legacy :generateContent + google_search tool if the
  interactions endpoint is unavailable, so the tool survives API churn.
- Never fabricates. If a call fails, the failure is recorded as a failure;
  it is not silently treated as "hotel not mentioned".
"""

import json
import os
import re
import threading
import time
import urllib.parse
import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"

# Verified against a live ListModels call (Sept 2026). gemini-2.0-flash is not
# returned at all any more, and gemini-2.5-flash IS returned by ListModels but
# rejects every call with "no longer available to new users" - so appearing in
# the model list is not proof a model can be called. Both were offered in the
# app's model picker and both were dead.
SELECTABLE_MODELS = [
    "gemini-3.8-flash",   # newest; can 503 under load, retried by _post_with_retry
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",   # verified working
    "gemini-flash-latest",
]


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key=None, model=DEFAULT_MODEL, pause=2.0, verbose=True):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise GeminiError("No API key. Set GEMINI_API_KEY or pass api_key=.")
        self.model = model
        self.pause = pause          # seconds between calls (free-tier RPM safety)
        self.verbose = verbose
        self.mode = None            # resolved on first successful call
        self.calls_made = 0
        self._lock = threading.Lock()  # this client is shared across worker threads

    # ---------- transport ----------

    def _post(self, path, payload, timeout=120):
        url = f"{API_ROOT}/{path}"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        return requests.post(url, headers=headers, json=payload, timeout=timeout)

    def _post_with_retry(self, path, payload, attempts=4):
        delay = 5
        last = None
        for i in range(attempts):
            try:
                r = self._post(path, payload)
            except requests.RequestException as e:
                last = f"network error: {e}"
                print(f"    [gemini] network error - retrying in {delay}s: {e}")
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                print(f"    [gemini] HTTP {r.status_code} - retrying in {delay}s "
                      f"(attempt {i+1}/{attempts})...")
                time.sleep(delay)
                delay *= 2
                continue
            # 400/403/404 are structural - do not retry
            raise GeminiError(f"HTTP {r.status_code}: {r.text[:600]}")
        raise GeminiError(f"exhausted retries. last: {last}")

    # ---------- grounded query ----------

    def ask_grounded(self, query):
        """
        Returns dict:
          ok, query, answer, citations[{url,title}], search_queries[], mode, error
        """
        out = {
            "query": query,
            "ok": False,
            "answer": "",
            "citations": [],
            "search_queries": [],
            "search_suggestions_html": "",
            "mode": None,
            "error": None,
        }

        # first call probes both transports; later calls reuse what worked
        order = ["interactions", "generate"] if self.mode is None else [self.mode]

        last_err = None
        for mode in order:
            try:
                if mode == "interactions":
                    data = self._post_with_retry(
                        "interactions",
                        {
                            "model": self.model,
                            "input": query,
                            "tools": [{"type": "google_search"}],
                        },
                    )
                    parsed = self._parse_interactions(data)
                else:
                    data = self._post_with_retry(
                        f"models/{self.model}:generateContent",
                        {
                            "contents": [{"parts": [{"text": query}]}],
                            "tools": [{"google_search": {}}],
                        },
                    )
                    parsed = self._parse_generate(data)

                with self._lock:
                    self.calls_made += 1

                # A 200 that parses to nothing is a parse failure, not an
                # answer. Treating it as success is exactly how a broken parser
                # turns into "the hotel was never mentioned" across a whole
                # run, with no error anywhere. Raise so the next transport is
                # tried and, if both fail, the row is recorded as a failure.
                if not parsed["answer"].strip():
                    raise GeminiError(
                        f"{mode}: HTTP 200 but no answer text could be parsed "
                        f"from the response (top-level keys: "
                        f"{sorted(data.keys()) if isinstance(data, dict) else type(data).__name__})"
                    )

                with self._lock:
                    self.mode = mode
                out.update(parsed)
                out["ok"] = True
                out["mode"] = mode
                out["raw"] = data
                out["search_suggestions_html"] = find_search_suggestions(data)
                time.sleep(self.pause)
                return out
            except GeminiError as e:
                last_err = str(e)
                continue

        out["error"] = last_err
        return out

    # ---------- response parsers ----------

    @staticmethod
    def _parse_interactions(data):
        """
        Parse the /v1beta/interactions response.

        The live schema (post the May 2026 breaking change) is a flat `steps`
        array where each step carries a `type` discriminator and its payload at
        the TOP LEVEL of the step:

            {"type": "google_search_call", "arguments": {"queries": [...]}}
            {"type": "google_search_result", "result": [{"search_suggestions": "<html>"}]}
            {"type": "model_output", "content": [{"type": "text", "text": ...,
                                                  "annotations": [{"type": "url_citation", ...}]}]}

        An earlier draft looked for a nested key named after the step type
        (step["google_search_call"]), which never exists - so it silently
        returned an empty answer with no citations for every single query,
        while ask_grounded still reported success. Both shapes are accepted
        now: the flat one is what the API actually returns, the nested one
        costs nothing to keep in case Google moves it back.
        """
        answer_parts, citations, searches = [], [], []

        # `outputs` was the pre-May-2026 name for `steps`.
        steps = data.get("steps") or data.get("outputs") or []

        for step in steps:
            if not isinstance(step, dict):
                continue
            stype = step.get("type")

            # --- the search queries the model actually issued
            if stype == "google_search_call" or "google_search_call" in step:
                gsc = step.get("google_search_call") or step
                args = gsc.get("arguments") or gsc
                for q in args.get("queries") or []:
                    if isinstance(q, str):
                        searches.append(q)
                continue

            # --- the answer text, and the citations annotated onto it
            if stype == "model_output" or "model_output" in step:
                mo = step.get("model_output") or step
                for block in mo.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("text"):
                        answer_parts.append(block["text"])
                    for ann in block.get("annotations") or []:
                        if isinstance(ann, dict) and ann.get("url"):
                            citations.append(
                                {"url": ann["url"], "title": ann.get("title", "")}
                            )
                continue

        # some responses expose a flattened convenience field
        if not answer_parts and data.get("output_text"):
            answer_parts.append(data["output_text"])
        return {
            "answer": "\n".join(answer_parts).strip(),
            "citations": _dedupe_citations(citations),
            "search_queries": sorted(set(searches)),
        }

    @staticmethod
    def _parse_generate(data):
        answer_parts, citations, searches = [], [], []
        for cand in data.get("candidates", []):
            for part in (cand.get("content") or {}).get("parts", []) or []:
                if part.get("text"):
                    answer_parts.append(part["text"])
            gm = cand.get("groundingMetadata") or {}
            for q in gm.get("webSearchQueries", []) or []:
                searches.append(q)
            for chunk in gm.get("groundingChunks", []) or []:
                web = chunk.get("web") or {}
                if web.get("uri"):
                    citations.append(
                        {"url": web["uri"], "title": web.get("title", "")}
                    )
        return {
            "answer": "\n".join(answer_parts).strip(),
            "citations": _dedupe_citations(citations),
            "search_queries": sorted(set(searches)),
        }

    # ---------- ungrounded structured extraction ----------

    def extract_json(self, prompt, attempts=2):
        """
        Ungrounded call used only to turn an answer into structured data.
        Returns parsed JSON or None. Never invents audit facts - it only
        reformats text the grounded call already produced.
        """
        for _ in range(attempts):
            try:
                if self.mode == "generate":
                    data = self._post_with_retry(
                        f"models/{self.model}:generateContent",
                        {"contents": [{"parts": [{"text": prompt}]}]},
                    )
                    parsed = self._parse_generate(data)
                else:
                    data = self._post_with_retry(
                        "interactions", {"model": self.model, "input": prompt}
                    )
                    parsed = self._parse_interactions(data)
                with self._lock:
                    self.calls_made += 1
                time.sleep(self.pause)
                blob = _find_json(parsed["answer"])
                if blob is not None:
                    return blob
            except GeminiError:
                time.sleep(3)
        return None


# ---------- helpers ----------

def _dedupe_citations(cites):
    seen, out = set(), []
    for c in cites:
        key = c["url"]
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _find_json(text):
    """Pull the first JSON object/array out of a model response."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def find_search_suggestions(data):
    """
    Google's terms require Grounded Results to be displayed with the
    associated Search Suggestion(s). The field name has moved between API
    versions, so search the whole response for it rather than assuming a path.
    Returns the rendered HTML string, or "".
    """
    hit = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower().replace("_", "")
                if kl in ("renderedcontent", "renderedhtml") and isinstance(v, str):
                    hit.append(v)
                elif kl in ("searchentrypoint", "searchsuggestions") and isinstance(v, str):
                    hit.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return hit[0] if hit else ""


def resolve_domain(url_or_domain):
    """Normalise a website input to a bare registrable-ish domain."""
    s = (url_or_domain or "").strip().lower()
    if not s:
        return ""
    if "//" not in s:
        s = "https://" + s
    host = urllib.parse.urlparse(s).netloc
    return host[4:] if host.startswith("www.") else host
