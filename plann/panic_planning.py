import re
from datetime import datetime, timedelta, timezone

from sortedcontainers import SortedKeyList

from plann.lib import _component_type, _ensure_ts, _now
from plann.timespec import parse_add_dur


class TimeLine(SortedKeyList):
    """
    The TimeLine is a sorted list of dicts, the dict should as the very minimum contain the datetime key begin.

    The TimeLine should be without holes.  Unallocated time should be presented as a dict with only the key begin (which should correspond to the end of the previous item on the timeline)

    The TimeLine should not contain overlapping events.
    """
    def __init__(self):
        SortedKeyList.__init__(self, key=lambda x: x['begin'])

    def count(self):
        """Includes all real objects on the list.  Ignores start and end markers, as well as slack"""
        return len([x for x in self if 'obj' in x and x['obj'] != 'slack'])

    def add_event(self, event):
        start = event.icalendar_component.get('dtstart')
        end = event.get_dtend()
        if not end and start and not isinstance(start.dt, datetime):
            end = start.dt + timedelta(days=1)
        if not end or not start:
            ## Todo: consider DURATION ...
            return
        start = _ensure_ts(start)
        end = _ensure_ts(end)
        self.add(start, end, event)

    def add(self, begin, end, obj=None):
        assert(begin.tzinfo)
        assert(end.tzinfo)
        obj_ = {'begin': begin, 'obj': obj}
        if end <= begin:
            ## TODO: error message (but how?  print?  click.echo?  logging?  callback?)
            ## this doesn't work?
            #end = begin + timedelta(minutes=1)
            return
        i = self.bisect_right(obj_)
        if i<len(self):
            if self[i]['begin'] < end:
                ## Possibly overlapping events.
                ## TODO: error message - but how?  raise an error and catch it further up?
                return
        if i>0:
            assert not any(key != 'begin' for key in self[i-1])
        if i>0 and i<len(self):
            if self[i-1]['begin'] == begin and self[i]['begin'] == end:
                self[i-1]['obj'] = obj
                return
        SortedKeyList.add(self, obj_)
        if i+1==len(self) or self[i+1]['begin'] > end:
            SortedKeyList.add(self, {'begin': end})

    def get(self, ts):
        if not (len(self)):
            return {'begin': ts}
        i = self.bisect_left({'begin': ts})
        if i>0:
            foo = self[i-1].copy()
        else:
            foo = {}
        if i<len(self):
            foo['end'] = self[i]['begin']
        return foo

    def find_opening(self, last_possibility, duration, slack_balance=timedelta(0)):
        end = last_possibility-duration
        while True:
            foo = self.get(end)
            if len(foo) == 2:
                if 'end' in foo and 'begin' in foo:
                    foodur = foo['end']-foo['begin']
                    if foodur > duration:
                        return (foo, slack_balance)
                    slack_balance += foodur
            if 'begin' not in foo or 'end' not in foo:
                return (foo, slack_balance)
            end = foo['begin']-timedelta(seconds=1)

    def pad_slack(self, end, duration):
        i = self.bisect_left({'begin': end})-1
        while i>=0 and duration>timedelta(0):
            if any(key != 'begin' for key in self[i]):
                end = self[i]['begin']
                i -= 1
                continue
            slot_dur = end - self[i]['begin']
            if slot_dur <= duration:
                duration -= slot_dur
                self[i]['obj'] = 'slack'
            else:
                self.add(end-duration, end, 'slack')
                duration = timedelta(0)
        if duration:
            self.add(begin=end-duration, end=end, obj='slack')

def timeline_suggestion(ctx, hours_per_day=4, timeline_end=None):
    timeline = TimeLine()
    objs = ctx.obj['objs']
    events = [x for x in objs if _component_type(x) == 'VEVENT']
    event_parents = []
    for event in events:
        comp = event.icalendar_component
        if comp.get('STATUS', '') == 'CANCELLED':
            continue
        dtend = event.get_dtend()
        if 'RELATED-TO' in comp and dtend is not None and _ensure_ts(dtend)>_now():
            rels = event.get_relatives(fetch_objects=False)
            for rel in rels['PARENT']:
                event_parents.append(str(rel))
    tasks = [x for x in objs if _component_type(x) == 'VTODO']
    assert len(events) + len(tasks) == len(objs)
    tasks = [x for x in tasks if ('\nDUE' in x.data or '\nDURATION' in x.data) and '\nDTSTART' in x.data]

    for event in events:
        ## TODO ... we should handle overlapping events a bit better than just ignoring AssertionErrors
        try:
            timeline.add_event(event)
        except AssertionError:
            pass
    tasks.sort(key=lambda x: (x.icalendar_component.get('PRIORITY',0), _now()-_ensure_ts(x.get_due())))
    slackbalance = timedelta(0)
    for task in tasks:
        if str(task.icalendar_component['UID']) in event_parents:
            ## task is presumably already included in timeline
            continue
        due = task.get_due()
        if due is None:
            due = timeline_end
        end = _ensure_ts(due)
        if timeline_end:
            end = min(end, timeline_end)
        duration = task.get_duration()
        ## TODO: we should verify that duration is set and positive, otherwise the panic planning will panic
        slackbalance -= duration*(24-hours_per_day)/hours_per_day
        slot, slackbalance = timeline.find_opening(end, duration, slackbalance)
        if 'end' in slot:
            end = min(end, slot['end'])
        begin = end - duration
        timeline.add(begin, end, task)
        if slackbalance<timedelta(0):
            timeline.pad_slack(begin, -slackbalance)
            slackbalance=timedelta(0)
    return timeline


## The editable plan used by check-for-panic --interactive-fix-timeline.
## One line per task: UID START DURATION SUMMARY.  The end is deliberately
## not written out, so moving the start keeps the length of the block.

PIN_PLAN_TS_FORMAT = '%Y-%m-%d %H:%M'
_pin_plan_re = re.compile(r'^(\S+)\s+(\d{4}-\d{2}-\d{2} \d{1,2}:\d{2})\s+(\+?[0-9.smhdwy]+)\s+(\S.*?)\s*$')

def format_duration(duration):
    """timedelta to the duration syntax parse_add_dur reads, like +1h30m"""
    secs = int(duration.total_seconds())
    ret = ''
    for unit, size in (('d', 86400), ('h', 3600), ('m', 60), ('s', 1)):
        if secs >= size:
            ret += f"{secs // size}{unit}"
            secs %= size
    return '+' + (ret or '0m')

def _utc_offset(ts):
    off = ts.strftime('%z')
    return f"UTC{off[:3]}:{off[3:]}"

def format_pin_plan(entries, tzinfo):
    """entries are (uid, begin, end, summary) tuples, uid None for
    existing events.  All timestamps are shown in tzinfo."""
    zone = getattr(tzinfo, 'key', None) or 'local time'
    offsets = []
    for (uid, begin, end, summary) in entries:
        ts = begin.astimezone(tzinfo)
        label = f"{ts:%Z} = {_utc_offset(ts)}"
        if label not in offsets:
            offsets.append(label)
    if len(offsets) > 1:
        offset_note = f" ({', '.join(offsets)}; the offset changes within this plan)"
    elif offsets:
        offset_note = f" ({offsets[0]})"
    else:
        offset_note = ''
    lines = [
        f"# All times are in {zone}{offset_note}.",
        "#",
        "# Each line is:  UID  START  DURATION  SUMMARY",
        "# There is no end time: the end is START + DURATION.  Change START to move",
        "# a task, it keeps its length.  Change DURATION (like +45m, +2h, +1h30m)",
        "# to make it shorter or longer.  The summary may be edited too.",
        "# Delete a line to leave that task off the calendar.  Delete all the task",
        "# lines to pin nothing - also the way out after an error.",
        "# Lines starting with '#' are existing events, they can't be changed here.",
        "# There is no collision check.",
        "",
    ]
    width = max([len(x[0]) for x in entries if x[0]] + [36])
    for (uid, begin, end, summary) in entries:
        prefix = uid.ljust(width) if uid else '#'.ljust(width)
        ## real elapsed time, as parse_pin_plan adds it back
        duration = end.astimezone(timezone.utc) - begin.astimezone(timezone.utc)
        summary = re.sub(r'\s*[\r\n]+\s*', ' ', str(summary)).strip()
        lines.append(f"{prefix} {begin.astimezone(tzinfo):{PIN_PLAN_TS_FORMAT}} {format_duration(duration):7} {summary}")
    return "\n".join(lines) + "\n"

def parse_pin_plan(text, tzinfo):
    """Inverse of format_pin_plan.  Returns a list of (uid, begin, end,
    summary), raises ValueError naming the line on syntax errors."""
    ret = []
    for (lineno, line) in enumerate(text.split('\n'), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parsed = _pin_plan_re.match(line)
        if not parsed:
            raise ValueError(f"line {lineno}: expected UID  YYYY-MM-DD HH:MM  DURATION  SUMMARY, got: {line}")
        (uid, begin, duration, summary) = parsed.groups()
        try:
            begin = datetime.strptime(begin, PIN_PLAN_TS_FORMAT).replace(tzinfo=tzinfo)
            duration = parse_add_dur(None, duration)
        except ValueError as e:
            raise ValueError(f"line {lineno}: {e}: {line}") from e
        if not duration or duration <= timedelta(0):
            raise ValueError(f"line {lineno}: the duration must be positive: {line}")
        end = (begin.astimezone(timezone.utc) + duration).astimezone(tzinfo)
        ret.append((uid, begin, end, summary))
    return ret
