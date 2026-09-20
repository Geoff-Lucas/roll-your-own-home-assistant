from datetime import datetime


def is_dim_time(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Whether `now` falls within the overnight dim window [start_hour, end_hour).

    `now` is expected to be the device's own local wall-clock time (e.g.
    datetime.now(), not UTC) — this is about what the household actually
    sees on the wall at that moment, unlike the naive-UTC convention used
    for calendar Event storage elsewhere in this app.

    Handles the normal case where the window wraps past midnight (e.g.
    start=22, end=7 means 10pm-7am) as well as a same-day window
    (start < end), so it's testable without needing to fake midnight.
    """
    if start_hour == end_hour:
        return False  # zero-length window means "never dim"
    hour = now.hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour
