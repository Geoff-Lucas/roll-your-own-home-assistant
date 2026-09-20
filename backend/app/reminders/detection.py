from typing import Dict, Optional, TypedDict

from ..models import Event


class ReminderInfo(TypedDict):
    lead_days: int
    text: str


# Keyword -> reminder info, matched against the event title (case-insensitive
# substring match). Deliberately limited to occasions that typically need
# advance prep (a gift, a card, an RSVP) — same keyword-matching spirit as
# the event emoji stickers planned in PLAN.md's Calendar section, but a
# separate list scoped to "needs advance action", not "looks nice with an
# icon". Not exhaustive — extend as it turns out to matter in practice.
AUTO_REMINDER_KEYWORDS: Dict[str, ReminderInfo] = {
    "birthday": {"lead_days": 7, "text": "Get a card or gift"},
    "anniversary": {"lead_days": 7, "text": "Get a card or gift"},
    "wedding": {"lead_days": 14, "text": "Get a gift; confirm RSVP"},
    "baby shower": {"lead_days": 7, "text": "Get a gift"},
    "graduation": {"lead_days": 7, "text": "Get a card or gift"},
}


def detect_auto_reminder(title: str) -> Optional[ReminderInfo]:
    lowered = title.lower()
    for keyword, info in AUTO_REMINDER_KEYWORDS.items():
        if keyword in lowered:
            return info
    return None


def compute_reminder(event: Event) -> Optional[ReminderInfo]:
    """The reminder that should surface for this event, if any.

    A manual flag (reminder_lead_days set on the event) always takes
    priority over keyword auto-detection — see the Event model docstring.
    reminder_dismissed suppresses either path the same way.
    """
    if event.reminder_dismissed:
        return None
    if event.reminder_lead_days is not None:
        return {
            "lead_days": event.reminder_lead_days,
            "text": event.reminder_text or "Upcoming event — prepare ahead",
        }
    return detect_auto_reminder(event.title)
