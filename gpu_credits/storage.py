"""Saving runs to disk, and working out what changed between two of them."""

import json
import re
from datetime import datetime, timezone

from . import config
from .providers import classify_source, registrable_domain
from .schema import normalise_name


def annotate(snapshot: dict) -> dict:
    """Record how far each row's sources can be trusted.

    Source URLs are classified in Python rather than by the model. Rows
    sourced only to third party sites are flagged.
    """
    for row in snapshot.get("programs", []):
        sources = row.get("source_urls") or []
        program_url = row.get("program_url", "")
        kinds = [classify_source(program_url, url) for url in sources]

        if "official" in kinds:
            row["source_trust"] = "official"
        elif "own site" in kinds:
            row["source_trust"] = "own site"
        elif kinds:
            row["source_trust"] = "third party"
        else:
            row["source_trust"] = "no source"

    return snapshot


def save(snapshot: dict) -> str:
    """Write the run to data/, keep a dated copy and refresh the markdown.

    The markdown is written here rather than by the caller so that the app and
    the command line script leave the repository in the same state.
    """
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    text = json.dumps(snapshot, indent=2, ensure_ascii=False)
    config.LATEST_FILE.write_text(text, encoding="utf-8")

    markdown_file = config.DATA_DIR / "latest.md"
    markdown_file.write_text(render_markdown(snapshot), encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    history_file = config.HISTORY_DIR / ("run-%s.json" % stamp)
    history_file.write_text(text, encoding="utf-8")

    return str(history_file)


def load_latest():
    """Last saved run, or None on a fresh checkout."""
    if not config.LATEST_FILE.exists():
        return None
    try:
        return json.loads(config.LATEST_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


MONEY = re.compile(r"\$\s?[\d,]+(?:\.\d+)?\s?(?:[KMkm]|million|thousand)?")


def money_in(text: str) -> set:
    """Every amount mentioned, normalised enough to compare across runs."""
    found = set()
    for raw in MONEY.findall(text or ""):
        cleaned = raw.replace(" ", "").replace(",", "").lower()
        cleaned = cleaned.replace("million", "m").replace("thousand", "k")
        found.add(cleaned)
    return found


def _row_key(row: dict) -> str:
    """Key used to match a program across runs.

    The domain is stable. Names are written by the model and drift between
    runs, which would otherwise show a rename as one removal and one addition.
    """
    domain = registrable_domain(row.get("program_url", ""))
    return domain or normalise_name(row.get("name", ""))


def diff(old, new) -> dict:
    """Compare two runs and report material changes.

    The model rewords its prose between runs, so comparing text directly
    marks nearly every row as changed. This compares the amounts quoted and
    the status instead. Rewording is counted separately.
    """
    empty = {"added": [], "removed": [], "changed": [], "reworded": 0}
    if not old or not new:
        return empty

    old_rows = {_row_key(r): r for r in old.get("programs", [])}
    new_rows = {_row_key(r): r for r in new.get("programs", [])}

    result = {
        "added": [new_rows[k]["name"] for k in new_rows if k not in old_rows],
        "removed": [old_rows[k]["name"] for k in old_rows if k not in new_rows],
        "changed": [],
        "reworded": 0,
    }

    for key in new_rows:
        if key not in old_rows:
            continue

        before, after = old_rows[key], new_rows[key]
        fields = []

        if before.get("status") != after.get("status"):
            fields.append("status")

        old_money = money_in(before.get("what_you_get", ""))
        new_money = money_in(after.get("what_you_get", ""))
        if old_money != new_money:
            fields.append("amounts")

        if not fields:
            prose_moved = any(
                (before.get(f) or "").strip() != (after.get(f) or "").strip()
                for f in ("what_you_get", "who_qualifies")
            )
            if prose_moved:
                result["reworded"] += 1
            continue

        result["changed"].append(
            {
                "name": after["name"],
                "fields": fields,
                "before": before.get("what_you_get", ""),
                "after": after.get("what_you_get", ""),
                "gained": sorted(new_money - old_money),
                "lost": sorted(old_money - new_money),
                "model_note": after.get("changed_since_last_run", ""),
            }
        )

    return result


def render_markdown(snapshot: dict) -> str:
    """Render the run as a markdown table for reading on GitHub."""
    lines = [
        "# Startup GPU and cloud credit programs",
        "",
        "Data as of %s. Generated by %s."
        % (
            snapshot.get("as_of", "unknown"),
            snapshot.get("run", {}).get("model", "the model"),
        ),
        "",
    ]

    if snapshot.get("summary"):
        lines += [snapshot["summary"], ""]

    lines += ["| Name | What you get | Who qualifies |", "| --- | --- | --- |"]

    for row in snapshot.get("programs", []):
        name = row.get("name", "")
        url = row.get("program_url", "")
        label = "[%s](%s)" % (_cell(name), url) if url else _cell(name)
        lines.append(
            "| %s | %s | %s |"
            % (
                label,
                _cell(row.get("what_you_get", "")),
                _cell(row.get("who_qualifies", "")),
            )
        )

    lines += ["", "Sources are in `data/latest.json`."]
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    """Flatten text so it fits in a single markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def to_rows(snapshot: dict, with_links: bool = False) -> list:
    """Flatten a snapshot into the table the app shows."""
    rows = []
    for row in snapshot.get("programs", []):
        item = {
            "Name": row.get("name", ""),
            "What you get": row.get("what_you_get", ""),
            "Who qualifies": row.get("who_qualifies", ""),
        }
        if with_links:
            item["Link"] = row.get("program_url", "")
            item["Status"] = row.get("status", "")
            item["Confidence"] = row.get("confidence", "")
            item["Source"] = row.get("source_trust", "")
        rows.append(item)
    return rows
