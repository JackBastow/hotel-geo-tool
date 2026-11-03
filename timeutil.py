"""Time as the people using the site read it: UK time."""

NBSP = chr(160)       # a non-breaking space, so a time never wraps onto two lines


def uk_time(value):
    """A saved UTC timestamp (text such as 2026-10-21T15:15:21+00:00, or a datetime) as clear UK time: 'Tue 21 Oct 2026, 16:15 BST' (GMT in winter, BST in summer). Anything it cannot read comes back as it was."""
    import datetime as _dt
    if value in (None, ""):
        return ""
    try:
        d = value if isinstance(value, _dt.datetime) else _dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        try:
            import zoneinfo
            d = d.astimezone(zoneinfo.ZoneInfo("Europe/London"))
            zone = d.tzname()
        except Exception:  # noqa: BLE001 - no timezone database on this machine: say it is UTC rather than guess
            d, zone = d.astimezone(_dt.timezone.utc), "UTC"
        return NBSP.join([d.strftime("%a"), str(d.day), d.strftime("%b"), str(d.year) + ",", d.strftime("%H:%M"), zone])
    except Exception:  # noqa: BLE001
        return str(value)


def uk_date(value):
    """Just the date, as 'Wed 21 Oct 2026'."""
    t = uk_time(value)
    return NBSP.join(t.split(NBSP)[:4]).rstrip(",") if t and NBSP in t else t
