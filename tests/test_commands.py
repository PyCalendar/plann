from unittest.mock import MagicMock, patch  # noqa: F401

from caldav import Todo


def test_todos_missing_treats_priority_zero_as_undefined():
    """PRIORITY:0 is RFC 5545 "undefined priority", and plann treats it as
    such everywhere else (`comp.get('PRIORITY', 0)`, _mass_reprioritize).
    set-task-attribs must therefore still offer to set a priority on such a
    task - filtering on "property absent" alone skips exactly the tasks the
    feature exists to fix."""
    from plann.commands import _todos_missing

    def _todo(uid, extra):
        return Todo(data=(
            "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\n"
            f"UID:{uid}\nSUMMARY:{uid}\n{extra}END:VTODO\nEND:VCALENDAR"))

    absent = _todo('no-priority', '')
    zero = _todo('zero-priority', 'PRIORITY:0\n')
    real = _todo('real-priority', 'PRIORITY:3\n')

    missing = _todos_missing([absent, zero, real], 'priority')
    uids = {x.icalendar_component['UID'] for x in missing}
    assert uids == {'no-priority', 'zero-priority'}


def _vtodo(uid, extra):
    return Todo(data=(
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\n"
        f"UID:{uid}\nSUMMARY:{uid}\n{extra}END:VTODO\nEND:VCALENDAR"))


def test_mismatched_date_types_fixed_on_due(monkeypatch):
    """A VTODO with DTSTART as a date and DUE as a timestamp has no DTEND.
    The sanity check must fix DUE, not crash with KeyError on DTEND - and
    must keep the time of day already on DUE.  The date becomes local
    midnight in the implicit timezone, also when DUE is in UTC."""
    import datetime
    from zoneinfo import ZoneInfo

    from plann import timespec
    from plann.commands import _fix_mismatched_date_types

    monkeypatch.setitem(vars(timespec.tz), "_implicit_timezone", ZoneInfo("America/New_York"))
    comp = _vtodo('mixed', "DTSTART;VALUE=DATE:20261116\nDUE:20261118T140000Z\n").icalendar_component
    _fix_mismatched_date_types(comp)
    assert 'DTEND' not in comp
    assert comp['DTSTART'].dt == datetime.datetime(2026, 11, 16, tzinfo=ZoneInfo("America/New_York"))
    assert comp['DTSTART'].dt.date() == datetime.date(2026, 11, 16)
    assert comp['DUE'].dt == datetime.datetime(2026, 11, 18, 14, 0, tzinfo=datetime.timezone.utc)
    assert b'VALUE=DATE' not in comp.to_ical()


def test_mismatched_date_types_floating_stays_floating():
    """With a floating timestamp on the other side, the date becomes a
    floating midnight too"""
    import datetime

    from plann.commands import _fix_mismatched_date_types

    comp = _vtodo('floating', "DTSTART:20261116T100000\nDUE;VALUE=DATE:20261118\n").icalendar_component
    _fix_mismatched_date_types(comp)
    assert comp['DUE'].dt == datetime.datetime(2026, 11, 18)


def test_aware_vs_floating_does_not_crash():
    """A floating DTSTART and a UTC DUE cannot be compared directly"""
    from plann.commands import _fix_mismatched_date_types

    comp = _vtodo('aware-floating', "DTSTART:20261119T100000\nDUE:20261118T140000Z\n").icalendar_component
    _fix_mismatched_date_types(comp)
