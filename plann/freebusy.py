"""Copy busy time from one set of calendars into another calendar.

Typical use is between a work calendar and a private calendar: the
target gets a placeholder event for every busy period in the source,
carrying nothing but the time and a fixed summary.

Every copy has a derived UID and an X-PLANN-FREEBUSY-SOURCE property
holding a tag naming the sync.  The tag lets a later run find, move and
delete its own copies without touching anything else in the target
calendar, and lets copies be recognised so they never sync back.
"""

import datetime
import hashlib
from collections.abc import Iterable
from typing import Any

import icalendar
from dateutil import tz as dateutil_tz

SOURCE_PROP = 'X-PLANN-FREEBUSY-SOURCE'
UID_PREFIX = 'plann-freebusy-'


def _end_of(comp: icalendar.cal.Component) -> datetime.date | None:
    start = comp['DTSTART'].dt
    if 'DTEND' in comp:
        return comp['DTEND'].dt
    if 'DURATION' in comp:
        return start + comp['DURATION'].dt
    ## RFC 5545 section 3.6.1: an all-day event lasts one day, a timed one no time
    if not isinstance(start, datetime.datetime):
        return start + datetime.timedelta(days=1)
    return None


def _clip(start: datetime.date, end: datetime.date, hours: tuple[int, int], weekdays: Iterable[int],
          tzinfo: datetime.tzinfo) -> list[tuple[datetime.date, datetime.datetime, datetime.datetime]]:
    """Cut a busy period down to the given hours (0-24), one piece per day.

    All-day periods become the full hours on every allowed day.
    """
    weekdays = set(weekdays)
    if isinstance(start, datetime.datetime):
        start = start if start.tzinfo else start.replace(tzinfo=tzinfo)
        end = end if end.tzinfo else end.replace(tzinfo=tzinfo)
        first_day = start.astimezone(tzinfo).date()
        last_day = end.astimezone(tzinfo).date()
    else:
        first_day = start
        last_day = end - datetime.timedelta(days=1)
    pieces = []
    day = first_day
    while day <= last_day:
        if day.weekday() in weekdays:
            day_start = datetime.datetime.combine(day, datetime.time(hours[0]), tzinfo)
            day_end = datetime.datetime.combine(day + datetime.timedelta(days=hours[1] // 24),
                                                datetime.time(hours[1] % 24), tzinfo)
            if isinstance(start, datetime.datetime):
                piece_start, piece_end = max(start, day_start), min(end, day_end)
            else:
                piece_start, piece_end = day_start, day_end
            if piece_start < piece_end:
                pieces.append((day, piece_start, piece_end))
        day += datetime.timedelta(days=1)
    return pieces


def _to_utc(value: datetime.date, tzinfo: datetime.tzinfo) -> datetime.date:
    """Timestamps go out in UTC: no TZID to resolve, and no zone name leaks."""
    if not isinstance(value, datetime.datetime):
        return value
    if not value.tzinfo:
        value = value.replace(tzinfo=tzinfo)
    return value.astimezone(datetime.timezone.utc)


def busy_copies(comp: icalendar.cal.Component, summary: str, tag: str, hours: tuple[int, int] | None = None,
                weekdays: Iterable[int] | None = None, tzinfo: datetime.tzinfo | None = None,
                window: tuple[datetime.datetime, datetime.datetime] | None = None) -> list[icalendar.Event]:
    """Return the placeholder events standing in for one (expanded) event.

    The result is empty for events that do not block time (transparent
    or cancelled), and for events that are themselves copies.  With
    ``hours`` (a range within 0-24) or ``weekdays`` (0 is Monday) set,
    the event is clipped to them in ``tzinfo``, which may split it into
    one copy per day; ``window`` then drops the days outside it.
    """
    if (str(comp.get('TRANSP', '')).upper() == 'TRANSPARENT'
            or str(comp.get('STATUS', '')).upper() == 'CANCELLED'
            or SOURCE_PROP in comp
            or str(comp.get('UID', '')).startswith(UID_PREFIX)
            or 'DTSTART' not in comp):
        return []
    start = comp['DTSTART'].dt
    end = _end_of(comp)
    if end is None:
        return []
    tzinfo = tzinfo or dateutil_tz.tzlocal()
    recurrence_id = comp['RECURRENCE-ID'].to_ical().decode() if 'RECURRENCE-ID' in comp else ''
    key = f"{tag}\0{comp['UID']}\0{recurrence_id}"
    if hours or weekdays is not None:
        pieces = _clip(start, end, hours or (0, 24), weekdays if weekdays is not None else range(7), tzinfo)
        if window:
            pieces = [p for p in pieces if p[1] < window[1] and p[2] > window[0]]
        pieces = [(f"{key}\0{day.isoformat()}", s, e) for day, s, e in pieces]
    else:
        pieces = [(key, start, end)]
    copies = []
    for piece_key, piece_start, piece_end in pieces:
        copy = icalendar.Event()
        copy.add('UID', UID_PREFIX + hashlib.sha1(piece_key.encode()).hexdigest())
        copy.add('DTSTAMP', datetime.datetime.now(datetime.timezone.utc))
        copy.add('DTSTART', _to_utc(piece_start, tzinfo))
        copy.add('DTEND', _to_utc(piece_end, tzinfo))
        copy.add('SUMMARY', summary)
        copy.add('TRANSP', 'OPAQUE')
        copy.add(SOURCE_PROP, tag)
        copies.append(copy)
    return copies


def _vcal(comp: icalendar.cal.Component) -> str:
    cal = icalendar.Calendar()
    cal.add('PRODID', '-//plann//freebusy-sync//EN')
    cal.add('VERSION', '2.0')
    cal.add_component(comp)
    return cal.to_ical().decode()


def _same(a: icalendar.cal.Component, b: icalendar.cal.Component) -> bool:
    return all(a.get(p) is not None and b.get(p) is not None and a[p].dt == b[p].dt
               for p in ('DTSTART', 'DTEND')) and str(a.get('SUMMARY')) == str(b.get('SUMMARY'))


def freebusy_sync(source_calendars: Iterable[Any], target: Any, start: datetime.datetime, end: datetime.datetime,
                  summary: str, tag: str, hours: tuple[int, int] | None = None, weekdays: Iterable[int] | None = None,
                  tzinfo: datetime.tzinfo | None = None, dry_run: bool = False) -> dict[str, int]:
    """Make the copies tagged ``tag`` in ``target`` mirror the busy time in
    ``source_calendars`` between ``start`` and ``end``.

    Copies are added, moved or deleted as needed; other objects in the
    target are never touched.  Returns how many copies were added,
    updated, deleted and left unchanged.

    Raises ValueError when there are no source calendars, since an
    unreachable source would otherwise read as no busy time at all and
    delete every copy.
    """
    source_calendars = list(source_calendars)
    if not source_calendars:
        raise ValueError("no source calendars; refusing to sync, as that would delete every copy")
    wanted = {}
    for calendar in source_calendars:
        for obj in calendar.search(event=True, start=start, end=end, expand=True):
            for copy in busy_copies(obj.icalendar_component, summary, tag, hours, weekdays, tzinfo, (start, end)):
                wanted[str(copy['UID'])] = copy

    existing = {}
    for obj in target.search(event=True, start=start, end=end, expand=False):
        comp = obj.icalendar_component
        if str(comp.get(SOURCE_PROP, '')) == tag:
            existing[str(comp['UID'])] = obj

    stats = {'added': 0, 'updated': 0, 'deleted': 0, 'unchanged': 0}
    for uid, copy in wanted.items():
        obj = existing.pop(uid, None)
        if obj is None:
            stats['added'] += 1
            if not dry_run:
                target.add_event(_vcal(copy))
        elif _same(obj.icalendar_component, copy):
            stats['unchanged'] += 1
        else:
            stats['updated'] += 1
            if not dry_run:
                obj.data = _vcal(copy)
                obj.save()
    for obj in existing.values():
        stats['deleted'] += 1
        if not dry_run:
            obj.delete()
    return stats
