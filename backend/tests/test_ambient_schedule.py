from datetime import datetime

from app.ambient.schedule import is_dim_time


def at_hour(hour: int) -> datetime:
    return datetime(2026, 7, 15, hour, 0)


def test_overnight_window_wraps_past_midnight():
    # 10pm-7am
    assert is_dim_time(at_hour(23), start_hour=22, end_hour=7) is True
    assert is_dim_time(at_hour(3), start_hour=22, end_hour=7) is True
    assert is_dim_time(at_hour(6), start_hour=22, end_hour=7) is True
    assert is_dim_time(at_hour(7), start_hour=22, end_hour=7) is False  # end is exclusive
    assert is_dim_time(at_hour(21), start_hour=22, end_hour=7) is False
    assert is_dim_time(at_hour(12), start_hour=22, end_hour=7) is False


def test_same_day_window_does_not_wrap():
    assert is_dim_time(at_hour(13), start_hour=12, end_hour=14) is True
    assert is_dim_time(at_hour(11), start_hour=12, end_hour=14) is False
    assert is_dim_time(at_hour(14), start_hour=12, end_hour=14) is False


def test_zero_length_window_never_dims():
    assert is_dim_time(at_hour(22), start_hour=22, end_hour=22) is False
