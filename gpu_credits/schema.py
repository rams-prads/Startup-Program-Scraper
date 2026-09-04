"""The shape we ask the model to answer in.

We read one provider page at a time and ask for one small object back. Small
questions are what free models are good at, and it means a single bad page
cannot poison the whole table.
"""

STATUS_VALUES = [
    "open to apply",
    "partner or invite only",
    "waitlist",
    "discontinued",
    "could not confirm",
]

CATEGORY_VALUES = [
    "GPU or AI cloud",
    "Hyperscaler cloud",
    "Inference or model API",
    "Data or AI infrastructure",
    "App platform or PaaS",
    "Ecosystem or hardware program",
]

CONFIDENCE_VALUES = ["high", "medium", "low"]

ONE_PROGRAM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The program name as the page calls it.",
        },
        "what_you_get": {
            "type": "string",
            "description": (
                "Credits, discounts, support and anything else on offer. Use "
                "the real numbers when the page states them. Write that the "
                "amount is not published when it does not. Two to four "
                "sentences."
            ),
        },
        "who_qualifies": {
            "type": "string",
            "description": (
                "Eligibility in plain words. Funding stage, company age, "
                "referral requirements, region limits, review time. Two to "
                "four sentences."
            ),
        },
        "category": {"type": "string", "enum": CATEGORY_VALUES},
        "status": {"type": "string", "enum": STATUS_VALUES},
        "confidence": {
            "type": "string",
            "enum": CONFIDENCE_VALUES,
            "description": (
                "high when the page states it outright, medium when you had "
                "to read between the lines, low when the page barely covers it."
            ),
        },
        "notes": {
            "type": "string",
            "description": (
                "Catches worth knowing, for example credits that need spend "
                "up front or exclude GPU hours. Empty string if there is "
                "nothing to add."
            ),
        },
        "is_a_startup_program": {
            "type": "boolean",
            "description": (
                "False if this page turned out not to be a startup credit or "
                "compute program at all."
            ),
        },
        "published_by_the_provider": {
            "type": "boolean",
            "description": (
                "True only if this page is the compute provider writing about "
                "their own program. False if it is a directory, a comparison "
                "site, a roundup or any page listing other companies' "
                "programs, even when it is accurate and useful."
            ),
        },
    },
    "required": [
        "name",
        "what_you_get",
        "who_qualifies",
        "category",
        "status",
        "confidence",
        "notes",
        "is_a_startup_program",
        "published_by_the_provider",
    ],
}


def describe_fields(schema: dict = None) -> str:
    """Spell the schema out in the prompt itself.

    Only some backends accept a schema as a parameter. The rest have to be
    told in words, so we write it out every time and every model sees the
    same instructions.
    """
    schema = schema or ONE_PROGRAM_SCHEMA
    lines = []

    for field, spec in schema["properties"].items():
        kind = spec.get("type", "string")
        detail = spec.get("description", "")
        if spec.get("enum"):
            detail = ("One of: %s. " % ", ".join(spec["enum"])) + detail
        lines.append("- %s (%s): %s" % (field, kind, detail.strip()))

    return "\n".join(lines)


def normalise_name(name: str) -> str:
    """Loose key for matching the same program across two runs."""
    return " ".join(name.lower().replace("-", " ").split())
