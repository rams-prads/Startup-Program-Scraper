"""Sanity check before you waste time on a full run.

    python check_setup.py

Tells you whether your key works, which models it can actually use, and
whether page downloading works from this machine.
"""

import sys

from gpu_credits import config, fetcher, llm


def main() -> int:
    print("Backend: %s" % config.LLM_PROVIDER)
    print("Model in config: %s" % config.model_name())
    print("")

    ok, message = config.credentials_ok()
    print("Credentials: %s" % message)
    if not ok:
        return 1

    print("")
    print("Models this key can use:")
    try:
        names = llm.list_models()
    except Exception as exc:  # noqa: BLE001 - we want the reason, whatever it is
        print("  could not list them: %s" % exc)
        return 1

    for name in sorted(names)[:40]:
        marker = "  <- the one in config" if name == config.model_name() else ""
        print("  %s%s" % (name, marker))

    if config.model_name() not in names:
        print("")
        print(
            "Heads up: %s is not in that list. Pick one from above and set it "
            "in gpu_credits/config.py or in your .env." % config.model_name()
        )

    print("")
    print("Testing the model with a small question...")
    try:
        answer = llm.complete_json(
            "You answer with JSON and nothing else.",
            'Reply with exactly {"ok": true}.',
            {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        print("  got back: %s" % answer)
    except Exception as exc:  # noqa: BLE001
        print("  that failed: %s" % exc)
        if "PerDay" in str(exc):
            print("")
            print(
                "  That is a daily cap on this model, not a short pause. Some "
                "models allow only 20 requests a day on the free tier, which "
                "is not enough for one run. Pick a lighter model from the "
                "list above, for example one with 'flash-lite' in the name, "
                "and set it in .env as GEMINI_MODEL=..."
            )
        return 1

    print("")
    print("Testing page downloading...")
    url, text, error = fetcher.fetch("https://www.runpod.io/startup-program")
    if error:
        print("  fetch failed: %s" % error)
    else:
        print("  read %d characters from %s" % (len(text), url))

    hits = fetcher.search("GPU cloud startup credits", max_results=3)
    if hits:
        print("  search works, first hit: %s" % hits[0]["url"])
    else:
        print("  search returned nothing. Discovery will be skipped, which is fine.")

    print("")
    print("All good. Run: streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
