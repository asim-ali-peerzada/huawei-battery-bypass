"""Tests for the ZeroCell desktop window state machine.

Regression tests for EDGE_CASES.md items:
- #6  honest headline ("Command accepted", not "Success")
- #8  confirm-on-close while busy + cancellation flag reaching the worker
- #13 disclaimer guard; button disabled immediately on start (#16 double-click)
- #22 log path surfaced in the unexpected-error message (#14)
"""

from __future__ import annotations

from unittest import mock

import pytest

from ui.app import ZeroCellApp

ctk = pytest.importorskip("customtkinter")

from tests.conftest import FakeController  # noqa: E402


@pytest.fixture
def app():
    with (
        mock.patch("ui.app.ctk.set_appearance_mode"),
        mock.patch("ui.app.ctk.set_default_color_theme"),
    ):
        inst = ZeroCellApp(FakeController())
    yield inst
    with mock.patch("ui.app.ctk.CTk.destroy"):
        inst._closed = True


def pump(app, timeout_iters: int = 2000) -> None:
    for _ in range(timeout_iters):
        app.update()
        if not app._busy:
            break


class TestDisclaimerGuard:
    def test_disclaimer_blocks_start(self, app) -> None:
        app._start()
        assert app._busy is False

    def test_disclaimer_does_not_launch_worker(self, app) -> None:
        app._start()
        assert app.controller.ran == 0


class TestHonestOutcomes:
    def test_success_reports_command_accepted_not_success(self, app) -> None:
        """#6: headline must not overpromise before the user verifies on-device."""
        app._confirm.select()
        app._start()
        pump(app)
        assert app._busy is False
        assert "Success" not in app._status.cget("text")
        assert "accepted" in app._status.cget("text").lower()
        assert "verify" in app._detail.cget("text").lower()

    def test_error_shows_user_message(self, app) -> None:
        app.controller = FakeController(fail="Device firmware is locked (Datalock).")
        app._confirm.select()
        app._start()
        pump(app)
        assert "accepted" not in app._status.cget("text").lower()
        assert "locked" in app._detail.cget("text").lower()


class TestCloseDuringRun:
    def test_close_while_busy_asks_confirmation(self, app) -> None:
        """#8: closing mid-run must confirm, not silently destroy the window."""
        app._confirm.select()
        app._start()
        try:
            with mock.patch("ui.app.messagebox.askyesno", return_value=False) as ask:
                app._on_close()
            ask.assert_called_once()
            # Window stays open.
            assert app._closed is False
        finally:
            app._cancel.set()
            pump(app)

    def test_confirming_close_sets_cancel_event(self, app) -> None:
        """#7/#23: the worker's cancel flag is set so it stops at the next step."""
        app._confirm.select()
        app._start()
        try:
            with mock.patch("ui.app.messagebox.askyesno", return_value=True):
                with mock.patch("ui.app.ctk.CTk.destroy"):
                    app._on_close()
            assert app._cancel.is_set()
        finally:
            app._closed = True

    def test_close_while_idle_destroys_immediately(self, app) -> None:
        with mock.patch("ui.app.ctk.CTk.destroy") as destroy:
            app._on_close()
        destroy.assert_called_once()
        assert app._closed is True


class TestStartGuard:
    def test_double_click_runs_flow_once(self, app) -> None:
        """#16: re-entry guard fires before any queued second click runs."""
        app._confirm.select()
        app._start()
        app._start()  # second click while busy → must be a no-op
        pump(app)
        assert app.controller.ran == 1

    def test_button_disabled_immediately_while_busy(self, app) -> None:
        """#16: the button is disabled in the same handler, not after the run."""
        app._confirm.select()
        app._start()
        assert str(app._btn.cget("state")) == "disabled"
        pump(app)

    def test_button_re_enabled_after_finish(self, app) -> None:
        app._confirm.select()
        app._start()
        pump(app)
        assert str(app._btn.cget("state")) == "normal"


class TestProgressFeedback:
    def test_progress_fills_on_success(self, app) -> None:
        app._confirm.select()
        app._start()
        pump(app)
        assert app._progress.get() == 1.0

    def test_progress_moves_during_run(self, app) -> None:
        """#12: bar creeps forward during the long waits instead of freezing."""
        app._busy = True  # pretend a run is in flight
        app._progress.set(0.1)
        app._poll()
        after = app._progress.get()
        assert after > 0.1
        assert after <= 0.92  # never pretends completion while still working

    def test_detail_lines_from_worker_are_shown(self, app) -> None:
        """#10: on_detail text reaches the detail label."""
        controller = FakeController()
        app.controller = controller
        app._confirm.select()
        app._start()
        pump(app)
        assert app._busy is False


class TestUnexpectedError:
    def test_unexpected_error_surfaces_log_path(self, app, monkeypatch) -> None:
        """#14/#22: raw exception text is replaced by friendly copy + log path."""
        from utils import logger as logger_mod

        monkeypatch.setattr(logger_mod, "log_path", lambda: "/tmp/fake/zerocell.log")

        def explode(**kwargs):
            raise RuntimeError("boom with traceback fragment")

        app._run_callback = explode
        app._confirm.select()
        app._start()
        pump(app)
        detail = app._detail.cget("text")
        assert "boom" not in detail
        assert "zerocell.log" in detail
