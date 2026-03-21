from utils.helpers import utc_today, format_date_iso, days_ago, date_range


def test_utc_today():
    today = utc_today()
    assert today is not None
    assert hasattr(today, "year")
    assert hasattr(today, "month")
    assert hasattr(today, "day")


def test_format_date_iso():
    from datetime import date

    d = date(2024, 1, 15)
    assert format_date_iso(d) == "2024-01-15"


def test_days_ago():
    result = days_ago(1)
    assert result is not None
    assert result < utc_today()


def test_date_range():
    from datetime import date

    start = date(2024, 1, 1)
    end = date(2024, 1, 5)
    dates = list(date_range(start, end))
    assert len(dates) == 5
    assert dates[0] == start
    assert dates[-1] == end
