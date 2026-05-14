from dataclasses import dataclass
from urllib.parse import urlparse

from app.services.document_extraction import normalize_text


class WebScrapeError(Exception):
    pass


@dataclass(frozen=True)
class WebScrapeResult:
    text: str
    metadata: dict[str, object]
    title: str
    final_url: str


def scrape_single_page(url: str, wait_seconds: int = 2) -> WebScrapeResult:
    validated_url = validate_scrape_url(url)
    wait_seconds = max(0, min(wait_seconds, 10))

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise WebScrapeError("Browser renderer is unavailable for web scraping") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            try:
                page.goto(validated_url, wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightTimeoutError as exc:
                raise WebScrapeError("Page did not load before the timeout") from exc

            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass

            if wait_seconds:
                page.wait_for_timeout(wait_seconds * 1000)

            title = normalize_text(page.title())
            final_url = page.url
            raw_text = page.evaluate(
                """() => {
                    const root = document.body ? document.body.cloneNode(true) : document.documentElement.cloneNode(true);
                    root.querySelectorAll(
                        'script, style, noscript, svg, canvas, iframe, nav, footer, form, input, button, [aria-hidden="true"]'
                    ).forEach((node) => node.remove());
                    return root.innerText || root.textContent || '';
                }"""
            )
        finally:
            browser.close()

    text = clean_scraped_text(str(raw_text or ""))
    if not text:
        raise WebScrapeError("No readable text found on the page")

    return WebScrapeResult(
        text=text,
        title=title or validated_url,
        final_url=final_url,
        metadata={
            "extractor": "playwright",
            "requested_url": validated_url,
            "final_url": final_url,
            "title": title,
            "wait_seconds": wait_seconds,
        },
    )


def validate_scrape_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebScrapeError("Only http and https page URLs can be scraped")
    return candidate


def clean_scraped_text(text: str) -> str:
    normalized = normalize_text(text)
    lines: list[str] = []
    previous = ""
    for line in normalized.splitlines():
        if len(line) == 1 and not line.isalnum():
            continue
        if line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()
