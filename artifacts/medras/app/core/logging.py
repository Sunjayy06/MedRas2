"""Structured logging setup.

Avoids ever logging document content. Modules should use ``get_logger`` and
log only operational metadata (route, status, duration, sizes, error types).
"""

from __future__ import annotations

import logging
import sys


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
