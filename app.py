"""Streamlit front end.

Run with:  streamlit run app.py
"""

import json
import math
import os
import traceback

import pandas as pd
import streamlit as st

# On Streamlit Community Cloud the keys are in secrets rather than the
# environment. Copy them across before importing the package, which reads
# its settings at import time.
SECRET_NAMES = [
    "LLM_PROVIDER",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
]
try:
    for name in SECRET_NAMES:
        if not os.environ.get(name) and name in st.secrets:
            os.environ[name] = st.secrets[name]
except Exception:  # noqa: BLE001 - there is normally no secrets file locally
    pass

from gpu_credits import config, research, storage  # noqa: E402 - after the secrets
from gpu_credits.providers import program_list  # noqa: E402
from gpu_credits.palette import stylesheet  # noqa: E402
from gpu_credits.render import (  # noqa: E402
    SORTS,
    apply_filters,
    sort_rows,
    stat_card,
    stat_row,
    table_html,
)
from gpu_credits.schema import STATUS_VALUES  # noqa: E402

st.set_page_config(
    page_title="Startup GPU and cloud credits",
    layout="wide",
)

def saved_file_stamp():
    """When the saved table last changed on disk, or zero if there is none."""
    try:
        return config.LATEST_FILE.stat().st_mtime
    except OSError:
        return 0.0


def load_state():
    """Load the last saved run, reloading it if the file changed on disk.

    The command line refresh can run while the app is open, so the modified
    time is checked on each rerun rather than caching the table for the life
    of the browser session.
    """
    stamp = saved_file_stamp()
    if "snapshot" not in st.session_state or st.session_state.get("stamp") != stamp:
        st.session_state.snapshot = storage.load_latest()
        st.session_state.stamp = stamp
        st.session_state.page = 1
    if "changes" not in st.session_state:
        st.session_state.changes = None


def run_refresh(scope: str):
    previous = storage.load_latest()

    total = len(program_list(scope))
    with st.status(
        "Reading %d provider pages. This takes a while, leave the tab open."
        % total,
        expanded=True,
    ) as status:
        bar = st.progress(0.0)
        line = st.empty()

        def progress(message, done=0, count=0):
            line.write(message)
            if count:
                bar.progress(min(1.0, done / count))

        try:
            snapshot = research.refresh(
                scope=scope,
                previous=previous,
                progress=progress,
            )
        except Exception as exc:  # noqa: BLE001 - any failure is shown in the UI
            status.update(label="That run failed", state="error")
            st.error(str(exc))
            with st.expander("Full traceback"):
                st.code(traceback.format_exc())
            return

        storage.annotate(snapshot)
        storage.save(snapshot)

        st.session_state.snapshot = snapshot
        st.session_state.changes = storage.diff(previous, snapshot)
        st.session_state.stamp = saved_file_stamp()
        st.session_state.page = 1
        bar.progress(1.0)

        found = len(snapshot.get("programs", []))
        took = snapshot.get("run", {}).get("seconds", 0)
        status.update(
            label="Done. %d programs in %.0f seconds" % (found, took),
            state="complete",
        )


load_state()

st.markdown(stylesheet(), unsafe_allow_html=True)
st.markdown(
    '<div class="hero"><h1>Startup GPU and cloud credits</h1>'
    "<p>Each row is read off the provider's own program page at the time you "
    "press refresh. Results are not cached.</p></div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Run a refresh")

    ok, message = config.credentials_ok()
    if ok:
        st.success(message)
    else:
        st.error(message)

    scope_label = st.radio(
        "How wide should it look",
        [
            "Quick, the core %d" % len(program_list("quick")),
            "Full, the main %d" % len(program_list("full")),
            "Deep, all %d" % len(program_list("deep")),
        ],
        index=2,
        help=(
            "Deep checks every tracked provider. Free tier rate limits set "
            "the pace. If the quota runs out partway, rows already collected "
            "are kept and the rest carry over from the previous run."
        ),
    )
    scope = {"Q": "quick", "F": "full", "D": "deep"}[scope_label[0]]

    minutes = {
        "quick": "about 5 minutes",
        "full": "about 15 minutes",
        "deep": "25 to 45 minutes",
    }[scope]
    st.caption("A %s run takes %s. Keep this tab open." % (scope, minutes))

    if st.button("Refresh the table", type="primary", width="stretch"):
        run_refresh(scope)

    st.divider()
    st.caption("Backend: %s" % config.LLM_PROVIDER)
    st.caption("Model: %s" % config.model_name())

snapshot = st.session_state.snapshot

if not snapshot:
    st.info("No data yet. Use Refresh in the sidebar to fetch the first table.")
    st.stop()

programs = snapshot.get("programs", [])
run_info = snapshot.get("run", {})
open_now = sum(1 for row in programs if row.get("status") == "open to apply")

st.markdown(
    stat_row(
        [
            stat_card(len(programs), "Programs tracked"),
            stat_card(open_now, "Open to apply"),
            stat_card(snapshot.get("as_of", "unknown"), "Data as of"),
            stat_card(
                "%s of %s"
                % (run_info.get("checked_this_run", len(programs)), len(programs)),
                "Checked that run",
            ),
        ]
    ),
    unsafe_allow_html=True,
)

if run_info.get("partial"):
    st.warning(
        "%d row%s could not be rechecked on that run and %s carried over from "
        "the previous one. They keep their old date and say so under the name."
        % (
            run_info.get("carried_forward", 0),
            "" if run_info.get("carried_forward") == 1 else "s",
            "was" if run_info.get("carried_forward") == 1 else "were",
        ),
    )

# ---------------------------------------------------------------- filtering
# Filters run before paging so the page count reflects the filtered set.
search_box, status_box, sort_box = st.columns([3, 2, 2])
needle = search_box.text_input(
    "Search",
    placeholder="Search by name, benefit or eligibility",
    label_visibility="collapsed",
)
wanted = status_box.multiselect(
    "Status",
    STATUS_VALUES,
    default=[],
    placeholder="Any status",
    label_visibility="collapsed",
)
sort_label = sort_box.selectbox(
    "Sort",
    list(SORTS),
    index=0,
    label_visibility="collapsed",
)

filtered = sort_rows(apply_filters(programs, needle, wanted), SORTS[sort_label])

if not filtered:
    st.info("No programs match. Clear the search box or the status filter.")
    st.stop()

if len(filtered) != len(programs):
    st.caption("Showing %d of %d programs." % (len(filtered), len(programs)))

# ---------------------------------------------------------------- paging
per_page = config.ROWS_PER_PAGE
total_pages = max(1, math.ceil(len(filtered) / per_page))

if "page" not in st.session_state:
    st.session_state.page = 1
# A shorter list after a refresh or a filter can leave us past the end.
st.session_state.page = min(max(1, st.session_state.page), total_pages)
page = st.session_state.page

start = (page - 1) * per_page
end = min(start + per_page, len(filtered))
visible = filtered[start:end]

st.markdown(table_html(visible), unsafe_allow_html=True)

back, middle, forward = st.columns([1, 3, 1])

if back.button("Previous", disabled=page == 1, width="stretch"):
    st.session_state.page -= 1
    st.rerun()

middle.markdown(
    '<div class="pager">Page %d of %d, showing %d to %d of %d</div>'
    % (page, total_pages, start + 1, end, len(filtered)),
    unsafe_allow_html=True,
)

if forward.button("Next", disabled=page == total_pages, width="stretch"):
    st.session_state.page += 1
    st.rerun()

# ---------------------------------------------------------------- extras
st.divider()

changes = st.session_state.changes
if changes and (changes["added"] or changes["removed"] or changes["changed"]):
    with st.expander("What moved since the last run", expanded=True):
        if changes["added"]:
            st.write("**New on the list:** " + ", ".join(changes["added"]))
        if changes["removed"]:
            st.write("**Gone from the list:** " + ", ".join(changes["removed"]))

        for item in changes["changed"]:
            st.write("**%s** changed: %s" % (item["name"], ", ".join(item["fields"])))
            if item["gained"]:
                st.caption("New amounts: %s" % ", ".join(item["gained"]))
            if item["lost"]:
                st.caption("No longer mentioned: %s" % ", ".join(item["lost"]))
            st.caption("Was: %s" % item["before"])
            st.caption("Now: %s" % item["after"])

        if changes["reworded"]:
            st.caption(
                "%d other rows were reworded but say the same thing."
                % changes["reworded"]
            )
elif changes is not None:
    if changes.get("reworded"):
        st.caption(
            "Nothing material changed on the last run. %d rows were reworded "
            "but the amounts and the eligibility are the same."
            % changes["reworded"]
        )
    else:
        st.caption("Nothing changed on the last run.")

shaky = [
    row
    for row in programs
    if row.get("source_trust") in ("third party", "no source")
    or row.get("confidence") == "low"
]
if shaky:
    with st.expander("Worth a second look before you rely on it (%d)" % len(shaky)):
        for row in shaky:
            st.write("**%s**" % row.get("name", ""))
            st.caption(
                "Source: %s, confidence: %s"
                % (row.get("source_trust", "unknown"), row.get("confidence", "unknown"))
            )
            for url in row.get("source_urls", []):
                st.caption(url)

with st.expander("Sources for the programs on this page"):
    for row in visible:
        st.write("**%s**" % row.get("name", ""))
        for url in row.get("source_urls", []):
            st.caption(url)

left, right = st.columns(2)
left.download_button(
    "Download CSV",
    pd.DataFrame(storage.to_rows(snapshot, with_links=True)).to_csv(index=False),
    file_name="startup-gpu-credits-%s.csv" % snapshot.get("as_of", "latest"),
    mime="text/csv",
    width="stretch",
)
right.download_button(
    "Download JSON",
    json.dumps(snapshot, indent=2, ensure_ascii=False),
    file_name="startup-gpu-credits-%s.json" % snapshot.get("as_of", "latest"),
    mime="application/json",
    width="stretch",
)
