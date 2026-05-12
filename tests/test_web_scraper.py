import pytest

from app.services.web_scraper import WebScrapeError, clean_scraped_text, validate_scrape_url


def test_clean_scraped_text_removes_duplicate_lines() -> None:
    text = clean_scraped_text("  Pricing  \n\nPricing\n$\nPlans start today.\x00")

    assert text == "Pricing\nPlans start today."


def test_validate_scrape_url_requires_http_url() -> None:
    with pytest.raises(WebScrapeError, match="Only http and https"):
        validate_scrape_url("file:///tmp/page.html")

    assert validate_scrape_url("https://example.com/help") == "https://example.com/help"
