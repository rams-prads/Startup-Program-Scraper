# Startup GPU and cloud credit tracker

A table of cloud, GPU and AI compute programs that give credits to startups,
with three columns: Name, What you get, Who qualifies.

Nothing in the table is hardcoded. Each refresh downloads the provider pages
again, so the figures change when the providers change them. It runs on a free
model tier, so there is no cost to operate it.

## How it works

1. Python downloads each provider's own program page over plain HTTP.
2. The page text goes to the model, one page per call, with the instruction to
   use nothing but the text supplied.
3. Programs not already tracked are found through a DuckDuckGo search and read
   the same way.
4. Rows are sorted, saved, and compared against the previous run.

The model does no searching and has no access to its own prior knowledge of
these programs. Its only input is a page downloaded during that run.

## Quick start

On Windows, double click `start.bat`. On macOS or Linux, run `./start.sh`.
Either one creates the virtual environment, installs the dependencies and
starts the app. The first run creates a `.env` file and stops so a key can be
added.

To do the same by hand:

```bash
git clone <this-repo>
cd startup-program-scraper

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS or Linux

pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add a free key. The default backend is Google AI Studio, which
does not require a card:

1. Go to https://aistudio.google.com/apikey
2. Create a key
3. Set it in `.env` as `GEMINI_API_KEY=...`

Then check the setup and start the app:

```bash
python check_setup.py
streamlit run app.py
```

`check_setup.py` verifies the key, prints the model names the key can use, and
confirms that page downloading works. Run it first. It takes about ten seconds
and rules out the most common setup problems.

## Choosing a different free backend

One line in `.env`. Nothing else changes.

| `LLM_PROVIDER` | Key needed | Where to get it | Notes |
| --- | --- | --- | --- |
| `gemini` | `GEMINI_API_KEY` | aistudio.google.com/apikey | Default. Free, no card. Check the per model quota, see below. |
| `groq` | `GROQ_API_KEY` | console.groq.com/keys | Free, no card. Fast. |
| `openrouter` | `OPENROUTER_API_KEY` | openrouter.ai/keys | Free models, one key for several. |
| `ollama` | none | ollama.com | Runs locally. No account, no rate limit. |
| `anthropic` | `ANTHROPIC_API_KEY` | console.anthropic.com | Paid. Higher quality output. |

For Ollama, install it, run `ollama pull llama3.1:8b` and set
`LLM_PROVIDER=ollama`. Nothing leaves the machine and there is no rate limit,
but a small local model writes rougher summaries than the hosted ones.

If a model name in `gpu_credits/config.py` has been retired, `check_setup.py`
prints the names the key can use. Set one in `.env` as `GEMINI_MODEL=...`.

## Using the app

The sidebar runs a refresh. The main panel shows the results.

The table has four columns: Program, Status, What you get, Who qualifies. The
program name links to the application page, and the line beneath it shows the
domain the row was read from. Status is a colour coded badge.

Search, status filter and sort controls sit above the table. Fifteen rows are
shown per page, with Previous and Next underneath. To change that, edit
`ROWS_PER_PAGE` in `gpu_credits/config.py`.

Rows that could not be rechecked on the last run are labelled under the
program name with the date they were last read.

The whole table can be downloaded as CSV or JSON at the bottom of the page.

### Colours

Colours are defined in `gpu_credits/palette.py`. The stylesheet, the status
badges and `.streamlit/config.toml` are generated from it, and the tests check
the contrast of every text and surface pair. To change the palette, edit that
file, run `python -m gpu_credits.palette` to rewrite the theme, then run the
tests.

## Scopes and how long a run takes

| Scope | Programs checked | Rough time |
| --- | --- | --- |
| Quick | 12 core programs | 3 to 6 minutes |
| Full | 37, the main providers | 12 to 20 minutes |
| Deep | 119, everything tracked | 25 to 45 minutes |

Deep is the default. It covers the hyperscalers, the GPU neoclouds, the
inference platforms, the data and vector infrastructure, the hardware
ecosystem programs and the India based providers.

Most of the elapsed time is deliberate waiting. Free tiers cap requests per
minute, so the app holds itself to 12 a minute and queues the rest.
`MAX_PER_MINUTE` in `gpu_credits/config.py` sets this. On Ollama it is zero,
since a local model has nothing to throttle.

A page that needs a second lookup costs two calls rather than one, so the
ceiling is set below the real limit rather than at it.

There is a second limit unrelated to pacing. See below.

## Free tier quotas

Google's free tier limits are per model and vary widely. Some models allow 20
requests per day, which is not enough to complete a single run. Others allow
thousands. The model name is the only difference.

The default is `gemini-3.1-flash-lite`, which has a workable allowance and is
sufficient for reading a page and filling in three fields. Check the quota
before switching to a larger model, or a run will stop partway.

`check_setup.py` reports which limit was hit. A limit with `PerDay` in the name
does not clear by waiting, so change the model or the backend.

## Running the tests

```bash
python tests/test_offline.py
```

No test framework is needed and nothing touches the network, so it takes about
a second. Run it after changing anything.

## When something goes wrong

A run stopped early and some rows say "not rechecked". The free tier quota ran
out partway. At deep scope that is a long run, so rather than discarding it the
app keeps every row it checked and fills the rest from the previous run with
their original dates. Those rows are labelled in the app and counted in the
summary. Run it again later to finish.

The one case where it refuses to save is a first run with no previous table to
fall back on, since there would be nothing useful to write.

A model name returns 404. Free tier model names get retired. Run
`python check_setup.py` for the names the key can use, then set one in `.env`.

Rows saying "Not confirmed on this run". The reason is written into the row.
A provider blocking the request, a page that is entirely JavaScript, and a
company with no public program page are all different, and the row says which.

## How the figures are kept accurate

1. The model cannot search. It only receives page text downloaded during that
   run, so it cannot reproduce a figure from memory.
2. Each program is a separate small call, so a confusing page cannot affect
   the other rows.
3. When a seed page turns out to be the wrong page, the app looks for a better
   one on the same domain only. A third party roundup is never substituted.
4. Directory and comparison sites are rejected during discovery. The model is
   asked directly whether a page is published by the provider itself.
5. Source URLs are classified in Python after the model answers. Rows sourced
   only to third party sites are flagged separately.
6. Each run is compared against the previous one on amounts and status, so
   rewording does not register as a change.

## Files

| File | What it does |
| --- | --- |
| `app.py` | The Streamlit page, filters and paging |
| `check_setup.py` | Verifies the key and lists usable models |
| `gpu_credits/fetcher.py` | Downloading pages and search |
| `gpu_credits/llm.py` | Model wrapper, one function per backend |
| `gpu_credits/research.py` | The refresh run |
| `gpu_credits/providers.py` | Programs checked, plus trusted domains |
| `gpu_credits/render.py` | Table HTML, badges, search and sort |
| `gpu_credits/palette.py` | Colours and the contrast rules |
| `gpu_credits/schema.py` | The JSON shape the model must answer in |
| `gpu_credits/storage.py` | Saving runs, diffing, markdown output |
| `gpu_credits/config.py` | Backend, models, pacing, fetch settings |
| `run_refresh.py` | The same refresh from the command line |
| `start.bat`, `start.sh` | First run setup, then start the app |
| `tests/test_offline.py` | The test suite, no network needed |
| `Startup-Credit-Tracker-Technical-Overview.pdf` | Ten page written explanation of the whole system |
| `data/latest.json` | Last run, with sources |
| `data/latest.md` | Last run as a markdown table |

## Without the UI

```bash
python run_refresh.py --scope deep
```

Writes `data/latest.json` and `data/latest.md`, and prints what changed.

## Scheduled refresh

`.github/workflows/refresh.yml` runs a deep refresh every Monday and commits
the result. To enable it, add the key as a repository secret named
`GEMINI_API_KEY` under Settings, Secrets and variables, Actions. After that
`data/latest.md` on GitHub stays current without anyone running anything.

## Adding a provider

Add a line to `CORE_PROGRAMS`, `EXTENDED_PROGRAMS` or `DEEP_PROGRAMS` in
`gpu_credits/providers.py`, depending on how central it is. Its domain becomes
a trusted source automatically. A homepage URL is acceptable, since the app
will look for the program page on that domain.

## Things worth checking before applying

- Headline numbers are the maximum, not the typical award. Bootstrapped teams
  usually receive between $10,000 and $25,000.
- Credits expire, most within 12 to 24 months of activation. Do not activate a
  program until you are close to using it.
- Apply with a company domain email. A Gmail address is the most common reason
  applications are rejected.
- Check what the credits cover. Several programs exclude GPU hours from the
  main credit pool.
- Do not design the architecture around credits that might not arrive. Choose
  the platform that suits the workload, then apply credits to reduce the cost.

## Known limits

This is an MVP.

- No database. Runs are JSON files in `data/`.
- No login. Anyone who can reach the app can use the API quota.
- Some provider pages are JavaScript applications that serve little text to a
  plain download. Those rows are recorded as "could not confirm" rather than
  guessed at, which leaves gaps.
- A free model writes plainer summaries than a larger one. For a run where the
  wording matters, set `LLM_PROVIDER` to `anthropic` for that run.
