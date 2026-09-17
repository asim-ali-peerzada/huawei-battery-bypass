"""ZeroCell main application window — Terminal style.

A single fixed-width terminal column drives one state machine
(_status/_detail/_progress/_confirm/_btn/_instructions): Idle → working steps →
done, with the worker thread reporting back through a queue.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from tkinter import messagebox

import customtkinter as ctk

from core.bypass_controller import BypassController, Step
from ui import components as c
from ui.themes import THEME, FontSpec
from utils.exceptions import BypassCancelled, BypassError
from utils.logger import log_path
from utils.version import __version__

logger = logging.getLogger("zerocell.ui")

LABEL_START = "Start Battery Bypass"
LABEL_WORKING = "Working..."
DISCLAIMER_TEXT = "I understand this writes firmware; it may not work."
CONTENT_WIDTH = 480
PAD = round(CONTENT_WIDTH * 0.03)  # ~3% gutter each side; one source of truth
WRAP_FULL = CONTENT_WIDTH - 2 * PAD


class ZeroCellApp(ctk.CTk):
    def __init__(
        self,
        controller: BypassController,
        run_callback: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self._run_callback = run_callback
        self._busy = False
        self._closed = False
        self._cancel = threading.Event()
        self._events: queue.Queue[Step | str | tuple[str, object]] = queue.Queue()

        ctk.set_appearance_mode(THEME.mode)
        self.title(f"ZeroCell v{__version__}")
        self.geometry("480x600")
        self.configure(fg_color=THEME.bg)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Fixed-width centred column: content never stretches edge-to-edge,
        # even if the window is maximised or enlarged by the user.
        self._body = ctk.CTkFrame(self, fg_color="transparent", width=CONTENT_WIDTH)
        self._body.pack(fill="y", expand=True, anchor="center")
        self._body.pack_propagate(False)

        self._build()

    # ------------------------------------------------------------------ build

    def _font(self, spec: FontSpec) -> ctk.CTkFont:
        family, size, weight = spec
        return ctk.CTkFont(family=family, size=size, weight=weight)

    def _heading(self, text: str) -> str:
        return text.upper() if THEME.uppercase else text

    def _build(self) -> None:
        t = THEME
        self.minsize(440, 560)
        self._start_text = self._heading(LABEL_START)
        self._working_text = self._heading(LABEL_WORKING)
        self.configure(fg_color=t.bg)
        for child in self._body.winfo_children():
            child.destroy()
        self._layout_terminal()
        self._set_idle()

    def _layout_terminal(self) -> None:
        t = THEME
        c.make_label(self._body, t.header, color=t.muted, font=self._font(t.label_font)).pack(
            anchor="w", padx=PAD, pady=(16, 4)
        )
        ctk.CTkFrame(self._body, height=1, fg_color=t.panel_border).pack(fill="x", padx=PAD)

        self._status = c.make_label(self._body, "", color=t.ink, font=self._font(t.status_font))
        self._status.pack(anchor="w", padx=PAD, pady=(20, 6))

        self._detail = c.make_label(
            self._body,
            "> awaiting device…",
            color=t.muted,
            wraplength=WRAP_FULL,
            font=self._font(t.body_font),
        )
        self._detail.pack(anchor="w", padx=PAD)

        self._progress = ctk.CTkProgressBar(
            self._body,
            width=WRAP_FULL,
            height=6,
            corner_radius=1,
            fg_color=t.panel_border,
            progress_color=t.accent,
        )
        self._progress.set(0)
        self._progress.pack(padx=PAD, pady=(24, 16))

        self._confirm = ctk.CTkCheckBox(
            self._body,
            text=DISCLAIMER_TEXT,
            text_color=t.muted,
            width=WRAP_FULL,
            checkbox_width=18,
            checkbox_height=18,
            height=22,
            fg_color=t.success,
            hover_color=t.success_hover,
            checkmark_color=t.bg,
            font=self._font((t.body_font[0], t.body_font[1], "normal")),
        )
        self._confirm.pack(anchor="w", padx=PAD, pady=(0, 14))

        self._btn = c.make_button(
            self._body,
            self._start_text,
            self._start,
            fg=t.accent,
            hover=t.panel_border if t.outline_button else t.accent_hover,
            ink=t.accent if t.outline_button else t.accent_ink,
            radius=t.radius,
            outline=t.outline_button,
            font=self._font(t.label_font),
        )
        self._btn.pack(fill="x", padx=PAD)

        self._instructions = c.make_label(
            self._body,
            self._heading("DATA SYNC CABLE · DEVICE POWERED ON · THEN PRESS RUN"),
            color=t.muted,
            font=self._font(t.body_font),
            wraplength=WRAP_FULL,
        )
        self._instructions.pack(anchor="w", padx=PAD, pady=(16, 0))

    # -------------------------------------------------------------- state machine

    def _set_idle(self) -> None:
        t = THEME
        self._status.configure(text=t.idle_status, text_color=t.accent)
        self._detail.configure(text=t.idle_detail, text_color=t.muted)
        self._progress.set(0)

    def _set_step(self, step: Step | str) -> None:
        t = THEME
        node = step if isinstance(step, Step) else Step[step]
        idx = list(Step).index(node) + 1
        self._status.configure(text=f"{idx}/{len(Step)} {node}", text_color=t.accent)
        self._progress.set(0.08 + 0.08 * idx)

    def _start(self) -> None:
        if self._busy:
            return
        # ponytail: Tk is single-threaded so this flag alone closes the window
        # between two queued click events; no lock needed.
        self._busy = True
        if not self._confirm.get():
            self._busy = False
            c.make_label(
                self._body,
                "Please confirm the firmware disclaimer above.",
                color=THEME.danger,
                wraplength=WRAP_FULL,
                font=self._font((THEME.body_font[0], THEME.body_font[1], "normal")),
            ).pack(padx=PAD, anchor="w")
            logger.info("disclaimer not acknowledged")
            return
        t = THEME
        self._btn.configure(state="disabled", text=self._working_text)
        self._confirm.configure(state="disabled")
        self._detail.configure(text="Please keep the device connected.", text_color=t.muted)
        self._status.configure(text="Starting...", text_color=t.ink)
        self._progress.set(0)

        self._cancel.clear()
        self._events = queue.Queue()
        self._worker = threading.Thread(target=self._job, daemon=True)
        self._worker.start()
        self.after(50, self._poll)

    def _job(self) -> None:
        try:
            if self._run_callback is not None:
                ok = self._run_callback()
            else:
                ok = self.controller.run(
                    on_step=self._events.put,
                    on_detail=lambda text: self._events.put(("detail", text)),
                    cancel=self._cancel,
                )
            self._events.put(("done", ok))
        except BypassCancelled:
            self._events.put(("cancelled", None))
        except BypassError as exc:
            self._events.put(("error", str(exc)))
        except Exception:  # pragma: no cover - defensive
            logger.exception("unexpected failure during bypass")
            self._events.put(
                (
                    "error",
                    "Something went wrong and the bypass stopped. "
                    f"Details were written to {log_path()}",
                )
            )

    def _poll(self) -> None:
        if self._closed:
            return
        if self._busy:
            if self._drain_events():
                return
            # Continuous movement so the app never looks frozen during the
            # long serial wait; capped below 1.0 so only real success fills it.
            self._progress.set(min(0.92, self._progress.get() + 0.008))
        if not self._closed:
            self.after(50, self._poll)

    def _drain_events(self) -> bool:
        try:
            while True:
                item = self._events.get_nowait()
                if isinstance(item, (Step, str)):
                    self._set_step(item)
                    continue
                kind, payload = item
                if kind == "detail":
                    self._detail.configure(text=str(payload), text_color=THEME.muted)
                elif kind == "done":
                    self._finish(bool(payload))
                    return True
                elif kind == "cancelled":
                    self._finish(False, cancelled=True)
                    return True
                elif kind == "error":
                    self._fail(str(payload))
                    return True
                else:
                    return True
        except queue.Empty:
            return False

    def _finish(self, ok: bool, *, cancelled: bool = False) -> None:
        t = THEME
        self._busy = False
        self._btn.configure(state="normal", text=self._start_text)
        self._confirm.configure(state="normal")
        if cancelled:
            self._status.configure(text="Cancelled", text_color=t.muted)
            self._detail.configure(text="No changes were applied.", text_color=t.muted)
            self._progress.set(0)
            logger.info("bypass cancelled by user")
        elif ok:
            # The API accepts the command; only the device can confirm success.
            self._status.configure(text="Command accepted", text_color=t.success)
            self._detail.configure(
                text=(
                    "Command accepted. Now verify on the device: unplug it, remove the "
                    "battery, then plug into a wall charger. It should power on without "
                    "the battery."
                ),
                text_color=t.success,
            )
            self._progress.set(1)
            logger.info("bypass command accepted")
        else:
            self._status.configure(text="Bypass did not complete.", text_color=t.danger)
            self._detail.configure(
                text="No changes were applied. Review the log for details.", text_color=t.danger
            )
            self._progress.set(0)

    def _fail(self, message: str) -> None:
        t = THEME
        self._busy = False
        self._btn.configure(state="normal", text=self._start_text)
        self._confirm.configure(state="normal")
        self._progress.set(0)
        self._status.configure(text="Error", text_color=t.danger)
        self._detail.configure(text=message, text_color=t.danger)
        logger.error("bypass error: %s", message)

    def _on_close(self) -> None:
        if self._busy and not messagebox.askyesno(
            "Bypass in progress",
            "A bypass is still running. Closing now may leave the device half-configured. "
            "Close anyway?",
        ):
            return
        # Ask the worker to stop at its next checkpoint rather than yanking the
        # window out from under it.
        self._cancel.set()
        self._closed = True
        self.destroy()

    def run(self) -> None:
        self.mainloop()
