"""Reusable styled widgets for the ZeroCell UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

# Palette — single dark neutral ramp plus one accent.
ONYX = "#101012"  # window background
BASALT = "#1a1b1e"  # card background
BASALT_2 = "#232529"  # card border / inset surface
SLATE = "#2b2b2b"  # unused legacy, kept for compatibility
BLUE = "#3b82f6"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
GRAY = "#8a8f98"
GRAY_DIM = "#6b7280"
WHITE = "#f8fafc"

STATE_COLORS = {"idle": GRAY, "active": BLUE, "done": GREEN, "failed": RED}


def make_button(
    master: ctk.CTkBaseClass,
    text: str,
    command: Callable[[], None],
    *,
    fg: str = BLUE,
    hover: str | None = None,
    ink: str = WHITE,
    radius: int = 10,
    outline: bool = False,
    height: int = 48,
    font: ctk.CTkFont | None = None,
) -> ctk.CTkButton:
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        fg_color="transparent" if outline else fg,
        hover_color=hover or (BLUE if outline else fg),
        border_color=fg,
        border_width=2 if outline else 0,
        text_color=ink,
        corner_radius=radius,
        height=height,
        font=font or ctk.CTkFont(size=15, weight="bold"),
    )


def make_label(
    master: ctk.CTkBaseClass,
    text: str,
    *,
    size: int = 13,
    color: str = GRAY,
    weight: str = "normal",
    family: str | None = None,
    wraplength: int = 0,
    justify: str = "left",
    font: ctk.CTkFont | None = None,
) -> ctk.CTkLabel:
    kwargs: dict[str, Any] = {}
    if wraplength:
        kwargs["wraplength"] = wraplength
    return ctk.CTkLabel(
        master,
        text=text,
        text_color=color,
        font=font or ctk.CTkFont(family=family, size=size, weight=weight),
        justify=justify,
        **kwargs,
    )


def make_card(master: ctk.CTkBaseClass, *, border: bool = True) -> ctk.CTkFrame:
    """Flat, subtly bordered container — the enterprise surface unit."""
    return ctk.CTkFrame(
        master,
        fg_color=BASALT,
        border_color=BASALT_2,
        border_width=1 if border else 0,
        corner_radius=12,
    )


class StepTracker(ctk.CTkFrame):
    """Vertical 1-2-3 checklist that mirrors the bypass flow.

    Tracks one current index: steps before it are done (green check),
    the current one pulses blue, the rest are dim.
    """

    def __init__(self, master: ctk.CTkBaseClass, labels: list[str]) -> None:
        super().__init__(master, fg_color="transparent")
        self._rows: list[tuple[ctk.CTkLabel, ctk.CTkLabel]] = []
        self._current = -1
        for text in labels:
            badge = ctk.CTkLabel(
                self,
                text="○",
                text_color=GRAY_DIM,
                font=ctk.CTkFont(size=15, weight="bold"),
                width=22,
            )
            row = ctk.CTkLabel(
                self,
                text=text,
                text_color=GRAY_DIM,
                font=ctk.CTkFont(size=13),
                anchor="w",
            )
            badge.grid(column=0, pady=3, padx=(4, 8), sticky="n")
            row.grid(column=1, pady=3, sticky="w")
            self._rows.append((badge, row))

    def set_current(self, index: int) -> None:
        """-1 resets to idle; otherwise index of the step in progress."""
        self._current = index
        self._paint()

    def reset(self) -> None:
        self.set_current(-1)

    def _paint(self) -> None:
        for i, (badge, row) in enumerate(self._rows):
            if self._current < 0:
                state = "idle"
            elif i < self._current:
                state = "done"
            elif i == self._current:
                state = "active"
            else:
                state = "idle"
            color = STATE_COLORS[state]
            badge.configure(text={"done": "✓", "active": "●"}.get(state, "○"), text_color=color)
            row.configure(text_color=color if state == "active" else GRAY_DIM)
