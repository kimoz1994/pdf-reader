"""Tests for the FSRS scheduler seam (#58).

Fuzzing is disabled here for deterministic interval assertions — the
app enables it by default (`make_scheduler(fuzz=True)`).
"""
from datetime import datetime, timedelta, timezone

from services.fsrs_scheduler import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    make_scheduler,
    rate_card,
)


def test_rate_card_new_card_good_stays_due_today():
    """(#58) Good on a brand-new card moves it along the learning steps:
    still due within minutes, hence still in today's set."""
    before = datetime.now(timezone.utc)
    fsrs_json, due = rate_card(
        None, RATING_GOOD, now=before, scheduler=make_scheduler(fuzz=False)
    )
    after = datetime.now(timezone.utc)
    assert fsrs_json  # state is serialized
    assert before < due <= after + timedelta(minutes=20)


def test_rate_card_again_keeps_card_due_today():
    """(#58) Again re-schedules in ~1 minute (learning step) — the card
    stays inside today's set."""
    before = datetime.now(timezone.utc)
    fsrs_json, due = rate_card(
        None, RATING_AGAIN, now=before, scheduler=make_scheduler(fuzz=False)
    )
    assert before < due <= before + timedelta(minutes=5)


def test_rate_card_easy_pushes_due_beyond_today():
    """(#58) Easy on a new card graduates it to a multi-day interval —
    the card leaves today's set."""
    now = datetime.now(timezone.utc)
    _, due = rate_card(
        None, RATING_EASY, now=now, scheduler=make_scheduler(fuzz=False)
    )
    assert due > now + timedelta(days=1)


def test_rate_card_round_trip_progresses_stability():
    """(#58) fsrs_json is the library's own serialization: feeding it
    back in advances the card (stability becomes non-null after review,
    and a second review schedules further out than the first)."""
    sched = make_scheduler(fuzz=False)
    now = datetime.now(timezone.utc)
    json1, due1 = rate_card(None, RATING_GOOD, now=now, scheduler=sched)
    json2, due2 = rate_card(
        json1, RATING_GOOD, now=due1, scheduler=sched
    )
    assert json1 != json2
    assert due2 > due1


def test_rate_card_hard_and_easy_accept_all_four_ratings():
    """(#58) Ratings map 1:1 to Again/Hard/Good/Easy (fsrs.Rating)."""
    sched = make_scheduler(fuzz=False)
    now = datetime.now(timezone.utc)
    for rating in (RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY):
        fsrs_json, due = rate_card(None, rating, now=now, scheduler=sched)
        assert fsrs_json
        assert due.tzinfo is not None


def test_make_scheduler_fuzz_toggle():
    """(#58 AC) Fuzzing is a constructor knob: on by default for the
    app, off in tests."""
    assert make_scheduler().enable_fuzzing is True
    assert make_scheduler(fuzz=False).enable_fuzzing is False
