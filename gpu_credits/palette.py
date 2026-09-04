"""Colour definitions for the app.

The stylesheet, the status badges and .streamlit/config.toml are all generated
from the values here, so colours cannot drift between them.

The tests measure the contrast of every text and surface pair defined below.
"""

# Warm neutral palette. The greys are red leaning to match the amber accent.
COLOURS = {
    # Surfaces
    "page": "#F3EDE1",
    "sidebar": "#EBE2D1",
    "card": "#FFFFFF",
    "header": "#F6F1E7",
    "zebra": "#FBF9F4",
    # Edges
    "border": "#D9CDB8",
    "rule": "#E8E0D0",
    # Text colours, darkest to lightest. Each clears 4.5:1 on every surface
    # listed in TEXT_ON_SURFACES.
    "heading": "#1A1613",
    "body": "#3A342E",
    "secondary": "#57504A",
    "muted": "#6A6058",
    # The one accent
    "accent": "#A24A07",
    "accent_soft": "#8C3F06",
}

# One colour per status. Pale background, dark text, for legibility.
BADGES = {
    "open to apply": ("#E2F0DE", "#256B2E"),
    "waitlist": ("#F8EBD0", "#79540A"),
    "partner or invite only": ("#E4E7F2", "#364A87"),
    "could not confirm": ("#EDE8DF", "#5F564D"),
    "discontinued": ("#F7E3DD", "#94301F"),
}

UNKNOWN_BADGE = BADGES["could not confirm"]

# Which text colours may appear on which surfaces. The tests check each pair.
TEXT_ON_SURFACES = {
    "heading": ("card", "page", "sidebar", "header", "zebra"),
    "body": ("card", "page", "sidebar", "header", "zebra"),
    "secondary": ("card", "page", "sidebar", "header", "zebra"),
    "muted": ("card", "page", "sidebar", "header", "zebra"),
    "accent": ("card", "page", "sidebar", "header", "zebra"),
}

MIN_TEXT_CONTRAST = 4.5
MIN_SURFACE_SEPARATION = 1.15
MIN_BORDER_CONTRAST = 1.4


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    red, green, blue = (_channel(part) for part in parts)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, two: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    light, dark = sorted([luminance(one), luminance(two)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


def stylesheet() -> str:
    """The app's CSS, built from the colours above rather than repeating them."""
    return """
<style>
  .block-container { padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1180px; }
  #MainMenu, footer { visibility: hidden; }

  .hero h1 {
    font-size: 1.95rem; font-weight: 700; margin: 0;
    letter-spacing: -0.022em; color: %(heading)s;
  }
  .hero p {
    color: %(secondary)s; margin: 9px 0 0; font-size: 0.94rem;
    line-height: 1.6; max-width: 68ch;
  }

  .stat-row { display: flex; gap: 12px; margin: 24px 0 8px; flex-wrap: wrap; }
  .stat {
    flex: 1 1 150px; border: 1px solid %(border)s; border-radius: 12px;
    padding: 15px 17px; background: %(card)s;
  }
  .stat-value {
    font-size: 1.5rem; font-weight: 700; color: %(heading)s;
    line-height: 1.15; letter-spacing: -0.015em;
  }
  .stat-label {
    font-size: 0.715rem; text-transform: uppercase; letter-spacing: 0.07em;
    color: %(muted)s; margin-top: 6px; font-weight: 650;
  }

  .tbl-wrap {
    border: 1px solid %(border)s; border-radius: 12px; overflow: hidden;
    background: %(card)s; box-shadow: 0 1px 2px rgba(26, 22, 19, 0.05);
  }
  .tbl-scroll { overflow-x: auto; }

  table.progs { width: 100%%; border-collapse: collapse; }
  table.progs thead th {
    background: %(header)s; text-align: left; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.075em; font-weight: 700;
    color: %(muted)s; padding: 12px 15px; border-bottom: 1px solid %(border)s;
    white-space: nowrap;
  }
  table.progs td {
    padding: 15px; vertical-align: top; font-size: 0.875rem; line-height: 1.6;
    color: %(body)s; border-bottom: 1px solid %(rule)s;
  }
  table.progs tbody tr:nth-child(even) { background: %(zebra)s; }
  table.progs tbody tr:hover { background: %(header)s; }
  table.progs tbody tr:last-child td { border-bottom: none; }

  .col-name { width: 19%%; min-width: 160px; }
  .col-status { width: 11%%; min-width: 120px; }
  .col-text { width: 35%%; min-width: 240px; }

  .tbl-name {
    font-weight: 680; font-size: 0.925rem; color: %(heading)s;
    text-decoration: none; letter-spacing: -0.008em;
  }
  .tbl-name:hover { color: %(accent)s; text-decoration: underline; }
  .tbl-sub {
    display: block; font-size: 0.715rem; color: %(muted)s; margin-top: 4px;
    word-break: break-word;
  }

  .badge {
    display: inline-block; font-size: 0.675rem; font-weight: 700;
    letter-spacing: 0.04em; padding: 3px 9px; border-radius: 999px;
    text-transform: uppercase; white-space: nowrap;
  }

  .pager {
    text-align: center; padding-top: 8px; font-size: 0.865rem;
    color: %(secondary)s;
  }
</style>
""" % COLOURS


def theme_toml() -> str:
    """The Streamlit theme file, generated so it cannot drift from the CSS."""
    return """# Generated from gpu_credits/palette.py. Edit the palette, then run
# python -m gpu_credits.palette to rewrite this file.

[theme]
base = "light"
primaryColor = "%(accent)s"
backgroundColor = "%(page)s"
secondaryBackgroundColor = "%(sidebar)s"
textColor = "%(heading)s"
font = "sans serif"

[browser]
gatherUsageStats = false
""" % COLOURS


def write_theme() -> str:
    """Rewrite .streamlit/config.toml from the palette."""
    from . import config

    target = config.ROOT / ".streamlit" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(theme_toml(), encoding="utf-8")
    return str(target)


if __name__ == "__main__":
    print("wrote %s" % write_theme())
