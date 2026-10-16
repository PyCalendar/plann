"""Collection of various utility functions moved out from cli.py

TODO: Should consider to remove the leading underscore from many of
them, document them and write up test code.

TODO: make a separate class for relations.  (perhaps in the caldav library?)

TODO: Sort all this mess.  Split out things that are interactive?
"""

import datetime
import logging
import subprocess
from collections import defaultdict

import caldav
import click  ## TODO - this should be removed, eventually
import icalendar
from caldav.config import extract_conn_params_from_section

from plann.template import Template
from plann.timespec import (
    _ensure_ts,
    _now,
    parse_add_dur,
    parse_dt,
)
from plann.timespec import (
    parse_timespec as parse_timespec,
)
from plann.timespec import (
    tz as tz,
)

## TODO: maybe find those attributes through the icalendar library? icalendar.cal.singletons, icalendar.cal.multiple, etc
attr_txt_one = ['location', 'description', 'geo', 'organizer', 'summary', 'class', 'rrule', 'status']
## NOTE: "category" (singular) looks like an odd-ball next to the plural
## "resources", but it is intentional: in a *search* the singular form means a
## substring match and the plural "categories" an exact match (this distinction
## is implemented in the caldav library / icalendar-searcher).  For *editing*,
## the singular/plural pair is a comma-literal/comma-split convenience handled
## through COMMA_LIST_ATTRS below.
attr_txt_many = ['category', 'comment', 'contact', 'resources', 'parent', 'child']
attr_time = ['dtstamp', 'dtstart', 'due', 'dtend', 'duration']
attr_int = ['priority']

## RFC 5545 "comma-token list" properties: multi-valued text properties whose
## value is a comma-separated list of short tokens.  Exposed on the CLI in both
## plural (comma-split, exact) and singular (comma-literal, substring) form.
## Maps the plural canonical property name -> the singular alias.  Adding a new
## such property here is all it takes for the edit machinery to handle it.
COMMA_LIST_ATTRS = {
    'categories': 'category',
    'resources': 'resource',
}
_COMMA_LIST_SINGULARS = {singular: plural for plural, singular in COMMA_LIST_ATTRS.items()}

def _is_comma_list_attr(name):
    return name in COMMA_LIST_ATTRS or name in _COMMA_LIST_SINGULARS

def _comma_list_is_plural(name):
    return name in COMMA_LIST_ATTRS

def _comma_list_canonical(name):
    """The plural canonical property name for a comma-list attr (either form)."""
    return name if name in COMMA_LIST_ATTRS else _COMMA_LIST_SINGULARS[name]

def _comma_list_tokens(name, value):
    """Normalise a CLI/interactive value into a list of tokens.

    A bare string (interactive ``set cat=a,b``) is always split on comma.  A
    tuple/list (click ``multiple=True``) is split only for the *plural* form and
    only when a lone value contains a comma - so ``--add-category a,b`` keeps the
    literal ``a,b`` while ``--add-categories a,b`` yields ``a`` and ``b``.
    """
    if hasattr(value, 'split'):
        return value.split(',')
    value = list(value)
    if _comma_list_is_plural(name) and len(value) == 1 and ',' in value[0]:
        return value[0].split(',')
    return value

def _comma_list_existing(comp, canonical):
    """Existing tokens of a comma-list property as a plain list of strings.

    icalendar returns CATEGORIES as ``vCategory`` (``.cats``) and RESOURCES as
    ``vText``, and a property that appears more than once as a list of those.
    A RESOURCES value comes back with its commas unescaped, so ``a,b`` and
    ``a\\,b`` cannot be told apart - both are read as two resources.
    """
    if canonical not in comp:
        return []
    val = comp.pop(canonical)
    tokens = []
    for item in (val if isinstance(val, list) else [val]):
        if hasattr(item, 'cats'):
            tokens.extend(str(x) for x in item.cats)
        else:
            tokens.extend(str(item).split(','))
    return tokens

def _add_comma_list(obj, canonical, tokens):
    """Append ``tokens`` to a comma-list property (e.g. CATEGORIES, RESOURCES)."""
    comp = _icalendar_component(obj)
    existing = _comma_list_existing(comp, canonical)
    existing.extend(tokens)
    comp.add(canonical, existing)

def _set_comma_list(obj, canonical, tokens):
    """Replace a comma-list property with ``tokens``."""
    comp = _icalendar_component(obj)
    if canonical in comp:
        comp.pop(canonical)
    comp.add(canonical, tokens)

def _split_vcal(ical):
    """
    This method will take an ical string containing one VCALENDAR with multiple calendar resource objects and split it into one VCALENDAR per calendar resource object.
    """
    ical_cal = icalendar.Calendar.from_ical(ical)
    split_by_uid = {}

    ## TODO: ical_cal.copy() gives an empty calendar without
    ## subcomponents.  Bug or feature?  If this behaviour changes,
    ## this needs rewriting.
    ical_cal_stripped = ical_cal.copy()

    for subcomponent in ical_cal.subcomponents:
        if isinstance(subcomponent, icalendar.Timezone):
            ical_cal_stripped.add_component(subcomponent)

    for subcomponent in ical_cal.subcomponents:
        if not isinstance(subcomponent, icalendar.Timezone):
            uid = subcomponent['UID']
            if uid not in split_by_uid:
                split_by_uid[uid] = ical_cal_stripped.copy()
                ## TODO: depends on the copy issue mentioned above
                for tz in ical_cal_stripped.subcomponents:
                    split_by_uid[uid].add_component(tz)
            split_by_uid[uid].add_component(subcomponent)

    ## Return ical strings, like _split_vcals does - the callers hand the
    ## result on to _caldav_objclass()/add_object(), which parse text.
    return [cal.to_ical().decode() for cal in split_by_uid.values()]

def _split_vcals(ical):
    """
    This method will take a string with multiple VCALENDAR entries and
    split it into a list (one ical string per VCALENDAR).

    Delegates the parsing to icalendar (which understands CRLF line endings
    and line folding) rather than scanning the raw string by hand.
    """
    return [cal.to_ical().decode() for cal in icalendar.Calendar.from_ical(ical, multiple=True)]

def _warn_orphaned_overrides(ical):
    """Warn about UIDs in the ical data that hold only RECURRENCE-ID overrides
    and no master event - typically left behind when the recurring event was
    deleted without cleaning up its overrides - or simply what you get when
    one instance of a series is exported on its own.  Meant for the import
    path (`add ical`); a UID is judged across the whole data, so a master in
    one VCALENDAR covers an override in another.  What the server ends up
    with is caldav's call: it merges an override into the master when the
    server has one."""
    by_uid = {}
    for cal in icalendar.Calendar.from_ical(ical, multiple=True):
        for comp in cal.subcomponents:
            if not isinstance(comp, icalendar.Timezone):
                by_uid.setdefault(comp.get('UID'), []).append(comp)
    for uid, components in by_uid.items():
        if all('RECURRENCE-ID' in x for x in components):
            logging.warning(
                "UID %s holds RECURRENCE-ID override(s) and no master event: %s. "
                "The caldav library merges them into the series if the server has the "
                "master, otherwise they are stored as detached occurrence(s).",
                uid, [str(x.get('SUMMARY', '(no summary)')) for x in components])

def find_calendars(args, raise_errors):
    """
    Find calendars from a dict of connection parameters - typically a config
    file section or the command line arguments.  The connection keys are
    caldav_-prefixed (caldav_url, caldav_user, caldav_pass, ...), optionally
    accompanied by `features` and the calendar_url/calendar_name filters.

    Connection parameter extraction (including resolving the URL from a
    `features` server profile when no caldav_url is given) and the calendar
    lookup itself are delegated to the caldav library.
    """
    conn_params = extract_conn_params_from_section(args)
    if not conn_params:
        return []
    calendars = caldav.get_calendars(
        check_config_file=False,
        environment=False,
        raise_errors=raise_errors,
        calendar_url=args.get('calendar_url'),
        calendar_name=args.get('calendar_name'),
        **conn_params,
    )
    ## Non-connection configuration (i.a. the time tracking integration,
    ## cf. add_time_tracking) is attached to the calendar objects
    for cal in calendars:
        cal.extra_config = args.get('extra_config', {})
    return calendars

def _icalendar_component(obj):
    try:
        return obj.icalendar_component
    except AttributeError:
        ## assume obj is an icalendar_component
        return obj

def _component_type(obj):
    """Return the iCalendar component name ('VEVENT', 'VTODO', 'VJOURNAL', ...)
    for a caldav object or icalendar component.

    Preferred over sniffing 'BEGIN:VEVENT' etc. in the raw .data, which also
    matches the substring inside a description/summary text body.
    """
    return _icalendar_component(obj).name

def _caldav_objclass(ical):
    """Map a single iCalendar object (raw text) to its caldav class, parsing
    it properly rather than substring-sniffing 'BEGIN:VTODO' etc. in the body.
    """
    classes = {'VTODO': caldav.Todo, 'VJOURNAL': caldav.Journal, 'VEVENT': caldav.Event}
    cal = icalendar.Calendar.from_ical(ical)
    ## a bare component without a VCALENDAR wrapper parses as that component
    for comp in (cal, *cal.subcomponents):
        if comp.name in classes:
            return classes[comp.name]
    return caldav.Event

def _add_category(obj, category):
    """Append one or more categories.

    Back-compat wrapper around the generic comma-list helper; ``category`` may
    be a comma-separated string or a list/tuple of categories.
    """
    tokens = category.split(',') if hasattr(category, 'split') else list(category)
    _add_comma_list(obj, 'categories', tokens)

def add_time_tracking_timew(obj, start=None, end=None):
    comp = _icalendar_component(obj)
    tags = ['plann-export']

    for cat in comp.categories:
        if cat:
            tags.append(f'category:{cat}')
    tags.append(f'uid:{comp["uid"]}')
    tags.append(f'summary:{_summary(obj)}')
    tags.append(f'comptype:{comp.name}')

    if start:
        start = start.strftime("%FT%H:%M")
    if end:
        end = end.strftime("%FT%H:%M")

    if start and end:
        subprocess.run(["timew", "track", start, '-', end] + tags)
    elif start:
        subprocess.run(["timew", "start", start] + tags)
    else:
        subprocess.run(["timew", "start"] + tags)

def add_time_tracking(obj, start=None, end=None):
    comp = _icalendar_component(obj)
    time_tracking = getattr(obj.parent, 'extra_config', {}).get('time_tracking')
    if time_tracking is None:
        raise NotImplementedError('Time tracking is so far not supported internally in plann, only through external tools, and only timewarrior as for now.  You have to set `time_tracking=timewarrior` in your calendar configuration')

    ## TODO: This is not tested
    if not start and comp.name == 'VEVENT':
        start = comp.start
        end = comp.end

    if isinstance(time_tracking, str):
        time_tracking = [time_tracking]
    for tt in time_tracking:
        ## TODO: this must be done in a more clever way if introducing more time tracking types
        if tt in ('timewarrior', 'Timewarrior', 'timew'):
            add_time_tracking_timew(obj, start, end)
        else:
            raise NotImplementedError('Only time tracking through taskw supported so far')

def _summary(obj):
    i = _icalendar_component(obj)
    return i.get('summary') or i.get('description') or i.get('uid')

childlike = {'CHILD', 'NEXT', 'FINISHTOSTART'}
parentlike = {'PARENT', 'FIRST', 'DEPENDS-ON', 'STARTTOFINISH'}

def _procrastinate(objs, delay, check_dependent="error", with_children=False, with_family=False, with_parent=False, err_callback=print, confirm_callback=lambda x: False, recursivity=0):
    if delay in ('0', '0s', '0m', '0h', '0d', datetime.timedelta(0)):
        ## Do nothing!
        return
    assert recursivity<16 ## TODO: better error message.  Probably we have some kind of relationship loop here.
    for x in objs:
        if not hasattr(x, 'set_due'):
            continue
        if x.icalendar_component.get('STATUS', 'NEEDS-ACTION') == 'COMPLETED':
            continue
        if x.icalendar_component.get('RELATED-TO'):
            if with_family == 'interactive':
                with_family = confirm_callback("There are relations - postpone the whole family tree?")
            if not with_family and with_parent == 'interactive' and x.get_relatives(parentlike, fetch_objects=False):
                with_parent = confirm_callback("There exists (a) parent(s) - postpone the parent?")
            if not with_family and with_children == 'interactive' and x.get_relatives(childlike, fetch_objects=False):
                with_children = confirm_callback("There exists children - postpone the children?")
        if with_family:
            ## TODO: refactor.  Make relations into a class.
            parents_ = x.get_relatives(reltypes=parentlike)
            parents = set()
            for rel_type in parents_:
                parents.update(parents_[rel_type])
            if parents:
                _procrastinate(parents, delay, check_dependent, with_children, with_family, with_parent, err_callback, confirm_callback, recursivity=recursivity+1)
                continue
            else:
                _procrastinate([x], delay, check_dependent, with_children=True, with_family=False, with_parent=False, err_callback=err_callback, confirm_callback=confirm_callback, recursivity=recursivity+1)
                continue
        if with_parent:
            parents = x.get_relatives(reltypes=parentlike)
            for rel_type in parents: ## Should only be PARENT as for now.
                _procrastinate(parents[rel_type], delay, check_dependent, with_children=True, with_family=False, with_parent=False, err_callback=err_callback, confirm_callback=confirm_callback, recursivity=recursivity+1)

        chk_parent = 'return' if check_dependent else False
        if isinstance(delay, datetime.date):
            new_due = delay
        else:
            old_due = _ensure_ts(x.get_due())
            new_due = _now()
            if old_due:
                new_due = max(new_due, old_due)
            new_due = parse_add_dur(new_due, delay, ts_allowed=True, for_storage=True)
            ## Let's force the due to be a timestamp
            if not isinstance(new_due, datetime.datetime):
                new_due = datetime.datetime(new_due.year, new_due.month, new_due.day)
        parent = x.set_due(new_due, move_dtstart=True, check_dependent=chk_parent)
        if parent:
            if check_dependent in ("error", "interactive"):
                i = x.icalendar_component
                summary = _summary(i)
                p = parent.icalendar_component
                if p.get('STATUS') == 'COMPLETED':
                    _procrastinate([x], new_due, check_dependent=False, err_callback=err_callback, confirm_callback=confirm_callback, recursivity=recursivity+1)
                else:
                    p_postponable = check_dependent == "interactive" and p.get('priority', 9)>2
                    p_auto_postponable = p_postponable and i.get('priority',0) <= p.get('priority', 0)
                    if p_auto_postponable:
                        err_callback(f"{summary} will be postponed together with parent {_summary(p)} with due {_ensure_ts(p['DUE'])} and priority {p.get('priority', 0)}")
                    else:
                        err_callback(f"{summary} could not be postponed due to parent {_summary(p)} with due {_ensure_ts(p['DUE'])} and priority {p.get('priority', 0)}")
                    if p_postponable and (p_auto_postponable or confirm_callback("procrastinate parent?")):
                        _procrastinate([parent], new_due+max(parent.get_duration()+x.get_duration()+datetime.timedelta(minutes=1), datetime.timedelta(minutes=1)), check_dependent=check_dependent, err_callback=err_callback, confirm_callback=confirm_callback, recursivity=recursivity+1)
                        _procrastinate([x], new_due, check_dependent=check_dependent, err_callback=err_callback, confirm_callback=confirm_callback, recursivity=recursivity+1)
            elif check_dependent == "return":
                return parent
        else:
            x.save()
        if with_children:
            ## TODO: refactor.  Make relations into a class.
            children_ = x.get_relatives(reltypes=childlike)
            children = set()
            for rel_type in children_:
                children.update(children_[rel_type])
            _procrastinate(children, delay, check_dependent, with_children=True, with_family=False, with_parent=False, err_callback=err_callback, confirm_callback=confirm_callback, recursivity=recursivity+1)

def _adjust_ical_relations(obj, relations_wanted={}):
    """
    obj is an event/task/journal object from caldav library or icalendar library.
    relations_wanted is a dict with RELTYPE as key and list or set of UUIDs as value.
    reltypes in OBJ that does not exist in RELATIONS_WANTED will be ignored.
    TODO: NOT SUPPORTED YET:
    If {'childlike'=>[]} or {'parentlike'=>[]} is in the dict, then:
      1) All "parentlike" or "childlike" relations not in relations_wanted will be wiped
      2) The original RELTYPE will be kept if ... TODO: we need another parameter for this

    Does not save the object.  Does not consider reverse relations, that's up to the caller.
    """
    rels = obj.get_relatives(fetch_objects=False)
    iobj = _icalendar_component(obj)
    mutated = defaultdict(dict)
    for rel_type in relations_wanted:
        if rel_type not in rels and relations_wanted[rel_type]:
            mutated['added'][rel_type] = set(rels[rel_type])
        if set(rels[rel_type]) != set(relations_wanted[rel_type]):
            mutated['removed'][rel_type] = set(rels[rel_type]) - set(relations_wanted[rel_type])
            mutated['added'][rel_type] = set(relations_wanted[rel_type]) - set(rels[rel_type])
        rels[rel_type] = relations_wanted[rel_type]
    if not mutated:
        return {}

    if 'RELATED-TO' in iobj:
        iobj.pop('RELATED-TO')

    for rel_type in rels:
        for uid in rels[rel_type]:
            iobj.add('RELATED-TO', uid, parameters={'RELTYPE': rel_type})

    return mutated

def _remove_reverse_relations(obj, removed_rels):
    """
    obj is an object that may have "lost" some relations,
    removed_rels is the relation-dict of "lost" relations,
    and this function will ensure the objects does not link back here.
    """
    for reltype in removed_rels:
        for uid in removed_rels[reltype]:
            rev_obj = obj.parent.object_by_uid(uid)
            rels = rev_obj.get_relatives(fetch_objects=False)
            backreltypes = rels.keys()
            ## TODO: should only consider the reverse relationship - check reltype attribute
            for backreltype in backreltypes:
                rels[backreltype] = rels[backreltype] - {str(obj.icalendar_component['UID'])}
            _adjust_ical_relations(rev_obj, rels)
            rev_obj.save()

## TODO: consolidate with similar code in the caldav library
def _adjust_relations(parent, children):
    """
    * Only classic parent/child-relations covered so far
    * Only one-parent-per-child covered so far
    * All relations should be bidirectional
    * siblings are not supported
    """
    if not parent:
        for child in children:
            old_parents = child.get_relatives('PARENT', fetch_objects=False)
            if len(old_parents['PARENT']) == 1:
                _remove_reverse_relations(child, old_parents)
                _adjust_ical_relations(child, {'PARENT': set()})
                child.save()
        return
    pmutated = _adjust_ical_relations(parent, {'CHILD': {str(x.icalendar_component['UID']) for x in children}})
    for child in children:
        cmutated = _adjust_ical_relations(child, {'PARENT': {str(parent.icalendar_component['UID'])}})
        if cmutated:
            _remove_reverse_relations(child, cmutated['removed'])
            child.save()
    if pmutated:
        parent.save()
        _remove_reverse_relations(parent, pmutated['removed'])

class _RelativeCache:
    """Per-traversal cache for relationship listing.

    A hierarchical ``list --top-down`` walks the parent/child graph and would
    otherwise re-fetch the same task from the server once per edge (a parent
    is fetched again for every child, and again on every recursion step):
    ~N×R round-trips for N tasks with R relations each (code review E3).

    This caches both the object-by-UID lookups and the per-object relationship
    scan, so each task is fetched - and its consistency-checked - at most once
    for the whole traversal.
    """
    def __init__(self):
        self._objects = {}
        self._relships = {}

    def add_objects(self, objs):
        """Seed the cache with objects already in memory, so relatives
        resolve to those very objects rather than to fresh copies"""
        for obj in objs:
            self._objects[(getattr(obj.parent, 'url', None), str(obj.icalendar_component['UID']))] = obj

    def get_object(self, calendar, uid):
        key = (getattr(calendar, 'url', None), str(uid))
        if key not in self._objects:
            self._objects[key] = calendar.get_object_by_uid(uid)
        return self._objects[key]

    def cached_relships(self, obj, reltype_wanted):
        return self._relships.get((str(obj.icalendar_component['UID']), reltype_wanted))

    def store_relships(self, obj, reltype_wanted, relships):
        self._relships[(str(obj.icalendar_component['UID']), reltype_wanted)] = relships

## TODO: As for now, this one will throw the user into the python debugger if inconsistencies are found.
## It for sure cannot be like that when releasing plann 1.0!
def _relships_by_type(obj, reltype_wanted=None, cache=None):
    if cache is None:
        cache = _RelativeCache()
    cached = cache.cached_relships(obj, reltype_wanted)
    if cached is not None:
        return cached

    backreltypes = {'CHILD': 'PARENT', 'PARENT': 'CHILD', 'undefined': 'CHILD', 'SIBLING': 'SIBLING'}
    ## Parse the related UIDs straight from obj's ical (no network) and resolve
    ## each one through the cache, rather than letting caldav fetch them anew.
    rels_by_type = obj.get_relatives(reltype_wanted, fetch_objects=False)
    ret = defaultdict(list)
    for reltype in rels_by_type:
        for other_uid in rels_by_type[reltype]:
            try:
                other = cache.get_object(obj.parent, other_uid)
            except caldav.error.NotFoundError:
                ## a dangling relation - mirrors get_relatives(ignore_missing=True)
                continue
            ret[reltype].append(other)

            ## Consistency check ... TODO ... look more into breakages
            ## TODO: make functionality for scanning through all relationships in the calendar
            other_rels = other.get_relatives(fetch_objects=False)
            back_rel_types = set()
            for back_rel_type in other_rels:
                if str(obj.icalendar_component['UID']) in other_rels[back_rel_type]:
                    back_rel_types.add(back_rel_type)

            if len(back_rel_types) > 1:
                logging.error(f"Inconsistency issue in relationships - has to be manually resolved (UID={obj.icalendar_component['UID']}, backrels: {back_rel_types})")
                ## Inconsistency has to be manually fixed: more than one related-to property pointing from other to obj
            if len(back_rel_types) == 0:
                logging.error("Inconsistency issue in relationships - will be automatically fixed: no related-to property pointing from other to obj")
                ## adding the missing back rel
                other.icalendar_component.add('RELATED-TO', str(obj.icalendar_component['UID']), parameters={'RELTYPE': backreltypes[reltype]})
                other.save()
            else:
                if back_rel_types != { backreltypes[reltype] }:
                    logging.error("Inconsistency issue in relationships - has to be manually resolved. Object and other points to each other, but reltype does not match")
    cache.store_relships(obj, reltype_wanted, ret)
    return ret

def _complete(obj, handle_rrule=True, rrule_mode='safe', err_callback=print, cache=None, _seen=None):
    """Mark obj as completed.

    A child has to be done before the parent can be completed, so
    completing a parent means the pending children (and grandchildren)
    are done as well - they get auto-completed first, with a warning for
    each.  Recurring children are handled the same way as obj.

    When completing several objects, pass the same cache (seeded with
    the objects) and the same _seen set to every call, so that an object
    that is also a child of another one is completed exactly once.
    """
    if cache is None:
        cache = _RelativeCache()
    if _seen is None:
        _seen = set()
    uid = str(obj.icalendar_component['UID'])
    if uid in _seen:
        return
    _seen.add(uid)
    for child in _relships_by_type(obj, 'CHILD', cache=cache).get('CHILD', []):
        if str(child.icalendar_component['UID']) in _seen or not child.is_pending():
            continue
        err_callback(f"Completing child task '{_summary(child)}' of '{_summary(obj)}'")
        _complete(child, handle_rrule, rrule_mode, err_callback, cache, _seen)
    if obj.is_pending():
        obj.complete(handle_rrule=handle_rrule, rrule_mode=rrule_mode)

def _relationship_text(obj, reltype_wanted=None):
    rels = obj.get_relatives(reltypes=reltype_wanted)
    if not rels:
        return "(None)"
    ret = []
    for reltype in rels:
        objs = []
        for relobj in rels[reltype]:
            objs.append(_summary(relobj))
        ret.append(reltype + "\n" + "\n".join(objs) + "\n")
    return "\n".join(ret)

## TODO - this needs to be better documented.  What's the difference between _process_set_arg and _set_something?  Do they overlap?  Are they intended to be used together?
def _process_set_arg(arg, value, keep_category=False):
    ret = {}
    if arg in attr_time and arg != 'duration':
        ret[arg] = parse_dt(value, for_storage=True)
    elif arg == 'duration':
        ret[arg] = parse_add_dur(dt=None, dur=value)
    elif arg == 'rrule':
        rrule = {}
        for split1 in value.split(';'):
            k,v = split1.split('=')
            rrule[k] = v
        ret[arg] = rrule
    elif _is_comma_list_attr(arg):
        value = _comma_list_tokens(arg, value)
        ## Without keep_category the singular alias is canonicalised to its
        ## plural (replace) form - used by the create path, which forwards
        ## set_args straight to caldav's save_todo(categories=...) etc.
        if not keep_category and not _comma_list_is_plural(arg):
            arg = _comma_list_canonical(arg)
        ret[arg] = value
    else:
        ret[arg] = value
    return ret

def _set_something(obj, arg, value):
    """
    set_something is used when editing objects.
    The arg and value is already processed through _process_set_arg
    """
    arg = arg.lower()
    comp = obj.icalendar_component
    if arg in ('child', 'parent'):
        for val in value:
            obj.set_relation(reltype=arg, other=val)
    elif arg == 'duration':
        obj.set_duration(value)
    elif arg in ('due', 'dtend'): ## TODO: dtstart!
        getattr(obj, f"set_{arg}")(value, move_dtstart=True, check_dependent=True)
    elif _is_comma_list_attr(arg):
        ## a list (already processed by _process_set_arg) or a raw comma string
        tokens = _comma_list_tokens(arg, value)
        canonical = _comma_list_canonical(arg)
        if _comma_list_is_plural(arg):
            _set_comma_list(obj, canonical, tokens)   ## plural -> replace
        else:
            _add_comma_list(obj, canonical, tokens)   ## singular -> append
    else:
        if arg in comp:
            comp.pop(arg)
        comp.add(arg, value)


## TODO: should be rewritten a bit, we should have a create_list method that does not call on click.echo directly
## let the caller decide if click is to be used or not.
## Use the yield method to avoid having to generate the full list prior to printing to screen
def _list(objs, ics=False, template="{DTSTART:?{DUE:?(date missing)?}?%F %H:%M:%S %Z}: {SUMMARY:?{DESCRIPTION:?(no summary given)?}?}", top_down=False, bottom_up=False, indent=0, echo=True, uids=None, filter=lambda obj: True, separator="\n", cache=None):
    """
    Actual implementation of list

    TODO: will crash if there are loops in the relationships
    TODO: if there are parent/child-relationships that aren't bidrectionally linked, we may get problems
    """
    if indent>32:
        raise NotImplementedError("too deep hierarchies, or circular links")
    ## one relationship cache for the whole (recursive) traversal, so the same
    ## task is not re-fetched from the server for every edge it touches (E3)
    if cache is None and (top_down or bottom_up):
        cache = _RelativeCache()
    if ics:
        accepted = [obj for obj in objs if filter(obj)]
        if not accepted:
            return
        icalendar = accepted[0].icalendar_instance
        for obj in accepted[1:]:
            icalendar.subcomponents.extend(obj.icalendar_instance.subcomponents)
        click.echo(icalendar.to_ical())
        return
    if isinstance(template, str):
        template=Template(template)
    output = []
    if uids is None:
        uids = set()

    for obj in objs:
        if isinstance(obj, str):
            output.append(obj)
            continue

        if not filter(obj):
            continue

        uid = obj.icalendar_component['UID']
        if uid in uids and 'RECURRENCE-ID' not in obj.icalendar_component:
            continue
        else:
            uids.add(uid)

        above = []
        below = []
        if top_down or bottom_up:
            relations = _relships_by_type(obj, cache=cache)
            parents = relations['PARENT']
            children = relations['CHILD']
            ## in a top-down view, the (grand)*parent should be shown as a top-level item rather than the object.
            ## in a bottom-up view, the (grand)*child should be shown as a top-level item rather than the object.
            if top_down:
                above = parents
                below = children
            if bottom_up:
                above = children
                below = parents
            if indent:
                above = []
        if not above:
            ## This should be a top-level thing
            more_info = {}
            if 'calendar_name' in template.template:
                more_info['calendar_name'] = obj.parent.get_display_name()
            more_info['calendar_url'] = obj.parent.url
            output.append(" "*indent + template.format(**obj.icalendar_component, **more_info))
            ## Recursively add children in an indented way
            output.extend(_list(below, template=template, top_down=top_down, bottom_up=bottom_up, indent=indent+2, echo=False, filter=filter, cache=cache))
            if indent and top_down:
                ## Include all siblings as same-level nodes
                ## Use the top-level uids to avoid infinite recursion
                ## TODO: siblings are probably not being handled correctly here.  Should write test code and investigate.
                output.extend(_list(relations['SIBLING'], template=template, top_down=top_down, bottom_up=bottom_up, indent=indent, echo=False, uids=uids, filter=filter, cache=cache))
        for p in above:
            ## The item should be part of a sublist.  Find and add the top-level item, and the full indented list under there - recursively.
            puid = p.icalendar_component['UID']
            if puid not in uids:
                output.extend(_list([p], template=template, top_down=top_down, bottom_up=bottom_up, indent=indent, echo=False, uids=uids, filter=filter, cache=cache))
    if echo:
        click.echo_via_pager(separator.join(output))
    return output
