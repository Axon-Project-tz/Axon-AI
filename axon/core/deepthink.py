"""
deepthink.py — DeepThink mode for Axon.

Pipeline:
  1. Extract the actual search term from the trigger phrase.
  2. Search DuckDuckGo for top results.
  3. Scrape the text from the top 3 URLs.
  4. Build a synthesis context and stream through LM Studio.
  5. Yield sources event before the final done event.

SSE event types emitted:
  {"type": "status", "step": "..."}   — single updating status line
  {"token": "..."}                    — streaming answer token  (from stream_chat)
  {"type": "sources", "urls": [...]}  — source URLs (emitted before done)
  {"done": true}                      — stream finished            (from stream_chat)
"""

import json
import re
import requests
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
from core.llm import stream_chat


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_SYNTH_PROMPT = (
    "You are Axon in DeepThink mode. You have been given a user question "
    "along with real web search results and scraped page content.\n\n"
    "Your job:\n"
    "1. Answer the question comprehensively using ONLY the provided information.\n"
    "2. Be thorough but concise — use bullet points or numbered lists for clarity.\n"
    "3. If sources disagree, note the disagreement explicitly.\n"
    "4. Never fabricate information not present in the sources.\n"
    "5. Write naturally — do not start with 'Based on the sources' or similar preamble.\n"
    "6. Finish with a brief summary or recommendation where appropriate."
)

# ── Trigger prefixes (ordered longest-first for greedy stripping) ──────────

_STRIP_PATTERNS = [
    r"^\/search\s+",
    r"^\/deep\s+",
    r"^search\s+the\s+web\s+for\s+",
    r"^search\s+for\s+",
    r"^do\s+a\s+deep\s+search\s+(?:for\s+)?",
    r"^deep\s+search\s+(?:for\s+)?",
    r"^look\s+up\s+",
    r"^find\s+information\s+about\s+",
    r"^what\s+does\s+the\s+internet\s+say\s+about\s+",
    r"^research\s+(?:about\s+|for\s+|on\s+|into\s+)?",
]


# ── Public helpers ─────────────────────────────────────

def extract_search_query(user_message):
    """Strip the trigger phrase and return just the search term."""
    msg = user_message.strip()
    for pat in _STRIP_PATTERNS:
        m = re.match(pat, msg, re.IGNORECASE)
        if m:
            remainder = msg[m.end():].strip()
            return remainder if remainder else msg
    return msg


def search_web(query, max_results=7):
    """DuckDuckGo text search. Returns list of {title, url, snippet}."""
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in raw
            if r.get("href")
        ]
    except Exception:
        return []


def fetch_page_content(url, max_chars=2500):
    """Fetch a page and return clean stripped text (empty string on any error)."""
    try:
        resp = requests.get(url, timeout=8, headers=_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def build_synthesis_context(query, search_results, page_contents):
    """Combine search results + page content into an LLM-ready context string."""
    parts = [
        "[DeepThink Research Query]: %s\n" % query,
        "[Web Search Results]:",
    ]
    for i, r in enumerate(search_results, 1):
        parts.append(
            "%d. %s\n   URL: %s\n   %s" % (i, r["title"], r["url"], r["snippet"])
        )
    if page_contents:
        parts.append("\n[Full Page Content from Top Sources]:")
        parts.extend(page_contents)
    parts.append(
        "\n[Task]: Answer the question directly and naturally. "
        "Do not narrate or describe the search results. "
        "Do not say what the user asked. "
        "Do not start with 'The user asked' or 'Based on the search results' or similar phrases. "
        "Just answer as if you already know this information, citing sources naturally in your response."
    )
    return "\n\n".join(parts)


# ── Main streaming function ────────────────────────────

def deepthink_stream(query, model_id, system_prompt, base_url=None):
    """
    Generator yielding SSE strings.
    Emits status events, then streams LM tokens (passing through stream_chat),
    then inserts a sources event before the final done event.
    """

    def sse(obj):
        return "data: " + json.dumps(obj) + "\n\n"

    # Step 1 — Search
    yield sse({"type": "status", "step": "Searching the web..."})

    actual_query = extract_search_query(query)
    results = search_web(actual_query)

    if not results:
        # No results — fall back to normal chat with a note
        yield sse({"type": "status", "step": "No results found — answering from model knowledge..."})
        fallback_msg = "[Web search returned no results for: %s]\n\nAnswer from your own knowledge." % actual_query
        messages = [{"role": "user", "content": fallback_msg}]
        for chunk in stream_chat(messages, model_id, system_prompt, base_url=base_url):
            yield chunk
        return

    urls = [r["url"] for r in results]

    # Step 2 — Fetch top pages
    fetch_count = min(3, len(urls))
    yield sse({"type": "status", "step": "Reading %d sources..." % fetch_count})

    page_contents = []
    fetched_urls = []
    for url in urls[:fetch_count]:
        content = fetch_page_content(url)
        if content:
            page_contents.append("[Source: %s]\n%s" % (url, content))
            fetched_urls.append(url)

    # Step 3 — Synthesize
    yield sse({"type": "status", "step": "Analyzing..."})

    context = build_synthesis_context(actual_query, results, page_contents)
    messages = [{"role": "user", "content": context}]

    # Stream tokens from LM Studio, intercepting the final done event
    # so we can insert the sources event immediately before it.
    source_urls = fetched_urls if fetched_urls else urls[:5]
    sources_sent = False

    for chunk in stream_chat(messages, model_id, _SYNTH_PROMPT, base_url=base_url):
        try:
            payload = chunk.replace("data: ", "").strip()
            parsed = json.loads(payload)
            if "done" in parsed and not sources_sent:
                # Emit sources before the done signal
                yield sse({"type": "sources", "urls": source_urls})
                sources_sent = True
        except Exception:
            pass
        yield chunk
