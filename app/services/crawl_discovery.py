from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.datetime import utc_now
from app.core.config import settings
from app.models import WebsiteCrawlCandidate, WebsiteCrawlJob
from app.services.jobs import JOB_COMPLETED, JOB_FAILED, JOB_PROCESSING

USER_AGENT = "BrainAssistantCrawler/0.1"
HTML_TYPES = ("text/html", "application/xhtml+xml")
SKIP_EXTENSIONS = {
    ".7z", ".avi", ".css", ".csv", ".doc", ".docx", ".gif", ".gz", ".ico", ".jpeg", ".jpg",
    ".js", ".json", ".map", ".mov", ".mp3", ".mp4", ".mpeg", ".pdf", ".png", ".ppt",
    ".pptx", ".rar", ".rss", ".svg", ".tar", ".webm", ".webp", ".xls", ".xlsx", ".xml",
    ".zip",
}
SKIP_PATH_PARTS = {
    "cart", "checkout", "login", "logout", "sign-in", "signin", "signup", "register",
    "wp-admin", "admin", "cdn-cgi", "feed", "tag", "author",
}


@dataclass(frozen=True)
class CrawlCategory:
    id: str
    label: str
    description: str
    patterns: tuple[str, ...]
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveredUrl:
    url: str
    title: str
    depth: int
    source: str


CRAWL_CATEGORIES = [
    CrawlCategory(
        id="policy",
        label="Policy related",
        description="Privacy, refund, shipping, terms, usage, compliance, and governance pages.",
        patterns=(r"privacy", r"policy", r"terms", r"refund", r"return", r"shipping", r"cookie", r"legal"),
        keywords=("privacy", "policy", "terms", "refund", "return", "shipping", "cookie", "legal", "compliance"),
    ),
    CrawlCategory(
        id="company_history",
        label="Company history",
        description="About, mission, story, leadership, timeline, and company background pages.",
        patterns=(r"about", r"company", r"history", r"story", r"mission", r"leadership", r"team"),
        keywords=("about", "company", "history", "story", "mission", "leadership", "team", "founded"),
    ),
    CrawlCategory(
        id="customer_support",
        label="Customer support",
        description="Help center, contact, FAQ, support, warranty, ticket, and troubleshooting pages.",
        patterns=(r"support", r"help", r"faq", r"contact", r"ticket", r"troubleshoot", r"warranty"),
        keywords=("support", "help", "faq", "contact", "ticket", "troubleshoot", "warranty", "customer"),
    ),
    CrawlCategory(
        id="product_service",
        label="Products and services",
        description="Product, service, feature, solution, use case, and offering pages.",
        patterns=(r"product", r"service", r"solution", r"feature", r"platform", r"use-case"),
        keywords=("product", "service", "solution", "feature", "platform", "use case", "offering"),
    ),
    CrawlCategory(
        id="pricing_billing",
        label="Pricing and billing",
        description="Pricing, billing, subscription, plan, payment, invoice, and quote pages.",
        patterns=(r"pricing", r"billing", r"subscription", r"plans?", r"payment", r"invoice", r"quote"),
        keywords=("pricing", "billing", "subscription", "plan", "payment", "invoice", "quote"),
    ),
    CrawlCategory(
        id="docs_guides",
        label="Docs and guides",
        description="Documentation, guides, tutorials, API docs, manuals, and knowledge-base pages.",
        patterns=(r"docs?", r"guide", r"tutorial", r"manual", r"knowledge", r"learn", r"api"),
        keywords=("docs", "documentation", "guide", "tutorial", "manual", "knowledge", "learn", "api"),
    ),
    CrawlCategory(
        id="security_compliance",
        label="Security and compliance",
        description="Security, trust, certifications, SLA, data protection, and compliance pages.",
        patterns=(r"security", r"trust", r"compliance", r"sla", r"gdpr", r"soc", r"iso", r"data-protection"),
        keywords=("security", "trust", "compliance", "sla", "gdpr", "soc", "iso", "data protection"),
    ),
    CrawlCategory(
        id="news_updates",
        label="News and updates",
        description="Blog, press, news, announcement, changelog, and update pages.",
        patterns=(r"blog", r"news", r"press", r"announcement", r"changelog", r"updates?"),
        keywords=("blog", "news", "press", "announcement", "changelog", "update"),
    ),
]


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())

    @property
    def title(self) -> str:
        return " ".join(part for part in self.title_parts if part).strip()


def category_options() -> list[dict[str, str]]:
    return [
        {"id": category.id, "label": category.label, "description": category.description}
        for category in CRAWL_CATEGORIES
    ]


def run_website_crawl_discovery(db: Session, crawl_job: WebsiteCrawlJob) -> WebsiteCrawlJob:
    crawl_job.status = JOB_PROCESSING
    crawl_job.started_at = utc_now()
    crawl_job.error_message = ""
    db.flush()

    try:
        discovered = discover_urls(crawl_job.root_url, crawl_job.max_depth, crawl_job.max_pages)
        selected_categories = set(crawl_job.selected_categories or [])
        prompt_selected = prompt_selected_urls(crawl_job.custom_prompt, discovered)
        matched_count = 0

        for item in discovered:
            matched_categories, score, reason = classify_url(
                item.url,
                item.title,
                selected_categories=selected_categories,
                prompt_selected=prompt_selected,
            )
            if not matched_categories:
                continue
            matched_count += 1
            db.add(
                WebsiteCrawlCandidate(
                    crawl_job_id=crawl_job.id,
                    company_id=crawl_job.company_id,
                    url=item.url,
                    title=item.title[:500],
                    depth=item.depth,
                    discovery_source=item.source,
                    matched_categories=matched_categories,
                    match_reason=reason,
                    score=score,
                )
            )

        crawl_job.total_discovered = len(discovered)
        crawl_job.total_matched = matched_count
        crawl_job.status = JOB_COMPLETED
        crawl_job.completed_at = utc_now()
        crawl_job.last_recrawl_at = crawl_job.completed_at
        db.flush()
    except Exception as exc:
        crawl_job.status = JOB_FAILED
        crawl_job.error_message = str(exc)[:1000]
        crawl_job.completed_at = utc_now()
        db.flush()

    return crawl_job


def discover_urls(root_url: str, max_depth: int, max_pages: int) -> list[DiscoveredUrl]:
    normalized_root = normalize_url(root_url)
    discovered: dict[str, DiscoveredUrl] = {}

    for url in sitemap_urls(normalized_root, max_pages):
        if len(discovered) >= max_pages:
            break
        if should_keep_url(url, normalized_root):
            discovered.setdefault(url, DiscoveredUrl(url=url, title="", depth=0, source="sitemap"))

    if len(discovered) < max_pages:
        for item in bfs_urls(normalized_root, max_depth, max_pages):
            discovered.setdefault(item.url, item)
            if len(discovered) >= max_pages:
                break

    return list(discovered.values())


def sitemap_urls(root_url: str, max_pages: int) -> list[str]:
    roots = [urljoin(root_url, "/sitemap.xml")]
    roots.extend(robots_sitemaps(root_url))
    seen: set[str] = set()
    urls: list[str] = []
    queue = deque(roots)

    while queue and len(urls) < max_pages:
        sitemap_url = queue.popleft()
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        try:
            content = fetch_text(sitemap_url, allow_xml=True)
        except Exception:
            continue
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            continue
        for loc in root.findall(".//{*}loc"):
            if not loc.text:
                continue
            candidate = normalize_url(loc.text)
            if candidate.endswith(".xml") and "sitemap" in candidate and candidate not in seen:
                queue.append(candidate)
            else:
                urls.append(candidate)
                if len(urls) >= max_pages:
                    break

    return urls


def robots_sitemaps(root_url: str) -> list[str]:
    try:
        robots = fetch_text(urljoin(root_url, "/robots.txt"), allow_xml=True)
    except Exception:
        return []
    sitemaps = []
    for line in robots.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            sitemaps.append(normalize_url(value.strip()))
    return sitemaps


def bfs_urls(root_url: str, max_depth: int, max_pages: int) -> list[DiscoveredUrl]:
    queue = deque([(root_url, 0)])
    visited: set[str] = set()
    discovered: list[DiscoveredUrl] = []

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited or depth > max_depth:
            continue
        visited.add(url)
        if not should_keep_url(url, root_url):
            continue
        try:
            html = fetch_text(url)
        except Exception:
            continue
        parser = LinkParser()
        parser.feed(html)
        discovered.append(DiscoveredUrl(url=url, title=parser.title, depth=depth, source="bfs"))
        if depth >= max_depth:
            continue
        for href in parser.links:
            child = normalize_url(urljoin(url, href))
            if child not in visited and should_keep_url(child, root_url):
                queue.append((child, depth + 1))

    return discovered


def classify_url(
    url: str,
    title: str,
    *,
    selected_categories: set[str],
    prompt_selected: set[str],
) -> tuple[list[str], int, str]:
    haystack = f"{url} {title}".lower()
    matches: list[str] = []
    reasons: list[str] = []
    score = 0

    for category in CRAWL_CATEGORIES:
        if selected_categories and category.id not in selected_categories:
            continue
        matched = False
        for pattern in category.patterns:
            if re.search(pattern, haystack):
                matched = True
                score += 25
                break
        keyword_hits = [keyword for keyword in category.keywords if keyword in haystack]
        if keyword_hits:
            matched = True
            score += min(30, len(keyword_hits) * 10)
        if matched:
            matches.append(category.id)
            reasons.append(category.label)

    if url in prompt_selected:
        matches.append("custom_prompt")
        reasons.append("Custom prompt")
        score += 40

    return sorted(set(matches)), score, ", ".join(reasons)


def prompt_selected_urls(prompt: str, discovered: list[DiscoveredUrl]) -> set[str]:
    prompt = prompt.strip()
    if not prompt:
        return set()
    try:
        selected = prompt_selected_urls_with_ai(prompt, discovered)
        if selected:
            return selected
    except Exception:
        pass
    return prompt_selected_urls_by_keywords(prompt, discovered)


def prompt_selected_urls_with_ai(prompt: str, discovered: list[DiscoveredUrl]) -> set[str]:
    if not settings.crawl_ai_api_key:
        return set()
    sample = discovered[:200]
    items = [{"index": index, "url": item.url, "title": item.title} for index, item in enumerate(sample)]
    response = httpx.post(
        f"{settings.crawl_ai_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.crawl_ai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.crawl_ai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Select website URLs that match the user's content-selection prompt. "
                        "Return only JSON like {\"indexes\":[0,2,5]}."
                    ),
                },
                {"role": "user", "content": f"Prompt: {prompt}\nURLs: {json.dumps(items)}"},
            ],
            "temperature": 0,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    content = str(
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return set()
    selected = json.loads(match.group(0))
    indexes = selected.get("indexes") if isinstance(selected, dict) else []
    return {sample[index].url for index in indexes if isinstance(index, int) and 0 <= index < len(sample)}


def prompt_selected_urls_by_keywords(prompt: str, discovered: list[DiscoveredUrl]) -> set[str]:
    words = {
        word.lower()
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", prompt)
        if word.lower() not in {"that", "with", "from", "page", "pages", "website", "related", "needed", "store"}
    }
    if not words:
        return set()
    selected = set()
    for item in discovered:
        haystack = f"{item.url} {item.title}".lower()
        hits = sum(1 for word in words if word in haystack)
        if hits >= min(2, len(words)):
            selected.add(item.url)
    return selected


def fetch_text(url: str, allow_xml: bool = False) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=10) as response:
            content_type = response.headers.get("content-type", "").lower()
            if not allow_xml and not any(kind in content_type for kind in HTML_TYPES):
                raise ValueError("URL is not an HTML page")
            data = response.read(1_500_000)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ValueError(f"Could not fetch {url}") from exc
    return data.decode("utf-8", errors="replace")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        parsed = urlparse(f"https://{url.strip()}")
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    cleaned, _ = urldefrag(urlunparse((scheme, host, path, "", parsed.query, "")))
    return cleaned


def should_keep_url(url: str, root_url: str) -> bool:
    parsed = urlparse(url)
    root = urlparse(root_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != root.netloc:
        return False
    path = parsed.path.lower()
    if any(path.endswith(extension) for extension in SKIP_EXTENSIONS):
        return False
    parts = {part for part in path.split("/") if part}
    if parts & SKIP_PATH_PARTS:
        return False
    return True


def crawl_job_for_company(db: Session, *, company_id, crawl_job_id) -> WebsiteCrawlJob:
    crawl_job = db.get(WebsiteCrawlJob, crawl_job_id)
    if crawl_job is None or crawl_job.company_id != company_id:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website crawl job not found")
    return crawl_job


def list_crawl_jobs(db: Session, *, company_id) -> list[WebsiteCrawlJob]:
    return list(
        db.scalars(
            select(WebsiteCrawlJob)
            .where(WebsiteCrawlJob.company_id == company_id)
            .order_by(WebsiteCrawlJob.created_at.desc())
        )
    )
