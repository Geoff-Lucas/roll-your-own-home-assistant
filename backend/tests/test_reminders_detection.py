from datetime import datetime

from app.models import Event
from app.reminders.detection import compute_reminder, detect_auto_reminder


def make_event(**overrides):
    defaults = dict(
        account_id=1,
        uid="e1",
        title="Sarah's Birthday",
        all_day=True,
        start_date=None,
        end_date=None,
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_detect_auto_reminder_matches_keyword_case_insensitively():
    assert detect_auto_reminder("Sarah's BIRTHDAY party") == {"lead_days": 7, "text": "Get a card or gift"}


def test_detect_auto_reminder_no_match():
    assert detect_auto_reminder("Dentist appointment") is None


def test_compute_reminder_uses_auto_detection_by_default():
    event = make_event(title="Mom's Anniversary")
    assert compute_reminder(event) == {"lead_days": 7, "text": "Get a card or gift"}


def test_compute_reminder_manual_override_takes_priority():
    event = make_event(title="Just a birthday-themed meeting", reminder_lead_days=3, reminder_text="Bring cupcakes")
    assert compute_reminder(event) == {"lead_days": 3, "text": "Bring cupcakes"}


def test_compute_reminder_manual_override_without_text_uses_default():
    event = make_event(title="Random event", reminder_lead_days=2)
    assert compute_reminder(event) == {"lead_days": 2, "text": "Upcoming event — prepare ahead"}


def test_compute_reminder_dismissed_suppresses_either_path():
    event = make_event(title="Sarah's Birthday", reminder_dismissed=True)
    assert compute_reminder(event) is None

    event2 = make_event(title="Random", reminder_lead_days=5, reminder_dismissed=True)
    assert compute_reminder(event2) is None
