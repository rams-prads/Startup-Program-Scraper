"""Tests that never touch the network or the model.

Run them with:  python tests/test_offline.py

No test framework needed on purpose, so anyone who has cloned the repo can
run them straight after pip install without extra tooling. Every test here
covers something that has actually broken at least once.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gpu_credits import config, fetcher, llm, research, storage  # noqa: E402
from gpu_credits.providers import classify_source, registrable_domain  # noqa: E402
from gpu_credits.schema import ONE_PROGRAM_SCHEMA, describe_fields  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        FAILED.append("%s %s" % (name, detail))


def good_answer(**overrides):
    answer = {
        "name": "Test Program",
        "what_you_get": "Up to $50,000 in credits.",
        "who_qualifies": "Seed stage startups.",
        "category": "GPU or AI cloud",
        "status": "open to apply",
        "confidence": "high",
        "notes": "",
        "is_a_startup_program": True,
        "published_by_the_provider": True,
    }
    answer.update(overrides)
    return answer


def row(name, url, what, status="open to apply"):
    return {
        "name": name,
        "program_url": url,
        "what_you_get": what,
        "who_qualifies": "Anyone.",
        "status": status,
        "confidence": "high",
        "source_urls": [url],
        "notes": "",
    }


# ---------------------------------------------------------------- prompting

def test_prompt_names_every_field():
    """Only some backends accept a schema. The rest need it written out."""
    prompt = research._reader_prompt("X", "https://x.test/", "page text")
    missing = [f for f in ONE_PROGRAM_SCHEMA["properties"] if f not in prompt]
    check("prompt names every schema field", not missing, "missing %s" % missing)
    check("prompt carries the page text", "page text" in prompt)
    check("field descriptions are rendered", "not published" in describe_fields())


# ------------------------------------------------------------ json handling

def test_json_parsing_is_forgiving():
    cases = [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here you go: {"a": 1} hope that helps', {"a": 1}),
    ]
    for text, expected in cases:
        check("parses %r" % text[:24], llm.parse_json(text) == expected)

    for bad in ["", "no json here at all", "{unclosed"]:
        try:
            llm.parse_json(bad)
            check("rejects %r" % bad[:20], False, "should have raised")
        except llm.LLMError:
            check("rejects %r" % bad[:20], True)


def test_schema_is_shaped_per_backend():
    """Gemini rejects additionalProperties. Anthropic requires it."""
    strict = llm._add_strictness(ONE_PROGRAM_SCHEMA)
    check("anthropic schema is strict", strict.get("additionalProperties") is False)
    loose = llm._strip_unsupported(strict)
    check("gemini schema is stripped", "additionalProperties" not in loose)
    check("stripping keeps the fields", set(loose["properties"]) == set(ONE_PROGRAM_SCHEMA["properties"]))


# -------------------------------------------------------------- rate limits

def test_rate_limiter_holds_the_line():
    config.LLM_PROVIDER = "gemini"
    config.MAX_PER_MINUTE["gemini"] = 3
    config.PAUSE_SECONDS["gemini"] = 0
    llm._recent_calls.clear()

    start = time.time()
    for _ in range(3):
        llm._pace()
    check("calls under the ceiling do not wait", time.time() - start < 0.5)

    now = time.time()
    llm._recent_calls[:] = [now - 58, now - 58, now - 58]
    start = time.time()
    llm._pace()
    waited = time.time() - start
    check("call over the ceiling waits", 1.0 < waited < 4.0, "waited %.1fs" % waited)


def test_retry_delay_believes_the_provider():
    class WithHeader:
        headers = {"retry-after": "7"}
        text = ""

    class WithBodyHint:
        headers = {}
        text = "quota exceeded. Please retry in 23.665s. see docs"

    class WithNothing:
        headers = {}
        text = "something went wrong"

    check("uses the retry-after header", llm._retry_delay(WithHeader()) == 8)
    check("reads the delay out of the body", llm._retry_delay(WithBodyHint()) > 24)
    check("falls back to our own guess", llm._retry_delay(WithNothing()) == config.RETRY_WAIT_SECONDS)


# --------------------------------------------------------- value validation

def test_model_values_are_kept_in_range():
    from gpu_credits.schema import STATUS_VALUES

    check("exact value passes through", research._one_of("waitlist", STATUS_VALUES, "x") == "waitlist")
    check("case does not matter", research._one_of("Open To Apply", STATUS_VALUES, "x") == "open to apply")
    check("near enough matches", research._one_of("open", STATUS_VALUES, "x") == "open to apply")
    check("nonsense falls back", research._one_of("Open!!! now", STATUS_VALUES, "fallback") in STATUS_VALUES + ["fallback"])
    check("missing falls back", research._one_of(None, STATUS_VALUES, "fallback") == "fallback")
    check("wrong type falls back", research._one_of(42, STATUS_VALUES, "fallback") == "fallback")


# ------------------------------------------------------------------- diffing

def test_diff_ignores_rewording():
    old = {"programs": [row("Nebius", "https://nebius.com/startups", "Up to $100,000 in credits.")]}
    new = {"programs": [row("Nebius", "https://nebius.com/startups", "Credits of up to $100,000 are on offer.")]}

    result = storage.diff(old, new)
    check("rewording is not a change", not result["changed"], result["changed"])
    check("rewording is counted", result["reworded"] == 1)


def test_diff_catches_real_movement():
    old = {"programs": [row("Nebius", "https://nebius.com/startups", "Up to $100,000 in credits.")]}
    new = {"programs": [row("Nebius", "https://nebius.com/startups", "Up to $150,000 in credits.")]}

    result = storage.diff(old, new)
    check("an amount change is caught", len(result["changed"]) == 1)
    if result["changed"]:
        item = result["changed"][0]
        check("the new amount is named", "$150000" in item["gained"], item["gained"])
        check("the old amount is named", "$100000" in item["lost"], item["lost"])


def test_diff_catches_a_closed_program():
    old = {"programs": [row("X", "https://x.test/p", "$5,000", "open to apply")]}
    new = {"programs": [row("X", "https://x.test/p", "$5,000", "discontinued")]}
    result = storage.diff(old, new)
    check("a status change is caught", result["changed"] and "status" in result["changed"][0]["fields"])


def test_diff_survives_a_rename():
    """The model renames things between runs. That is not an add plus a drop."""
    old = {"programs": [row("Microsoft for Startups", "https://startups.microsoft.com/", "$150,000")]}
    new = {"programs": [row("Microsoft for Startups Founders Hub", "https://startups.microsoft.com/", "$150,000")]}

    result = storage.diff(old, new)
    check("a rename is not an addition", not result["added"], result["added"])
    check("a rename is not a removal", not result["removed"], result["removed"])


def test_money_parsing():
    cases = {
        "Up to $100,000 in credits": {"$100000"},
        "$5K to start, then $1.5M": {"$5k", "$1.5m"},
        "$10,000 a month and $10,000 total": {"$10000"},
        "no amounts here": set(),
        "": set(),
    }
    for text, expected in cases.items():
        got = storage.money_in(text)
        check("money in %r" % text[:26], got == expected, "got %s want %s" % (got, expected))


# ------------------------------------------------------------------- sources

def test_source_classification():
    check("known provider is official", classify_source("https://fal.ai/", "https://nebius.com/x") == "official")
    check("same domain counts", classify_source("https://newco.test/p", "https://newco.test/p") == "own site")
    check("a blog does not count", classify_source("https://newco.test/p", "https://medium.com/@a/b") == "third party")
    check("no source is caught", classify_source("https://x.test/", "") == "third party")
    check("subdomains resolve", registrable_domain("https://startup.google.com/x") == "google.com")


def test_roundup_filter():
    blocked = [
        "https://medium.com/@someone/gpu-credits",
        "https://www.gmicloud.ai/en/blog/gpu-credit-programs",
        "https://example.test/news/startup-credits",
        "https://www.bing.com/aclick?ld=abc&u=aHR0cHM",
        "https://duckduckgo.com/y.js?ad=1",
    ]
    allowed = ["https://fal.ai/grants", "https://www.runpod.io/startup-program"]
    for url in blocked:
        check("blocks %s" % url[:34], research._looks_like_a_roundup(url))
    for url in allowed:
        check("allows %s" % url[:34], not research._looks_like_a_roundup(url))


# ------------------------------------------------------------ page handling

def test_text_extraction():
    html = """
    <html><head><style>body{color:red}</style><title>T</title></head>
    <body><nav>menu junk</nav><script>var x = 1;</script>
    <h1>Startup Program</h1><p>Get $10,000 in credits.</p>
    <footer>footer junk</footer></body></html>
    """
    text = fetcher.extract_text(html)
    check("keeps the real content", "Get $10,000 in credits." in text)
    check("drops script tags", "var x" not in text)
    check("drops style tags", "color:red" not in text)
    check("drops nav and footer", "menu junk" not in text and "footer junk" not in text)


def test_page_text_is_capped():
    html = "<html><body><p>%s</p></body></html>" % ("word " * 100000)
    check("long pages are truncated", len(fetcher.extract_text(html)) <= config.MAX_PAGE_CHARS)


def test_fancy_punctuation_is_flattened():
    """The model writes en dashes and curly quotes. We do not want them."""
    messy = "Raised –5M–$10M — the “Grow” tier’s range"
    clean = research._plain(messy)
    for bad in ["—", "–", "‘", "’", "“", "”", " "]:
        check("strips %r" % bad, bad not in clean)
    check("non strings become empty", research._plain(None) == "")
    check("whitespace is collapsed", research._plain("a   b\n c") == "a b c")


# ------------------------------------------------------------- the run itself

def test_a_failed_page_still_produces_a_row():
    """A program on our list must never vanish silently."""
    fetcher.fetch = lambda url: (url, "", "HTTP 403")
    fetcher.search = lambda q, max_results=5: []
    result = research._read_program("Blocked Co", "https://blocked.test/p")

    check("a blocked page still gives a row", result is not None)
    check("the row says it is unconfirmed", result["status"] == "could not confirm")
    check("the reason is written down", "403" in result["what_you_get"])
    check("it is marked a page failure", result.get("failure") == "page")


def test_a_model_failure_is_marked_as_ours():
    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    llm.complete_json = lambda s, u, sc=None: (_ for _ in ()).throw(
        llm.LLMError("rate limited, out of free tier quota")
    )
    result = research._read_program("Some Co", "https://some.test/p")

    check("a model failure gives a row", result is not None)
    check("it is marked a model failure", result.get("failure") == "model")
    check("the real reason survives", "rate limited" in result["what_you_get"])


def test_a_healthy_run_produces_a_table():
    import gpu_credits.providers as providers

    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = lambda s, u, sc=None: good_answer()
    config.MAX_NEW_PROGRAMS = 0
    providers.CORE_PROGRAMS[:] = [
        {"name": "A", "url": "https://a.test/"},
        {"name": "B", "url": "https://b.test/"},
    ]

    snapshot = research.refresh(scope="quick", progress=lambda m: None)
    storage.annotate(snapshot)

    check("every program becomes a row", len(snapshot["programs"]) == 2)
    check("the run is described", snapshot["run"]["model"] == config.model_name())
    check("a summary is written", "Checked 2 programs" in snapshot["summary"])
    check("rows carry a trust label", all("source_trust" in r for r in snapshot["programs"]))

    rows = storage.to_rows(snapshot)
    check("the table has the three columns", list(rows[0]) == ["Name", "What you get", "Who qualifies"])

    markdown = storage.render_markdown(snapshot)
    check("markdown has a header row", "| Name | What you get | Who qualifies |" in markdown)
    check("markdown rows stay on one line", markdown.count("\n|") == 4)


def test_a_directory_page_never_becomes_a_row():
    """Aggregator sites read as legitimate providers. They are not."""
    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = lambda s, u, sc=None: good_answer(
        name="CloudCredits.io",
        what_you_get="A directory listing 187 startup programs.",
        published_by_the_provider=False,
    )

    discovered = research._read_program("Junk", "https://cloudcredits.test/", seeded=False)
    check("a directory page is dropped", discovered is None)

    seeded = research._read_program("Real Co", "https://real.test/", seeded=True)
    check("our own seed list is not second guessed", seeded is not None)


def test_discovered_junk_is_dropped_but_seeded_is_kept():
    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = lambda s, u, sc=None: good_answer(is_a_startup_program=False)

    discovered = research._read_program("Junk", "https://junk.test/", seeded=False)
    check("a discovered non program is dropped", discovered is None)

    seeded = research._read_program("Real Co", "https://real.test/", seeded=True)
    check("a seeded non program is kept as a row", seeded is not None)
    check("and marked unconfirmed", seeded["status"] == "could not confirm")


def test_markdown_cells_cannot_break_the_table():
    snapshot = {
        "as_of": "2026-01-01",
        "programs": [row("Pipe | Co", "https://x.test/", "Line one\nline two | with a pipe")],
        "run": {"model": "test"},
    }
    markdown = storage.render_markdown(snapshot)
    body = [line for line in markdown.splitlines() if line.startswith("| [")]
    check("one row is one line", len(body) == 1)
    check("pipes are escaped", body and body[0].count("|") == 4 + body[0].count("\\|"))


# --------------------------------------------------------------- colours

def test_every_colour_pair_is_readable():
    """Regression: an earlier palette had labels at 2.8:1."""
    from gpu_credits import palette

    failures = []
    for ink, surfaces in palette.TEXT_ON_SURFACES.items():
        for surface in surfaces:
            ratio = palette.contrast(palette.COLOURS[ink], palette.COLOURS[surface])
            if ratio < palette.MIN_TEXT_CONTRAST:
                failures.append("%s on %s is %.1f:1" % (ink, surface, ratio))
    check("all text clears 4.5 to 1", not failures, failures)


def test_surfaces_are_distinguishable():
    """Surfaces must be distinguishable from the page behind them."""
    from gpu_credits import palette

    separation = palette.contrast(palette.COLOURS["card"], palette.COLOURS["page"])
    check(
        "the table separates from the page",
        separation >= palette.MIN_SURFACE_SEPARATION,
        "%.2f:1" % separation,
    )

    edge = palette.contrast(palette.COLOURS["border"], palette.COLOURS["card"])
    check("the border is visible", edge >= palette.MIN_BORDER_CONTRAST, "%.2f:1" % edge)


def test_badges_stay_readable():
    """A repaint must not quietly make a badge unreadable."""
    from gpu_credits import palette

    for name, (background, ink) in palette.BADGES.items():
        ratio = palette.contrast(background, ink)
        check(
            "%s badge is readable" % name,
            ratio >= palette.MIN_TEXT_CONTRAST,
            "%.1f:1" % ratio,
        )
        lift = palette.contrast(background, palette.COLOURS["card"])
        check("%s badge is visible on the row" % name, lift >= 1.1, "%.2f:1" % lift)


def test_the_theme_file_matches_the_palette():
    """The CSS and the Streamlit theme must not drift apart."""
    from gpu_credits import config, palette

    target = config.ROOT / ".streamlit" / "config.toml"
    check("the theme file exists", target.exists())
    if not target.exists():
        return

    on_disk = target.read_text(encoding="utf-8")
    check("the theme file is what the palette generates", on_disk == palette.theme_toml())


def test_the_stylesheet_has_no_stray_colours():
    """Every colour in the CSS should have come from the palette."""
    import re

    from gpu_credits import palette

    known = {value.lower() for value in palette.COLOURS.values()}
    used = {m.lower() for m in re.findall(r"#[0-9A-Fa-f]{6}", palette.stylesheet())}
    strays = sorted(used - known)
    check("no hardcoded colours in the stylesheet", not strays, strays)


# ----------------------------------------------------------- the table view

def test_scraped_text_cannot_inject_markup():
    """Table text comes off other people's websites. None of it is trusted."""
    from gpu_credits import render

    nasty = {
        "name": "<script>alert(1)</script>",
        "what_you_get": '<img src=x onerror="alert(2)">',
        "who_qualifies": 'Anyone " onmouseover="alert(3)',
        "status": "open to apply",
        "program_url": "https://real.test/p",
    }
    cell = render.program_row(nasty)

    check("no script tag survives", "<script" not in cell)
    check("no img tag survives", "<img" not in cell)
    check("angle brackets are escaped", "&lt;script&gt;" in cell)
    check("quotes are escaped", "&quot;" in cell)
    check("the real text is still there", "Anyone" in cell)

    # A name with a stray tag must not be able to close the row early.
    check("the row stays one row", cell.count("<tr>") == 1)
    check("the row has four cells", cell.count("<td") == 4)


def test_only_http_links_become_clickable():
    from gpu_credits import render

    check("https is fine", render.safe_link("https://a.test/p") == "https://a.test/p")
    check("http is fine", render.safe_link("http://a.test/p") == "http://a.test/p")
    for bad in ["javascript:alert(1)", "data:text/html,<script>", "", None, "ftp://a/b"]:
        check("refuses %r" % bad, render.safe_link(bad) == "")

    row = {"name": "X", "program_url": "javascript:alert(1)", "status": "open to apply"}
    cell = render.program_row(row)
    check("a bad url is not linked", "<a " not in cell)
    check("but the name still shows", ">X<" in cell)


def test_every_status_has_its_own_badge():
    from gpu_credits import palette, render
    from gpu_credits.schema import STATUS_VALUES

    missing = [s for s in STATUS_VALUES if s not in palette.BADGES]
    check("no status is left without a colour", not missing, missing)
    check("the colours are distinct", len(set(palette.BADGES.values())) == len(palette.BADGES))

    for status in STATUS_VALUES:
        badge = render.status_badge(status)
        check("%s renders a badge" % status, 'class="badge"' in badge and status in badge)

    check("an unknown status still renders", "badge" in render.status_badge("made up"))


def test_the_table_is_well_formed():
    from gpu_credits import render

    rows = [
        {"name": "A", "status": "open to apply", "program_url": "https://a.test/x"},
        {"name": "B", "status": "discontinued", "program_url": "https://b.test/x"},
    ]
    table = render.table_html(rows)

    check("there is a table", '<table class="progs">' in table)
    check("headers match the columns", all("<th" in table and c in table for c in render.COLUMNS))
    check("one header row plus one row per program", table.count("<tr>") == len(rows) + 1)
    check("every cell is closed", table.count("<td") == table.count("</td>"))
    check("the table is closed", table.count("<table") == table.count("</table>"))
    check("an empty table still renders", '<table class="progs">' in render.table_html([]))


def test_carried_rows_are_flagged_in_the_table():
    from gpu_credits import render

    fresh = render.program_row(
        {"name": "X", "status": "open to apply", "checked_this_run": True,
         "program_url": "https://x.test/p"}
    )
    check("a fresh row shows its domain", "x.test" in fresh)
    check("a fresh row carries no warning", "not rechecked" not in fresh)

    old = render.program_row({
        "name": "X", "status": "open to apply",
        "checked_this_run": False, "last_checked": "2026-07-01",
        "program_url": "https://x.test/p",
    })
    check("a carried row says so", "not rechecked" in old)
    check("and shows when it was read", "2026-07-01" in old)


def test_sorting():
    from gpu_credits import render

    rows = [
        {"name": "Zeta", "status": "open to apply", "confidence": "high", "last_checked": "2026-01-01"},
        {"name": "Alpha", "status": "could not confirm", "confidence": "low", "last_checked": "2026-09-01"},
        {"name": "Mid", "status": "open to apply", "confidence": "low", "last_checked": "2026-05-01"},
    ]

    useful = [r["name"] for r in render.sort_rows(rows, "useful")]
    check("open programs come first", useful[0] in ("Mid", "Zeta") and useful[-1] == "Alpha", useful)
    check("confidence breaks the tie", useful[:2] == ["Zeta", "Mid"], useful)

    by_name = [r["name"] for r in render.sort_rows(rows, "name")]
    check("name sort is alphabetical", by_name == ["Alpha", "Mid", "Zeta"], by_name)

    by_date = [r["name"] for r in render.sort_rows(rows, "checked")]
    check("date sort is newest first", by_date == ["Alpha", "Mid", "Zeta"], by_date)

    check("sorting does not lose rows", len(render.sort_rows(rows, "useful")) == 3)
    check("every sort option is real", all(v in ("useful", "name", "checked") for v in render.SORTS.values()))


def test_the_search_box():
    from gpu_credits import render

    programs = [
        {"name": "Nebius", "what_you_get": "H100 credits", "who_qualifies": "AI teams", "status": "open to apply"},
        {"name": "Oracle", "what_you_get": "OCI credits", "who_qualifies": "Early stage", "status": "could not confirm"},
        {"name": "E2E", "what_you_get": "H200 GPUs", "who_qualifies": "Indian startups", "status": "open to apply"},
    ]

    check("empty search keeps everything", len(render.apply_filters(programs)) == 3)
    check("search matches the name", len(render.apply_filters(programs, "nebius")) == 1)
    check("search matches the benefit", len(render.apply_filters(programs, "h100")) == 1)
    check("search matches eligibility", len(render.apply_filters(programs, "indian")) == 1)
    check("search is case insensitive", len(render.apply_filters(programs, "ORACLE")) == 1)
    check("no match gives nothing", len(render.apply_filters(programs, "zzzz")) == 0)

    check("status filter works", len(render.apply_filters(programs, "", ["open to apply"])) == 2)
    check("search and status combine", len(render.apply_filters(programs, "h200", ["open to apply"])) == 1)


def test_missing_fields_do_not_crash_a_row():
    from gpu_credits import render

    cell = render.program_row({})
    check("an empty row still renders", "<tr>" in cell)
    check("it says unnamed", "Unnamed" in cell)


# ---------------------------------------------- what went wrong on 3 Sept

def test_a_brief_network_problem_cannot_wipe_the_table():
    """Regression: a run once replaced 80 good rows with HTTP errors."""
    import gpu_credits.providers as providers

    previous = {
        "as_of": "2026-09-02",
        "programs": [
            {
                "name": "Steady Co",
                "program_url": "https://steady.test/p",
                "what_you_get": "Up to $50,000 in credits.",
                "who_qualifies": "Seed stage.",
                "status": "open to apply",
                "confidence": "high",
                "notes": "",
                "source_urls": ["https://steady.test/p"],
                "last_checked": "2026-09-02",
            }
        ],
    }

    # The provider is briefly unreachable on this run.
    fetcher.fetch = lambda url, retries=None: (url, "", "HTTP 503")
    fetcher.fetch_many = lambda urls, workers=None, report=None: {
        u: (u, "", "HTTP 503") for u in urls
    }
    fetcher.search = lambda q, max_results=5: []
    config.MAX_NEW_PROGRAMS = 0
    providers.CORE_PROGRAMS[:] = [
        {"name": "Steady Co", "url": "https://steady.test/p"}
    ]

    snapshot = research.refresh(
        scope="quick", previous=previous, progress=lambda *a: None
    )
    row = snapshot["programs"][0]

    check("the good figures survive", "$50,000" in row["what_you_get"], row["what_you_get"])
    check("the row still says open", row["status"] == "open to apply")
    check("it is marked as not rechecked", row.get("checked_this_run") is False)
    check("it keeps its original date", row["last_checked"] == "2026-09-02")
    check("the run reports it carried something", snapshot["run"]["carried_forward"] == 1)


def test_a_first_run_still_records_an_unreachable_page():
    """With nothing to fall back on the failure has to be visible."""
    import gpu_credits.providers as providers

    fetcher.fetch = lambda url, retries=None: (url, "", "HTTP 503")
    fetcher.fetch_many = lambda urls, workers=None, report=None: {
        u: (u, "", "HTTP 503") for u in urls
    }
    fetcher.search = lambda q, max_results=5: []
    config.MAX_NEW_PROGRAMS = 0
    providers.CORE_PROGRAMS[:] = [{"name": "New Co", "url": "https://new.test/p"}]

    snapshot = research.refresh(scope="quick", previous=None, progress=lambda *a: None)
    row = snapshot["programs"][0]

    check("the row exists", row is not None)
    check("it says it could not be confirmed", row["status"] == "could not confirm")
    check("and says why", "503" in row["what_you_get"], row["what_you_get"])


def test_transient_failures_are_retried():
    """A single dropped connection should not cost a row."""
    import gpu_credits.fetcher as real

    calls = {"n": 0}

    class Response:
        def __init__(self, code, body=""):
            self.status_code = code
            self.text = body
            self.url = "https://x.test/p"

    def flaky(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return Response(503)
        return Response(200, "<html><body><p>%s</p></body></html>" % ("word " * 200))

    original = real.requests.get
    original_wait = config.FETCH_RETRY_WAIT
    config.FETCH_RETRY_WAIT = 0
    real.requests.get = flaky
    try:
        url, text, error = real.fetch("https://x.test/p")
    finally:
        real.requests.get = original
        config.FETCH_RETRY_WAIT = original_wait

    check("it retried", calls["n"] == 2, calls["n"])
    check("and succeeded", error == "", error)
    check("and returned the text", "word" in text)


def test_permanent_failures_are_not_retried():
    """A 403 will not change on a second attempt, so it is not retried."""
    import gpu_credits.fetcher as real

    calls = {"n": 0}

    class Response:
        status_code = 403
        text = ""
        url = "https://x.test/p"

    def blocked(url, **kwargs):
        calls["n"] += 1
        return Response()

    original = real.requests.get
    real.requests.get = blocked
    try:
        _, _, error = real.fetch("https://x.test/p")
    finally:
        real.requests.get = original

    check("it gave up immediately", calls["n"] == 1, calls["n"])
    check("and reported the code", error == "HTTP 403", error)


def test_pages_are_fetched_in_parallel():
    import gpu_credits.fetcher as real

    seen = []
    original = real.fetch
    real.fetch = lambda url, retries=None: (seen.append(url), (url, "text", ""))[1]
    try:
        pages = real.fetch_many(
            ["https://a.test/", "https://b.test/", "https://a.test/"]
        )
    finally:
        real.fetch = original

    check("duplicates are only fetched once", len(seen) == 2, seen)
    check("every url comes back", set(pages) == {"https://a.test/", "https://b.test/"})
    check("an empty list is fine", real.fetch_many([]) == {})


def snapshot_globals():
    """Remember everything a test is allowed to reach in and change."""
    import gpu_credits.providers as providers

    return {
        "fetch": fetcher.fetch,
        "fetch_many": fetcher.fetch_many,
        "search": fetcher.search,
        "complete_json": llm.complete_json,
        "provider": config.LLM_PROVIDER,
        "per_minute": dict(config.MAX_PER_MINUTE),
        "pause": dict(config.PAUSE_SECONDS),
        "max_failures": config.MAX_CONSECUTIVE_FAILURES,
        "max_new": config.MAX_NEW_PROGRAMS,
        "core": list(providers.CORE_PROGRAMS),
        "recent_calls": list(llm._recent_calls),
    }


def restore_globals(saved):
    """Put it all back, so one test cannot quietly break the next one."""
    import gpu_credits.providers as providers

    fetcher.fetch = saved["fetch"]
    fetcher.fetch_many = saved["fetch_many"]
    fetcher.search = saved["search"]
    llm.complete_json = saved["complete_json"]
    config.LLM_PROVIDER = saved["provider"]
    config.MAX_PER_MINUTE.clear()
    config.MAX_PER_MINUTE.update(saved["per_minute"])
    config.PAUSE_SECONDS.clear()
    config.PAUSE_SECONDS.update(saved["pause"])
    config.MAX_CONSECUTIVE_FAILURES = saved["max_failures"]
    config.MAX_NEW_PROGRAMS = saved["max_new"]
    providers.CORE_PROGRAMS[:] = saved["core"]
    llm._recent_calls[:] = saved["recent_calls"]


# ------------------------------------------------------------ scope and size

def test_progress_accepts_either_callback_shape():
    """The app wants numbers for its bar. A script just wants the text."""
    import gpu_credits.providers as providers

    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = lambda s, u, sc=None: good_answer()
    config.MAX_NEW_PROGRAMS = 0
    providers.CORE_PROGRAMS[:] = [{"name": "A", "url": "https://a.test/"}]

    simple = []
    research.refresh(scope="quick", progress=lambda message: simple.append(message))
    check("a one argument callback still works", len(simple) >= 1, simple)
    check("it reports the download step", any("Downloading" in m for m in simple), simple)
    check("and the reading step", any("Reading" in m for m in simple), simple)

    detailed = []
    research.refresh(
        scope="quick",
        progress=lambda message, done, count: detailed.append((done, count)),
    )
    check("a three argument callback gets numbers", (1, 1) in detailed, detailed)

    research.refresh(scope="quick", progress=None)
    check("no callback at all is fine", True)


def test_the_cli_offers_every_scope():
    """Regression: the CLI once accepted only two of the three scopes."""
    import run_refresh
    from gpu_credits.providers import SCOPES, program_list

    scopes = sorted(SCOPES)
    check("there are three scopes", scopes == ["deep", "full", "quick"], scopes)
    for name in scopes:
        check("program_list knows %s" % name, len(program_list(name)) > 0)

    source = open(run_refresh.__file__, encoding="utf-8").read()
    check("the CLI reads its choices from SCOPES", "choices=sorted(SCOPES)" in source)
    check("no hardcoded scope list is left", '["quick", "full"]' not in source)


def test_the_deep_scope_is_actually_deep():
    from gpu_credits.providers import ALL_PROGRAMS, program_list

    quick, full, deep = (len(program_list(s)) for s in ("quick", "full", "deep"))
    check("quick is the short list", quick == 12, "got %d" % quick)
    check("full sits in the middle", quick < full < deep, "%d %d %d" % (quick, full, deep))
    check("deep is at least a hundred", deep >= 100, "got %d" % deep)

    urls = [p["url"] for p in ALL_PROGRAMS]
    names = [p["name"] for p in ALL_PROGRAMS]
    check("no duplicate urls", len(urls) == len(set(urls)))
    check("no duplicate names", len(names) == len(set(names)))
    check("every entry has both fields", all(p.get("name") and p.get("url") for p in ALL_PROGRAMS))
    check("every url is absolute", all(p["url"].startswith("https://") for p in ALL_PROGRAMS))


def test_every_seed_domain_is_trusted():
    """A seeded provider must never be flagged as a third party source."""
    from gpu_credits.providers import ALL_PROGRAMS

    strangers = [
        p["name"] for p in ALL_PROGRAMS
        if classify_source(p["url"], p["url"]) == "third party"
    ]
    check("all seed domains are trusted", not strangers, strangers[:4])


# ---------------------------------------------------------------- pagination

def test_pagination_maths():
    """Fifteen to a page, and the last page holds the remainder."""
    import math

    per_page = config.ROWS_PER_PAGE
    check("the page size is fifteen", per_page == 15)

    for total, expected_pages in [(0, 1), (1, 1), (15, 1), (16, 2), (119, 8), (120, 8)]:
        pages = max(1, math.ceil(total / per_page))
        check("%d rows is %d pages" % (total, expected_pages), pages == expected_pages,
              "got %d" % pages)

    rows = list(range(119))
    seen = []
    for page in range(1, 9):
        start = (page - 1) * per_page
        seen.extend(rows[start:start + per_page])
    check("paging covers every row exactly once", seen == rows)

    last_start = 7 * per_page
    check("the last page has the remainder", len(rows[last_start:last_start + per_page]) == 14)


# ------------------------------------------------------- partial run recovery

def test_a_stopped_run_keeps_what_it_knew():
    """Running out of quota at row 90 must not throw away rows 1 to 89."""
    import gpu_credits.providers as providers

    previous = {
        "as_of": "2026-08-01",
        "programs": [
            {
                "name": "Carried Co", "program_url": "https://carried.test/p",
                "what_you_get": "Up to $40,000 in credits.", "who_qualifies": "Anyone.",
                "status": "open to apply", "confidence": "high", "notes": "",
                "source_urls": ["https://carried.test/p"], "last_checked": "2026-08-01",
            }
        ],
    }

    programs = [{"name": "Good %d" % i, "url": "https://good%d.test/" % i} for i in range(6)]
    programs.append({"name": "Carried Co", "url": "https://carried.test/p"})

    calls = {"n": 0}

    def flaky(system, user, schema=None):
        calls["n"] += 1
        if calls["n"] <= 6:
            return good_answer()
        raise llm.LLMError("rate limited, out of free tier quota")

    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = flaky
    config.MAX_CONSECUTIVE_FAILURES = 2
    config.MAX_NEW_PROGRAMS = 0
    providers.CORE_PROGRAMS[:] = programs

    snapshot = research.refresh(scope="quick", previous=previous, progress=lambda m: None)

    check("the run survived", snapshot is not None)
    check("the good rows were kept", snapshot["run"]["checked_this_run"] >= 6)
    check("the run is flagged partial", snapshot["run"]["partial"] is True)

    carried = [r for r in snapshot["programs"] if not r.get("checked_this_run")]
    check("the unreached row was carried over", len(carried) == 1, len(carried))
    if carried:
        check("it kept its old figures", "$40,000" in carried[0]["what_you_get"])
        check("it kept its old date", carried[0]["last_checked"] == "2026-08-01")
        check("it says it was not rechecked", "not rechecked" in carried[0]["notes"].lower())

    check("the summary admits it", "carried over" in snapshot["summary"])


def test_a_first_run_with_no_baseline_still_refuses_to_save_junk():
    """With nothing to fall back on, blanks are worse than no table."""
    import gpu_credits.providers as providers

    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = lambda s, u, sc=None: (_ for _ in ()).throw(
        llm.LLMError("rate limited")
    )
    config.MAX_CONSECUTIVE_FAILURES = 2
    providers.CORE_PROGRAMS[:] = [{"name": "A", "url": "https://a.test/"}] * 5

    try:
        research.refresh(scope="quick", previous=None, progress=lambda m: None)
        check("a hopeless run still raises", False, "it returned instead")
    except research.OutOfQuota as exc:
        check("a hopeless run still raises", True)
        check("it explains itself", "untouched" in str(exc))


def test_fresh_rows_are_dated():
    import gpu_credits.providers as providers
    from datetime import date

    fetcher.fetch = lambda url: (url, "x" * 5000, "")
    fetcher.search = lambda q, max_results=5: []
    llm.complete_json = lambda s, u, sc=None: good_answer()
    config.MAX_NEW_PROGRAMS = 0
    providers.CORE_PROGRAMS[:] = [{"name": "A", "url": "https://a.test/"}]

    snapshot = research.refresh(scope="quick", progress=lambda m: None)
    row = snapshot["programs"][0]
    check("a checked row is dated today", row["last_checked"] == date.today().isoformat())
    check("a checked row says so", row["checked_this_run"] is True)
    check("the run counts what it checked", snapshot["run"]["checked_this_run"] == 1)
    check("and nothing was carried", snapshot["run"]["carried_forward"] == 0)
    check("and it is not partial", snapshot["run"]["partial"] is False)



def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        saved = snapshot_globals()
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - a crashing test is a failing test
            FAILED.append("%s crashed: %s: %s" % (test.__name__, type(exc).__name__, exc))
        finally:
            restore_globals(saved)

    print("%d passed" % len(PASSED))
    if FAILED:
        print("%d FAILED" % len(FAILED))
        for failure in FAILED:
            print("  %s" % failure)
        return 1

    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
