from datetime import datetime, timedelta
from unittest import mock

from caldav import Event, Todo
from caldav.lib.vcal import create_ical

from plann import panic_planning


def datetime_(*largs, **kwargs):
    ret = datetime(*largs, **kwargs)
    if 'tzinfo' not in kwargs:
        ret = ret.astimezone()
    return ret

def test_timeline():
    timeline = panic_planning.TimeLine()
    timeline.add(
        begin=datetime_(year=2025, month=2, day=25, hour=20),
        end=datetime_(year=2025, month=2, day=25, hour=20, minute=30), obj=5)
    timeline.add(
        begin=datetime_(year=2025, month=2, day=25, hour=20, minute=30),
        end=datetime_(year=2025, month=2, day=25, hour=20, minute=40), obj=6)
    timeline.add(
        begin=datetime_(year=2025, month=2, day=26, hour=20, minute=30),
        end=datetime_(year=2025, month=2, day=26, hour=20, minute=40), obj=7)
    timeline.add(
        begin=datetime_(year=2025, month=2, day=26, hour=10, minute=30),
        end=datetime_(year=2025, month=2, day=26, hour=10, minute=40), obj=8)
    foo = timeline.get(datetime_(year=2025, month=2, day=26, hour=20, minute=35))
    assert foo['end'] == datetime_(year=2025, month=2, day=26, hour=20, minute=40)
    foo = timeline.get(datetime_(year=2025, month=2, day=26, hour=12, minute=35))
    assert foo['end'] == datetime_(year=2025, month=2, day=26, hour=20, minute=30)
    foo = timeline.get(datetime_(year=2025, month=2, day=27, hour=12, minute=35))
    assert foo['begin'] == datetime_(year=2025, month=2, day=26, hour=20, minute=40)
    assert 'end' not in foo
    foo = timeline.get(datetime_(year=2020, month=2, day=27, hour=12, minute=35))
    assert foo['end'] == datetime_(year=2025, month=2, day=25, hour=20, minute=00)
    assert 'begin' not in foo
    (opening, slack_balance) = timeline.find_opening(last_possibility=datetime_(year=2025, month=3, day=25, hour=20), duration=timedelta(days=2))
    assert slack_balance == timedelta(0)
    assert 'end' not in opening
    (opening, slack_balance) = timeline.find_opening(last_possibility=datetime_(year=2025, month=2, day=28, hour=20), duration=timedelta(days=2))
    assert slack_balance > timedelta(0)
    assert 'begin' not in opening
    timeline.pad_slack(end=datetime_(year=2025, month=2, day=26, hour=12, minute=45), duration=timedelta(seconds=3600))
    timeline.pad_slack(end=datetime_(year=2025, month=2, day=26, hour=22, minute=45), duration=timedelta(days=2))

def test_timeline_add():
    def t(hour):
        return datetime_(year=2025, month=2, day=25, hour=hour)
    timeline = panic_planning.TimeLine()

    assert len(timeline) == 0

    timeline.add(begin=t(14), end=t(15), obj='14')
    assert len(timeline) == 2
    assert timeline[0]['begin'] == t(14)
    assert timeline[0]['obj'] == '14'
    assert timeline[1]['begin'] == t(15)

    timeline.add(begin=t(12), end=t(13), obj='12')
    assert len(timeline) == 4
    assert timeline[0]['begin'] == t(12)
    assert timeline[0]['obj'] == '12'
    assert timeline[1]['begin'] == t(13)
    assert timeline[2]['begin'] == t(14)
    assert timeline[2]['obj'] == '14'
    assert timeline[3]['begin'] == t(15)

    timeline.add(begin=t(13), end=t(14), obj='13')
    assert len(timeline) == 4
    assert timeline[0]['begin'] == t(12)
    assert timeline[0]['obj'] == '12'
    assert timeline[1]['begin'] == t(13)
    assert timeline[1]['obj'] == '13'
    assert timeline[2]['begin'] == t(14)
    assert timeline[2]['obj'] == '14'
    assert timeline[3]['begin'] == t(15)

def create_obj(comp_class='VTODO', duehour=None, **data):
    if duehour:
        tomorrow = (datetime.now() + timedelta(days=1)).replace(minute=0, second=0)
        data['due'] = tomorrow.replace(hour=duehour)
        data['dtstart'] = tomorrow.replace(hour=duehour-1)
    compclass={'VEVENT': Event, 'VTODO': Todo}
    ical = create_ical(**data)
    return compclass[data.get('objtype', 'VEVENT')](client=None, url=f"https://example.com/{data['uid']}", data=ical)

def test_timeline_suggestion():
    pri1 = create_obj(uid=1, priority=1, duehour=12)
    pri2 = create_obj(uid=2, priority=1, duehour=10)
    pri3 = create_obj(uid=3, priority=1, duehour=14)

    ctx = mock.Mock
    ctx.obj = {'objs': [pri1, pri2, pri3]}

    timeline = panic_planning.timeline_suggestion(ctx, hours_per_day=23)

    ## Can we make asserts that are robust enough not to fail should the algorithm change completely?
    ## The only requirement is that it creates a timeline, isn't it?
    assert timeline[0]['begin']>=datetime.now().astimezone()
    assert len([x['obj'] for x in timeline if 'obj' in x]) == 3
    assert len(set([x['obj'].url for x in timeline if 'obj' in x])) == 3

    ## parents should always be handled after children
    pri3.icalendar_component.add('RELATED_TO', 'https://example.com/2', parameters={'RELTYPE': 'CHILD'})
    pri2.icalendar_component.add('RELATED_TO', 'https://example.com/3', parameters={'RELTYPE': 'PARENT'})

    timeline = panic_planning.timeline_suggestion(ctx, hours_per_day=23)
    #['x' for x in assert

## The editable plan of interactive_fix_timeline: one line per task,
## UID START DURATION SUMMARY.  The end is START+DURATION, so moving the
## start keeps the length.

def test_pin_plan_format():
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo('Europe/Oslo')
    utc = ZoneInfo('UTC')
    entries = [
        ## an existing event, stored in UTC
        (None, datetime(2026, 11, 24, 8, 0, tzinfo=utc), datetime(2026, 11, 24, 9, 0, tzinfo=utc), 'Standup'),
        ('uid-1', datetime(2026, 11, 24, 10, 0, tzinfo=oslo), datetime(2026, 11, 24, 11, 30, tzinfo=oslo), 'Write #1 report'),
    ]
    text = panic_planning.format_pin_plan(entries, oslo)
    ## time zone named in the header
    assert 'Europe/Oslo' in text
    assert 'UTC+01:00' in text
    ## all timestamps converted to the display zone, the end is not written out
    assert '2026-11-24 09:00 +1h' in text
    assert '2026-11-24 10:00 +1h30m' in text
    assert '11:30' not in text
    ## the existing event is a comment, the task is not
    lines = text.split('\n')
    assert [x for x in lines if 'Standup' in x][0].startswith('#')
    assert [x for x in lines if 'Write' in x][0].startswith('uid-1 ')

    ## Unchanged text parses back to the same plan, converted to the
    ## display zone - and a '#' in a summary is not a comment
    parsed = panic_planning.parse_pin_plan(text, oslo)
    assert parsed == [('uid-1', entries[1][1], entries[1][2], 'Write #1 report')]

    ## Moving the start moves the end
    moved = text.replace('2026-11-24 10:00 +1h30m', '2026-11-24 13:15 +1h30m')
    ((uid, begin, end, summary),) = panic_planning.parse_pin_plan(moved, oslo)
    assert begin == datetime(2026, 11, 24, 13, 15, tzinfo=oslo)
    assert end == datetime(2026, 11, 24, 14, 45, tzinfo=oslo)

    ## Changing the duration resizes; no plus sign is fine too
    resized = text.replace('+1h30m', '45m')
    ((uid, begin, end, summary),) = panic_planning.parse_pin_plan(resized, oslo)
    assert end - begin == timedelta(minutes=45)

def test_pin_plan_dst_switch():
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo('Europe/Oslo')
    entries = [
        ('a', datetime(2026, 10, 24, 10, 0, tzinfo=oslo), datetime(2026, 10, 24, 11, 0, tzinfo=oslo), 'before'),
        ('b', datetime(2026, 10, 26, 10, 0, tzinfo=oslo), datetime(2026, 10, 26, 11, 0, tzinfo=oslo), 'after'),
    ]
    text = panic_planning.format_pin_plan(entries, oslo)
    assert 'UTC+02:00' in text
    assert 'UTC+01:00' in text
    assert panic_planning.parse_pin_plan(text, oslo) == entries

def test_pin_plan_entry_spanning_dst_switch():
    """The duration is real elapsed time, so an unedited plan gives
    back the same start and end, whatever zone the entry came in"""
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo('Europe/Oslo')
    utc = ZoneInfo('UTC')
    ## three hours across the night the clocks go back
    stored_utc = ('a', datetime(2026, 10, 24, 23, 30, tzinfo=utc), datetime(2026, 10, 25, 2, 30, tzinfo=utc), 'utc')
    ## 00:30 to 03:30 Oslo wall clock is four hours
    stored_oslo = ('b', datetime(2026, 10, 25, 0, 30, tzinfo=oslo), datetime(2026, 10, 25, 3, 30, tzinfo=oslo), 'oslo')
    for (entry, shown) in ((stored_utc, '+3h '), (stored_oslo, '+4h ')):
        text = panic_planning.format_pin_plan([entry], oslo)
        assert shown in text
        ((uid, begin, end, summary),) = panic_planning.parse_pin_plan(text, oslo)
        assert (begin, end) == (entry[1], entry[2])

def test_pin_plan_multiline_summary():
    """A summary taken from a multi-line DESCRIPTION stays on its line"""
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo('Europe/Oslo')
    entries = [
        (None, datetime(2026, 11, 24, 8, 0, tzinfo=oslo), datetime(2026, 11, 24, 9, 0, tzinfo=oslo), 'Standup\nwith the team'),
        ('uid-1', datetime(2026, 11, 24, 10, 0, tzinfo=oslo), datetime(2026, 11, 24, 11, 0, tzinfo=oslo), 'Buy milk\r\nand bread\n'),
    ]
    text = panic_planning.format_pin_plan(entries, oslo)
    assert panic_planning.parse_pin_plan(text, oslo) == [
        ('uid-1', entries[1][1], entries[1][2], 'Buy milk and bread')]

def test_pin_plan_says_how_to_cancel():
    from zoneinfo import ZoneInfo
    text = panic_planning.format_pin_plan([], ZoneInfo('Europe/Oslo'))
    assert 'Delete all the task\n# lines to pin nothing' in text

def test_pin_plan_parse_errors():
    from zoneinfo import ZoneInfo

    import pytest
    oslo = ZoneInfo('Europe/Oslo')
    for bad in ('uid-1 2026-11-24 10:00 - 11:30 summary',
                'uid-1 tomorrow +1h summary',
                'uid-1 2026-11-24 10:00 +0m summary',
                'uid-1 2026-11-24 10:00 +1h'):
        with pytest.raises(ValueError, match='line 2'):
            panic_planning.parse_pin_plan('# comment\n' + bad, oslo)
    assert panic_planning.parse_pin_plan('\n# only comments\n   \n', oslo) == []
