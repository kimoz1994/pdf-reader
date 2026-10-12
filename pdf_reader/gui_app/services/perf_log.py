"""Opt-in performance timing for the snappiness work (#87-#89, #94).

Enable with EITHER:
  * env PDFR_DEBUG_PERF=1 (truthy: 1/true/yes/on, any case), or
  * an empty marker file gui_app/perf.enabled (no env fiddling needed).

Every line goes to stdout AND is appended to gui_app/perf.log, so a launch
that swallows the console (dev.ps1's Start-Process, a detached window) still
leaves a file to send over. Without either switch every entry point no-ops
after one attribute check, so the hot paths pay nothing in normal use.

mark()/log_since() measure *perceived* latency: mark at the click, pop on
the first paint that shows the result ("back: click -> library first paint").
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_ENV = os.environ.get("PDFR_DEBUG_PERF", "").strip().lower()
_MARKER = Path(__file__).resolve().parent.parent / "perf.enabled"
# Any non-empty spelling the user may have tried counts ("1", "true",
# "yes"…); only empty / 0 / false / no / off stay off.
ENABLED = _ENV not in ("", "0", "false", "no", "off") or _MARKER.exists()

_LOG_PATH = Path(__file__).resolve().parent.parent / "perf.log"
_started = False
_marks: dict[str, float] = {}


def _emit(line: str) -> None:
    print(f"[perf] {line}", flush=True)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[perf] {line}\n")
    except OSError:
        pass


def _banner() -> None:
    global _started
    if _started:
        return
    _started = True
    _emit(
        f"=== session start pid {os.getpid()} "
        f"{datetime.now():%Y-%m-%d %H:%M:%S} "
        f"(log: {_LOG_PATH}) ==="
    )


def log(label: str, ms: float) -> None:
    if not ENABLED:
        return
    _banner()
    _emit(f"{label}: {ms:.2f} ms")


@contextmanager
def span(label: str):
    """Time the enclosed block; no-op unless perf logging is enabled."""
    if not ENABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log(label, (time.perf_counter() - t0) * 1000.0)


def mark(name: str) -> None:
    """Stamp 'now' (e.g. at the click) for a later log_since."""
    if not ENABLED:
        return
    _banner()
    _marks[name] = time.perf_counter()


def log_since(name: str, label: str) -> None:
    """Log ms elapsed since mark(name); no-op when the mark is absent."""
    if not ENABLED:
        return
    t0 = _marks.pop(name, None)
    if t0 is None:
        return
    log(label, (time.perf_counter() - t0) * 1000.0)


def discard(name: str) -> None:
    """Drop a mark that will never be paid out (Back that goes elsewhere)."""
    if ENABLED:
        _marks.pop(name, None)
