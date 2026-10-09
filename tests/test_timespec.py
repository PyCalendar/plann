from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from plann.lib import _ensure_ts, parse_add_dur, parse_dt, parse_timespec, tz
from plann.timespec import DURATION_RE, is_duration

utc = timezone.utc
OSLO = ZoneInfo('Europe/Oslo')

def test_tz_starts_at_defaults():
    """Every test starts with the default tz settings (tests/conftest.py),
    whatever an earlier test - in any module - assigned."""
    assert tz.implicit_timezone is None
    assert tz.store_timezone == ZoneInfo('UTC')

class TestParseTimestamp:
    @pytest.mark.parametrize("input", ["2012-12-12", "2011-11-11 11:11:11", datetime(2011, 11, 11, 11, 11, 11), date(2012, 12, 12), "+14d"])
    def testParseDt(self, input):
        tz.implicit_timezone = 'Europe/Helsinki'
        ts = parse_dt(input)
        if input == '+14d':
            assert ts > datetime.now().astimezone(tz.implicit_timezone)
        else:
            assert ts in (
                datetime(2011, 11, 11, 11, 11, 11, tzinfo=tz.implicit_timezone),
                date(2012, 12, 12))
        ts = parse_dt(input, return_type=datetime)
        if input == '+14d':
            assert ts > datetime.now().astimezone(tz.implicit_timezone)
        else:
            assert ts in (
                datetime(2011, 11, 11, 11, 11, 11, tzinfo=tz.implicit_timezone),
                datetime(2012, 12, 12, 0, 0, tzinfo=tz.implicit_timezone))
        ts = parse_dt(input, return_type=date)
        if input == '+14d':
            assert ts > date.today()
        else:
            assert ts in (
                date(2011, 11, 11), date(2012, 12, 12))
        ts = parse_dt(input, for_storage=True)
        ## TODO: asserts

    @pytest.mark.parametrize("dt,dur,expected", [
        (date(2020,2,20),'1d',date(2020,2,21)),
        (date(2020,2,20),'+1d',date(2020,2,21)),
        ("2020-02-20",'+1d',date(2020,2,21)),

        ## Should this yield a date or a datetime?  TODO!
        #(date(2020,2,20),'1s',date(2020,2,20)),

        (datetime(2020,2,20),'1s', datetime(2020,2,20,0,0,1)),
        (datetime(2020,2,20),'2m', datetime(2020,2,20,0,2,0)),
        (datetime(2020,2,20),'3h', datetime(2020,2,20,3,0,0)),
        (datetime(2020,2,20),'4d', datetime(2020,2,24)),
        (datetime(2020,2,20),'1w1s', datetime(2020,2,27,0,0,1)),
        (datetime(2020,2,20),'2y1d', datetime(2022,2,21)),
        (None, '1s', timedelta(seconds=1)),
        ## Regression tests for the code review bugs #6, #7 and #8.
        ## #6: the year constant was 1314000 seconds (~15 days), not 31536000.
        (None, '1y', timedelta(days=365)),
        ## #8: `diff` was reassigned rather than accumulated, so only the
        ## last unit of a compound duration survived.
        (None, '1h30m', timedelta(minutes=90)),
        (None, '2d3h', timedelta(days=2, hours=3)),
        ## #7: the year branch used to do datetime arithmetic that blew up on
        ## a plain date, and on a Feb 29 base date.
        (date(2021,1,8), '1y', date(2022,1,8)),
        (date(2020,2,29), '1y', date(2021,2,28)),
         ])
    def test_parseAddDur(self, dt, dur, expected):
         if isinstance(dt, datetime):
             dt = dt.replace(tzinfo=tz.implicit_timezone)
         if isinstance(expected, datetime):
             expected = expected.replace(tzinfo=tz.implicit_timezone)
         assert parse_add_dur(dt, dur) == expected

    @pytest.mark.parametrize("dt", [None, date(2021,1,8)])
    def test_parseAddDur_fractional_year(self, dt):
        ## relativedelta only takes whole years - reject rather than
        ## silently truncating 1.5y to 1y
        with pytest.raises(ValueError):
            parse_add_dur(dt, '1.5y')

    def _expected_tz(self, dt):
        """
        Finds the expected time zone
        """
        ## Find the default expected timezone
        expected_tz = tz.implicit_timezone
        if not expected_tz:
            ## Local UTC offset in effect at dt, not now - they differ
            ## when the test runs on the other side of a DST change.
            expected_tz = dt.astimezone().tzinfo
        return expected_tz


    def _stz(self, dt):
        """
        Ensures the dt has a timezone set
        """
        if dt and isinstance(dt, datetime):
            return dt.replace(tzinfo=self._expected_tz(dt))
        return dt

    def _atz(self, dt):
        """
        Ensures the dt has a timezone set
        """
        if dt and isinstance(dt, datetime):
            return dt.astimezone(self._expected_tz(dt))
        return dt

    def _testTimeSpec(self, expected):
        for input in expected:
            expv = tuple([self._stz(x) for x in expected[input]])
            assert parse_timespec(input)== expv

    def _testRelativeTimeSpec(self, expected):
        for input in expected:
            ## Slow tests may sometimes span the exact moment when the second changes, so the
            expected_ = self._atz(datetime.now().replace(microsecond=0)) + expected[input]
            assert parse_dt(input) in (expected_, expected_ + timedelta(seconds=1))

    @pytest.mark.skip(reason="Not implemented yet, waiting for feedback on https://github.com/gweis/isodate/issues/77")
    def testIsoIntervals(self):
        raise pytest.SkipTest("")
        expected = {
            "2007-03-01T13:00:00Z/2008-05-11T15:30:00Z":
                (datetime(2007,3,1,13), datetime(2008,5,11,15,30)),
            "2007-03-01T13:00:00Z/P1Y2M10DT2H30M":
                (datetime(2007,3,1,13), datetime(2008,5,11,15,30)),
            "P1Y2M10DT2H30M/2008-05-11T15:30:00Z":
                (datetime(2007,3,1,13), datetime(2008,5,11,15,30))
        }
        self._testTimeSpec(expected)

    @pytest.mark.parametrize("tz_",['UTC', 'Pacific/Tongatapu', None])
    def testOneTimestamp(self, tz_):
        expected = {
            "2007-03-01T13:00:00":
                (datetime(2007,3,1,13), None),
            "2007-03-01 13:00:00":
                (datetime(2007,3,1,13), None),
        }
        tz.implicit_timezone = tz_
        self._testTimeSpec(expected)

    def testOneDate(self):
        expected = {
            "2007-03-01":
                (date(2007,3,1), None)
        }
        self._testTimeSpec(expected)

    def testRelative(self):
        expected = {
            "+1h": timedelta(hours=1),
            "now": timedelta(hours=0)
        }
        self._testRelativeTimeSpec(expected)

    def testTwoTimestamps(self):
        expected = {
            "2007-03-01T13:00:00 2007-03-11T13:30:00":
                (datetime(2007,3,1,13), datetime(2007,3,11,13,30)),
            "2007-03-01 13:00:00 2007-03-11 13:30:00":
                (datetime(2007,3,1,13), datetime(2007,3,11,13,30)),
        }
        self._testTimeSpec(expected)

    def testTwoDates(self):
        expected = {
            "2007-03-01 2007-03-11":
                (date(2007,3,1), date(2007,3,11))
        }
        self._testTimeSpec(expected)

    def testCalendarCliFormat(self):
        expected = {
            "2007-03-01T13:00:00+10d":
                (datetime(2007,3,1,13), datetime(2007,3,11,13)),
            "2007-03-01T13:00:00+2h":
                (datetime(2007,3,1,13), datetime(2007,3,1,15)),
            "2007-03-01T13:00:00+2.5h":
                (datetime(2007,3,1,13), datetime(2007,3,1,15,30)),
            "2007-03-01T13:00:00+2h30m":
                (datetime(2007,3,1,13), datetime(2007,3,1,15,30)),
            "2007-03-01+10d":
                (date(2007,3,1), date(2007,3,11))
        }
        self._testTimeSpec(expected)

class TestNaturalLanguage:
    """Tests for natural language date parsing enabled by switching to dateparser.

    The expected values are computed in Europe/Oslo, the implicit timezone
    the tests set - not in the host's, whose date may differ."""

    def test_yesterday(self):
        tz.implicit_timezone = "Europe/Oslo"
        result = parse_dt("yesterday")
        expected_date = (datetime.now(OSLO) - timedelta(days=1)).date()
        assert result.date() == expected_date

    def test_today(self):
        tz.implicit_timezone = "Europe/Oslo"
        result = parse_dt("today")
        assert result.date() == datetime.now(OSLO).date()

    def test_relative_hours_ago(self):
        tz.implicit_timezone = "Europe/Oslo"
        result = parse_dt("3 hours ago")
        expected = datetime.now(OSLO) - timedelta(hours=3)
        assert abs((result - expected).total_seconds()) < 5

    def test_day_name(self):
        tz.implicit_timezone = "Europe/Oslo"
        result = parse_dt("Monday")
        assert result.weekday() == 0  # Monday

    def test_relative_future(self):
        tz.implicit_timezone = "Europe/Oslo"
        result = parse_dt("in 2 days")
        expected = (datetime.now(OSLO) + timedelta(days=2)).date()
        got = result.date() if isinstance(result, datetime) else result
        assert got == expected

    def test_yesterday_via_timespec(self):
        """Natural-language dates should also flow through parse_timespec()."""
        tz.implicit_timezone = "Europe/Oslo"
        start, end = parse_timespec("yesterday")
        expected = (datetime.now(OSLO) - timedelta(days=1)).date()
        got = start.date() if isinstance(start, datetime) else start
        assert got == expected
        assert end is None

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_dt("not a date at all !!!!")


class TestDurationGrammar:
    """The [smhdwy] relative-duration grammar is centralised in timespec.py."""

    @pytest.mark.parametrize("text,expected", [
        ("1y1w2h", True),
        ("2.5h", True),
        ("30m", True),
        ("1s", True),
        ("yesterday", False),
        ("2021-01-08", False),
        ("3M", False),   # months not part of the grammar (yet)
        ("", False),
    ])
    def test_is_duration(self, text, expected):
        assert is_duration(text) == expected

    def test_duration_re_is_shared(self):
        """The same compiled regex backs is_duration() and the suffix matcher."""
        assert DURATION_RE.fullmatch("1y1w2h")
        assert not DURATION_RE.fullmatch("1y1w2x")


def test_ensure_ts():
    now = datetime.now()
    utcnow = now.astimezone(utc)
    implicitnow = now.replace(tzinfo=tz.implicit_timezone) if tz.implicit_timezone else now.astimezone()

    assert(_ensure_ts(now) == implicitnow)
    assert(_ensure_ts(utcnow) == utcnow)
    assert(_ensure_ts(implicitnow) == implicitnow)
