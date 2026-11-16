import datetime
import re
import zoneinfo
from dataclasses import dataclass

import dateparser
from dateutil.relativedelta import relativedelta

"""
Most important content:

* parse_dt - parses almost anything into a datetime.
* parse_timespec - parses a string (which may be a timestamp or an interval) into two datetimes
* tz - a singleton containing the default timezones to be used

parse_dt supports things like "+2h", "now", "yesterday", or "3 hours ago",
while parse_timespec doesn't.

The naming of those two are a bit arbitrary and may be changed in a future version of the library.  Old names will then continue working as legacy aliases.
"""

## The relative-duration mini-grammar (e.g. "2h", "1y1w", "+2.5h").  Historically
## this [smhdwy] unit set was duplicated in four places (parse_add_dur,
## _parse_timespec, commands.__select and interactive._command_line_edit); it lives
## here now so adding a new unit (e.g. months) only touches one spot.
DURATION_UNITS = "smhdwy"
## A single magnitude+unit token (signed/decimal), with the remainder captured in
## group 3 so callers can tokenize a multi-unit duration one component at a time.
DURATION_TOKEN_RE = re.compile(rf'([+-]?\d+(?:\.\d+)?)([{DURATION_UNITS}])(.*)')
## A complete bare duration such as "1y1w2h" (one capturing group around the whole).
DURATION_RE = re.compile(rf'((?:\d+(?:\.\d+)?[{DURATION_UNITS}])+)')

def is_duration(text):
    """True if the whole string is a bare relative duration like "1y1w2h"."""
    return bool(re.fullmatch(DURATION_RE, text))

## Singleton (aka global variable)
@dataclass
class Tz:
    """
    Singleton class storing timezone preferences

    (floating time not supported yet)

    "implicit" is the timezone that is implicitly used for timestamps given by the user
    "store" is the timezone used by the storage backend
    """
    show_native_timezone: bool=False
    _implicit_timezone: zoneinfo.ZoneInfo = None
    _store_timezone: zoneinfo.ZoneInfo = zoneinfo.ZoneInfo('UTC')

    @property
    def implicit_timezone(self):
        return self._implicit_timezone

    @property
    def store_timezone(self):
        return self._store_timezone

    @implicit_timezone.setter
    def implicit_timezone(self, value):
        if value:
            self._implicit_timezone = zoneinfo.ZoneInfo(value)
            if not self.store_timezone:
                self._store_timezone = self._implicit_timezone

    @store_timezone.setter
    def store_timezone(self, value):
        if value:
            self._store_timezone = zoneinfo.ZoneInfo(value)

tz=Tz()

def _now():
    return datetime.datetime.now().astimezone(tz.implicit_timezone).replace(microsecond=0)

def _ensure_ts(dt):
    """
    TODO: do we need this?  it's a bit overlapping with parse_dt
    """
    if hasattr(dt, 'dt'):
        dt = dt.dt
    if dt is None:
        return datetime.datetime(1970,1,1).astimezone(tz.implicit_timezone)
    if isinstance(dt, datetime.datetime):
        if not dt.tzinfo:
            return dt.replace(tzinfo=tz.implicit_timezone).astimezone(tz.implicit_timezone)
        else:
            return dt
    return datetime.datetime(dt.year, dt.month, dt.day, tzinfo=tz.implicit_timezone).astimezone(tz.implicit_timezone)

def parse_dt(input, return_type=None, for_storage=False):
    """
    Convenience-method, it is very liberal in what it accepts as input:

    * Date string or datetime string (uses dateutil.parser)
    * datetime or date
    * VDDDTypes from the icalendar library
    * strings like "+2h" means "two hours in the future"
    * special string "now"

    If return_type is date, return a date - if return_type is
    datetime, return a datetime.  If no return_type is given, try to
    guess if we should return a date or a datetime.  Datetime should
    always have a timezone.
    """
    ret = _parse_dt(input, return_type)
    if for_storage and hasattr(ret, "astimezone"):
        ret = ret.astimezone(tz.store_timezone)
    return ret

def _parse_dt(input, return_type=None):
    if hasattr(input, 'dt'):
        input = input.dt
    if isinstance(input, datetime.datetime):
        if return_type is datetime.date:
            return input.date()
        return _ensure_ts(input)
    if isinstance(input, datetime.date):
        if return_type is datetime.datetime:
            return _ensure_ts(input)
        return input
    if input == 'now':
        ret = _now()
    elif input.isdigit() and len(input) <= 2 and int(input) < 24:
        ## a bare hour, i.e. `--set-dtstart=14` means 14:00 today.
        ## dateparser would take it as a day of the month.
        ret = _now().replace(hour=int(input), minute=0, second=0, microsecond=0)
        return ret.date() if return_type is datetime.date else ret
    elif input.startswith('+'):
        ret = parse_add_dur(_now(), input[1:])
    else:
        settings: dict = {"RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "current_period"}
        if tz.implicit_timezone:
            settings["TIMEZONE"] = str(tz.implicit_timezone)
        ret = dateparser.parse(input, settings=settings)
        if ret is None:
            raise ValueError(f"Could not parse datetime string: {input!r}")
    if return_type is datetime.datetime:
        return _ensure_ts(ret)
    elif return_type is datetime.date:
        return ret.date()
    elif ret.time() == datetime.time(0,0) and len(input)<12 and '00:00' not in input and '0000' not in input:
        return ret.date()
    else:
        return _ensure_ts(ret)


def parse_add_dur(dt, dur, for_storage=False, ts_allowed=False):
    """
    duration may be something like this:
      * 1s (one second)
      * 3m (three minutes, not months
      * 3.5h
      * 1y1w

    It may also be a ISO8601 duration

    Returns the dt plus duration.

    If no dt is given, return the duration.

    TODO: months not supported yet
    TODO: return of delta in years not supported yet
    TODO: ISO8601 duration not supported yet
    """
    if dt and not (isinstance(dt, datetime.date)):
        dt = parse_dt(dt)
    time_units = {
        's': 1, 'm': 60, 'h': 3600,
        'd': 86400, 'w': 604800,
        'y': 31536000
    }
    diff = datetime.timedelta(0)
    while dur:
        rx = DURATION_TOKEN_RE.match(dur)
        if not rx:
            if ts_allowed:
                return parse_dt(dur)
            else:
                raise ValueError(f"A duration (like 3h for three hours) expected, but got: {dur}")
        i = float(rx.group(1))
        u = rx.group(2)
        dur = rx.group(3)
        if u=='y':
            if i != int(i):
                raise ValueError(f"Fractional years are not supported, got: {i:g}y")
            if dt:
                dt = dt + relativedelta(years=int(i))
            else:
                diff += datetime.timedelta(seconds=int(i)*time_units['y'])
        else:
            component = datetime.timedelta(0, i*time_units[u])
            diff += component
            if dt:
                dt = dt + component
    if dt:
        return dt.astimezone(tz.store_timezone) if for_storage else dt
    else:
        return diff


def parse_timespec(timespec, for_storage=False):
    """parses a timespec and return two timestamps

    The ISO8601 interval format, format 1, 2 or 3 as described at
    https://en.wikipedia.org/wiki/ISO_8601#Time_intervals should be
    accepted, though it may be dependent on
    https://github.com/gweis/isodate/issues/77 or perhaps
    https://github.com/dateutil/dateutil/issues/1184

    The calendar-cli format (i.e. 2021-01-08 15:00:00+1h) should be accepted

    Two timestamps should be accepted.

    One timestamp should be accepted, and the second return value will be None.
    """
    ret = _parse_timespec(timespec)
    # do not try to adjust timezone for datetime.date (all-day events)
    if for_storage and isinstance(ret[0], datetime.datetime):
        ret = (x and x.astimezone(tz.store_timezone) for x in ret)
    return ret

def _parse_timespec(timespec):
    if isinstance(timespec, datetime.date):
        return (timespec,timespec)

    if (
            isinstance(timespec, tuple) and
            len(timespec)==2 and
            isinstance(timespec[0], datetime.date) and
            isinstance(timespec[1], datetime.date)):
        return timespec

    ## calendar-cli format, 1998-10-03 15:00+2h
    if '+' in timespec:
        rx = re.match(rf'(.*)\+{DURATION_RE.pattern}$', timespec)
        if rx:
            start = parse_dt(rx.group(1))
            end = parse_add_dur(start, rx.group(2))
            return (start, end)
    try:
        ## dateparser may misparse strings containing multiple dates; detect early
        if timespec.count('-') > 3:
            raise ValueError("Seems to be two dates here")
        ret = parse_dt(timespec)
        return (ret, None)
    except ValueError:
        split_by_space = timespec.split(' ')
        if len(split_by_space) == 2:
            return (parse_dt(split_by_space[0]), parse_dt(split_by_space[1]))
        elif len(split_by_space) == 4:
            return (parse_dt(f"{split_by_space[0]} {split_by_space[1]}"), parse_dt(f"{split_by_space[2]} {split_by_space[3]}"))
        else:
            raise ValueError(f"couldn't parse time interval {timespec}")
