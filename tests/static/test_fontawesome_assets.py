"""Static checks for vendored Font Awesome assets."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FONT_AWESOME_CSS = ROOT / "app/static/fonts/fontawesome.min.css"
WEBFONTS_DIR = ROOT / "app/static/webfonts"


def test_fontawesome_css_references_existing_webfonts():
    css = FONT_AWESOME_CSS.read_text(encoding="utf-8")
    urls = re.findall(r"url\(\.\./webfonts/([^)]+)\)", css)

    assert urls, "Font Awesome CSS should reference vendored webfonts"
    missing = sorted({url for url in urls if not (WEBFONTS_DIR / url).exists()})
    assert missing == []


def test_fontawesome_css_does_not_reference_unvendored_ttf_fallbacks():
    css = FONT_AWESOME_CSS.read_text(encoding="utf-8")

    assert ".ttf" not in css
