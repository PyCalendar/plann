#import isodate
import datetime
import logging
import re
import shlex

import caldav

## TODO: can we remove the click-dependency?
import click
import icalendar
from caldav.lib.error import ETagMismatchError, NotFoundError, PutError, ScheduleTagMismatchError
from dateutil import tz as dateutil_tz
from icalendar_searcher import Searcher

from plann.interactive import (
    _abort,
    _editor,
    _get_obj_from_line,
    _interactive_edit,
    _interactive_ical_edit,
    _interactive_relation_edit,
    _mass_interactive_edit,
    _mass_reprioritize,
    _pdb_edit,
    interactive_split_task,
)
from plann.lib import (
    COMMA_LIST_ATTRS,
    _add_comma_list,
    _comma_list_canonical,
    _comma_list_is_plural,
    _comma_list_tokens,
    _complete,
    _component_type,
    _is_comma_list_attr,
    _list,
    _process_set_arg,
    _procrastinate,
    _RelativeCache,
    _relships_by_type,
    _set_something,
    _summary,
    attr_txt_many,
    childlike,
    parentlike,
)
from plann.panic_planning import format_pin_plan, parse_pin_plan, timeline_suggestion
from plann.template import Template
from plann.timespec import DURATION_RE, _ensure_ts, _now, parse_add_dur, parse_dt, parse_timespec, tz


def _select(ctx, interactive=False, mass_interactive=False, **kwargs):
    """
    wrapper function for __select.  Will honor the --interactive flag.
    """
    __select(ctx, **kwargs)
    ## TODO: move the rest to interactive module?
    if (interactive or mass_interactive) and ctx.obj['objs']:
        objs = ctx.obj['objs']
        if mass_interactive:
            ctx.obj['objs'] = []
            select_list = "\n".join(_list(
                objs, echo=False,
                template="{UID}: {SUMMARY:?{DESCRIPTION:?(no summary given)?}?} (STATUS={STATUS:-})"))
            edited = _editor("## delete things that should not be selected:\n" + select_list)
            for objectline in edited.split("\n"):
                objectline.split(': ')
                obj = _get_obj_from_line(objectline, objs[0].parent)
                if obj:
                    ctx.obj['objs'].append(obj)

        if interactive:
            for obj in objs:
                if click.confirm(f"select {_summary(obj)}?"):
                    ctx.obj['objs'].append(obj)

def _sort_key_function(skey):
    """Build a ``(reverse, key_function)`` pair from a single sort-key spec.

    A leading ``-`` reverses the sort.  A spec containing ``{`` is treated as
    a template and compiled once here - not rebuilt on every comparison during
    the sort (code review E2).  ``get_duration()`` is special-cased; any other
    spec is a plain icalendar component property name.
    """
    reverse = skey.startswith('-')
    if reverse:
        skey = skey[1:]
    if '{' in skey:
        template = Template(skey)
        def fkey(obj):
            return template.format_component(obj.icalendar_component)
    elif skey == 'get_duration()':
        def fkey(obj):
            return obj.get_duration()
    else:
        def fkey(obj):
            return obj.icalendar_component.get(skey)
    return reverse, fkey

def __select(ctx, extend_objects=False, all=None, uid=[], abort_on_missing_uid=None, warn_on_missing_uid=True, sort_key=[], skip_parents=None, skip_children=None, limit=None, offset=None, freebusyhack=None, pinned_tasks=None, **kwargs_):
    """
    select/search/filter tasks/events, for listing/editing/deleting, etc
    """
    if extend_objects:
        objs = ctx.obj.get('objs', [])
    else:
        objs = []
    ctx.obj['objs'] = objs

    ## TODO: move all search/filter/select logic to caldav library?

    ## handle all/none options
    if all is False: ## means --none.
        return
    if all:
        for c in ctx.obj['calendars']:
            objs.extend(c.objects())
        return

    kwargs = {}
    for kw in kwargs_:
        if kwargs_[kw] is not None and kwargs_[kw] != ():
            kwargs[kw] = kwargs_[kw]

    ## uid(s)
    ## NB: we deliberately query every calendar and collect every match rather
    ## than stopping at the first hit - the same UID may legitimately exist in
    ## more than one calendar (e.g. a copied event/task), and the caller may
    ## want to act on all of them.  This costs one lookup per (uid, calendar),
    ## but that is inherent to "find this UID in any of my calendars": to know
    ## whether a UID is in a calendar you have to ask that calendar.  Do not
    ## "optimise" this into a break-on-first-match - it would silently drop the
    ## cross-calendar duplicates.
    missing_uids = []
    for uid_ in uid:
        cnt = 0
        for c in ctx.obj['calendars']:
            try:
                objs.append(c.get_object_by_uid(uid_))
                cnt += 1
            except caldav.error.NotFoundError:
                pass
        if not cnt:
            missing_uids.append(uid_)
    if missing_uids:
        if abort_on_missing_uid:
            _abort(f"Did not find the following uids in any calendars: {missing_uids}")
        elif warn_on_missing_uid:
            click.echo(f"Warning: did not find the following uids in any calendars: {missing_uids}", err=True)
    if uid:
        return

    if pinned_tasks:
        kwargs['event'] = True
        kwargs['todo'] = None

    if kwargs_.get('start') or kwargs_.get('end'):
        if kwargs_.get('start'):
            kwargs['start'] = parse_dt(kwargs['start'])
        if kwargs_.get('end') and not isinstance(kwargs_.get('end'), datetime.date):
            rx = re.match(rf'\+{DURATION_RE.pattern}', kwargs['end'])
            if rx:
                kwargs['end'] = parse_add_dur(kwargs.get('start', datetime.datetime.now()), rx.group(1))
            else:
                kwargs['end'] = parse_dt(kwargs['end'])
    elif kwargs_.get('timespan'):
        kwargs['start'], kwargs['end'] = parse_timespec(kwargs['timespan'])

    for attr in attr_txt_many:
        if len(kwargs_.get(attr, []))>1:
            raise NotImplementedError(f"is it really needed to search for more than one {attr}?")
        elif kwargs_.get(attr):
            kwargs[attr] = kwargs[attr][0]

    ## TODO: special handling of parent and child! (and test for that!)

    if 'start' in kwargs and 'end' in kwargs:
        kwargs['expand'] = True
    for c in ctx.obj['calendars']:
        objs.extend(c.search(**kwargs))

    if skip_children or skip_parents:
        i = 0
        while i < len(objs):
            obj = objs[i]
            if skip_children and obj.get_relatives(parentlike, fetch_objects=False):
                objs.pop(i)
                continue
            if skip_parents and obj.get_relatives(childlike, fetch_objects=False):
                objs.pop(i)
                continue
            i += 1

    if pinned_tasks is not None:
        ret_objs = []
        for obj in ctx.obj['objs']:
            if isinstance(obj, caldav.Event):
                if obj.icalendar_component.get('STATUS', '') != 'CANCELLED':
                    open_parents = _pinned_task_parents(obj)
                    if bool(open_parents) == pinned_tasks:
                        if kwargs_.get('todo'):
                            ## TODO: special handling for recurring tasks
                            ret_objs.extend(open_parents)
                        else:
                            ret_objs.append(obj)
            if isinstance(obj, caldav.Todo) and not pinned_tasks:
                children = _relships_by_type(obj, 'CHILD').get('CHILD',[])
                if not any(x.icalendar_component.get('STATUS', '')!='CANCELLED' for x in children if isinstance(x, caldav.Event)):
                    ret_objs.append(obj)
        ctx.obj['objs'] = ret_objs

    ## OPTIMIZE TODO: sorting the list multiple times rather than once is a bit of brute force, if there are several sort keys and long list of objects, we should sort once and consider all sort keys while sorting
    ## TODO: Consider that an object may be expanded and contain lots of event instances.  We will then need to expand the caldav.Event object into multiple objects, each containing one recurrance instance.  This should probably be done on the caldav side of things.
    for skey in reversed(sort_key):
        reverse, fkey = _sort_key_function(skey)
        ctx.obj['objs'].sort(key=fkey, reverse=reverse)

    ## OPTIMIZE TODO: this is also suboptimal, if ctx.obj is a very long list
    if offset is not None:
        ctx.obj['objs'] = ctx.obj['objs'][offset:]
    if limit is not None:
        ctx.obj['objs'] = ctx.obj['objs'][0:limit]

    ## some sanity checks
    for obj in ctx.obj['objs']:
        _fix_mismatched_date_types(obj.icalendar_component)

    ## I need a way to copy time information from one calendar to another
    ## (typically between private and work calendars) without carrying over
    ## (too much potentially) private/confidential information.
    if freebusyhack:
        logging.warning("--freebusyhack is deprecated, use the freebusy-sync command")
        for obj in ctx.obj['objs']:
            comp = obj.icalendar_component
            attribs = list(comp.keys())
            for attr in attribs:
                if attr not in ('DUE', 'DTEND', 'DTSTART', 'DTSTAMP', 'UID', 'RRULE', 'SEQUENCE', 'EXDATE', 'STATUS', 'CLASS'):
                    del comp[attr]
                if attr == 'SUMMARY':
                    comp[attr] = freebusyhack

def _fix_mismatched_date_types(comp):
    """If one of DTSTART and DTEND/DUE is a date and the other a timestamp,
    turn the date into a timestamp at midnight, so they can be compared: in
    the timezone of the timestamp if it has a named one (TZID), floating if
    it is floating, and in the implicit timezone if it is in UTC (also a
    TZID naming UTC).  The time
    of day on the timestamp is kept.  Logs an error if DTSTART comes after
    DTEND/DUE."""
    endkey = 'DTEND' if 'DTEND' in comp else 'DUE'
    dtstart = comp.get('DTSTART')
    dtend = comp.get(endkey)
    if not (dtstart and dtend):
        return
    start_is_ts = isinstance(dtstart.dt, datetime.datetime)
    if start_is_ts != isinstance(dtend.dt, datetime.datetime):
        logging.error(f"task with uuid {comp['uid']} has non-matching types on dtstart and dtend/due, setting both to timestamps")
        date_key, d, other_key, other = (endkey, dtend, 'DTSTART', dtstart) if start_is_ts else ('DTSTART', dtstart, endkey, dtend)
        d = d.dt
        tz = other.dt.tzinfo
        is_utc = tz is datetime.timezone.utc or str(tz) in ('UTC', 'Etc/UTC', 'Etc/Zulu', 'Zulu', 'Etc/UCT', 'UCT')
        new_ts = datetime.datetime(d.year, d.month, d.day)
        if tz and 'TZID' in other.params and not is_utc:
            new_ts = new_ts.replace(tzinfo=tz)
            ## re-add the other one too, so icalendar writes its own name for
            ## the timezone (e.g. Europe/Berlin for "W. Europe Standard Time")
            ## in both properties
            comp.pop(other_key)
            comp.add(other_key, other.dt)
        elif tz:
            new_ts = _ensure_ts(d)
        ## replace the property rather than setting .dt, so VALUE=DATE goes away
        comp.pop(date_key)
        comp.add(date_key, new_ts)
    if _ensure_ts(comp['DTSTART'].dt) > _ensure_ts(comp[endkey].dt):
        logging.error(f"task with uuid {comp['uid']} has dtstart after dtend/due")

def _categories_in_use(objs):
    categories = set()
    for obj in objs:
        categories.update(str(x) for x in obj.icalendar_component.categories if x)
    return categories

def _cats(ctx):
    return _categories_in_use(ctx.obj['objs'])

def _todos_missing(objs, prop):
    """Return the objects from ``objs`` that have no ``prop`` property set.

    Client-side filtering via icalendar_searcher's ``undef`` operator - the
    same semantics the caldav library uses for the server-side ``no_<prop>``
    search, so we can fetch the task list once and filter locally rather than
    issuing one server query per attribute (code review E4)."""
    searcher = Searcher(todo=True)
    searcher.add_property_filter(prop, None, operator="undef")

    def _missing(obj):
        ## "undef" only catches a property that is absent altogether.  An
        ## empty value is no value, and RFC 5545 PRIORITY:0 means "undefined
        ## priority" - plann treats it that way everywhere else, so those
        ## tasks must still be offered for editing.
        return searcher.check_component(obj) or not obj.icalendar_component.get(prop)

    return [obj for obj in objs if _missing(obj)]

def _edit(ctx, cancel=None, interactive_ical=False, interactive_relations=False, mass_interactive_default='ignore', mass_interactive=False, interactive=False, complete=None, complete_recurrence_mode='safe', postpone=None, postpone_with_children=None, interactive_reprioritize=False, **kwargs):
    """
    Edits a task/event/journal
    """
    ## TODO: consolidate with command_edit
    if 'recurrence_mode' in kwargs:
        complete_recurrence_mode = kwargs.pop('recurrence_mode')
    add_args = _process_add_args(kwargs)
    _process_set_args(ctx, kwargs, keep_category=True)
    if interactive_ical:
        _interactive_ical_edit(ctx.obj['objs'])
        ## TODO: should be possible to combine this with other opitions
        return

    if interactive_relations:
        _interactive_relation_edit(ctx.obj['objs'])
        ## TODO: should be possible to combine this with other opitions
        return

    if mass_interactive:
        _mass_interactive_edit(ctx.obj['objs'], default=mass_interactive_default)
        ## TODO: should be possible to combine this with other opitions
        return

    if interactive_reprioritize:
        _mass_reprioritize(ctx.obj['objs'])
        ## TODO: should be possible to combine this with other opitions
        return

    complete_cache = _RelativeCache()
    complete_cache.add_objects(ctx.obj['objs'])
    completed = set()
    for obj in ctx.obj['objs']:
        if interactive and str(obj.icalendar_component['UID']) not in completed:
            ## (a task completed along with its parent is not asked about again)
            _interactive_edit(obj, complete_cache, completed)
        comp = obj.icalendar_component
        if kwargs.get('pdb'):
            _pdb_edit(obj)
        ## DTSTART last: setting DUE/DTEND moves DTSTART along with it
        for arg in sorted(ctx.obj['set_args'], key=lambda a: a.lower() == 'dtstart'):
            _set_something(obj, arg, ctx.obj['set_args'][arg])
        for canonical, tokens in add_args:
            _add_comma_list(obj, canonical, tokens)
        if complete:
            _complete(obj, handle_rrule=complete_recurrence_mode, rrule_mode=complete_recurrence_mode, err_callback=lambda msg: click.echo(msg, err=True), cache=complete_cache, _seen=completed)
        elif complete is False:
            obj.uncomplete()
        if cancel:
            comp.status='CANCELLED'
        elif cancel is False:
            comp.status='NEEDS-ACTION'
        if postpone or postpone_with_children:
            _procrastinate([obj], postpone or postpone_with_children, with_children=postpone_with_children and True)

        ## OPTIMIZE TODO: only save objects that actually have been edited
        obj.save()

def _display_timezone():
    return tz.implicit_timezone or dateutil_tz.tzlocal()

def _timeline_entries(possible_timeline, timeline_start):
    """(uid, begin, end, summary) for the future items of the timeline,
    uid is None for things that are already events"""
    ret = []
    for (foo, next) in zip(possible_timeline, possible_timeline[1:]):
        if 'begin' in foo and 'obj' in foo and not isinstance(foo['obj'], str):
            if _ensure_ts(foo['begin'])>timeline_start:
                obj = foo['obj']
                uid = str(obj.icalendar_component['UID']) if isinstance(obj, caldav.Todo) else None
                ret.append((uid, foo['begin'], next['begin'], _summary(obj)))
    return ret

def _interactive_fix_timeline(ctx, possible_timeline, timeline_start):
    """Lets the user edit the suggested plan and pins the tasks in it to
    the calendar.  Returns the number of events added."""
    tzinfo = _display_timezone()
    text = format_pin_plan(_timeline_entries(possible_timeline, timeline_start), tzinfo)
    while True:
        text = _editor(text)
        try:
            plan = parse_pin_plan(text, tzinfo)
            break
        except ValueError as e:
            text = "\n".join([f"# ERROR: {e}"] + [x for x in text.split("\n") if not x.startswith("# ERROR: ")])
    for (uid, begin, end, summary) in plan:
        event = _add_event(ctx, summary=summary, timespec=(begin, end), set_status='TENTATIVE', first_calendar=True, set_parent=[uid])
        ## so a new plan won't suggest the task again
        ctx.obj['objs'].append(event)
    return len(plan)

def _check_for_panic(ctx, hours_per_day, output=True, print_timeline=True, fix_timeline=False, interactive_fix_timeline=False, timeline_start=None, timeline_end=None, include_all_events=False):
    if not timeline_start:
        timeline_start = _now()
    else:
        timeline_start = parse_dt(timeline_start, datetime.datetime)
    if not timeline_end:
        timeline_end = parse_add_dur(timeline_start, '+1y')
    timeline_end = parse_dt(timeline_end, datetime.datetime)
    if include_all_events:
        ## Remove events from the list to prevent duplicates ...
        ctx.obj['objs'] = [x for x in ctx.obj['objs'] if _component_type(x) != 'VEVENT']
        ## ... and then add all events
        _select(ctx, event=True, start=timeline_start, end=timeline_end, extend_objects=True)
    possible_timeline = timeline_suggestion(ctx, hours_per_day=hours_per_day, timeline_end=timeline_end)
    def summary(obj):
        if obj is None:
            return "-- unallocated time --"
        if isinstance(obj, str):
            return obj
        return _summary(obj)

    if (print_timeline):
        tzinfo = _display_timezone()
        click.echo("Calculated timeline suggestion:")
        for foo in possible_timeline:
            if 'begin' in foo:
                click.echo(f"{foo['begin'].astimezone(tzinfo):%FT%H:%M %Z} {summary(foo.get('obj'))}")

    if output:
        click.echo()
        click.echo("THESE TASKS WILL NEED TO BE PROCRASTINATED:")
        for foo in possible_timeline:
            if 'begin' in foo and 'obj' in foo and not isinstance(foo['obj'], str):
                if _ensure_ts(foo['begin'])<timeline_start:
                    due = _ensure_ts(foo['obj'].get_due()).astimezone(_display_timezone())
                    click.echo(f"{due:%FT%H%M %Z} {foo['obj'].icalendar_component.get('PRIORITY', 0)} {_summary(foo['obj'])}")

    if fix_timeline:
        for (uid, begin, end, summary) in _timeline_entries(possible_timeline, timeline_start):
            if uid:
                ## TODO: copy other attributes?
                _add_event(ctx, summary=summary, timespec=(begin, end), set_status='TENTATIVE', first_calendar=True, set_parent=[uid])
    if interactive_fix_timeline:
        while (_interactive_fix_timeline(ctx, possible_timeline, timeline_start) and
               click.confirm("Plan again, with the events just added?", default=False)):
            possible_timeline = timeline_suggestion(ctx, hours_per_day=hours_per_day, timeline_end=timeline_end)

    return possible_timeline

def _warn_comma_literal(verb, attr, value):
    """The singular --add-category/--add-resource/--set-category keep a comma
    literally, giving one category (or resource) containing a comma, and so
    does a plural option given more than once.  That is intended, but nearly
    always a mistake - warn.  (A bare string, as from the interactive editor,
    is always split on comma: nothing to warn about.)"""
    if not _is_comma_list_attr(attr) or hasattr(value, 'split'):
        return
    if _comma_list_is_plural(attr):
        if len(value) > 1:
            for v in value:
                if ',' in v:
                    logging.warning(
                        f"--{verb}-{attr} given more than once keeps the comma in "
                        f"{shlex.quote(v)}, giving one {COMMA_LIST_ATTRS[attr]} "
                        f"containing a comma; give all of them in one --{verb}-{attr}")
        return
    plural = _comma_list_canonical(attr)
    for v in value:
        if ',' in v:
            logging.warning(
                f"--{verb}-{attr}={shlex.quote(v)} gives one {attr} containing a comma; "
                f"use --{verb}-{plural}={shlex.quote(v)} for several")

def _process_add_args(kwargs):
    """Pop the --add-<attr> options out of kwargs and return a list of
    ``(canonical_property, tokens)`` pairs to append.  Only comma-list
    properties (categories, resources) have add-options; the plural form splits
    on comma, the singular form keeps the comma literal."""
    ret = []
    for key in [k for k in kwargs if k.startswith('add_')]:
        value = kwargs.pop(key)
        attr = key[4:]
        if not value or not _is_comma_list_attr(attr):
            continue
        _warn_comma_literal('add', attr, value)
        ret.append((_comma_list_canonical(attr), _comma_list_tokens(attr, value)))
    return ret

def _process_set_args(ctx, kwargs, keep_category=False):
    ctx.obj['set_args'] = {}
    for x in kwargs:
        if kwargs[x] is None or kwargs[x]==():
            continue
        if not x.startswith('set_'):
            continue
        _warn_comma_literal('set', x[4:], kwargs[x])
        ctx.obj['set_args'].update(_process_set_arg(x[4:], kwargs[x], keep_category=keep_category))
    if 'summary' in kwargs:
        ctx.obj['set_args']['summary'] = ctx.obj['set_args'].get('summary', '') + kwargs['summary']
    if 'ical_fragment' in kwargs:
        ctx.obj['set_args']['ics'] = kwargs['ical_fragment']

def _alarm_args(set_args, summary, related_end=False, anchored=False):
    """
    Turns the value of --set-alarm into the alarm_* arguments of caldav's
    save_todo/save_event.  A duration (a number without a unit is minutes)
    means that long before DTSTART - or before DUE when related_end is
    set - and with a "+" that long after, as in an iCalendar TRIGGER.
    Anything else is a timestamp.
    """
    alarm = set_args.pop('alarm', None)
    if not alarm:
        return {}
    alarm = alarm.strip()
    ## a number without a unit is minutes, as in most calendar software
    unitless = re.fullmatch(r'[+-]?\d+(\.\d+)?', alarm)
    duration = alarm + 'm' if unitless else alarm
    if re.fullmatch(r'[+-]?[\d.]+[a-z]*', duration):
        try:
            delta = parse_add_dur(None, duration.lstrip('+-'))
        except ValueError as e:
            _abort(f"--set-alarm={alarm}: {e}")
        if unitless and datetime.timedelta(0) < delta < datetime.timedelta(minutes=1):
            logging.warning(
                f"--set-alarm={alarm} is {delta.total_seconds():g} seconds: a number "
                f"without a unit is minutes (for a fraction of an hour, use e.g. 0.25h)")
        if not alarm.startswith('+'):
            delta = -delta
        if not ({'due', 'dtstart'} & set(set_args)) and not anchored:
            _abort(f"--set-alarm={alarm} is relative to DTSTART or DUE, but neither is given")
        trigger = icalendar.vDDDTypes(delta)
        if related_end:
            trigger.params['RELATED'] = 'END'
    else:
        try:
            when = parse_dt(alarm, return_type=datetime.datetime)
        except ValueError:
            _abort(f"--set-alarm={alarm}: neither a duration (like 10m) nor a timestamp")
        trigger = icalendar.vDDDTypes(when.astimezone(datetime.timezone.utc))
        trigger.params['VALUE'] = 'DATE-TIME'
    return {'alarm_trigger': trigger, 'alarm_action': 'DISPLAY', 'alarm_description': summary}

def _add_todo(ctx, **kwargs):
    """
    Creates a new task with given SUMMARY

    Examples:

    plann add todo "fix all known bugs in plann"
    plann add todo --set-due=2050-12-10 "release plann version 42.0.0"
    """
    if 'status' not in kwargs:
        kwargs['status'] = 'NEEDS-ACTION'
    kwargs['summary'] = " ".join(kwargs['summary'])
    _process_set_args(ctx, kwargs)
    if not ctx.obj['set_args']['summary']:
        _abort("denying to add a TODO with no summary given")
        return

    ## If we just pass duration, we risk to set both due and duration on the object,
    ## which is not allowed according to the rfc
    duration = None
    if ctx.obj['set_args'].get('duration'):
        duration = ctx.obj['set_args'].pop('duration')
    alarm = _alarm_args(ctx.obj['set_args'], ctx.obj['set_args']['summary'],
                        related_end='due' in ctx.obj['set_args'] or duration is not None)

    for cal in ctx.obj['calendars']:
        todo = cal.save_todo(ical=ctx.obj.get('ical_fragment', ""), **ctx.obj['set_args'], **alarm, no_overwrite=True)
        if duration:
            todo.set_duration(duration)
            todo.save()
        click.echo(f"uid={todo.id}")
    return todo

def _add_journal(ctx, **kwargs):
    kwargs['summary'] = " ".join(kwargs['summary'])
    _process_set_args(ctx, kwargs)
    if not ctx.obj['set_args']['summary']:
        _abort("denying to add a JOURNAL with no summary given")
        return
    for cal in ctx.obj['calendars']:
        journal = cal.save_journal(ical=ctx.obj.get('ical_fragment', ""), **ctx.obj['set_args'], no_overwrite=True)
        click.echo(f"uid={journal.id}")
    return journal

def _add_event(ctx, timespec, **kwargs):
    _process_set_args(ctx, kwargs)
    alarm = _alarm_args(ctx.obj['set_args'], ctx.obj['set_args'].get('summary', kwargs.get('summary')), anchored=True)
    for cal in ctx.obj['calendars']:
        (dtstart, dtend) = parse_timespec(timespec, for_storage=True)
        event = cal.save_event(ical=ctx.obj.get('ical_fragment', ""), dtstart=dtstart, dtend=dtend, **ctx.obj['set_args'], **alarm, no_overwrite=True)
        click.echo(f"uid={event.id}")
    return event

def _agenda(ctx):
    start = datetime.datetime.now()
    _select(ctx=ctx, start=start, event=True, end='+7d', limit=16, sort_key=['{DTSTART:%F %H:%M:%S}', 'get_duration()'])
    objs = ctx.obj['objs']
    _select(ctx=ctx, todo=True, end='+7d', limit=16, sort_key=['{DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}', '{PRIORITY:?0?}'], skip_parents=True)
    ctx.obj['objs'] = objs + ["======"] + ctx.obj['objs']
    return _list(ctx.obj['objs'])

def _check_due(ctx, limit=16, lookahead='24h'):
    end_ = parse_add_dur(datetime.datetime.now(), lookahead)
    _select(ctx=ctx, todo=True, end=end_, sort_key=['{PRIORITY:?0?} {DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}'])
    def is_due(obj):
        ## client side filtering in case the server returns too much
        ## TODO: should be moved to the caldav library
        comp = obj.icalendar_component
        dtstart = _ensure_ts(comp.get('dtstart') or comp.get('due'))
        return dtstart.strftime("%F%H%M") <= end_.strftime("%F%H%M")
    objs = [obj for obj in ctx.obj['objs'] if is_due(obj)]
    if limit is not None and len(objs) > limit:
        click.echo(f"{len(objs)} tasks are due, only the first {limit} are shown here.  "
                   "Consider postponing many at once with `plann interactive dismiss-panic`.")
        objs = objs[:limit]
    for obj in objs:
        _interactive_edit(obj)

def _pinned_task_parents(event):
    """the open tasks an event pins to the calendar"""
    return [x for x in _relships_by_type(event, 'PARENT').get('PARENT', [])
            if isinstance(x, caldav.Todo) and x.icalendar_component.get('STATUS', 'NEEDS-ACTION') == 'NEEDS-ACTION']

## errors that should not stop the questions about the remaining events
_save_errors = (ETagMismatchError, ScheduleTagMismatchError, PutError, NotFoundError)

def _set_event_status(event, status):
    event.icalendar_component['STATUS'] = status
    event.save()

def _cancel_other_pins(task, event):
    """offer to cancel the other events pinning a completed task to the
    calendar - unless they also pin some task that is still open"""
    if task.icalendar_component.get('RRULE'):
        ## the next recurrence is still to be done
        return
    pins = [x for x in _relships_by_type(task, 'CHILD').get('CHILD', [])
            if isinstance(x, caldav.Event)
            and x.icalendar_component.get('STATUS', '') not in ('CANCELLED', 'CONFIRMED')
            and x.icalendar_component['UID'] != event.icalendar_component['UID']
            and not _pinned_task_parents(x)]
    if pins and click.confirm(f"Cancel {len(pins)} other pinned event(s) for '{_summary(task)}'?"):
        for pin in pins:
            try:
                _set_event_status(pin, 'CANCELLED')
            except _save_errors as e:
                click.echo(f"Could not cancel '{_summary(pin)}': {e}")

def _check_pinned(ctx, lookback='7d'):
    """Go through past events pinning a task to the calendar, and ask
    if the task was done.  A done task is completed, the event is
    marked as CONFIRMED.  If the task wasn't done, the event is
    cancelled.
    """
    now = _now()
    _select(ctx=ctx, event=True, start=now-parse_add_dur(None, lookback), end=now, pinned_tasks=True)
    ## sorted on the timestamps, events may be stored in different timezones
    for event in sorted(ctx.obj['objs'], key=lambda x: _ensure_ts(x.icalendar_component.get('DTSTART'))):
        comp = event.icalendar_component
        if comp.get('STATUS', '') == 'CONFIRMED':
            ## already dealt with
            continue
        dtstart = _ensure_ts(comp.get('DTSTART')).astimezone(tz.implicit_timezone)
        dtend = _ensure_ts(comp.get('DTEND')).astimezone(tz.implicit_timezone) if comp.get('DTEND') else dtstart + event.get_duration()
        if dtend > now:
            ## still ongoing
            continue
        tasks = _pinned_task_parents(event)
        if not tasks:
            ## e.g. completed when answering for an earlier pin
            continue
        end_format = '%H:%M' if dtend.date() == dtstart.date() else '%F %H:%M'
        click.echo(f"{dtstart:%F %H:%M} - {dtend:{end_format}}: {_summary(event)}")
        edited = []
        while True:
            answer = click.prompt("Was it done? y(es) / n(o) / p(artially) / e(dit task) / s(kip)", default='s')[:1].lower()
            if answer == 'e':
                for task in tasks:
                    _interactive_edit(task)
                edited.extend(tasks)
                tasks = _pinned_task_parents(event)
                if not tasks:
                    break
                continue
            break
        try:
            if answer == 'e':
                ## every task was closed in the edit
                done = any(x.icalendar_component.get('STATUS') == 'COMPLETED' for x in edited)
                _set_event_status(event, 'CONFIRMED' if done else 'CANCELLED')
            elif answer == 'y':
                ## one cache for all, so a subtask pinned along with its parent is completed once
                cache = _RelativeCache()
                cache.add_objects(tasks)
                completed = set()
                for task in tasks:
                    _complete(task, err_callback=click.echo, cache=cache, _seen=completed)
                ## before confirming the event: if that fails, the event
                ## is not asked about again, as the task is done
                for task in tasks:
                    _cancel_other_pins(task, event)
                _set_event_status(event, 'CONFIRMED')
            elif answer == 'n':
                _set_event_status(event, 'CANCELLED')
            elif answer == 'p':
                split = [interactive_split_task(task, partially_complete=True, too_big=False) for task in tasks]
                if any(split):
                    _set_event_status(event, 'CONFIRMED')
        except _save_errors as e:
            ## i.e. 423 Locked from a busy server - don't abort the rest of the list
            click.echo(f"Could not save the changes for '{_summary(event)}': {e}")

def _dismiss_panic(ctx, hours_per_day, lookahead='60d'):
    ## TODO: fetch both events and tasks
    lookahead=f"+{lookahead}"
    _select(ctx=ctx, todo=True, end=lookahead)
    timeline = _check_for_panic(ctx=ctx, output=False, hours_per_day=hours_per_day, timeline_end=lookahead, include_all_events=True)

    if not timeline or _ensure_ts(timeline[0]['begin'])>_now():
        click.echo("No need to panic :-)")
        return

    ## a task may be postponed through its child before its own turn
    postponed = set()
    for priority in range(9,0,-1):
        first_low_pri_tasks = []
        other_low_pri_tasks = []
        lpt = first_low_pri_tasks
        for item in timeline:
            if isinstance(item.get('obj', ''), str):
                continue
            if _ensure_ts(item['begin'])>_now():
                if not lpt:
                    break
                lpt = other_low_pri_tasks
            if item['obj'].icalendar_component.get('priority', 0) != priority:
                continue
            lpt.append(item)
        if not first_low_pri_tasks:
            continue

        click.echo(f"Tasks that needs to be postponed (priority={priority}):")
        for item in first_low_pri_tasks:
            obj = item['obj']
            comp = obj.icalendar_component
            summary = _summary(comp)
            due = obj.get_due()
            _ensure_ts(comp.get('dtstart') or comp.get('due'))
            click.echo(f"Should have started: {item['begin']:%F %H:%M:%S %Z} - Due: {due:%F %H:%M:%S %Z}: {summary}")

        if priority == 1:
            _abort("PANIC!  Those are all high-priority tasks and cannot be postponed!")

        if priority == 2:
            _abort("PANIC!  Those tasks cannot be postponed.  Maybe you want to cancel some of them?  (interactive cancelling not supported yet)")

        procrastination_time = (_now()-_ensure_ts(first_low_pri_tasks[0]['begin']))/2
        if procrastination_time.days:
            procrastination_time = f"{procrastination_time.days+1}d"
        else:
            procrastination_time = f"{procrastination_time.seconds//3600+1}h"
        default_procrastination_time = procrastination_time
        procrastination_time = click.prompt("Push the due-date with ... (press O for one-by-one, E for edit all, P for reprioritize)", default=procrastination_time)
        if procrastination_time == 'O':
            for item in first_low_pri_tasks:
                _interactive_edit(item['obj'])
        elif procrastination_time == 'P':
            _mass_reprioritize([x['obj'] for x in first_low_pri_tasks])
            ## TODO: after reprioritation, the whole algorithm needs to be restarted
        elif procrastination_time == 'E':
            ## TODO: since tasks with different priority may be affected, it's needed to restart the algorithm
            _mass_interactive_edit([x['obj'] for x in first_low_pri_tasks], default=f"postpone {default_procrastination_time}")
        else:
            _procrastinate([x['obj'] for x in first_low_pri_tasks], procrastination_time,  check_dependent='interactive', err_callback=click.echo, confirm_callback=click.confirm, postponed=postponed)

        if other_low_pri_tasks:
            click.echo(f"There are {len(other_low_pri_tasks)} later pri>={priority} tasks selected which should maybe be considered to be postponed a bit as well")
            procrastination_time = click.prompt("Push the due-date for those with ...", default='0h')
            if procrastination_time not in ('0', '0h', '0m', '0d', 0):
                _procrastinate([x['obj'] for x in other_low_pri_tasks], procrastination_time, check_dependent='interactive', err_callback=click.echo, confirm_callback=click.confirm, postponed=postponed)

def _split_huge_tasks(ctx, threshold='4h', max_lookahead='60d', limit_lookahead=640):
    _select(ctx=ctx, todo=True, end=f"+{max_lookahead}", limit=limit_lookahead, sort_key=['{DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}', '{PRIORITY:?0?}'])
    objs = ctx.obj['objs']
    threshold = parse_add_dur(None, threshold)
    for obj in objs:
        if obj.get_duration() > threshold:
            interactive_split_task(obj)

def _split_high_pri_tasks(ctx, threshold=2, max_lookahead='60d', limit_lookahead=640):
    _select(ctx=ctx, todo=True, end=f"+{max_lookahead}", limit=limit_lookahead, sort_key=['{DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}', '{PRIORITY:?0?}'])
    objs = ctx.obj['objs']
    for obj in objs:
        if obj.icalendar_component.get('PRIORITY') and obj.icalendar_component.get('PRIORITY') <= threshold:
            ## TODO: get_relatives refactoring
            relations = obj.get_relatives(fetch_objects=False)
            if 'CHILD' not in relations:
                interactive_split_task(obj, too_big=False)

def _set_task_attribs(ctx):
    """
    actual implementation of set_task_attribs
    """
    LIMIT = 16

    ## Fetch the pending todos once, then filter client-side per attribute -
    ## rather than issuing a fresh server select for each attribute (E4).
    _select(ctx=ctx, todo=True, sort_key=['{DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}', '{PRIORITY:?0?}'])
    todos = list(ctx.obj['objs'])
    ## completing a task completes its children - make them resolve to the
    ## objects in todos, so a stale copy is neither prompted for nor saved
    complete_cache = _RelativeCache()
    complete_cache.add_objects(todos)
    completed = set()

    def _set_something_(something, help_text, help_url=None, default=None, objs=None):
        something_ = _comma_list_canonical(something) if _is_comma_list_attr(something) else something
        if something == 'duration':
            something_ = 'dtstart'
        objs_ = _todos_missing(todos, something_)

        ## add all non-duplicated objects from objs to objs_
        uids_ = {x.icalendar_component['UID'] for x in objs_}
        ## skip tasks answered "completed!" at an earlier attribute
        pending = {id(x) for x in todos}
        for obj in objs or []:
            if id(obj) in pending and obj.icalendar_component['UID'] not in uids_:
                objs_.append(obj)
        objs = objs_
        if something == 'duration':
            objs = [x for x in objs if x.icalendar_component.get('due')]

        if objs:
            capped = len(objs) > LIMIT
            objs = objs[:LIMIT]
            num = f"{LIMIT} or more" if capped else len(objs)
            click.echo(f"There are {num} tasks with no {something} set.")
            click.echo(help_url)
            if something == 'category':
                cats = sorted(_categories_in_use(todos))
                click.echo("List of existing categories in use (if any):")
                click.echo("\n".join(cats))
            click.echo(f"For each task, {help_text}")
            click.echo('(or enter "completed!" with bang but without quotes if the task is already done)')
            for obj in objs:
                if str(obj.icalendar_component['UID']) in completed:
                    continue
                comp = obj.icalendar_component
                summary = _summary(comp)
                value = click.prompt(summary, default=default)
                if value == 'completed!':
                    _complete(obj, err_callback=lambda msg: click.echo(msg, err=True), cache=complete_cache, _seen=completed)
                    obj.save()
                    ## todos is fetched once - drop the task and the children
                    ## completed with it, so later attributes don't prompt for them
                    todos[:] = [x for x in todos if str(x.icalendar_component['UID']) not in completed]
                    continue
                if _is_comma_list_attr(something):
                    comp.add(something_, _comma_list_tokens(something, value))
                elif something == 'due':
                    _procrastinate([obj], parse_dt(value, datetime.datetime), check_dependent='interactive', err_callback=click.echo, confirm_callback=click.confirm)
                elif something == 'duration':
                    obj.set_duration(parse_add_dur(None, value), movable_attr='DTSTART')
                else:
                    comp.add(something_, value)
                    if hasattr(comp[something], 'dt'):
                        if not comp[something].dt.tzinfo:
                            comp[something].dt = comp[something].dt.astimezone(tz.store_timezone)
                obj.save()
            click.echo()
        return objs

    ## Tasks missing categories
    _set_something_('category', "enter a comma-separated list of CATEGORIES to be added", "https://github.com/pycalendar/plann/blob/master/TASK_MANAGEMENT.md#categories-resources-concept-refid")

    ## Tasks missing a due date.  Save those objects (workaround for https://gitlab.com/davical-project/davical/-/issues/281)
    duration_missing = _set_something_('due', "enter the DUE DATE (default +2d)", default="+2d", help_url="https://github.com/pycalendar/plann/blob/master/TASK_MANAGEMENT.md#dtstart-due-duration-completion")

    _set_something_('priority', 'Enter the PRIORITY', help_url='https://github.com/pycalendar/plann/blob/master/TASK_MANAGEMENT.md#priority', default="5")

    ## Tasks missing a duration
    _set_something_('duration', """Enter the DURATION (i.e. 5h or 2d)""", help_url="https://github.com/pycalendar/plann/blob/master/TASK_MANAGEMENT.md#dtstart-due-duration-completion", objs=duration_missing)
