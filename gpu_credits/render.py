"""Building the table HTML.

Kept out of app.py so it can be tested without starting Streamlit. All text
here originates from scraped pages, so it is escaped before rendering.
"""

import html
from urllib.parse import urlparse

from .palette import BADGES, UNKNOWN_BADGE

COLUMNS = ("Program", "Status", "What you get", "Who qualifies")

SORTS = {
    "Most useful first": "useful",
    "Name, A to Z": "name",
    "Recently checked first": "checked",
}

STATUS_ORDER = {
    "open to apply": 0,
    "waitlist": 1,
    "partner or invite only": 2,
    "could not confirm": 3,
    "discontinued": 4,
}

CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def esc(value) -> str:
    """Escape scraped text before it is rendered as HTML."""
    return html.escape(str(value or ""))


def safe_link(url: str) -> str:
    """Return the URL only if it is http or https, otherwise an empty string.

    program_url is whatever the provider redirected to, so other schemes such
    as javascript: are possible and must not become clickable links.
    """
    url = str(url or "").strip()
    if url.lower().startswith(("https://", "http://")):
        return url
    return ""


def short_host(url: str) -> str:
    """The domain, shown on the second line of the name cell."""
    host = urlparse(str(url or "")).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def stat_card(value, label) -> str:
    return (
        '<div class="stat"><div class="stat-value">%s</div>'
        '<div class="stat-label">%s</div></div>' % (esc(value), esc(label))
    )


def stat_row(cards) -> str:
    return '<div class="stat-row">%s</div>' % "".join(cards)


def status_badge(status: str) -> str:
    background, ink = BADGES.get(status, UNKNOWN_BADGE)
    return '<span class="badge" style="background:%s;color:%s">%s</span>' % (
        background,
        ink,
        esc(status or "unknown"),
    )


def _name_cell(row) -> str:
    name = esc(row.get("name", "Unnamed"))
    url = safe_link(row.get("program_url", ""))

    if url:
        title = (
            '<a class="tbl-name" href="%s" target="_blank" '
            'rel="noopener noreferrer">%s</a>' % (esc(url), name)
        )
    else:
        title = '<span class="tbl-name">%s</span>' % name

    # Second line: the source domain, or a note if the row was not rechecked.
    if not row.get("checked_this_run", True):
        sub = "not rechecked since %s" % esc(row.get("last_checked", "an earlier run"))
    else:
        sub = esc(short_host(url))

    if sub:
        title += '<span class="tbl-sub">%s</span>' % sub
    return title


def program_row(row) -> str:
    """One table row."""
    return (
        "<tr>"
        '<td class="col-name">%s</td>'
        '<td class="col-status">%s</td>'
        '<td class="col-text">%s</td>'
        '<td class="col-text">%s</td>'
        "</tr>"
        % (
            _name_cell(row),
            status_badge(row.get("status", "")),
            esc(row.get("what_you_get", "")),
            esc(row.get("who_qualifies", "")),
        )
    )


def table_html(rows) -> str:
    """The whole table, header included."""
    head = "".join(
        '<th class="%s">%s</th>'
        % (
            {"Program": "col-name", "Status": "col-status"}.get(name, "col-text"),
            esc(name),
        )
        for name in COLUMNS
    )
    body = "".join(program_row(row) for row in rows)
    return (
        '<div class="tbl-wrap"><table class="progs">'
        "<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>" % (head, body)
    )


def sort_rows(rows, how: str = "useful") -> list:
    """Order the table.

    "useful" sorts open programs first, then by confidence, then by name.
    """
    if how == "name":
        return sorted(rows, key=lambda r: (r.get("name") or "").lower())

    if how == "checked":
        return sorted(
            rows,
            key=lambda r: (r.get("last_checked") or "", r.get("name") or ""),
            reverse=True,
        )

    return sorted(
        rows,
        key=lambda r: (
            STATUS_ORDER.get(r.get("status"), 5),
            CONFIDENCE_ORDER.get(r.get("confidence"), 3),
            (r.get("name") or "").lower(),
        ),
    )


def matches(row, needle: str) -> bool:
    """True if the row contains the search text in any of its main fields."""
    if not needle:
        return True

    lowered = needle.lower()
    return any(
        lowered in (row.get(field) or "").lower()
        for field in ("name", "what_you_get", "who_qualifies")
    )


def apply_filters(programs, needle: str = "", statuses=None) -> list:
    """Apply the search text and status filter before paging."""
    rows = [row for row in programs if matches(row, needle)]
    if statuses:
        rows = [row for row in rows if row.get("status") in statuses]
    return rows
