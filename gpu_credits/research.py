"""The refresh run.

Steps:

1. Download each provider's own program page over plain HTTP.
2. Pass that page text to the model and ask it to fill in the three columns.
   It is told to use nothing but the text in front of it.
3. Do the same for a handful of programs we found by searching but do not
   already track.
4. Sort the rows and work out what moved since last time.

The model does no searching of its own. Its only input is the text of a page
downloaded during the current run.
"""

import inspect
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from . import config, fetcher, llm
from .providers import ALL_PROGRAMS, program_list, registrable_domain
from .schema import normalise_name as _normalise_name
from .schema import (
    CATEGORY_VALUES,
    CONFIDENCE_VALUES,
    ONE_PROGRAM_SCHEMA,
    STATUS_VALUES,
    describe_fields,
)

READER_SYSTEM = """You read one company web page and report what their startup
credit or free compute program offers.

The only thing you know is the page text you are given. That is the whole
point, so stick to it.

Rules:
1. Every number you write must appear on the page. If the page does not give
   an amount, write that the amount is not published.
2. Do not fill gaps from memory. If the page says nothing about eligibility,
   say the page does not spell it out.
3. Do not use marketing language. Write in plain, short sentences.
4. If the page is an error page, a login wall, a cookie banner or simply not
   about a startup program, set is_a_startup_program to false and keep the
   other fields short.
5. If the page says the program has closed, record that.
6. A page listing many companies' programs is a directory, not a provider.
   Set published_by_the_provider to false for those."""


def _one_of(value, allowed: list, fallback: str) -> str:
    """Constrain a model written value to the allowed set.

    Only some backends accept a schema, so others may return an unexpected
    status or omit the field. Sorting and counting depend on these values.
    """
    if not isinstance(value, str):
        return fallback

    cleaned = value.strip().lower()
    for option in allowed:
        if cleaned == option.lower():
            return option

    # Near enough counts, so "open" matches "open to apply".
    for option in allowed:
        if cleaned and (cleaned in option.lower() or option.lower() in cleaned):
            return option

    return fallback


def _plain(text) -> str:
    """Normalise punctuation in model output.

    Replaces typographic dashes, curly quotes and non breaking spaces, which
    render inconsistently in terminals and markdown tables.
    """
    if not isinstance(text, str):
        return ""

    for fancy, plain in (
        ("—", "-"),
        ("–", "-"),
        ("‘", "'"),
        ("’", "'"),
        ("“", '"'),
        ("”", '"'),
        (" ", " "),
    ):
        text = text.replace(fancy, plain)

    return " ".join(text.split())


def _reader_prompt(name: str, url: str, page_text: str, extra_text: str = "") -> str:
    body = (
        "We were looking for this program: %s\n"
        "Page we downloaded: %s\n\n"
        "Read the page text below and reply with a single JSON object with "
        "exactly these fields:\n\n"
        "%s\n\n"
        "Reply with the JSON object and nothing else.\n\n"
        "PAGE TEXT\n"
        "---------\n"
        "%s\n" % (name, url, describe_fields(), page_text)
    )

    if extra_text:
        body += (
            "\nA second page from the same provider, in case the first one was "
            "thin:\n---------\n%s\n" % extra_text
        )

    return body


def _blank_row(name: str, url: str, reason: str, failure: str = "page") -> dict:
    """The row recorded when a page will not load or the model will not answer.

    The reason is written into the row so that "could not check" is
    distinguishable from "this program offers nothing".

    The failure field records which side failed: "page" for the provider,
    "model" for us. A run of consecutive "model" failures indicates the
    account has stopped answering.
    """
    return {
        "name": name,
        "what_you_get": "Not confirmed on this run. %s" % reason,
        "who_qualifies": "Not confirmed on this run.",
        "category": "GPU or AI cloud",
        "status": "could not confirm",
        "program_url": url,
        "source_urls": [url],
        "confidence": "low",
        "notes": "Check this one by hand.",
        "changed_since_last_run": "",
        "failure": failure,
    }


# Common locations for a program page. Each guess is one HTTP request and no
# model call, so these are tried before falling back to search.
PROGRAM_PATHS = [
    "/startups",
    "/startup",
    "/startup-program",
    "/for-startups",
    "/programs/startups",
    "/company/startups",
    "/grants",
    "/credits",
]

# Words a program page will contain. Without this check a single page app
# returns its homepage for every path tried and the homepage is accepted.
PROGRAM_WORDS = ("startup", "founder")
OFFER_WORDS = ("credit", "program", "grant", "free", "discount", "apply")


def _looks_like_a_program(text: str) -> bool:
    lowered = text.lower()
    return any(w in lowered for w in PROGRAM_WORDS) and any(
        w in lowered for w in OFFER_WORDS
    )


def _guess_program_urls(url: str) -> list:
    """The obvious places to look on the same site."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return []

    base = "%s://%s" % (parsed.scheme, parsed.netloc)
    already = parsed.path.rstrip("/")
    return [base + path for path in PROGRAM_PATHS if path != already]


def _rescue_pages(name: str, url: str, seen: str = "") -> tuple:
    """When a seed page turns out to be the wrong page, find the right one.

    Most seeds are company homepages, since those URLs are stable. The
    program page is usually one hop away, so the common paths are tried first,
    then a search restricted to the same domain.

    Replacements are only accepted from the provider's own domain, so a
    third party roundup can never be substituted for the provider's page.
    """
    wanted = registrable_domain(url)

    guesses = _guess_program_urls(url)
    pages = fetcher.fetch_many(guesses)
    for candidate in guesses:
        final_url, text, _ = pages.get(candidate, (candidate, "", "skipped"))
        if (
            len(text) >= config.MIN_USEFUL_CHARS
            and text != seen
            and _looks_like_a_program(text)
        ):
            return final_url, text

    queries = [
        "site:%s startup program credits" % wanted,
        "%s startup program credits" % name,
    ]
    stripped = url.rstrip("/")
    for query in queries:
        for hit in fetcher.search(query, max_results=6):
            candidate = hit.get("url", "")
            if not candidate or registrable_domain(candidate) != wanted:
                continue
            # Search engines love handing back the homepage we started from.
            if candidate.rstrip("/") == stripped:
                continue
            final_url, text, _ = fetcher.fetch(candidate)
            if (
                len(text) >= config.MIN_USEFUL_CHARS
                and text != seen
                and _looks_like_a_program(text)
            ):
                return final_url, text

    return "", ""


class OutOfQuota(RuntimeError):
    """The account will not answer any more calls, so the run is pointless."""


def _ask_about_page(name: str, url: str, text: str, extra_text: str = ""):
    """One question about one page.

    Returns (answer, error). The error text is kept so that a throttled call
    can be told apart from a page with no program on it.
    """
    try:
        answer = llm.complete_json(
            READER_SYSTEM,
            _reader_prompt(name, url, text, extra_text),
            ONE_PROGRAM_SCHEMA,
        )
        return answer, ""
    except llm.LLMError as exc:
        return None, str(exc)


def _read_program(name: str, url: str, seeded: bool = True, page=None) -> dict:
    """Read one program.

    A seeded program comes from the curated list and always returns a row,
    even when nothing was confirmed, so the absence of a result is visible.
    A program found by search is dropped instead when it cannot be confirmed.
    """
    if page is None:
        page = fetcher.fetch(url)
    final_url, text, error = page
    extra_text = ""

    if len(text) < config.MIN_USEFUL_CHARS:
        rescue_url, rescue_text = _rescue_pages(name, url, seen=text)
        if rescue_text:
            if not text:
                final_url, text = rescue_url, rescue_text
            else:
                extra_text = rescue_text

    # Most seeds are homepages. If the page does not mention a startup
    # program, find the right page before spending a model call.
    elif not _looks_like_a_program(text):
        rescue_url, rescue_text = _rescue_pages(name, url, seen=text)
        if rescue_text:
            final_url, text = rescue_url, rescue_text

    if len(text) < config.MIN_USEFUL_CHARS:
        return _blank_row(name, url, error or "The page had almost no text on it.")

    answer, error = _ask_about_page(name, final_url, text, extra_text)
    if answer is None:
        return _blank_row(
            name, url, "The model would not answer. %s" % error, failure="model"
        )

    # A seed URL is often just a company homepage. When that happens, go
    # looking for the real program page on the same domain before giving up.
    # Directory pages are rejected. Only applied to discovered pages, since
    # the seed list already contains provider domains.
    if not seeded and answer.get("published_by_the_provider") is False:
        return None

    if answer.get("is_a_startup_program") is False:
        if not seeded:
            return None

        rescue_url, rescue_text = _rescue_pages(name, url, seen=text)
        if rescue_text and rescue_url != final_url:
            retry, _ = _ask_about_page(name, rescue_url, rescue_text)
            if retry and retry.get("is_a_startup_program") is not False:
                answer, final_url = retry, rescue_url
            else:
                return _blank_row(
                    name, url, "No startup program page found on their site."
                )
        else:
            return _blank_row(
                name, url, "That page is not about a startup program."
            )

    return {
        "name": _plain(answer.get("name")) or name,
        "what_you_get": _plain(answer.get("what_you_get")),
        "who_qualifies": _plain(answer.get("who_qualifies")),
        "category": _one_of(answer.get("category"), CATEGORY_VALUES, "GPU or AI cloud"),
        "status": _one_of(answer.get("status"), STATUS_VALUES, "could not confirm"),
        "program_url": final_url or url,
        "source_urls": [u for u in [final_url or url] if u],
        "confidence": _one_of(answer.get("confidence"), CONFIDENCE_VALUES, "medium"),
        "notes": _plain(answer.get("notes")),
        "changed_since_last_run": "",
    }


# Domains that host roundups rather than a provider's own program page.
NOT_A_PROVIDER = (
    # Search engines and their ad redirects, which are not a provider page
    # even though they turn up looking like one.
    "bing.com",
    "google.com",
    "duckduckgo.com",
    "yahoo.com",
    "medium.com",
    "reddit.com",
    "linkedin.com",
    "youtube.com",
    "quora.com",
    "substack.com",
    "hackernoon.com",
    "dev.to",
    "github.io",
    "wikipedia.org",
    "producthunt.com",
    "ycombinator.com",
)


def _looks_like_a_roundup(url: str) -> bool:
    """True if the URL looks like an article about programs, not a program."""
    lowered = url.lower()
    if registrable_domain(url) in NOT_A_PROVIDER:
        return True
    return any(part in lowered for part in ("/blog/", "/news/", "/article", "/posts/"))


def _discover(known_domains: set, progress=None) -> list:
    """Look for programs that are not on our list yet.

    Filtering here is strict, because a search for GPU credits mostly returns
    third party roundups rather than provider pages.
    """
    if config.MAX_NEW_PROGRAMS <= 0:
        return []

    candidates = {}
    for query in config.DISCOVERY_QUERIES:
        for hit in fetcher.search(query, max_results=6):
            url = hit.get("url", "")
            if not url or _looks_like_a_roundup(url):
                continue
            domain = registrable_domain(url)
            if domain in known_domains or domain in candidates:
                continue
            candidates[domain] = {"url": url, "title": hit.get("title", domain)}

    found = []
    for domain, hit in list(candidates.items())[: config.MAX_NEW_PROGRAMS]:
        if progress:
            progress("Checking something new: %s" % domain, 0, 0)

        row = _read_program(hit["title"], hit["url"], seeded=False)
        if not row:
            continue
        if row["status"] == "could not confirm" or row["confidence"] == "low":
            continue

        row["notes"] = (row["notes"] + " Found by search, not on our list.").strip()
        found.append(row)

    return found


def _row_key(row: dict) -> str:
    """Match a program to its row from a previous run. Domain first."""
    return registrable_domain(row.get("program_url", "")) or _normalise_name(
        row.get("name", "")
    )


def _previous_by_key(previous) -> dict:
    if not previous:
        return {}
    return {_row_key(row): row for row in previous.get("programs", [])}


def _carry_forward(row: dict, previous_rows: dict, reason: str):
    """Reuse the previous run's row when this run could not check it.

    A run over a hundred programs may exhaust its quota partway. Rows already
    collected are kept, along with their original last_checked date so they
    are not mistaken for fresh results.
    """
    old = previous_rows.get(_row_key(row))
    if not old:
        return None

    carried = dict(old)
    carried["checked_this_run"] = False
    carried["notes"] = ("%s %s" % (carried.get("notes", ""), reason)).strip()
    carried.pop("failure", None)
    return carried


def _sort_key(row: dict):
    """Open programs first, then the ones we are most sure about."""
    status_order = {
        "open to apply": 0,
        "waitlist": 1,
        "partner or invite only": 2,
        "could not confirm": 3,
        "discontinued": 4,
    }
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    return (
        status_order.get(row.get("status"), 5),
        confidence_order.get(row.get("confidence"), 3),
        row.get("name", "").lower(),
    )


def _summary(rows: list, found: int, carried: int = 0, advice: str = "") -> str:
    open_now = sum(1 for row in rows if row["status"] == "open to apply")
    unsure = sum(1 for row in rows if row["status"] == "could not confirm")

    parts = [
        "Checked %d program%s, %d of them open to apply right now."
        % (len(rows), "" if len(rows) == 1 else "s", open_now)
    ]
    if unsure:
        parts.append(
            "%d could not be confirmed and %s worth a manual look."
            % (unsure, "is" if unsure == 1 else "are")
        )
    if found:
        parts.append(
            "%d new one%s turned up that we did not already track."
            % (found, "" if found == 1 else "s")
        )
    if carried:
        parts.append(
            "%d row%s carried over from the previous run and %s not rechecked. %s"
            % (
                carried,
                "" if carried == 1 else "s",
                "was" if carried == 1 else "were",
                advice,
            )
        )

    return " ".join(parts).strip()


def _progress_adapter(progress):
    """Take either kind of progress callback.

    The app wants numbers so it can draw a bar. A script usually just wants
    the line of text. Rather than forcing every caller to take three
    arguments, we look at what they accept and give them that.
    """
    if progress is None:
        return lambda message, done=0, count=0: None

    try:
        wanted = len(inspect.signature(progress).parameters)
    except (TypeError, ValueError):
        wanted = 1

    if wanted >= 3:
        return progress

    return lambda message, done=0, count=0: progress(message)


def _quota_advice(reason: str) -> str:
    if "PerDay" in reason:
        return (
            "That is a daily cap, so waiting will not help today. Switch "
            "GEMINI_MODEL or LLM_PROVIDER in your .env."
        )
    return (
        "That usually means the free tier quota is used up. Wait a minute and "
        "press the button again, or switch LLM_PROVIDER in your .env."
    )


def refresh(scope: str = "quick", previous=None, progress=None) -> dict:
    """Run the whole thing and hand back a snapshot ready to save."""
    started = datetime.now(timezone.utc)
    today = date.today().isoformat()
    programs = program_list(scope)
    previous_rows = _previous_by_key(previous)
    report = _progress_adapter(progress)

    # Fetching is not rate limited, so all pages are downloaded up front.
    pages = fetcher.fetch_many([p["url"] for p in programs], report=report)

    rows = []
    failures_in_a_row = 0
    stopped_at = 0
    advice = ""

    for index, program in enumerate(programs, 1):
        report(
            "Reading %d of %d: %s" % (index, len(programs), program["name"]),
            index,
            len(programs),
        )

        row = _read_program(
            program["name"], program["url"], page=pages.get(program["url"])
        )
        row["last_checked"] = today
        row["checked_this_run"] = True
        rows.append(row)

        # Consecutive model failures indicate the account has stopped
        # answering rather than a change on the provider side.
        if row.get("failure") == "model":
            failures_in_a_row += 1
            if failures_in_a_row >= config.MAX_CONSECUTIVE_FAILURES:
                stopped_at = index
                advice = _quota_advice(row["what_you_get"])
                break
        else:
            failures_in_a_row = 0

    # Programs never reached keep their previous values and original date.
    if stopped_at:
        for program in programs[stopped_at:]:
            carried = _carry_forward(
                {"name": program["name"], "program_url": program["url"]},
                previous_rows,
                "Not rechecked on this run.",
            )
            if carried:
                rows.append(carried)

    # Any failed row falls back to the previous run's values. A provider
    # that is briefly unreachable would otherwise replace a good row with an
    # error and appear to have withdrawn its program.
    for position, row in enumerate(rows):
        if not row.get("failure"):
            continue
        carried = _carry_forward(row, previous_rows, "Not rechecked on this run.")
        if carried:
            rows[position] = carried

    fresh = [r for r in rows if r.get("checked_this_run") and not r.get("failure")]

    # With no previous data to fall back on there is nothing worth saving,
    # so raise rather than write a table of empty rows.
    if stopped_at and len(fresh) < 5:
        raise OutOfQuota(
            "Stopped at %d of %d after %d model calls failed in a row, and "
            "there was not enough usable data to save. Your previous table is "
            "untouched. %s"
            % (stopped_at, len(programs), failures_in_a_row, advice)
        )

    discovered = []
    if not stopped_at and config.MAX_NEW_PROGRAMS > 0:
        report("Looking for programs we do not track yet", len(programs), len(programs))
        known_domains = {registrable_domain(p["url"]) for p in ALL_PROGRAMS}
        discovered = _discover(known_domains, report)
        for row in discovered:
            row["last_checked"] = today
            row["checked_this_run"] = True
        rows.extend(discovered)

    rows.sort(key=_sort_key)
    finished = datetime.now(timezone.utc)

    carried_count = sum(1 for r in rows if not r.get("checked_this_run"))

    return {
        "as_of": today,
        "summary": _summary(rows, len(discovered), carried_count, advice),
        "programs": rows,
        "run": {
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "seconds": round((finished - started).total_seconds(), 1),
            "provider": config.LLM_PROVIDER,
            "model": config.model_name(),
            "scope": scope,
            "programs_in_scope": len(programs),
            "checked_this_run": len(rows) - carried_count,
            "carried_forward": carried_count,
            "stopped_early": bool(stopped_at),
            # Partial means do not read this as a full sweep, whether we
            # stopped early or just could not reach a few pages.
            "partial": bool(stopped_at) or carried_count > 0,
        },
    }
