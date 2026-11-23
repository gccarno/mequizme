from datetime import datetime, timezone

import pytest

from app.core.grading import grade
from app.core.scheduler import FsrsScheduler, Sm2Scheduler

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# Ported from StudyDeck Sm2AlgorithmTest.kt semantics
@pytest.mark.parametrize(
    "score,ef,reps,interval,expected",
    [
        (5, 2.5, 0, 1, (2.6, 1, 1)),        # first success -> 1 day, EF up
        (4, 2.5, 1, 1, (2.5, 2, 6)),        # second success -> 6 days, EF unchanged
        (4, 2.5, 2, 6, (2.5, 3, 15)),       # third -> round(6 * 2.5)
        (1, 2.5, 5, 30, (1.96, 0, 1)),      # failure resets
        (1, 1.3, 0, 1, (1.3, 0, 1)),        # EF floor 1.3
    ],
)
def test_sm2_step(score, ef, reps, interval, expected):
    e, r, i = Sm2Scheduler.step(score, ef, reps, interval)
    assert (round(e, 2), r, i) == expected


def test_sm2_rejects_bad_score():
    with pytest.raises(ValueError):
        Sm2Scheduler.step(0, 2.5, 0, 1)


def test_fsrs_good_beats_again():
    s = FsrsScheduler(fuzz=False)
    state = s.new(NOW).state
    good = s.review(state, 3, NOW)
    again = s.review(state, 1, NOW)
    assert good.due > again.due >= NOW
    # graduate: several good reviews push the interval out to days
    st, t = good.state, good.due
    for _ in range(3):
        nxt = s.review(st, 3, t)
        st, t = nxt.state, nxt.due
    assert (t - NOW).days >= 3


MCQ = {"type": "mcq_single", "answer": {"choiceIds": ["B"]}}
MULTI = {"type": "mcq_multi", "answer": {"choiceIds": ["A", "C"]}}
SHORT = {"type": "short_answer", "answer": {"text": "15 minutes", "accepted": ["900 seconds"]}}


def test_grading():
    assert grade(MCQ, ["B"]) is True
    assert grade(MCQ, ["A"]) is False
    assert grade(MCQ, None) is False
    assert grade(MULTI, ["C", "A"]) is True
    assert grade(MULTI, ["A"]) is False
    assert grade(SHORT, text="  15  Minutes. ") is True
    assert grade(SHORT, text="900 seconds") is True
    assert grade(SHORT, text="10 minutes") is False
    assert grade({"type": "flashcard", "answer": {"text": "x"}}) is None
