#!/usr/bin/env bash
# First run sets everything up. After that it just starts the app.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found. Install it, then run this again."
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Setting up for the first time. This takes a minute."
    python3 -m venv .venv
fi
. .venv/bin/activate

# Cheap when everything is already installed.
pip install --quiet --disable-pip-version-check -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "Created a .env file. Open it, paste in a free API key, save it,"
    echo "then run this again. Get a key at:"
    echo "  https://aistudio.google.com/apikey"
    exit 1
fi

streamlit run app.py
