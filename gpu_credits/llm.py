"""One small wrapper so the rest of the app does not care which model runs.

Every backend answers the same question: here is a system prompt and a user
prompt, hand me back a JSON object. Change LLM_PROVIDER in config.py and
nothing else in the app has to change.
"""

import json
import os
import re
import time

import requests

from . import config


class LLMError(RuntimeError):
    """Something went wrong talking to the model."""


_last_call_at = 0.0
_recent_calls = []


def _pace():
    """Stay under the free tier's requests per minute.

    Two things at once. A short floor between calls so we are not bursty, and
    a sliding window over the last minute so a page that needs two calls
    cannot quietly push us over the ceiling.
    """
    global _last_call_at

    ceiling = config.MAX_PER_MINUTE.get(config.LLM_PROVIDER, 0)
    if ceiling > 0:
        now = time.time()
        _recent_calls[:] = [t for t in _recent_calls if now - t < 60]
        if len(_recent_calls) >= ceiling:
            # Wait for the oldest call to drop out of the window.
            sleep_for = 60 - (now - _recent_calls[0]) + 0.5
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            _recent_calls[:] = [t for t in _recent_calls if now - t < 60]
        _recent_calls.append(time.time())

    gap = config.PAUSE_SECONDS.get(config.LLM_PROVIDER, 0.0)
    if gap > 0:
        waited = time.time() - _last_call_at
        if waited < gap:
            time.sleep(gap - waited)

    _last_call_at = time.time()


def _quota_detail(response) -> str:
    """Report which quota was exceeded, not just that one was.

    Some free models allow 20 requests a minute and others allow 20 a day.
    The two are indistinguishable unless the quota name is read out of the
    error body.
    """
    try:
        error = response.json().get("error", {})
        for detail in error.get("details", []):
            for violation in detail.get("violations", []):
                quota = violation.get("quotaId", "")
                value = violation.get("quotaValue", "")
                if quota:
                    return "quota %s exceeded (limit %s)" % (quota, value)
    except ValueError:
        pass

    return "rate limited, out of free tier quota"


def _retry_delay(response) -> float:
    """How long to wait after a 429.

    Providers tell us, in a header or buried in the error text. Believe them
    rather than our own guess, and add a second so we are not right on the
    boundary.
    """
    header = response.headers.get("retry-after", "")
    if header.isdigit():
        return int(header) + 1

    match = re.search(r"retry in ([\d.]+)s", response.text)
    if match:
        return float(match.group(1)) + 1

    return config.RETRY_WAIT_SECONDS


def _key(name):
    value = os.environ.get(name)
    if not value:
        raise LLMError("No %s set. See the README for where to get one." % name)
    return value


def parse_json(text: str) -> dict:
    """Get a dict out of whatever the model handed back.

    Free models like wrapping JSON in a code fence or adding a sentence in
    front of it, so we are forgiving about the packaging.
    """
    if not text:
        raise LLMError("The model returned nothing.")

    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise LLMError("Could not read JSON out of: %s" % cleaned[:200])


def _strip_unsupported(schema):
    """Gemini rejects a few JSON Schema keywords, so take them out."""
    if isinstance(schema, dict):
        return {
            key: _strip_unsupported(value)
            for key, value in schema.items()
            if key not in ("additionalProperties", "$schema")
        }
    if isinstance(schema, list):
        return [_strip_unsupported(item) for item in schema]
    return schema


def _add_strictness(schema):
    """Put additionalProperties back on every object in a schema."""
    if isinstance(schema, dict):
        result = {key: _add_strictness(value) for key, value in schema.items()}
        if result.get("type") == "object" and "properties" in result:
            result["additionalProperties"] = False
        return result
    if isinstance(schema, list):
        return [_add_strictness(item) for item in schema]
    return schema


def _post(url, **kwargs):
    """POST with a retry, because free tiers throttle.

    Every attempt goes through the pacer, retries included. Counting only the
    first attempt is how we got throttled before: a burst of retries does not
    show up in the window and quietly puts us over the line.

    Anything that goes wrong at the network level comes back as an LLMError
    rather than a requests exception, so one flaky call cannot take down a
    run that is thirty programs deep.
    """
    last_error = None
    for attempt in range(config.MAX_RETRIES):
        _pace()
        try:
            response = requests.post(url, timeout=config.LLM_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            last_error = str(exc)[:120]
            if attempt == config.MAX_RETRIES - 1:
                break
            time.sleep(config.RETRY_WAIT_SECONDS)
            continue

        if response.status_code == 429:
            last_error = _quota_detail(response)
            # A daily cap will not clear no matter how long we sit here, so
            # do not burn minutes retrying one.
            if "PerDay" in last_error or attempt == config.MAX_RETRIES - 1:
                break
            time.sleep(_retry_delay(response))
            continue

        if response.status_code >= 500:
            last_error = "server error %d" % response.status_code
            time.sleep(config.RETRY_WAIT_SECONDS)
            continue

        return response

    raise LLMError("Gave up after %d tries (%s)." % (config.MAX_RETRIES, last_error))


def _gemini(system, user, schema):
    key = _key("GEMINI_API_KEY")
    model = config.MODELS["gemini"]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
        % model
    )

    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }
    if schema:
        body["generationConfig"]["responseSchema"] = _strip_unsupported(schema)

    response = _post(url, params={"key": key}, json=body)

    # Some schemas upset the API. Drop it and let the prompt do the work.
    if response.status_code == 400 and schema:
        body["generationConfig"].pop("responseSchema", None)
        response = _post(url, params={"key": key}, json=body)

    if response.status_code != 200:
        raise LLMError("Gemini said %d: %s" % (response.status_code, response.text[:300]))

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError("Gemini returned no answer: %s" % json.dumps(data)[:300])

    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text:
        reason = candidates[0].get("finishReason", "unknown")
        raise LLMError("Gemini returned empty text, finish reason %s." % reason)

    return text


def _openai_style(url, key, model, system, user, extra_headers=None):
    """Groq and OpenRouter both speak the OpenAI chat shape."""
    headers = {"Authorization": "Bearer %s" % key, "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    response = _post(url, headers=headers, json=body)

    # Not every free model supports JSON mode. Ask again without it.
    if response.status_code == 400:
        body.pop("response_format", None)
        response = _post(url, headers=headers, json=body)

    if response.status_code != 200:
        raise LLMError("%d from the model: %s" % (response.status_code, response.text[:300]))

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("No answer came back: %s" % json.dumps(data)[:300])

    return choices[0].get("message", {}).get("content", "")


def _groq(system, user, schema):
    return _openai_style(
        "https://api.groq.com/openai/v1/chat/completions",
        _key("GROQ_API_KEY"),
        config.MODELS["groq"],
        system,
        user,
    )


def _openrouter(system, user, schema):
    return _openai_style(
        "https://openrouter.ai/api/v1/chat/completions",
        _key("OPENROUTER_API_KEY"),
        config.MODELS["openrouter"],
        system,
        user,
        extra_headers={"X-Title": "Startup credit tracker"},
    )


def _ollama(system, user, schema):
    body = {
        "model": config.MODELS["ollama"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    try:
        response = _post(config.OLLAMA_URL + "/api/chat", json=body)
    except LLMError as exc:
        raise LLMError(
            "Could not reach Ollama at %s. Is it running? (%s)"
            % (config.OLLAMA_URL, exc)
        ) from exc

    if response.status_code != 200:
        raise LLMError("Ollama said %d: %s" % (response.status_code, response.text[:300]))

    return response.json().get("message", {}).get("content", "")


def _anthropic(system, user, schema):
    """The paid path. Imported lazily so the package stays optional."""
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError("pip install anthropic to use this backend.") from exc

    client = anthropic.Anthropic()
    output_config = {"effort": "high"}
    if schema:
        # This one wants the opposite of Gemini: the strict keywords have to
        # be there rather than stripped out.
        output_config["format"] = {
            "type": "json_schema",
            "schema": _add_strictness(schema),
        }

    with client.messages.stream(
        model=config.MODELS["anthropic"],
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config=output_config,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        message = stream.get_final_message()

    return "\n".join(block.text for block in message.content if block.type == "text")


BACKENDS = {
    "gemini": _gemini,
    "groq": _groq,
    "openrouter": _openrouter,
    "ollama": _ollama,
    "anthropic": _anthropic,
}


def complete_json(system: str, user: str, schema=None) -> dict:
    """Ask the selected model a question and get a dict back.

    Everything that can go wrong comes out of here as an LLMError, so callers
    only have to catch one thing.
    """
    backend = BACKENDS.get(config.LLM_PROVIDER)
    if backend is None:
        raise LLMError("Unknown LLM_PROVIDER: %s" % config.LLM_PROVIDER)

    try:
        return parse_json(backend(system, user, schema))
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - one bad call must not end the run
        raise LLMError("%s: %s" % (type(exc).__name__, exc)) from exc


def list_models():
    """What the current key is actually allowed to use. Used by check_setup."""
    provider = config.LLM_PROVIDER

    if provider == "gemini":
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": _key("GEMINI_API_KEY")},
            timeout=30,
        )
        response.raise_for_status()
        return [
            model["name"].replace("models/", "")
            for model in response.json().get("models", [])
            if "generateContent" in model.get("supportedGenerationMethods", [])
        ]

    if provider in ("groq", "openrouter"):
        url = (
            "https://api.groq.com/openai/v1/models"
            if provider == "groq"
            else "https://openrouter.ai/api/v1/models"
        )
        headers = {"Authorization": "Bearer %s" % _key(config.KEY_NAMES[provider])}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return [model["id"] for model in response.json().get("data", [])]

    if provider == "ollama":
        response = requests.get(config.OLLAMA_URL + "/api/tags", timeout=30)
        response.raise_for_status()
        return [model["name"] for model in response.json().get("models", [])]

    return [config.MODELS.get(provider, "unknown")]
