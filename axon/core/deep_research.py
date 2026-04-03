"""
deep_research.py — Autonomous multi-step research engine for Axon.

Pipeline:
  1. LLM breaks user topic into sub-questions + search queries.
  2. For each sub-question: DuckDuckGo search → fetch pages → LLM summarize.
  3. LLM synthesizes all findings into a structured report with citations.
  4. Report saved as .md and .pdf; download links streamed to the client.

All progress is yielded as SSE events so the frontend can render a live panel.
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime

import markdown as _markdown
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from tavily import TavilyClient

from config import Config

log = logging.getLogger("deep_research")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")

# ── Source quality filtering ────────────────────────────

_BLOCKED_DOMAINS = {
    "baidu.com", "zhihu.com", "zhidao.baidu.com", "weibo.com",
    "qq.com", "163.com", "sina.com.cn", "sohu.com", "ifeng.com",
}
_BLOCKED_TLDS = {".cn", ".ru", ".jp", ".de", ".fr", ".kr", ".pl", ".cz"}
_PREFERRED_DOMAINS = [
    "wikipedia.org", "britannica.com", "history.com", "smithsonianmag.com",
    "nationalgeographic.com", "bbc.com", "theguardian.com", "nytimes.com",
    "reuters.com", "nature.com", "science.org", "arxiv.org",
    "scientificamerican.com", "pbs.org", "apnews.com",
]

# ── Prompts ────────────────────────────────────────────

_PLAN_SYSTEM = (
    "You are a research planning assistant. "
    "Given a topic, break it into 4-6 focused sub-questions that together cover "
    "the topic comprehensively. For each sub-question, write a concise DuckDuckGo "
    "search query.\n\n"
    "Respond ONLY with valid JSON — no markdown, no code fences:\n"
    '{"sub_questions": [\n'
    '  {"question": "...", "search_query": "..."},\n'
    "  ...\n"
    "]}"
)

_SUMMARIZE_SYSTEM = (
    "You are a meticulous research analyst. "
    "You will receive a sub-question and extracted text from several web pages. "
    "Write a detailed, informative summary of the key findings relevant to the sub-question. "
    "Your summary MUST:\n"
    "- Be at least 300 words\n"
    "- Include specific facts, statistics, names, dates, and figures from the sources\n"
    "- Quote or closely paraphrase important details — do not be vague\n"
    "- Cite the source URL inline for each key fact using [Source: URL] notation\n"
    "- Be written in well-structured paragraphs (not bullet points)\n"
    "- Cover multiple angles and perspectives from the sources\n"
    "Do not truncate. Write until all key information is captured."
)

_SYNTHESIZE_SYSTEM = (
    "You are an expert research writer for Axon AI. "
    "You will receive findings from multiple research sub-questions. "
    "Write a comprehensive, well-structured report in markdown. "
    "The report MUST be at least 2500 words — do not stop early.\n\n"
    "Required structure:\n"
    "# {topic}\n\n"
    "## Executive Summary\n"
    "A detailed 3-4 paragraph overview covering the most important findings, "
    "key facts, and overall significance.\n\n"
    "## {One section per sub-question — use a descriptive heading}\n"
    "Full analysis of each sub-question with all supporting evidence, quotes, data, "
    "and inline citations [1], [2], etc. Each section should be 3-5 substantial paragraphs.\n\n"
    "## Timeline of Key Events (if applicable)\n"
    "A markdown table with columns: | Date | Event | Significance |\n\n"
    "## Conclusion\n"
    "2-3 paragraphs synthesizing the key takeaways, patterns, and implications.\n\n"
    "## Sources\n"
    "Numbered list: [1] Title — URL\n\n"
    "Rules:\n"
    "- Minimum 2500 words. Write substantively — do not pad but do not truncate\n"
    "- Use proper markdown: headers, **bold**, *italic*, tables, bullet points\n"
    "- Every factual claim must have an inline citation [N]\n"
    "- Write in authoritative, encyclopedic prose\n"
    "- Do NOT use meta-commentary like 'Based on our research' or 'In this report'"
)


# ── Helpers ────────────────────────────────────────────

def _sse(obj):
    return "data: " + json.dumps(obj) + "\n\n"


def _get_client(base_url=None):
    url = base_url or Config.LM_STUDIO_URL
    return OpenAI(base_url=url, api_key=Config.LM_STUDIO_API_KEY, timeout=120.0)


def _llm_call(client, model_id, system_prompt, user_content, max_tokens=1000):
    """Non-streaming LLM call. Returns the response text."""
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        stream=False,
        temperature=0.5,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _topic_slug(topic, max_words=5):
    words = re.sub(r"[^\w\s]", "", topic).lower().split()[:max_words]
    return "_".join(words) or "research"


def _search_web(query, max_results=7):
    """DuckDuckGo search — reuses same approach as deepthink."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw if r.get("href")
        ]
    except Exception as e:
        log.warning("Search failed for %r: %s", query, e)
        return []


def _search_tavily(query, max_results=5):
    """Tavily search — returns clean content per result, no extra fetch needed."""
    try:
        client = TavilyClient(api_key=Config.TAVILY_API_KEY)
        resp = client.search(
            query,
            search_depth="advanced",
            include_answer=False,
            max_results=max_results,
        )
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            }
            for r in resp.get("results", [])
            if r.get("url") and r.get("content")
        ]
    except Exception as e:
        log.warning("Tavily search failed for %r: %s", query, e)
        return []


def _is_quality_url(url):
    """Return False if URL is from a blocked domain or unfavoured TLD."""
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        for blocked in _BLOCKED_DOMAINS:
            if hostname == blocked or hostname.endswith("." + blocked):
                return False
        for tld in _BLOCKED_TLDS:
            if hostname.endswith(tld):
                return False
        return True
    except Exception:
        return True


def _quality_score(url):
    """Lower is better. Preferred English-language encyclopedic sources = 0."""
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        for pref in _PREFERRED_DOMAINS:
            if pref in hostname:
                return 0
        return 1
    except Exception:
        return 1


def _fetch_page(url, max_chars=4000):
    """Fetch and clean a web page. Returns (title, text)."""
    try:
        resp = requests.get(url, timeout=10, headers=_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return title, text[:max_chars]
    except Exception:
        return "", ""


def _markdown_to_pdf(md_content, output_path):
    """Convert markdown to PDF using weasyprint."""
    try:
        from weasyprint import HTML
        html_body = _markdown.markdown(
            md_content, extensions=["tables", "fenced_code", "toc"]
        )
        full_html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>"
            "body { font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; "
            "margin: 40px auto; padding: 0 20px; line-height: 1.7; color: #222; } "
            "h1 { font-size: 26px; border-bottom: 2px solid #333; padding-bottom: 8px; } "
            "h2 { font-size: 20px; color: #333; margin-top: 32px; } "
            "h3 { font-size: 16px; color: #555; } "
            "a { color: #0066cc; } "
            "blockquote { border-left: 3px solid #ccc; padding-left: 1em; color: #555; } "
            "code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 14px; } "
            "pre { background: #f4f4f4; padding: 12px; border-radius: 6px; overflow-x: auto; } "
            "ul, ol { padding-left: 24px; } "
            "table { border-collapse: collapse; width: 100%; margin: 16px 0; } "
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; } "
            "th { background: #f4f4f4; }"
            "</style></head><body>"
            + html_body
            + "</body></html>"
        )
        HTML(string=full_html).write_pdf(output_path)
        return True
    except Exception as e:
        log.error("PDF generation failed: %s", e)
        return False


# ── Main Research Engine ───────────────────────────────

class DeepResearch:
    def __init__(self, base_url=None, model_id=None):
        self.base_url = base_url or Config.LM_STUDIO_URL
        # Default to Slot 1 (Chat model)
        self.model_id = model_id or Config.MODEL_SLOTS[0]["model_id"]
        self.client = _get_client(self.base_url)

    def plan(self, topic):
        """Ask the LLM to decompose the topic into sub-questions + queries."""
        raw = _llm_call(
            self.client, self.model_id, _PLAN_SYSTEM,
            "Research topic: " + topic,
            max_tokens=800,
        )
        # Strip markdown code fences if the model wrapped it
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
        return json.loads(raw)

    def search_and_fetch(self, query, max_pages=5):
        """Tavily search — already returns clean content, no page fetching needed."""
        results = _search_tavily(query, max_results=max_pages)
        # Filter blocked domains / TLDs just in case
        results = [r for r in results if _is_quality_url(r["url"])]
        # Sort preferred sources first
        results.sort(key=lambda r: _quality_score(r["url"]))
        return results

    def summarize_findings(self, sub_question, sources):
        """Summarize fetched data for one sub-question."""
        source_text = "\n\n---\n\n".join(
            "[Source: %s]\nTitle: %s\n%s" % (s["url"], s["title"], s["content"])
            for s in sources
        )
        user_msg = "Sub-question: %s\n\nSources:\n%s" % (sub_question, source_text)
        return _llm_call(
            self.client, self.model_id, _SUMMARIZE_SYSTEM,
            user_msg, max_tokens=2000,
        )

    def synthesize(self, topic, all_findings):
        """Produce the final structured report."""
        findings_text = "\n\n===\n\n".join(
            "## Sub-question: %s\n\n%s\n\nSources consulted:\n%s" % (
                f["question"],
                f["summary"],
                "\n".join("- %s (%s)" % (s["title"], s["url"]) for s in f["sources"]),
            )
            for f in all_findings
        )
        user_msg = "Topic: %s\n\nFindings:\n%s" % (topic, findings_text)
        return _llm_call(
            self.client, self.model_id, _SYNTHESIZE_SYSTEM,
            user_msg, max_tokens=6000,
        )

    def save_report(self, report_md, topic):
        """Save .md and .pdf to reports/ folder. Returns {md_path, pdf_path, md_filename, pdf_filename}."""
        os.makedirs(_REPORTS_DIR, exist_ok=True)
        slug = _topic_slug(topic)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = "research_%s_%s" % (slug, ts)
        md_filename = base + ".md"
        pdf_filename = base + ".pdf"
        md_path = os.path.join(_REPORTS_DIR, md_filename)
        pdf_path = os.path.join(_REPORTS_DIR, pdf_filename)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        pdf_ok = _markdown_to_pdf(report_md, pdf_path)

        return {
            "md_path": md_path,
            "pdf_path": pdf_path if pdf_ok else None,
            "md_filename": md_filename,
            "pdf_filename": pdf_filename if pdf_ok else None,
        }

    def run(self, topic):
        """
        Main generator — yields SSE events for every step.

        Event types:
          {"type": "status", "step": "..."} — progress line
          {"type": "plan", "sub_questions": [...]} — research plan
          {"type": "finding", "index": N, "question": "...", "summary": "...", "sources": [...]}
          {"type": "report", "markdown": "...", "md_file": "...", "pdf_file": "..."}
          {"token": "..."} — for streaming the final report into the chat bubble
          {"done": true}
        """
        start_time = time.time()
        all_sources_flat = []

        # ── Phase 1: Planning ──────────────────────────
        yield _sse({"type": "status", "step": "Creating research plan..."})
        try:
            plan = self.plan(topic)
            sub_questions = plan.get("sub_questions", [])
        except Exception as e:
            log.error("Planning failed: %s", e)
            yield _sse({"type": "status", "step": "⚠️ Planning failed — using topic as single query"})
            sub_questions = [{"question": topic, "search_query": topic}]

        sq_count = len(sub_questions)
        yield _sse({"type": "status", "step": "✅ Research plan created (%d sub-questions)" % sq_count})
        yield _sse({"type": "plan", "sub_questions": sub_questions})

        # ── Phase 2: Search + summarize each sub-question ──
        all_findings = []
        for i, sq in enumerate(sub_questions, 1):
            question = sq.get("question", "")
            query = sq.get("search_query", question)

            yield _sse({"type": "status", "step": '🔍 Searching: "%s"...' % query})

            sources = self.search_and_fetch(query)
            if not sources:
                yield _sse({"type": "status", "step": "⚠️ No sources found for sub-question %d" % i})
                all_findings.append({
                    "question": question,
                    "summary": "No sources found for this sub-question.",
                    "sources": [],
                })
                continue

            yield _sse({
                "type": "status",
                "step": "✅ Read %d sources for sub-question %d/%d" % (len(sources), i, sq_count),
            })

            yield _sse({"type": "status", "step": "⚙️ Summarizing findings for: %s..." % question[:60]})
            try:
                summary = self.summarize_findings(question, sources)
            except Exception as e:
                log.error("Summarize failed for %r: %s", question, e)
                summary = "Summarization failed for this sub-question."

            finding = {"question": question, "summary": summary, "sources": sources}
            all_findings.append(finding)
            all_sources_flat.extend(sources)

            yield _sse({
                "type": "finding",
                "index": i,
                "question": question,
                "summary": summary,
                "sources": [{"url": s["url"], "title": s["title"]} for s in sources],
            })

        # ── Phase 3: Synthesis ─────────────────────────
        yield _sse({"type": "status", "step": "⚙️ Synthesizing findings into report..."})
        try:
            report_md = self.synthesize(topic, all_findings)
        except Exception as e:
            log.error("Synthesis failed: %s", e)
            # Fallback: concatenate findings
            parts = ["# Research: %s\n" % topic]
            for f in all_findings:
                parts.append("## %s\n\n%s\n" % (f["question"], f["summary"]))
            report_md = "\n".join(parts)

        word_count = len(report_md.split())
        elapsed = int(time.time() - start_time)
        yield _sse({
            "type": "status",
            "step": "✅ Report complete — %d words (%d min %ds)" % (
                word_count, elapsed // 60, elapsed % 60
            ),
        })

        # ── Phase 4: Save report files ─────────────────
        yield _sse({"type": "status", "step": "💾 Saving report files..."})
        report_info = self.save_report(report_md, topic)

        # Stream the full report as tokens so it renders in the chat bubble
        yield _sse({"token": report_md})

        # Send sources list for the collapsible "See my thinking" panel
        yield _sse({
            "type": "sources",
            "urls": list({s["url"] for s in all_sources_flat}),
        })

        # Send report metadata so frontend can show download buttons
        yield _sse({
            "type": "report",
            "md_file": report_info["md_filename"],
            "pdf_file": report_info.get("pdf_filename"),
            "word_count": word_count,
            "elapsed_seconds": elapsed,
        })

        yield _sse({"done": True})
