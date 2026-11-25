"""The UI is always dark (near-black page, white text), whatever the system setting is."""

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / ".streamlit" / "config.toml"


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_theme_is_dark_with_white_text_and_readable_contrast() -> None:
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    theme = config["theme"]
    assert theme["base"] == "dark"
    assert theme["textColor"].lower() == "#ffffff"
    assert _luminance(theme["backgroundColor"]) < 0.01  # near black
    assert _contrast(theme["textColor"], theme["backgroundColor"]) >= 15
    assert _contrast(theme["textColor"], theme["secondaryBackgroundColor"]) >= 12  # inputs, panels
    assert _contrast("#ffffff", theme["primaryColor"]) >= 3  # white button text on the accent


def test_the_server_stays_on_loopback() -> None:
    server = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["server"]
    assert server["address"] == "127.0.0.1"
