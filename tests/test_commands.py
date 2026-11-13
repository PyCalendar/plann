from unittest.mock import MagicMock, patch  # noqa: F401

import click
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


def _saved_ical(save_method, objtype, **kwargs):
    """Run an _add_* function on a mocked calendar and return the icalendar
    caldav would build from the arguments given to save_todo/save_event"""
    import icalendar
    from caldav.lib.vcal import create_ical

    saved = {}

    def save(**kw):
        saved.update(kw)
        return MagicMock(id='uid')

    cal = MagicMock()
    setattr(cal, save_method, save)
    ctx = MagicMock()
    ctx.obj = {'calendars': [cal]}
    if objtype == 'VTODO':
        from plann.commands import _add_todo
        _add_todo(ctx, **kwargs)
    else:
        from plann.commands import _add_event
        _add_event(ctx, **kwargs)
    saved.pop('no_overwrite', None)
    saved.pop('ical', None)
    return icalendar.Calendar.from_ical(create_ical(objtype=objtype, **saved))


def _alarm(cal):
    [comp] = [x for x in cal.subcomponents if x.name != 'VTIMEZONE']
    [alarm] = comp.subcomponents
    return comp, alarm


def test_set_alarm_todo_before_due():
    import datetime
    cal = _saved_ical('save_todo', 'VTODO', summary=['water the plants'],
                      set_due='2032-12-01 10:00', set_alarm='10m')
    todo, alarm = _alarm(cal)
    assert alarm.name == 'VALARM'
    assert str(alarm['ACTION']) == 'DISPLAY'
    assert str(alarm['DESCRIPTION']) == 'water the plants'
    assert alarm['TRIGGER'].dt == -datetime.timedelta(minutes=10)
    assert alarm['TRIGGER'].params['RELATED'] == 'END'


def test_set_alarm_todo_without_due_before_dtstart():
    import datetime
    cal = _saved_ical('save_todo', 'VTODO', summary=['call'],
                      set_dtstart='2032-12-01 10:00', set_alarm='1h')
    todo, alarm = _alarm(cal)
    assert alarm['TRIGGER'].dt == -datetime.timedelta(hours=1)
    assert alarm['TRIGGER'].params.get('RELATED', 'START') == 'START'


def test_set_alarm_event_before_dtstart():
    import datetime
    cal = _saved_ical('save_event', 'VEVENT', summary='dentist',
                      timespec='2032-12-01T10:00+1h', set_alarm='15m')
    event, alarm = _alarm(cal)
    assert str(alarm['DESCRIPTION']) == 'dentist'
    assert alarm['TRIGGER'].dt == -datetime.timedelta(minutes=15)
    assert alarm['TRIGGER'].params.get('RELATED', 'START') == 'START'


def test_set_alarm_absolute_time():
    import datetime
    cal = _saved_ical('save_todo', 'VTODO', summary=['pay the bill'],
                      set_due='2032-12-05', set_alarm='2032-12-01 08:00+00:00')
    todo, alarm = _alarm(cal)
    assert alarm['TRIGGER'].dt == datetime.datetime(2032, 12, 1, 8, tzinfo=datetime.timezone.utc)


def test_set_alarm_relative_without_anchor_is_refused():
    import click
    import pytest
    with pytest.raises(click.Abort):
        _saved_ical('save_todo', 'VTODO', summary=['someday'], set_alarm='10m')


def test_set_alarm_cli_option():
    """add todo and add event take --set-alarm"""
    from plann.cli import add

    for cmd in ('todo', 'event'):
        assert '--set-alarm' in [o for p in add.commands[cmd].params for o in p.opts]


def test_set_alarm_signs_follow_icalendar():
    """-10m is before, like TRIGGER:-PT10M; +10m is after"""
    import datetime
    for value, expected in (('-10m', -10), ('10m', -10), ('+10m', 10)):
        cal = _saved_ical('save_todo', 'VTODO', summary=['x'],
                          set_due='2032-12-01 10:00', set_alarm=value)
        todo, alarm = _alarm(cal)
        assert alarm['TRIGGER'].dt == datetime.timedelta(minutes=expected), value


def test_set_alarm_absolute_time_is_tagged_date_time():
    cal = _saved_ical('save_todo', 'VTODO', summary=['pay the bill'],
                      set_due='2032-12-05', set_alarm='2032-12-01 08:00+00:00')
    todo, alarm = _alarm(cal)
    assert alarm['TRIGGER'].params['VALUE'] == 'DATE-TIME'


def test_set_alarm_number_without_unit_is_minutes():
    """A number without a unit is minutes, as in most calendar software -
    not an hour of the day, as a bare number is in a date or time argument.
    The same for every number, so 58 and 61 work alike."""
    import datetime
    for value, minutes in (('15', -15), ('61', -61), ('+5', 5), ('0.25h', -15)):
        cal = _saved_ical('save_todo', 'VTODO', summary=['x'],
                          set_due='2032-12-01 10:00', set_alarm=value)
        todo, alarm = _alarm(cal)
        assert alarm['TRIGGER'].dt == datetime.timedelta(minutes=minutes), value


def test_set_alarm_under_a_minute_without_unit_warns(caplog):
    """0.25 is 15 seconds, which is hardly meant - warn, pointing to 0.25h"""
    import datetime
    cal = _saved_ical('save_todo', 'VTODO', summary=['x'],
                      set_due='2032-12-01 10:00', set_alarm='0.25')
    todo, alarm = _alarm(cal)
    assert alarm['TRIGGER'].dt == -datetime.timedelta(seconds=15)
    assert any('0.25h' in r.getMessage() for r in caplog.records if r.levelname == 'WARNING')
    caplog.clear()
    _saved_ical('save_todo', 'VTODO', summary=['x'],
                set_due='2032-12-01 10:00', set_alarm='30s')
    assert not [r for r in caplog.records if r.levelname == 'WARNING']


def test_set_alarm_bad_number_error_shows_the_value_given(capsys):
    """The minutes unit added to a bare number does not show up in errors"""
    import click
    import pytest
    for value in ('1.2.3', '.', '1.'):
        with pytest.raises(click.Abort):
            _saved_ical('save_todo', 'VTODO', summary=['x'],
                        set_due='2032-12-01 10:00', set_alarm=value)
        out = capsys.readouterr().out
        assert f'{value}m' not in out, out


def test_set_alarm_bad_values_are_refused():
    """A fractional year or garbage is refused, not read as some timestamp"""
    import click
    import pytest
    for value in ('1.5y', 'garbage xyz'):
        with pytest.raises(click.Abort):
            _saved_ical('save_todo', 'VTODO', summary=['x'],
                        set_due='2032-12-01 10:00', set_alarm=value)


def test_set_alarm_with_duration_only_is_refused():
    """DURATION without DTSTART gives the alarm nothing to be relative to"""
    import click
    import pytest
    with pytest.raises(click.Abort):
        _saved_ical('save_todo', 'VTODO', summary=['x'], set_duration='1h', set_alarm='10m')



def test_add_event_passes_ical_lines():
    """`add -l ... event` used to drop the lines"""
    from plann.commands import _add_event

    cal = MagicMock()
    ctx = MagicMock()
    ctx.obj = {'calendars': [cal], 'ical_fragment': 'LOCATION:here'}
    _add_event(ctx, summary='x', timespec='2032-12-01T10:00+1h')
    assert cal.save_event.call_args.kwargs['ical'] == 'LOCATION:here'


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


def test_aware_vs_floating_does_not_crash(caplog):
    """A floating DTSTART and a UTC DUE cannot be compared directly - but
    the check still works, and reports a DTSTART after the DUE"""
    from plann.commands import _fix_mismatched_date_types

    comp = _vtodo('aware-floating', "DTSTART:20261119T100000\nDUE:20261118T140000Z\n").icalendar_component
    _fix_mismatched_date_types(comp)
    assert any('has dtstart after dtend/due' in r.getMessage() for r in caplog.records)


def test_mismatched_date_types_keeps_the_tzid():
    """With a named timezone on the other side, the date becomes midnight in
    that timezone, not in the implicit one, so the task keeps one timezone"""
    from plann.commands import _fix_mismatched_date_types

    comp = _vtodo('tzid', "DTSTART;VALUE=DATE:20261101\nDUE;TZID=America/New_York:20261110T120000\n").icalendar_component
    _fix_mismatched_date_types(comp)
    assert b'DTSTART;TZID=America/New_York:20261101T000000' in comp.to_ical()

    comp = _vtodo('tzid-end', "DTSTART;TZID=America/New_York:20261101T120000\nDUE;VALUE=DATE:20261110\n").icalendar_component
    _fix_mismatched_date_types(comp)
    assert b'DUE;TZID=America/New_York:20261110T000000' in comp.to_ical()


def test_mismatched_date_types_utc_tzid_is_utc(monkeypatch):
    """A TZID naming UTC is UTC: the date becomes midnight in the implicit
    timezone, as with a timestamp ending in Z"""
    import datetime
    from zoneinfo import ZoneInfo

    from plann import timespec
    from plann.commands import _fix_mismatched_date_types

    monkeypatch.setitem(vars(timespec.tz), "_implicit_timezone", ZoneInfo("America/New_York"))
    for tzid in ('UTC', 'Etc/UTC'):
        comp = _vtodo('utc', f"DTSTART;VALUE=DATE:20261101\nDUE;TZID={tzid}:20261110T120000\n").icalendar_component
        _fix_mismatched_date_types(comp)
        assert comp['DTSTART'].dt == datetime.datetime(2026, 11, 1, tzinfo=ZoneInfo("America/New_York")), tzid


def test_mismatched_date_types_one_tzid_name():
    """A TZID that icalendar knows under another name (a Windows name) is
    written under that name in both properties, not in one of them only"""
    from plann.commands import _fix_mismatched_date_types

    comp = _vtodo('windows', "DTSTART;VALUE=DATE:20261101\nDUE;TZID=W. Europe Standard Time:20261110T120000\n").icalendar_component
    _fix_mismatched_date_types(comp)
    ical = comp.to_ical()
    assert comp['DTSTART'].params['TZID'] == comp['DUE'].params['TZID'], ical
    assert b'20261101T000000' in ical and b'20261110T120000' in ical


def test_mismatched_date_types_still_checks_the_order(caplog):
    """After the date is made a timestamp, a DTSTART after the DUE is still
    reported"""
    from plann.commands import _fix_mismatched_date_types

    comp = _vtodo('late', "DTSTART;VALUE=DATE:20261201\nDUE;TZID=Europe/Oslo:20261110T120000\n").icalendar_component
    _fix_mismatched_date_types(comp)
    assert any('has dtstart after dtend/due' in r.getMessage() for r in caplog.records)


def _prio_todo(uid, priority=None):
    extra = f"PRIORITY:{priority}\n" if priority is not None else ""
    return Todo(data=(
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\n"
        f"UID:{uid}\nSUMMARY:{uid}\n{extra}END:VTODO\nEND:VCALENDAR"))


def test_select_by_priority():
    """`select --priority` filters client-side: CalDAV has no integer
    comparison, so the server cannot do it.  0 means undefined, matching
    a missing PRIORITY as well; ranges and lists are accepted."""
    import pytest

    from plann.commands import _filter_priority, _parse_priority

    objs = [_prio_todo('absent'), _prio_todo('zero', 0), _prio_todo('one', 1),
            _prio_todo('three', 3), _prio_todo('five', 5), _prio_todo('nine', 9)]

    def uids(spec):
        return {x.icalendar_component['UID'] for x in _filter_priority(objs, _parse_priority(spec))}

    assert uids('5') == {'five'}
    assert uids('0') == {'absent', 'zero'}
    assert uids('1-3') == {'one', 'three'}
    assert uids('3-1') == {'one', 'three'}
    assert uids('1,5-9') == {'one', 'five', 'nine'}
    with pytest.raises(click.BadParameter):
        uids('high')
    with pytest.raises(click.BadParameter):
        uids('10')


def test_select_passes_priority_filter_not_to_server():
    """--priority must not reach caldav's search (it would become a text
    match there), but must filter the search result."""
    from plann.commands import _select

    cal = MagicMock()
    cal.search.return_value = [_prio_todo('one', 1), _prio_todo('five', 5)]
    ctx = MagicMock()
    ctx.obj = {'calendars': [cal]}
    _select(ctx, todo=True, priority='5')
    assert 'priority' not in cal.search.call_args.kwargs
    assert [x.icalendar_component['UID'] for x in ctx.obj['objs']] == ['five']


def test_select_priority_with_pinned_tasks_filters_the_tasks():
    """--pinned-tasks --todo searches the pinning events and returns their
    parent tasks; --priority is about the tasks, not the events."""
    from caldav import Event

    from plann.commands import _select

    event = Event(data=(
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:pin\n"
        "DTSTART:20261113T100000Z\nDTEND:20261113T110000Z\n"
        "END:VEVENT\nEND:VCALENDAR"))
    cal = MagicMock()
    cal.search.return_value = [event]
    ctx = MagicMock()
    ctx.obj = {'calendars': [cal]}
    parents = [_prio_todo('one', 1), _prio_todo('five', 5)]
    with patch('plann.commands._pinned_task_parents', return_value=parents):
        _select(ctx, todo=True, pinned_tasks=True, priority='5')
    assert [x.icalendar_component['UID'] for x in ctx.obj['objs']] == ['five']


def test_select_rejects_bad_priority_before_searching():
    import pytest

    from plann.commands import _select

    cal = MagicMock()
    ctx = MagicMock()
    ctx.obj = {'calendars': [cal]}
    with pytest.raises(click.BadParameter):
        _select(ctx, todo=True, priority='high')
    cal.search.assert_not_called()
