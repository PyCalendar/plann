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

