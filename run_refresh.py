"""Refresh the table without opening the app.

Handy for a scheduled job, or when you just want the file updated:

    python run_refresh.py --scope full
"""

import argparse
import sys

from gpu_credits import config, research, storage
from gpu_credits.providers import SCOPES

# Program names come off other people's web pages and are full of things the
# default Windows console cannot print. Without this a rupee sign in a name
# takes the whole run down at the last step.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the credit program table.")
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        default="deep",
        help=", ".join("%s is %s" % (name, why) for name, why in SCOPES.items()),
    )
    parser.add_argument(
        "--markdown",
        default=str(config.DATA_DIR / "latest.md"),
        help="where to write the readable table, set to an empty string to skip",
    )
    args = parser.parse_args()

    ok, message = config.credentials_ok()
    if not ok:
        print(message)
        return 1

    print("Backend: %s, model: %s" % (config.LLM_PROVIDER, config.model_name()))

    previous = storage.load_latest()

    def progress(message, done=0, count=0):
        print(message, flush=True)

    try:
        snapshot = research.refresh(
            scope=args.scope,
            previous=previous,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001 - a failed run should say why
        print("The run failed: %s" % exc)
        return 1

    storage.annotate(snapshot)
    history_file = storage.save(snapshot)

    # storage.save already wrote data/latest.md. Only write a second copy if
    # somebody asked for it somewhere else.
    if args.markdown and args.markdown != str(config.DATA_DIR / "latest.md"):
        with open(args.markdown, "w", encoding="utf-8") as handle:
            handle.write(storage.render_markdown(snapshot))

    changes = storage.diff(previous, snapshot)
    print("")
    print("Saved %d programs. History copy: %s" % (len(snapshot["programs"]), history_file))
    if changes["added"]:
        print("New: %s" % ", ".join(changes["added"]))
    if changes["removed"]:
        print("Gone: %s" % ", ".join(changes["removed"]))
    for item in changes["changed"]:
        print("Changed: %s (%s)" % (item["name"], ", ".join(item["fields"])))

    return 0


if __name__ == "__main__":
    sys.exit(main())
