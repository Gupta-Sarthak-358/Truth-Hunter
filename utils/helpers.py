from datetime import datetime, timezone, date, timedelta


def utc_today():
    """Returns current UTC date"""
    return datetime.now(timezone.utc).date()


def utc_now():
    """Returns current UTC datetime"""
    return datetime.now(timezone.utc)


def format_date_iso(d):
    """Format date/datetime to YYYY-MM-DD string"""
    if isinstance(d, str):
        return d
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def parse_date(date_str):
    """Parse YYYY-MM-DD string to date object"""
    return date.fromisoformat(date_str)


def format_short_date(date_str):
    """Format YYYY-MM-DD string to Mon DD"""
    if not date_str:
        return ""
    return parse_date(date_str).strftime("%b %d")


def days_between(date1, date2):
    """Calculate days between two dates"""
    d1 = (
        parse_date(format_date_iso(date1))
        if isinstance(date1, (str, datetime, date))
        else date1
    )
    d2 = (
        parse_date(format_date_iso(date2))
        if isinstance(date2, (str, datetime, date))
        else date2
    )
    return (d2 - d1).days


def days_ago(days):
    """Return date that is <days> days ago"""
    return utc_today() - timedelta(days=days)


def date_range(start_date, end_date):
    """Yield dates between start_date and end_date inclusive"""
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)
