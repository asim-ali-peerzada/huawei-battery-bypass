"""ZeroCell visual style — the Terminal theme.

Kept as a dataclass so the palette/typography/geometry stay tunable in one
place without touching layout code.
"""

from __future__ import annotations

from dataclasses import dataclass

FONT_MONO = "Courier New"

FontSpec = tuple[str, int, str]


@dataclass(frozen=True)
class Theme:
    mode: str
    bg: str
    panel_border: str
    ink: str
    muted: str
    accent: str
    accent_hover: str
    accent_ink: str
    success: str
    success_hover: str
    danger: str
    radius: int
    outline_button: bool = True
    uppercase: bool = True
    status_font: FontSpec = (FONT_MONO, 19, "bold")
    body_font: FontSpec = (FONT_MONO, 14, "normal")
    label_font: FontSpec = (FONT_MONO, 14, "bold")
    header: str = "ZEROCELL :: AT MODEM BYPASS"
    idle_status: str = "$ READY"
    idle_detail: str = "> run the steps below, then press start"


THEME = Theme(
    mode="dark",
    bg="#0A0A0A",
    panel_border="#1E1E1E",
    ink="#E6E6E6",
    muted="#7A7A7A",
    accent="#D9F24A",
    accent_hover="#C3DA3C",
    accent_ink="#161F00",
    success="#34D399",
    success_hover="#28B487",
    danger="#FF6B6B",
    radius=2,
)
