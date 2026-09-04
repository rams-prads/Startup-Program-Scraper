"""Settings for the scraper.

Everything you might want to tweak lives here so you do not have to dig
through the app code.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Picks up a .env sitting next to the app so nobody has to fiddle with
    # shell environment variables.
    load_dotenv()
except ImportError:
    pass


# Which backend writes the rows. The rest of the app does not care which one
# you pick, so switching is a one line change.
#
#   "gemini"      Google AI Studio free tier. No card, just a key.
#   "groq"        Groq free tier. Very fast. No card, just a key.
#   "openrouter"  Free models on OpenRouter. One key for a lot of them.
#   "ollama"      Runs on your own machine. No account, no limits, no key.
#   "anthropic"   Paid. Best quality. Here for when a run really matters.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")

# If a model name here has been retired, run `python check_setup.py` and it
# will print the names your key can actually use right now.
MODELS = {
    "gemini": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
    "groq": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "openrouter": os.environ.get(
        "OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324:free"
    ),
    "ollama": os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"),
}

# Which environment variable each backend reads its key from. Ollama has no
# key because it runs locally.
KEY_NAMES = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
    "anthropic": "ANTHROPIC_API_KEY",
}

# Free tiers count requests per minute and will refuse you flatly once you
# cross the line. Gemini's free tier is 20 a minute, so we sit below it. A
# fixed pause between calls is not enough on its own, because a page that
# needs a second look costs two calls instead of one and the bursts add up.
MAX_PER_MINUTE = {
    "gemini": 12,
    "groq": 25,
    "openrouter": 15,
    "ollama": 0,  # zero means do not throttle at all
    "anthropic": 0,
}

# A floor between calls, on top of the per minute ceiling above.
PAUSE_SECONDS = {
    "gemini": 1.0,
    "groq": 0.5,
    "openrouter": 1.0,
    "ollama": 0.0,
    "anthropic": 0.0,
}

# When a free tier throttles us anyway, back off and try again. Providers
# usually tell us how long to wait and we believe them over this number.
MAX_RETRIES = 4
RETRY_WAIT_SECONDS = 25

# If this many model calls fail in a row, something is wrong with the account
# rather than with the pages, so stop instead of saving a table full of
# blanks over a good one.
MAX_CONSECUTIVE_FAILURES = 4

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

LLM_TIMEOUT = 180

# Page fetching. Plain HTTP, not rate limited, so it runs in parallel.
FETCH_TIMEOUT = 25
FETCH_WORKERS = 6

# A dropped connection should not turn a good row into a failure, so a fetch
# is retried before it is believed.
FETCH_RETRIES = 2
FETCH_RETRY_WAIT = 1.5
MAX_PAGE_CHARS = 14000
MIN_USEFUL_CHARS = 400

# Looking for programs that are not on our list. Set MAX_NEW_PROGRAMS to 0 to
# skip the discovery pass and only check what we already track.
MAX_NEW_PROGRAMS = 8
DISCOVERY_QUERIES = [
    "GPU cloud startup program free credits",
    "AI startup program cloud credits apply",
    "startup credits H100 GPU cloud provider",
    "inference API free credits for startups",
    "neocloud startup program apply GPU",
    "cloud credits for AI startups India",
]

# How many rows the app shows on one page.
ROWS_PER_PAGE = 15

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_DIR = DATA_DIR / "history"


def model_name() -> str:
    return MODELS.get(LLM_PROVIDER, "unknown")


def credentials_ok():
    """Return (ok, message) for whichever backend is selected."""
    if LLM_PROVIDER not in MODELS:
        return False, "Unknown LLM_PROVIDER: %s" % LLM_PROVIDER

    key_name = KEY_NAMES.get(LLM_PROVIDER)
    if key_name is None:
        return True, "Ollama runs locally, no key needed"

    if os.environ.get(key_name):
        return True, "%s found" % key_name

    return False, "No %s set. See the README." % key_name
