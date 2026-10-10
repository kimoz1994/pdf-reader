"""FSRS scheduling seam (#58) — thin wrapper over the pinned `fsrs` lib.

Owns the mapping between our stored `fsrs_json` / rating ints (1-4,
matching the review keys) and the library's `Card` / `Rating` types.
Pure Python + `fsrs`, no Qt — the GUI never talks to the library
directly.

Fuzzing: `make_scheduler()` enables it (the app's default — real spaced
repetition wants jittered intervals); tests pass `fuzz=False` for
deterministic interval assertions (#58 AC).
"""
from datetime import datetime, time, timezone
from typing import Optional, Tuple

import fsrs

# Rating ints — match fsrs.Rating and the review keys 1-4 (#58).
RATING_AGAIN = 1
RATING_HARD = 2
RATING_GOOD = 3
RATING_EASY = 4


def make_scheduler(fuzz: bool = True) -> fsrs.Scheduler:
    """The project's scheduler: default FSRS-6 parameters, fuzzing on
    (app) or off (tests)."""
    return fsrs.Scheduler(enable_fuzzing=fuzz)


def end_of_local_day_utc(now: Optional[datetime] = None) -> datetime:
    """End of the local calendar day containing `now`, as a UTC
    datetime — the cutoff `list_due_cards` needs for "today's set"
    (#58 US19: due at any point during the local day counts).

    The library's time base is UTC; the app owns the day boundary.
    """
    if now is None:
        now = datetime.now().astimezone()
    end_local = datetime.combine(now.date(), time(23, 59, 59), tzinfo=now.tzinfo)
    return end_local.astimezone(timezone.utc)


def rate_card(
    fsrs_json: Optional[str],
    rating: int,
    *,
    now: Optional[datetime] = None,
    scheduler: Optional[fsrs.Scheduler] = None,
) -> Tuple[str, datetime]:
    """Advance one card through FSRS; returns (new_fsrs_json, new_due_utc).

    `fsrs_json=None` starts a brand-new card. `rating` is 1-4
    (Again/Hard/Good/Easy). `now` defaults to the current UTC time and
    exists so tests can pin the review moment. The returned JSON is the
    library's own serialization — store it verbatim; the due datetime
    is timezone-aware UTC, ready for `record_review`.
    """
    if scheduler is None:
        scheduler = make_scheduler()
    if fsrs_json:
        card = fsrs.Card.from_json(fsrs_json)
    else:
        card = fsrs.Card()
    card, _log = scheduler.review_card(
        card,
        fsrs.Rating(rating),
        review_datetime=now or datetime.now(timezone.utc),
    )
    due = card.due
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return card.to_json(), due.astimezone(timezone.utc)
