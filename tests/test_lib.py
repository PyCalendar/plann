from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from caldav import Calendar, Todo

from plann.lib import (
    _add_category,
    _add_comma_list,
    _adjust_ical_relations,
    _caldav_objclass,
    _complete,
    _component_type,
    _process_set_arg,
    _procrastinate,
    _RelativeCache,
    _set_something,
    _split_vcal,
    _summary,
    add_time_tracking,
    add_time_tracking_timew,
)

utc=timezone.utc
todo = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//CalDAV Client//EN
BEGIN:VTODO
UID:19970901T130000Z-123404@host.com
DTSTAMP:19970901T130000Z
DTSTART:19970415T133000Z
DUE:19970416T045959Z
SUMMARY:Fix a party
DESCRIPTION:Buy some food and drinks, clean up the place, hang up some baloons
PRIORITY:2
STATUS:NEEDS-ACTION
END:VTODO
END:VCALENDAR"""

## find_calendars also tested in test_functional.py

class TestFindCalendars:
    """The heavy lifting (connection parameter extraction, URL resolution
    from features, calendar lookup) is delegated to the caldav library -
    these tests only verify the plann-side glue."""

    ## auto-connect hints instead of a caldav_url - the caldav library
    ## resolves the URL from these.  (A dict rather than a profile name like
    ## "ecloud" to keep the test independent of compatibility_hints, and a
    ## username without @ to avoid triggering RFC6764 network discovery)
    features = {'auto-connect.url': {'domain': 'calendar.example.com', 'scheme': 'https', 'basepath': '/dav'}}

    def _find_calendars(self, args):
        class FakeCalendar:
            pass
        from plann.lib import find_calendars
        with patch('caldav.davclient.DAVClient.principal') as principal:
            cal = FakeCalendar()
            principal.return_value.calendars.return_value = [cal]
            principal.return_value.get_calendars.return_value = [cal]
            return find_calendars(args, raise_errors=True), cal

    def test_explicit_url(self):
        calendars, cal = self._find_calendars({
            'caldav_url': 'https://calendar.example.com/dav',
            'caldav_user': 'user', 'caldav_pass': 'hunter2'})
        assert calendars == [cal]

    def test_features_without_url(self):
        """A config section without caldav_url should work when the URL can
        be derived from the features (auto-connect.url hints)."""
        calendars, cal = self._find_calendars({
            'caldav_user': 'user', 'caldav_pass': 'hunter2',
            'features': self.features})
        assert calendars == [cal]

    def test_password_command(self, tmp_path):
        """caldav runs a password_command only with the config file it came
        from, so plann has to pass that file along."""
        import sys
        config_file = tmp_path / "calendar.conf"
        config_file.write_text("")
        config_file.chmod(0o600)
        section = {'caldav_url': 'https://calendar.example.com/dav',
                   'caldav_password_command': [sys.executable, '-c', "print('s3cr3t')"]}
        from plann.lib import find_calendars
        with patch('caldav.get_calendars', return_value=[]) as get_calendars:
            find_calendars(section, raise_errors=True, config_file=str(config_file))
        assert get_calendars.call_args.kwargs['password'] == 's3cr3t'

    def test_failing_password_command(self, tmp_path, caplog):
        """A failing command is reported, and only stops discovery under
        --raise-errors."""
        import sys

        import pytest
        config_file = tmp_path / "calendar.conf"
        config_file.write_text("")
        config_file.chmod(0o600)
        section = {'caldav_url': 'https://calendar.example.com/dav',
                   'caldav_password_command': [sys.executable, '-c', 'raise SystemExit(3)']}
        from plann.lib import find_calendars
        assert find_calendars(section, raise_errors=False, config_file=str(config_file),
                              section_name='work') == []
        assert 'section work exited with status 3' in caplog.text
        with pytest.raises(ValueError, match='status 3'):
            find_calendars(section, raise_errors=True, config_file=str(config_file))

    def test_no_connection_params(self):
        calendars, cal = self._find_calendars({})
        assert calendars == []

    def test_extra_config(self):
        """The extra_config section key (used i.a. for the time tracking
        integration, cf. add_time_tracking) should be attached to all
        calendars found, defaulting to an empty dict."""
        class FakeCalendar:
            pass
        from plann.lib import find_calendars
        with patch('caldav.davclient.DAVClient.principal') as principal:
            cal = FakeCalendar()
            principal.return_value.calendars.return_value = [cal]
            principal.return_value.get_calendars.return_value = [cal]
            calendars = find_calendars({
                'caldav_url': 'https://calendar.example.com/dav',
                'extra_config': {'time_tracking': ['timew']}},
                raise_errors=True)
            assert calendars == [cal]
            assert cal.extra_config == {'time_tracking': ['timew']}

            calendars = find_calendars(
                {'caldav_url': 'https://calendar.example.com/dav'},
                raise_errors=True)
            assert calendars[0].extra_config == {}

def test_summary():
    t = Todo()
    t.data = todo
    assert(_summary(t) == "Fix a party")
    assert(_summary(t.icalendar_component) == "Fix a party")
    t.icalendar_component.pop('SUMMARY')
    assert(_summary(t) == "Buy some food and drinks, clean up the place, hang up some baloons")
    t.icalendar_component.pop('DESCRIPTION')
    assert(_summary(t) == "19970901T130000Z-123404@host.com")

def test_component_type():
    from caldav import Event, Journal
    t = Todo()
    t.data = todo
    assert _component_type(t) == 'VTODO'
    assert _component_type(t.icalendar_component) == 'VTODO'

    ## a description text that mentions BEGIN:VEVENT must not be misclassified
    t.icalendar_component['DESCRIPTION'] = 'paste this BEGIN:VEVENT into the calendar'
    assert _component_type(t) == 'VTODO'

    assert _caldav_objclass(todo) is Todo
    assert _caldav_objclass(t.data) is Todo
    event_ical = todo.replace('VTODO', 'VEVENT').replace('DUE:19970416T045959Z\n', '')
    assert _caldav_objclass(event_ical) is Event
    journal_ical = todo.replace('VTODO', 'VJOURNAL').replace('DUE:19970416T045959Z\n', '')
    assert _caldav_objclass(journal_ical) is Journal
    ## add ical also accepts a bare component without the VCALENDAR wrapper
    bare_todo = todo[todo.index('BEGIN:VTODO'):todo.index('END:VCALENDAR')]
    assert _caldav_objclass(bare_todo) is Todo

@pytest.mark.parametrize("method", [add_time_tracking_timew, add_time_tracking])
@patch("plann.lib.subprocess.run")
def test_add_time_tracking_timew(mock_run, method):
    ts1 = datetime(2020, 2, 20, 20, 2)
    ts2 = datetime(2020, 2, 20, 20, 20)
    obj = Todo()
    obj.data = todo
    obj.parent=Calendar()
    ## "timewarrior" as in the config file documentation - "timew" and
    ## "Timewarrior" should also be accepted
    obj.parent.extra_config={'time_tracking': ['timewarrior']}

    method(obj, ts1, ts2)

    mock_run.assert_called_once()
    cmd_arr = mock_run.mock_calls[0].args[0]
    assert cmd_arr[0:5] == ['timew', 'track', '2020-02-20T20:02', '-', '2020-02-20T20:20']


def test_list_separator():
    """_list joins output with newlines by default, but the separator
    should be configurable."""
    from plann.lib import _list
    with patch('plann.lib.click.echo_via_pager') as pager:
        _list(['a', 'b', 'c'])
        pager.assert_called_once_with('a\nb\nc')
    with patch('plann.lib.click.echo_via_pager') as pager:
        _list(['a', 'b', 'c'], separator=' | ')
        pager.assert_called_once_with('a | b | c')


def test_interactive_edit_start():
    """The interactive 'start' command kicks off time tracking and then
    re-prompts, so a follow-up command can be given for the same task."""
    from plann.interactive import _interactive_edit
    obj = Todo()
    obj.data = todo
    prompts = iter(['start', 'ignore'])
    with patch('plann.interactive.add_time_tracking') as att:
        with patch.object(obj, 'save'):
            with patch('click.echo'):
                with patch('click.prompt', side_effect=lambda *a, **k: next(prompts)) as prompt:
                    _interactive_edit(obj)
    att.assert_called_once_with(obj)
    assert prompt.call_count == 2


def _comma_list_set(obj, prop):
    """Read a comma-list property (CATEGORIES single-line vCategory, or
    RESOURCES multi-line list) back as a set of strings."""
    val = obj.icalendar_component.get(prop)
    if val is None:
        return set()
    if hasattr(val, 'cats'):
        return {str(x) for x in val.cats}
    if isinstance(val, list):
        return {str(x) for x in val}
    return {str(val)}


def test_add_set_category():
    t = Todo()
    t.data = todo
    _add_category(t, 'foo')
    assert 'CATEGORIES:foo' in t.data
    assert _comma_list_set(t, 'CATEGORIES') == {'foo'}
    _add_category(t, 'bar')
    assert _comma_list_set(t, 'CATEGORIES') == {'foo', 'bar'}
    ## singular "category" appends ...
    _set_something(t, 'category', 'zoo')
    assert _comma_list_set(t, 'CATEGORIES') == {'foo', 'bar', 'zoo'}
    ## ... while plural "categories" replaces (and splits on comma)
    _set_something(t, 'categories', 'zoo,bar')
    assert _comma_list_set(t, 'CATEGORIES') == {'zoo', 'bar'}


def test_add_set_resources():
    """RESOURCES is the other RFC 5545 comma-list property and should behave
    like CATEGORIES: append via _add_comma_list, replace via plural set."""
    t = Todo()
    t.data = todo
    _add_comma_list(t, 'resources', ['Projector'])
    _add_comma_list(t, 'resources', ['Easel', 'Screen'])
    assert _comma_list_set(t, 'RESOURCES') == {'Projector', 'Easel', 'Screen'}
    ## plural "resources" replaces
    _set_something(t, 'resources', ['Whiteboard'])
    assert _comma_list_set(t, 'RESOURCES') == {'Whiteboard'}


@pytest.mark.parametrize("lines, prop, expected", [
    ## icalendar returns a list of vCategory when CATEGORIES appears twice
    ("CATEGORIES:a,b\nCATEGORIES:c\n", 'categories', {'a', 'b', 'c', 'x'}),
    ## ... and a single comma-joined vText for RESOURCES
    ("RESOURCES:a,b\n", 'resources', {'a', 'b', 'x'}),
])
def test_add_comma_list_keeps_existing_values(lines, prop, expected):
    t = Todo()
    t.data = todo.replace('END:VTODO', lines + 'END:VTODO')
    _add_comma_list(t, prop, ['x'])
    assert _comma_list_set(t, prop.upper()) == expected


def test_process_set_arg_comma_list():
    """Plural forms split a lone comma value; singular forms keep it literal.
    Resources must get the same treatment as categories (previously it did not
    split)."""
    ## plural: comma-split
    assert _process_set_arg('categories', ('a,b',), keep_category=True) == {'categories': ['a', 'b']}
    assert _process_set_arg('resources', ('a,b',), keep_category=True) == {'resources': ['a', 'b']}
    ## singular: comma kept literal (one token)
    assert _process_set_arg('category', ('a,b',), keep_category=True) == {'category': ['a,b']}
    ## without keep_category, the singular alias is canonicalised to plural
    ## (replace semantics, used by the create path -> save_todo(categories=...))
    assert _process_set_arg('category', ('a,b',), keep_category=False) == {'categories': ['a,b']}

## _hasreltype is skipped as for now (too small and only used in _procrastinate)

## _procrastinate is quite complex because of the relationship handling.
## With the defaults, the only "functional" stuff it's doing is to call
## obj.set_due, which can easily be mocked up.
def test_procrastinate_without_relations():
    t = Todo()
    t.data = todo
    with patch.object(t, 'save'):
        with patch.object(t, 'set_due', return_value=None) as set_due_mocked:
            ## procrasting an overdue task should always end up with a future due
            _procrastinate([t], '10d')
            assert(set_due_mocked.call_count == 1)
            timearg = set_due_mocked.call_args[0][0]
            assert(timearg.astimezone(utc) <=
                   datetime.now().astimezone(utc)+timedelta(days=10))
            assert(timearg.astimezone(utc) >
                   datetime.now().astimezone(utc)+timedelta(days=9, hours=23, minutes=59))

            ## In 2033, surely plann must be obsoleted by AI-tools, let's add 20 years to that to be sure
            future = datetime(2053, 1, 1, 12, 0, 0).astimezone(utc)
            t.icalendar_component.pop('DUE')
            t.icalendar_component.add('DUE', future)
            _procrastinate([t], '10d')
            assert(set_due_mocked.call_count == 2)
            timearg = set_due_mocked.call_args[0][0]
            assert(timearg.astimezone(utc) == future+timedelta(days=10))

def test_adjust_ical_relations():
    t = Todo()
    t.data = todo

    ## populate some children and parents, series A and B, serial 0 and 2:
    for reltype in ['CHILD', 'PARENT']:
        for series in ('A', 'B'):
            for num in (0,2):
                t.icalendar_component.add('RELATED-TO', f"{reltype}-{series}{num}", parameters={'RELTYPE': reltype})
    ical_data1 = t.data

    ## This should keep all the parents, add all missing A-children, and remove all B-children
    assert not _adjust_ical_relations(t, {})
    assert(t.data == ical_data1)
    _adjust_ical_relations(t, {'CHILD': {'CHILD-A0', 'CHILD-A1', 'CHILD-A2'}}) is True
    assert(t.data != ical_data1)

    rels = t.get_relatives(reltypes={'CHILD'}, fetch_objects=False)

    assert(rels['CHILD'] == {'CHILD-A0', 'CHILD-A1', 'CHILD-A2'})

    ## CHILD should be the only key now
    rels.pop('CHILD')
    assert not rels

    rels = t.get_relatives(fetch_objects=False)
    ## should return both parents and children
    ## parent list should be unchanged
    assert(rels['PARENT'] == {'PARENT-A0', 'PARENT-A2', 'PARENT-B0', 'PARENT-B2'})
    assert(rels['CHILD'] == {'CHILD-A0', 'CHILD-A1', 'CHILD-A2'})

def _one_vcal(uid):
    return (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Example Corp.//CalDAV Client//EN\n"
        "BEGIN:VEVENT\n"
        f"UID:{uid}\n"
        f"SUMMARY:event {uid}\n"
        "DTSTART:20250101T100000Z\n"
        "END:VEVENT\n"
        "END:VCALENDAR"
    )


def test_split_vcals():
    """Multiple concatenated VCALENDAR streams are split into one entry each."""
    from icalendar import Calendar

    from plann.lib import _split_vcals

    joined = _one_vcal("a") + "\n" + _one_vcal("b") + "\n" + _one_vcal("c")
    output = _split_vcals(joined)
    assert len(output) == 3
    ## each piece must round-trip as a standalone single-event VCALENDAR
    uids = []
    for piece in output:
        cal = Calendar.from_ical(piece)
        events = [c for c in cal.subcomponents if c.name == 'VEVENT']
        assert len(events) == 1
        uids.append(str(events[0]['UID']))
    assert uids == ['a', 'b', 'c']


def test_split_vcals_crlf():
    """CRLF line endings (RFC 5545 canonical) must split too - the previous
    hand-rolled LF-only scanner silently returned nothing (code review C11)."""
    from plann.lib import _split_vcals

    joined = (_one_vcal("a") + "\n" + _one_vcal("b")).replace("\n", "\r\n")
    assert len(_split_vcals(joined)) == 2


def test_split_vcal():
    ## This VCALENDAR contains three events, but only two separate
    ## event components as one of the events is a recurrence object.
    ## According to the CalDAV standard it should be wrapped in two VCALENDAR
    input = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//eome//prodid//en_DK
BEGIN:VTIMEZONE
TZID:Europe/Oslo
X-LIC-LOCATION:Europe/Oslo
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:20251026T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:20250330T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:2025-09-27-189a6563aa65236c@techtalks.com
SUMMARY:Varnish - the world's fastest web cache
DTSTART:20250927T103000Z
DTEND:20250927T110000Z
DESCRIPTION: A talk about Varnish
LOCATION:Room 1: Dubulti 2
END:VEVENT
BEGIN:VEVENT
SUMMARY:recurrence with attendee one single item
DTSTART;TZID=Europe/Zurich:20240101T090000
DTEND;TZID=Europe/Zurich:20240101T180000
UID:test1
DESCRIPTION:this is the recurrent series
TRANSP:OPAQUE
RRULE:FREQ=WEEKLY;BYDAY=TU,WE,TH
END:VEVENT
BEGIN:VEVENT
SUMMARY:single item
DTSTART;TZID=Europe/Zurich:20240605T090000
DTEND;TZID=Europe/Zurich:20240605T170000
UID:test1
DESCRIPTION:this is the single item assigning a attendee to just one event
ATTENDEE:foo.bar@corge.baz
RECURRENCE-ID:20240605T070000Z
END:VEVENT
END:VCALENDAR
"""
    output = _split_vcal(input)
    assert(len(output) == 2)


def test_warn_orphaned_recurrence_id(caplog):
    """A UID group holding only RECURRENCE-ID overrides has lost its master
    event - typically deleted by the originating calendar application without
    cleaning up the overrides.  `add ical` imports it, but says so."""
    from plann.lib import _warn_orphaned_overrides
    orphan = todo.replace(
        'UID:19970901T130000Z-123404@host.com',
        'UID:orphan-uid@host.com\nRECURRENCE-ID:19970415T133000Z')
    with caplog.at_level('WARNING'):
        _warn_orphaned_overrides(orphan)
    assert 'orphan-uid@host.com' in caplog.text

    ## several concatenated VCALENDARs are checked one by one
    caplog.clear()
    with caplog.at_level('WARNING'):
        _warn_orphaned_overrides(todo + '\n' + orphan)
    assert 'orphan-uid@host.com' in caplog.text
    assert '19970901T130000Z-123404@host.com' not in caplog.text

    ## a normal object must not warn
    caplog.clear()
    with caplog.at_level('WARNING'):
        _warn_orphaned_overrides(todo)
    assert caplog.text == ''


def test_split_vcal_does_not_warn(caplog):
    """The warning belongs to the import path only - `edit --interactive-ical`
    splits the very same data and imports nothing."""
    orphan = todo.replace(
        'UID:19970901T130000Z-123404@host.com',
        'UID:orphan-uid@host.com\nRECURRENCE-ID:19970415T133000Z')
    with caplog.at_level('WARNING'):
        _split_vcal(orphan)
    assert caplog.text == ''


def test_split_vcal_yields_ical_strings():
    """`add ical` feeds every element of _split_vcal() straight into
    _caldav_objclass(), which parses text - so _split_vcal must yield ical
    strings, exactly as _split_vcals() does for the multi-VCALENDAR case.

    Yielding icalendar.Calendar objects instead made the ordinary
    single-VCALENDAR `plann add ical` abort with
    `ValueError: Expected StringType with content lines`."""
    parts = list(_split_vcal(todo))
    assert len(parts) == 1
    for part in parts:
        assert isinstance(part, str), f"expected ical text, got {type(part).__name__}"
        ## and the component type must survive the round-trip
        assert _caldav_objclass(part) is Todo


class _FakeCalendar:
    """A minimal in-memory calendar that counts get_object_by_uid lookups, so
    tests can assert how many server round-trips a traversal would issue."""
    def __init__(self):
        import collections
        self.objs = {}
        self.fetch_counts = collections.Counter()
        self.url = "http://cal.example/"

    def add(self, todo):
        todo.parent = self
        self.objs[str(todo.icalendar_component['UID'])] = todo

    def get_object_by_uid(self, uid):
        import caldav
        uid = str(uid)
        self.fetch_counts[uid] += 1
        if uid not in self.objs:
            raise caldav.error.NotFoundError(uid)
        return self.objs[uid]

    def get_display_name(self):
        return "Fake"


def _todo_with_rels(uid, rels):
    """Build a Todo with the given (reltype, target_uid) RELATED-TO links."""
    rel_lines = "".join(f"RELATED-TO;RELTYPE={rt}:{target}\n" for rt, target in rels)
    obj = Todo()
    obj.data = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Example Corp.//CalDAV Client//EN\n"
        "BEGIN:VTODO\n"
        f"UID:{uid}\n"
        f"SUMMARY:task {uid}\n"
        f"{rel_lines}"
        "END:VTODO\nEND:VCALENDAR"
    )
    return obj


def test_list_top_down_caches_relative_fetches():
    """A hierarchical `list --top-down` must not re-fetch the same task from
    the server once per graph edge - each related object is fetched at most
    once per traversal (code review E3)."""
    from plann.lib import _list

    cal = _FakeCalendar()
    ## parent p with two children c1, c2 (bidirectionally linked)
    p = _todo_with_rels('p', [('CHILD', 'c1'), ('CHILD', 'c2')])
    c1 = _todo_with_rels('c1', [('PARENT', 'p')])
    c2 = _todo_with_rels('c2', [('PARENT', 'p')])
    for obj in (p, c1, c2):
        cal.add(obj)

    with patch('plann.lib.click.echo_via_pager'):
        _list([c1, c2], top_down=True)

    ## without caching, p is fetched once per child (and more via recursion)
    assert cal.fetch_counts['p'] == 1, dict(cal.fetch_counts)
    assert all(count <= 1 for count in cal.fetch_counts.values()), dict(cal.fetch_counts)


def test_procrastinate_has_no_breakpoint():
    """A stray breakpoint() drops the user into pdb (or appears to hang when
    there is no tty).  Code review item #13 - the recursive postpone-parent
    path in _procrastinate had one guarded by an inspect.stack() depth check,
    which is reachable from `interactive check-due` / `dismiss-panic`."""
    import inspect as _inspect

    source = _inspect.getsource(_procrastinate)
    assert 'breakpoint()' not in source
    assert 'inspect.stack()' not in source


## RFC 5545 allows CATEGORIES more than once; icalendar then returns a list.
## https://github.com/pycalendar/plann/issues/71
todo_multicats = todo.replace('STATUS:NEEDS-ACTION\n', 'STATUS:NEEDS-ACTION\nCATEGORIES:\nCATEGORIES:foo\nCATEGORIES:bar,baz\n')

def test_categories_in_use_multiple_lines():
    from plann.commands import _categories_in_use
    obj = Todo(data=todo_multicats)
    assert _categories_in_use([obj]) == {'foo', 'bar', 'baz'}

@patch("plann.lib.subprocess.run")
def test_add_time_tracking_timew_multiple_category_lines(mock_run):
    obj = Todo(data=todo_multicats)
    obj.parent = Calendar()
    obj.parent.extra_config = {'time_tracking': ['timewarrior']}
    add_time_tracking_timew(obj, datetime(2020, 2, 20, 20, 2), datetime(2020, 2, 20, 20, 20))
    cmd_arr = mock_run.mock_calls[0].args[0]
    assert [x for x in cmd_arr if x.startswith('category:')] == ['category:foo', 'category:bar', 'category:baz']

def _todo_with_uid(uid, status='NEEDS-ACTION'):
    t = Todo()
    t.data = todo.replace('19970901T130000Z-123404@host.com', uid).replace('STATUS:NEEDS-ACTION', f'STATUS:{status}').replace('SUMMARY:Fix a party', f'SUMMARY:task {uid}')
    return t

def test_complete_also_completes_pending_children():
    """Completing a parent means the children are done too - they are
    auto-completed (grandchildren included) before the parent, with a
    warning for each"""
    parent = _todo_with_uid('parent')
    child = _todo_with_uid('child')
    grandchild = _todo_with_uid('grandchild')
    done_child = _todo_with_uid('done_child', status='COMPLETED')
    children = {'parent': [child, done_child], 'child': [grandchild]}
    def relships(obj, reltype_wanted=None, cache=None):
        assert reltype_wanted == 'CHILD'
        return {'CHILD': children.get(str(obj.icalendar_component['UID']), [])}
    order = []
    def complete(self, **kwargs):
        order.append(str(self.icalendar_component['UID']))
        self._complete_ical(completion_timestamp=datetime.now(utc))
    warnings = []
    with patch('plann.lib._relships_by_type', side_effect=relships), \
         patch.object(Todo, 'complete', complete):
        _complete(parent, err_callback=warnings.append)
    assert order == ['grandchild', 'child', 'parent']
    assert warnings == ["Completing child task 'task child' of 'task parent'",
                        "Completing child task 'task grandchild' of 'task child'"]

def test_complete_survives_relation_cycles():
    a = _todo_with_uid('a')
    b = _todo_with_uid('b')
    children = {'a': [b], 'b': [a]}
    def relships(obj, reltype_wanted=None, cache=None):
        return {'CHILD': children[str(obj.icalendar_component['UID'])]}
    with patch('plann.lib._relships_by_type', side_effect=relships), \
         patch.object(Todo, 'save'), patch.object(Todo, 'load'):
        _complete(a, err_callback=lambda x: None)
    assert a.icalendar_component['STATUS'] == 'COMPLETED'
    assert b.icalendar_component['STATUS'] == 'COMPLETED'

def test_complete_selection_with_parent_and_child_completes_child_once():
    """`select ... edit --complete` may hold both a parent and its child.
    The child must be completed once - a recurring child is pending again
    after completion, and would otherwise advance twice - and on the
    selected object itself, so that saving the selection afterwards does
    not write a stale copy back"""
    parent = _todo_with_uid('parent')
    child = _todo_with_uid('child')
    cache = _RelativeCache()
    cache.add_objects([parent, child])
    def relships(obj, reltype_wanted=None, cache=None):
        if str(obj.icalendar_component['UID']) != 'parent':
            return {'CHILD': []}
        return {'CHILD': [cache.get_object(obj.parent, 'child')]}
    completed = []
    def complete(self, **kwargs):
        ## like a recurring task moved on to its next occurrence: still pending
        completed.append(self)
    seen = set()
    with patch('plann.lib._relships_by_type', side_effect=relships), \
         patch.object(Todo, 'complete', complete):
        for obj in (parent, child):
            _complete(obj, err_callback=lambda x: None, cache=cache, _seen=seen)
    assert completed == [child, parent]
    assert completed[0] is child

def test_complete_explicit_non_pending_task_warns():
    """caldav cannot complete a task that is not pending, e.g. a
    cancelled one; it is left alone, but not silently"""
    cancelled = _todo_with_uid('cancelled', status='CANCELLED')
    warnings = []
    with patch('plann.lib._relships_by_type', return_value={}), \
         patch.object(Todo, 'save'), patch.object(Todo, 'load'):
        _complete(cancelled, err_callback=warnings.append)
    assert cancelled.icalendar_component['STATUS'] == 'CANCELLED'
    assert warnings == ["Not completing 'task cancelled': STATUS is CANCELLED"]

def test_complete_skips_child_with_non_standard_status():
    """A child with a STATUS outside the RFC is left alone, with a
    warning, rather than crashing halfway through the tree"""
    parent = _todo_with_uid('parent')
    odd = _todo_with_uid('odd', status='WAITING')
    def relships(obj, reltype_wanted=None, cache=None):
        return {'CHILD': [odd] if obj is parent else []}
    warnings = []
    with patch('plann.lib._relships_by_type', side_effect=relships), \
         patch.object(Todo, 'save'), patch.object(Todo, 'load'):
        _complete(parent, err_callback=warnings.append)
    assert parent.icalendar_component['STATUS'] == 'COMPLETED'
    assert odd.icalendar_component['STATUS'] == 'WAITING'
    assert len(warnings) == 1 and 'task odd' in warnings[0]

def test_complete_task_with_non_standard_status_warns():
    """A selected task with a STATUS outside the RFC gets a warning, not
    a crash after its children were completed"""
    odd = _todo_with_uid('odd', status='WAITING')
    child = _todo_with_uid('child')
    def relships(obj, reltype_wanted=None, cache=None):
        return {'CHILD': [child] if obj is odd else []}
    warnings = []
    with patch('plann.lib._relships_by_type', side_effect=relships), \
         patch.object(Todo, 'save'), patch.object(Todo, 'load'):
        _complete(odd, err_callback=warnings.append)
    assert odd.icalendar_component['STATUS'] == 'WAITING'
    assert child.icalendar_component['STATUS'] == 'NEEDS-ACTION'
    assert warnings == ["Not completing 'task odd': STATUS is WAITING"]
