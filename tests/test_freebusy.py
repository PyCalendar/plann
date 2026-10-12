from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import pytest

from plann.freebusy import SOURCE_PROP, _end_of, busy_copies, freebusy_sync

oslo = ZoneInfo('Europe/Oslo')


def _event(uid='ev1', summary='Secret meeting with ACME', start=datetime(2026, 10, 14, 10, 0, tzinfo=oslo),
           end=datetime(2026, 10, 14, 11, 0, tzinfo=oslo), **props):
    ev = icalendar.Event()
    ev.add('UID', uid)
    ev.add('DTSTAMP', datetime(2026, 10, 1, tzinfo=oslo))
    ev.add('SUMMARY', summary)
    ev.add('DESCRIPTION', 'confidential details')
    ev.add('LOCATION', 'ACME HQ')
    ev.add('DTSTART', start)
    if end is not None:
        ev.add('DTEND', end)
    for key, value in props.items():
        ev.add(key.replace('_', '-'), value)
    return ev


class FakeObject:
    def __init__(self, calendar, ical):
        self.calendar = calendar
        self.data = ical

    @property
    def icalendar_component(self):
        return [c for c in icalendar.Calendar.from_ical(self.data).walk('VEVENT')][0]

    def save(self):
        self.calendar.saves += 1

    def delete(self):
        self.calendar.objects.remove(self)


def _as_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time(), oslo)


class FakeCalendar:
    """Just enough of caldav.Calendar for freebusy_sync.

    search() ignores the time range; the tests keep everything inside it.
    """
    def __init__(self, components=()):
        self.objects = []
        self.saves = 0
        for comp in components:
            self.add_event(_vcal(comp))

    def search(self, event=None, start=None, end=None, expand=None):
        ## time-range overlap only; no recurrence expansion
        def overlaps(obj):
            comp = obj.icalendar_component
            s, e = _as_dt(comp['DTSTART'].dt), _as_dt(_end_of(comp) or comp['DTSTART'].dt)
            return (end is None or s < end) and (start is None or e > start)
        return [o for o in self.objects if overlaps(o)]

    def add_event(self, ical):
        obj = FakeObject(self, ical if isinstance(ical, str) else ical.decode())
        self.objects.append(obj)
        return obj

    def components(self):
        return [o.icalendar_component for o in self.objects]


def _vcal(comp):
    cal = icalendar.Calendar()
    cal.add('PRODID', '-//test//')
    cal.add('VERSION', '2.0')
    cal.add_component(comp)
    return cal.to_ical().decode()


class TestBusyCopies:
    def test_strips_everything_but_the_time(self):
        [copy] = busy_copies(_event(), summary='busy', tag='work')
        assert str(copy['SUMMARY']) == 'busy'
        for prop in ('DESCRIPTION', 'LOCATION'):
            assert prop not in copy
        assert copy['DTSTART'].dt == datetime(2026, 10, 14, 10, 0, tzinfo=oslo)
        assert copy['DTEND'].dt == datetime(2026, 10, 14, 11, 0, tzinfo=oslo)
        assert str(copy[SOURCE_PROP]) == 'work'

    def test_times_are_stored_in_utc(self):
        ## no TZID to resolve, and the source's zone name does not leak
        ev = _event()
        ev['DTSTART'].params['TZID'] = 'W. Europe Standard Time'
        [copy] = busy_copies(ev, summary='busy', tag='work')
        assert copy['DTSTART'].dt.utcoffset() == timedelta(0)
        assert b'TZID' not in copy.to_ical()
        [clipped] = busy_copies(_event(start=date(2026, 10, 14), end=date(2026, 10, 15)), summary='busy', tag='home',
                                hours=(9, 16), tzinfo=oslo)
        assert clipped['DTSTART'].dt == datetime(2026, 10, 14, 7, 0, tzinfo=ZoneInfo('UTC'))
        assert b'TZID' not in clipped.to_ical()

    def test_skips_copies_whose_tag_property_was_dropped(self):
        [copy] = busy_copies(_event(), summary='busy', tag='work')
        del copy[SOURCE_PROP]
        assert busy_copies(copy, summary='busy', tag='home') == []

    def test_uid_is_derived_stable_and_hides_the_source_uid(self):
        [a] = busy_copies(_event(uid='secret-uid@acme.example.com'), summary='busy', tag='work')
        [b] = busy_copies(_event(uid='secret-uid@acme.example.com'), summary='busy', tag='work')
        [c] = busy_copies(_event(uid='secret-uid@acme.example.com'), summary='busy', tag='home')
        assert a['UID'] == b['UID']
        assert a['UID'] != c['UID']
        assert 'acme' not in str(a['UID'])

    def test_recurrence_instances_get_distinct_uids(self):
        first = _event(recurrence_id=datetime(2026, 10, 14, 10, 0, tzinfo=oslo))
        second = _event(start=datetime(2026, 10, 21, 10, 0, tzinfo=oslo), end=datetime(2026, 10, 21, 11, 0, tzinfo=oslo),
                        recurrence_id=datetime(2026, 10, 21, 10, 0, tzinfo=oslo))
        [a] = busy_copies(first, summary='busy', tag='work')
        [b] = busy_copies(second, summary='busy', tag='work')
        assert a['UID'] != b['UID']
        assert 'RECURRENCE-ID' not in a

    def test_skips_free_cancelled_and_copies(self):
        assert busy_copies(_event(transp='TRANSPARENT'), summary='busy', tag='work') == []
        assert busy_copies(_event(status='CANCELLED'), summary='busy', tag='work') == []
        [copy] = busy_copies(_event(), summary='busy', tag='work')
        assert busy_copies(copy, summary='busy', tag='home') == []

    def test_duration_and_missing_end(self):
        [copy] = busy_copies(_event(end=None, duration=timedelta(minutes=30)), summary='busy', tag='work')
        assert copy['DTEND'].dt == datetime(2026, 10, 14, 10, 30, tzinfo=oslo)
        ## RFC 5545: a timed event without DTEND or DURATION takes no time
        assert busy_copies(_event(end=None), summary='busy', tag='work') == []

    def test_all_day_event_kept_as_all_day_without_hours(self):
        [copy] = busy_copies(_event(start=date(2026, 10, 14), end=date(2026, 10, 15)), summary='busy', tag='work')
        assert copy['DTSTART'].dt == date(2026, 10, 14)
        assert copy['DTEND'].dt == date(2026, 10, 15)

    def test_hours_clip_a_timed_event(self):
        ev = _event(start=datetime(2026, 10, 14, 7, 0, tzinfo=oslo), end=datetime(2026, 10, 14, 10, 0, tzinfo=oslo))
        [copy] = busy_copies(ev, summary='busy', tag='home', hours=(9, 16), weekdays=range(5), tzinfo=oslo)
        assert copy['DTSTART'].dt == datetime(2026, 10, 14, 9, 0, tzinfo=oslo)
        assert copy['DTEND'].dt == datetime(2026, 10, 14, 10, 0, tzinfo=oslo)

    def test_hours_drop_events_outside_and_weekends(self):
        evening = _event(start=datetime(2026, 10, 14, 18, 0, tzinfo=oslo), end=datetime(2026, 10, 14, 20, 0, tzinfo=oslo))
        saturday = _event(start=datetime(2026, 10, 17, 10, 0, tzinfo=oslo), end=datetime(2026, 10, 17, 11, 0, tzinfo=oslo))
        for ev in (evening, saturday):
            assert busy_copies(ev, summary='busy', tag='home', hours=(9, 16), weekdays=range(5), tzinfo=oslo) == []

    def test_hours_turn_all_day_events_into_working_hours_per_weekday(self):
        ## Friday to Monday (exclusive end Tuesday): Friday and Monday remain
        ev = _event(start=date(2026, 10, 16), end=date(2026, 10, 20))
        copies = busy_copies(ev, summary='busy', tag='home', hours=(9, 16), weekdays=range(5), tzinfo=oslo)
        assert [(c['DTSTART'].dt, c['DTEND'].dt) for c in copies] == [
            (datetime(2026, 10, 16, 9, 0, tzinfo=oslo), datetime(2026, 10, 16, 16, 0, tzinfo=oslo)),
            (datetime(2026, 10, 19, 9, 0, tzinfo=oslo), datetime(2026, 10, 19, 16, 0, tzinfo=oslo)),
        ]
        assert len({c['UID'] for c in copies}) == 2


    def test_hours_until_midnight(self):
        ev = _event(start=datetime(2026, 10, 14, 22, 0, tzinfo=oslo), end=datetime(2026, 10, 15, 1, 0, tzinfo=oslo))
        copies = busy_copies(ev, summary='busy', tag='home', hours=(20, 24), tzinfo=oslo)
        assert [(c['DTSTART'].dt, c['DTEND'].dt) for c in copies] == [
            (datetime(2026, 10, 14, 22, 0, tzinfo=oslo), datetime(2026, 10, 15, 0, 0, tzinfo=oslo))]

    def test_weekdays_without_hours(self):
        saturday = _event(start=datetime(2026, 10, 17, 10, 0, tzinfo=oslo), end=datetime(2026, 10, 17, 11, 0, tzinfo=oslo))
        assert busy_copies(saturday, summary='busy', tag='home', weekdays=range(5), tzinfo=oslo) == []
        [copy] = busy_copies(_event(), summary='busy', tag='home', weekdays=range(5), tzinfo=oslo)
        assert copy['DTSTART'].dt == datetime(2026, 10, 14, 10, 0, tzinfo=oslo)

    def test_pieces_outside_the_window_are_dropped(self):
        holiday = _event(start=date(2026, 10, 12), end=date(2026, 10, 24))
        copies = busy_copies(holiday, summary='busy', tag='home', hours=(9, 16), weekdays=range(5), tzinfo=oslo,
                             window=(datetime(2026, 10, 14, tzinfo=oslo), datetime(2026, 10, 16, tzinfo=oslo)))
        assert [c['DTSTART'].dt.astimezone(oslo).date() for c in copies] == [date(2026, 10, 14), date(2026, 10, 15)]


class TestFreebusySync:
    window = dict(start=datetime(2026, 10, 13, tzinfo=oslo), end=datetime(2026, 12, 12, tzinfo=oslo))

    def _sync(self, source, target, **kwargs):
        return freebusy_sync([source], target, summary='event from work calendar', tag='work', **self.window, **kwargs)

    def test_adds_copies(self):
        source = FakeCalendar([_event()])
        target = FakeCalendar()
        assert self._sync(source, target) == {'added': 1, 'updated': 0, 'deleted': 0, 'unchanged': 0}
        [copy] = target.components()
        assert str(copy['SUMMARY']) == 'event from work calendar'
        assert 'DESCRIPTION' not in copy

    def test_second_run_is_a_noop(self):
        source = FakeCalendar([_event()])
        target = FakeCalendar()
        self._sync(source, target)
        assert self._sync(source, target) == {'added': 0, 'updated': 0, 'deleted': 0, 'unchanged': 1}
        assert len(target.objects) == 1

    def test_moved_source_updates_the_copy(self):
        source = FakeCalendar([_event()])
        target = FakeCalendar()
        self._sync(source, target)
        source = FakeCalendar([_event(start=datetime(2026, 10, 14, 12, 0, tzinfo=oslo), end=datetime(2026, 10, 14, 13, 0, tzinfo=oslo))])
        assert self._sync(source, target)['updated'] == 1
        [copy] = target.components()
        assert copy['DTSTART'].dt == datetime(2026, 10, 14, 12, 0, tzinfo=oslo)
        assert target.saves == 1

    def test_removed_source_deletes_the_copy_but_nothing_else(self):
        own = _event(uid='my-own-event', summary='dentist')
        target = FakeCalendar([own])
        self._sync(FakeCalendar([_event()]), target)
        assert len(target.objects) == 2
        assert self._sync(FakeCalendar(), target)['deleted'] == 1
        assert [str(c['UID']) for c in target.components()] == ['my-own-event']

    def test_copies_from_another_tag_are_left_alone(self):
        target = FakeCalendar()
        freebusy_sync([FakeCalendar([_event()])], target, summary='x', tag='other', **self.window)
        assert self._sync(FakeCalendar(), target)['deleted'] == 0
        assert len(target.objects) == 1

    def test_copies_in_the_source_are_not_synced_back(self):
        ## private -> work, then work -> private must not bounce the copy back
        private = FakeCalendar([_event(uid='p1', summary='dentist')])
        work = FakeCalendar()
        freebusy_sync([private], work, summary='private', tag='private', **self.window)
        self._sync(work, private)
        assert len(private.objects) == 1

    def test_dry_run_changes_nothing(self):
        target = FakeCalendar()
        assert self._sync(FakeCalendar([_event()]), target, dry_run=True)['added'] == 1
        assert target.objects == []

    def test_window_edge_settles(self):
        ## a holiday starting before the window must not be re-added every run
        source = FakeCalendar([_event(start=date(2026, 10, 5), end=date(2026, 10, 24))])
        target = FakeCalendar()
        self._sync(source, target, hours=(9, 16), weekdays=range(5), tzinfo=oslo)
        assert self._sync(source, target, hours=(9, 16), weekdays=range(5), tzinfo=oslo)['added'] == 0

    def test_move_to_another_zone_at_the_same_wall_time(self):
        target = FakeCalendar()
        self._sync(FakeCalendar([_event()]), target)
        ny = ZoneInfo('America/New_York')
        moved = _event(start=datetime(2026, 10, 14, 10, 0, tzinfo=ny), end=datetime(2026, 10, 14, 11, 0, tzinfo=ny))
        assert self._sync(FakeCalendar([moved]), target)['updated'] == 1

    def test_refuses_without_source_calendars(self):
        ## an unreachable source must not read as "no busy time": that would delete every copy
        target = FakeCalendar()
        self._sync(FakeCalendar([_event()]), target)
        with pytest.raises(ValueError):
            freebusy_sync([], target, summary='x', tag='work', **self.window)
        assert len(target.objects) == 1
