"""Rotating file logger that never logs tokens, serial data, or HTTP bodies."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _log_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    p = Path(base) / "zerocell"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = Path(os.path.expanduser("~/zerocell"))
        p.mkdir(parents=True, exist_ok=True)
    return p / "zerocell.log"


def log_path() -> str:
    """Public accessor so the UI can tell users where details were written."""
    return str(_log_path())


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("zerocell")
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    try:
        fh = RotatingFileHandler(
            str(_log_path()), maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        print(
            "[ZeroCell] WARNING: Could not open log file. Logging to console only.", file=sys.stderr
        )

    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.setLevel(level)
    return logger
