"""Opt-in performance timing for the snappiness work (#87-#89).

Set PDFR_DEBUG_PERF=1 to get one flushed `[perf] <label>: <n> ms` line per
measurement (a probe run can diff these before/after a fix). Without the env
var every entry point no-ops after one attribute check, so the hot paths pay
nothing in normal use.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager

ENABLED = os.environ.get("PDFR_DEBUG_PERF") == "1"


def log(label: str, ms: float) -> None:
    if ENABLED:
        print(f"[perf] {label}: {ms:.2f} ms", flush=True)


@contextmanager
def span(label: str):
    """Time the enclosed block; no-op unless PDFR_DEBUG_PERF=1."""
    if not ENABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log(label, (time.perf_counter() - t0) * 1000.0)
