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


def test_set_alarm_bad_values_are_refused():
    """A duration without a unit, a fractional year or garbage is refused,
    not read as some timestamp"""
    import click
    import pytest
    for value in ('10', '1.5y', 'garbage xyz'):
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
