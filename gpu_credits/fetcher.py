"""Downloading pages and extracting their text.

Uses plain HTTP rather than a hosted search tool, so the model is only ever
given text that was downloaded during the current run.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from . import config

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Page furniture that never contains program details.
DROP_TAGS = [
    "script",
    "style",
    "noscript",
    "svg",
    "header",
    "footer",
    "nav",
    "form",
    "iframe",
]


def extract_text(html: str) -> str:
    """Strip a page down to its readable text."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(DROP_TAGS):
        tag.decompose()

    text = soup.get_text(" ", strip=True)
    text = " ".join(text.split())
    return text[: config.MAX_PAGE_CHARS]


# Status codes that may succeed on a retry. A 403 or 404 will not.
RETRY_CODES = (408, 429, 500, 502, 503, 504)


def fetch(url: str, retries: int = None):
    """Download a page.

    Returns (final_url, text, error). The error is a short string when
    something went wrong, otherwise empty. This never raises, so a single
    unreachable page does not end the run.

    Transient failures are retried, so a brief network problem does not
    register as a page that could not be read.
    """
    if retries is None:
        retries = config.FETCH_RETRIES

    error = "unknown"
    for attempt in range(retries + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=config.FETCH_TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            error = str(exc)[:120]
            if attempt < retries:
                time.sleep(config.FETCH_RETRY_WAIT * (attempt + 1))
                continue
            return url, "", error

        if response.status_code == 200:
            return response.url, extract_text(response.text), ""

        error = "HTTP %d" % response.status_code
        if response.status_code in RETRY_CODES and attempt < retries:
            time.sleep(config.FETCH_RETRY_WAIT * (attempt + 1))
            continue
        return response.url, "", error

    return url, "", error


def fetch_many(urls, workers: int = None, report=None) -> dict:
    """Download a batch of pages at once.

    Fetching is not rate limited, so it runs concurrently.
    Returns {url: (final_url, text, error)}.
    """
    if workers is None:
        workers = config.FETCH_WORKERS

    urls = list(dict.fromkeys(urls))
    pages = {}
    if not urls:
        return pages

    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch, url): url for url in urls}
        for done, job in enumerate(as_completed(jobs), 1):
            url = jobs[job]
            try:
                pages[url] = job.result()
            except Exception as exc:  # noqa: BLE001 - recorded, not raised
                pages[url] = (url, "", str(exc)[:120])
            if report:
                report("Downloading pages: %d of %d" % (done, len(urls)), done, len(urls))

    return pages


def search(query: str, max_results: int = 5) -> list:
    """Web search, used to find pages the seed URLs missed.

    Returns a list of dicts with title, url and snippet. Returns an empty
    list if the search library is missing or the search fails, since
    discovery is optional.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []

    try:
        with DDGS() as engine:
            hits = list(engine.text(query, max_results=max_results))
    except Exception:  # noqa: BLE001 - a failed search is not a failed run
        return []

    results = []
    for hit in hits:
        results.append(
            {
                "title": hit.get("title", ""),
                "url": hit.get("href") or hit.get("url", ""),
                "snippet": hit.get("body", ""),
            }
        )
    return results
