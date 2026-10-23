#!/usr/bin/env python

"""https://plann.no/ - high-level cli against caldav servers.

Copyright (C) 2013-2024 Tobias Brox and other contributors.

See https://www.gnu.org/licenses/gpl-3.0.en.html for license information.

plann is a "next generation" reimplementation of calendar-cli
"""

## This file should preferably just be a thin interface between public
## python libraries (including the plann library) and the command
## line.

## TODO: there is some logic in this file that isn't strictly tied to the
## cli as such.  It should be moved out and made available through
## `from plann import ...`

import datetime
import logging
import sys

import caldav
import click

from plann.commands import (
    _add_event,
    _add_journal,
    _add_todo,
    _agenda,
    _cats,
    _check_due,
    _check_for_panic,
    _dismiss_panic,
    _edit,
    _select,
    _set_task_attribs,
    _split_high_pri_tasks,
    _split_huge_tasks,
)
from plann.config import (
    config_section,
    expand_config_section,
    interactive_config,
    read_config,
    resolve_config_file,
    writable_config_file,
)
from plann.interactive import _abort
from plann.lib import (
    COMMA_LIST_ATTRS,
    _caldav_objclass,
    _list,
    _split_vcal,
    _split_vcals,
    _summary,
    _warn_orphaned_overrides,
    attr_int,
    attr_time,
    attr_txt_many,
    attr_txt_one,
    find_calendars,
)
from plann.lib import add_time_tracking as add_time_tracking_
from plann.timespec import _now, parse_dt, tz

list_type = list

## TODO:

## should make some subclasses of click.ParamType:

## class DateOrDateTime - perhaps a subclass of click.DateTime, returns date
## if no time is given (can probably just be subclassed directly from
## click.DateTime?

## class DurationOrDateTime - perhaps a subclass of the above, should attempt
## to use pytimeparse if the given info is not a datetime.

## See https://click.palletsprojects.com/en/8.0.x/api/#click.ParamType and
## /usr/lib/*/site-packages/click/types.py on how to do this.

class _LazyCalendars:
    """A list-like wrapper that defers calendar discovery until first use.

    Discovery hits the network (one connect per configured calendar), so we
    only want to pay for it when a command actually uses the calendars - not
    when click merely runs the group callback to e.g. show subcommand help
    (code review E1).  Supports the handful of operations the commands use:
    iteration, ``len()``, indexing and truthiness.
    """
    def __init__(self, discover):
        self._discover = discover
        self._resolved = None

    @property
    def _calendars(self):
        if self._resolved is None:
            self._resolved = self._discover()
        return self._resolved

    def __iter__(self):
        return iter(self._calendars)

    def __len__(self):
        return len(self._calendars)

    def __getitem__(self, index):
        return self._calendars[index]

    def __bool__(self):
        return bool(self._calendars)

    def extend(self, more):
        self._calendars.extend(more)

@click.group()
@click.version_option(None, "--version", "-V", package_name="plann")
## TODO: interactive config building
## TODO: language
@click.option('--show-native-timezone/--show-local-timezone', help="Show timestamps as they are in the calendar (default is to convert to local timezone)")
@click.option('--implicit-timezone', help="Timestamps entered without timezone is assumed to be in this timezone (default: local/system tz)")
@click.option('--store-timezone', help="Timestamps saved to the calendar should be converted to this timezone (default: same as --implicit-timezone)")
@click.option('-c', '--config-file', help="Configuration file (default: the first that exists of ~/.config/pycal/calendar.yaml, ~/.config/caldav/calendar.conf and the other paths shared with the caldav library)")
@click.option('--skip-config/--read-config', help="Skip reading the config file")
@click.option('--config-section', default=["default"], multiple=True)
@click.option('--caldav-url', help="Full URL to the caldav server", metavar='URL')
@click.option('--caldav-username', '--caldav-user', help="Full URL to the caldav server", metavar='URL')
@click.option('--caldav-password', '--caldav-pass', help="Password for the caldav server", metavar='URL')
@click.option('--calendar-url', help="Calendar id, path or URL", metavar='cal', multiple=True)
@click.option('--calendar-name', help="Calendar name", metavar='cal', multiple=True)
@click.option('--raise-errors/--print-errors', help="Raise errors found on calendar discovery")
@click.pass_context
def cli(ctx, **kwargs):
    """
    CalDAV Command Line Interface

    https://plann.no
    """
    ## The cli function will prepare a context object, a dict containing the
    ## caldav_client, principal and calendar

    ctx.ensure_object(dict)
    ## TODO: add all relevant connection parameters for the DAVClient as options
    ## TODO: logic to read the config file and edit kwargs from config file
    ## TODO: catch errors, present nice error messages
    ## Calendar discovery talks to the network; defer it (E1) so commands that
    ## never touch the server - notably `plann <subcommand> --help` - don't
    ## connect to every configured calendar.
    ctx.obj['calendars'] = _LazyCalendars(lambda: _discover_calendars(kwargs))
    ## the discovery options, for a command that must tighten them before the
    ## (lazy) discovery happens
    ctx.obj['discovery_options'] = kwargs
    ## stashed for the `configure` subcommand (and any other command that needs
    ## to know which config file / section the user pointed at)
    ctx.obj['config_file'] = kwargs['config_file']
    ctx.obj['config_section'] = kwargs['config_section']
    ctx.obj['raise_errors'] = kwargs['raise_errors']
    for flag in ('show_native_timezone', 'store_timezone', 'implicit_timezone'):
        setattr(tz, flag, kwargs[flag])

def _discover_calendars(kwargs):
    """Find calendars from the command-line connection options and, unless
    --skip-config is given, from every selected config-file section."""
    calendars = find_calendars(kwargs, kwargs['raise_errors'])
    if not kwargs['skip_config']:
        config_file = _config_file(kwargs['config_file'])
        config = read_config(config_file)
        if config:
            for meta_section in kwargs['config_section']:
                calendars.extend(_config_calendars(config, meta_section, kwargs['raise_errors'], config_file))
    return calendars

def _config_file(given):
    """The config file to read, looked up only when it is needed, so that
    --help and --skip-config work whatever CALDAV_CONFIG_FILE says.  caldav
    checks this file before running a password_command from it."""
    try:
        return resolve_config_file(given)
    except ValueError as e:  ## CALDAV_CONFIG_FILE naming a file that is not there
        raise click.UsageError(str(e)) from e

def _config_calendars(config, meta_section, raise_errors, config_file):
    calendars = []
    for section in expand_config_section(config, meta_section):
        try:
            args = config_section(config, section)
        except ValueError as e:
            ## inherits naming a missing section, a cycle, ... - as in find_calendars
            if raise_errors:
                raise
            logging.error(f"Skipping a config section: {e}")
            continue
        calendars.extend(find_calendars(args, raise_errors=raise_errors,
                                        config_file=config_file, section_name=section))
    return calendars

def _section_calendars(ctx, meta_section):
    """Find the calendars of one config-file section, independent of the
    sections selected with --config-section.  Errors are raised."""
    config_file = _config_file(ctx.obj['config_file'])
    config = read_config(config_file)
    if not config:
        return []
    return _config_calendars(config, meta_section, raise_errors=True, config_file=config_file)

@cli.command()
@click.pass_context
def list_calendars(ctx):
    """
    Will output all calendars found
    """
    if not ctx.obj['calendars']:
        _abort("No calendars found!")
    else:
        output = "Accessible calendars found:\n"
        calendar_info = [(x.get_display_name(), x.url) for x in ctx.obj['calendars']]
        max_display_name = max([len(x[0]) for x in calendar_info])
        lines = [f"{name:<{max_display_name}} {url}" for name, url in calendar_info]
        click.echo_via_pager(output + "\n".join(lines) + "\n")

@cli.command()
@click.pass_context
def configure(ctx):
    """
    Interactive configuration mode (EXPERIMENTAL - under-tested, here be dragons).

    Prompts for connection parameters and writes them to the config file.
    """
    config_file = _config_file(ctx.obj['config_file'])
    sections = ctx.obj['config_section']
    section = sections[0] if sections else 'default'
    config = read_config(config_file, interactive_error=True) or {}
    interactive_config(config, writable_config_file(ctx.obj['config_file'], config_file), config_section=section)

def _set_attr_options_(func, verb, desc=""):
    """
    decorator that will add options --set-category, --set-description etc
    """
    if verb:
        if not desc:
            desc = verb
        verb = f"{verb}-"
    else:
        verb = ""
    if verb == 'no-':
        for foo in attr_txt_one + attr_txt_many + attr_time + attr_int:
            func = click.option(f"--{verb}{foo}/--has-{foo}", default=None, help=f"{desc} ical attribute {foo}")(func)
    elif verb == 'add-':
        ## append-options, only for the comma-list properties, in both the
        ## plural (comma-split) and singular (comma-literal) form
        for plural, singular in COMMA_LIST_ATTRS.items():
            for foo in (singular, plural):
                func = click.option(f"--{verb}{foo}", help=f"{desc} ical attribute {plural}", multiple=True)(func)
    else:
        if verb == 'set-':
            attr__one = attr_txt_one + attr_time + attr_int
        else:
            attr__one = attr_txt_one
        for foo in attr__one:
            func = click.option(f"--{verb}{foo}", help=f"{desc} ical attribute {foo}")(func)
        ## the extra 'categories' gives the plural form for the comma-list
        ## attributes (attr_txt_many carries the singular 'category' as that is
        ## the substring-search form; see lib.COMMA_LIST_ATTRS)
        singular_to_plural = {s: p for p, s in COMMA_LIST_ATTRS.items()}
        for foo in attr_txt_many + ['categories']:
            help_text = f"{desc} ical attribute {foo}"
            if verb == 'set-' and foo in singular_to_plural:
                ## e.g. --set-category: kept for backwards compatibility, but it
                ## *appends* rather than replaces, which the name does not convey
                help_text = (f"{desc} ical attribute {foo} (DEPRECATED - this appends; use "
                             f"--add-{foo} to append or --set-{singular_to_plural[foo]} to replace)")
            func = click.option(f"--{verb}{foo}", help=help_text, multiple=True)(func)
    return func

def _set_attr_options(verb="", desc=""):
    return lambda func: _set_attr_options_(func, verb, desc)

@cli.command()
@click.option('--to-section', required=True, help="Config section holding the target calendar (the first calendar found is used)")
@click.option('--summary', required=True, help="Summary of every copied event, e.g. 'event from work calendar'")
@click.option('--tag', help="Name of this sync, stored in the copies.  Copies with the tag that no longer match a busy period are deleted.  Defaults to the --config-section value(s)")
@click.option('--days', default=60, show_default=True, help="Sync from the start of today and this many days ahead")
@click.option('--hours', help="Only copy busy time within these local hours, e.g. 9-16.  All-day events become events covering these hours")
@click.option('--weekdays-only/--all-days', default=False, help="Only copy busy time on Monday to Friday")
@click.option('--dry-run/--no-dry-run', default=False, help="Report what would change without changing anything")
@click.pass_context
def freebusy_sync(ctx, to_section, summary, tag, days, hours, weekdays_only, dry_run):
    """
    Copy busy time from the selected calendars into another calendar.

    Each busy period in the calendars selected by --config-section becomes
    an event in the --to-section calendar holding only the time and
    SUMMARY.  Run it regularly: copies are moved and deleted as the
    source changes.  Example, run from a timer:

    plann --config-section work freebusy-sync --to-section default --summary 'event from work calendar'
    """
    from plann.freebusy import freebusy_sync as freebusy_sync_
    if hours:
        try:
            hours = tuple(int(x) for x in hours.split('-'))
        except ValueError:
            hours = ()
        if len(hours) != 2 or not 0 <= hours[0] < hours[1] <= 24:
            raise click.BadParameter("expected two hours within 0-24, like 9-16", param_hint='--hours')
    ## A source that fails to load must stop the run: read as "no busy time",
    ## it would delete every copy.
    ctx.obj['discovery_options']['raise_errors'] = True
    try:
        sources = list_type(ctx.obj['calendars'])
        targets = _section_calendars(ctx, to_section)
    except Exception as e:
        _abort(f"Calendar discovery failed, nothing synced: {e}")
    if not sources:
        _abort("No source calendars found, nothing synced")
    if len(targets) != 1:
        _abort(f"Config section {to_section} must resolve to exactly one calendar, found {len(targets)}.  Set calendar_url or calendar_name in it.")
    start = _now().replace(hour=0, minute=0, second=0)
    stats = freebusy_sync_(
        sources, targets[0], start=start, end=start + datetime.timedelta(days=days),
        summary=summary, tag=tag or ','.join(ctx.obj['config_section']), hours=hours,
        weekdays=range(5) if weekdays_only else None, tzinfo=tz.implicit_timezone, dry_run=dry_run)
    click.echo(("dry run, nothing changed: " if dry_run else "") + ", ".join(f"{k} {v}" for k, v in stats.items()))

@cli.group()
@click.option('--interactive/--no-interactive-select', help="line based interactive filtering")
@click.option('--mass-interactive/--no-mass-interactive-select', help="editor based interactive filtering")
@click.option('--all/--none', default=None, help='Select all (or none) of the objects.  Overrides all other selection options.')
@click.option('--uid', multiple=True, help='select an object with a given uid (or select more object with given uids).  Overrides all other selection options')
@click.option('--abort-on-missing-uid/--ignore-missing-uid', default=False, help='Abort if (one or more) uids are not found (default: carry on with whatever was found).  Only effective when used with --uid')
@click.option('--warn-on-missing-uid/--no-warn-on-missing-uid', default=True, help='Print a warning (to stderr) for uids that are not found (default: warn).  Has no effect when --abort-on-missing-uid is given.  Only effective when used with --uid')
@click.option('--todo/--no-todo', default=None, help='select only todos (or no todos)')
@click.option('--event/--no-event', default=None, help='select only events (or no events)')
@click.option('--journal/--no-journal', default=None, help='select only journal entries (or no journal entries)')
@click.option('--include-completed/--exclude-completed', default=False, help='select only todos (or no todos)')
@_set_attr_options(desc="select by")
@_set_attr_options('no', desc="select objects without")
@click.option('--start', help='do a time search, with this start timestamp')
@click.option('--begin', 'start', help='alias for start')
@click.option('--since', 'start', help='alias for start')
@click.option('--from', 'start', help='alias for start')
@click.option('--end', help='do a time search, with this end timestamp (or duration)')
@click.option('--to', 'end', help='alias for end')
@click.option('--until', 'end', help='alias for end')
@click.option('--timespan', help='do a time search for this interval')
@click.option('--sort-key', help='use this attributes for sorting.  Templating can be used.  Prepend with - for reverse sort.  Special: "get_duration()" yields the duration or the distance between dtend and dtstart, or an empty timedelta', default=['{DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}{PRIORITY:?0?}'],  multiple=True)
@click.option('--skip-parents/--include-parents', help="Skip parents if it's children is selected.  Useful for finding tasks that can be started if parent depends on child", default=False)
@click.option('--skip-children/--include-children', help="Skip children if it's parent is selected.  Useful for getting an overview of the big picture if children are subtasks", default=False)
@click.option('--limit', help='Number of objects to show', type=int)
@click.option('--offset', help='Skip the first objects', type=int)
@click.option('--freebusyhack', help='DEPRECATED, use the freebusy-sync command.  Removes almost everything from the ical and replaces the summary with the provided string.  Leaks the details of recurrence exceptions.')
@click.option('--pinned-tasks/--no-pinned-tasks', default=None, help='select all/no pinned tasks')
@click.pass_context
def select(*largs, **kwargs):
    """Search command, allows listing, editing, etc

    This command is intended to be used every time one is to
    select/filter/search for one or more events/tasks/journals.  It
    offers a simple templating language built on top of python
    string.format for sorting and listing.  It offers several
    subcommands for doing things on the objects found.

    The command is powerful and complex, but may also be non-trivial
    in usage - hence there are some convenience-commands built for
    allowing the common use-cases to be done in easier ways (like
    agenda and fix-tasks-interactive)
    """
    return _select(*largs, **kwargs)

@select.command()
@click.pass_context
@click.option('--startnow/--track', help="the event starts now vs track the original timespan", default=True)
def add_time_tracking(ctx, startnow):
    """
    Track time spent on events/tasks
    """
    objs = ctx.obj['objs']
    if startnow:
        start_time = _now()
    else:
        start_time = None
    if not startnow and not all(isinstance(x, caldav.Event) for x in objs):
        _abort("original timespan is only allowed for events - and you've selected tasks or journals")
    if len(objs)>1 and startnow:
        _abort("Only one event/task can be started at the time")
    if not len(objs):
        _abort("No items selected for tracking")
    for x in objs:
        add_time_tracking_(x, start_time)

@select.command()
@click.pass_context
def list_categories(ctx):
    """
    List all categories used in the selection
    """
    cats = _cats(ctx)
    for c in cats:
        click.echo(c)


list_type = list

@select.command()
@click.option('--ics/--no-ics', default=False, help="Output in ics format")
@click.option('--template', default="{DTSTART:?{DUE:?(date missing)?}?%F %H:%M:%S %Z}: {SUMMARY:?{DESCRIPTION:?(no summary given)?}?}")
@click.option('--separator', default="\n", help="String to separate the listed items with (defaults to a newline)")
@click.option('--top-down/--flat-list', help="Check relations and list the relations in a hierarchical way")
@click.option('--bottom-up/--flat-list', help="List parents (dependencies) in a hierarchical way (cannot be combined with top-down)")
@click.pass_context
def list(ctx, ics, template, separator="\n", top_down=False, bottom_up=False):
    """
    Print out a list of tasks/events/journals
    """
    return _list(ctx.obj['objs'], ics, template, top_down=top_down, bottom_up=bottom_up, separator=separator)


@select.command()
@click.pass_context
def print_uid(ctx):
    """
    Convenience command, prints UID of first item

    This can also be achieved by using select with template and limit
    """
    click.echo(ctx.obj['objs'][0].icalendar_component['UID'])

@select.command()
@click.pass_context
def print_ical(ctx):
    """
    Dumps everything selected as an ICS feed
    """
    for obj in ctx.obj['objs']:
        click.echo(obj.data)

@select.command()
@click.option('--multi-delete/--no-multi-delete', default=None, help="Delete multiple things without confirmation prompt")
@click.pass_context
def delete(ctx, multi_delete, **kwargs):
    """
    Delete the selected item(s)
    """
    objs = ctx.obj['objs']
    if not objs:
        click.echo("No items selected for deletion")
        return
    if multi_delete is None and len(objs)>1:
        multi_delete = click.confirm(f"OK to delete {len(objs)} items?")
    if len(objs)>1 and not multi_delete:
        _abort(f"Not going to delete {len(objs)} items")
    for obj in objs:
        click.echo(f"Deleting {_summary(obj)}")
        obj.delete()

## TODO: reconsider the naming of the attributes and functions - --mass-interactive should probably be --interactive-editor - and the interactive reprioritization function needs to be renamed
@select.command()
@click.option('--pdb/--no-pdb', default=None, help="Interactive edit through pdb (experts only)")
@click.option('--postpone', help="Add something to the DTSTART and DTEND/DUE")
@click.option('--postpone-with-children', help="Add something to the DTSTART and DTEND/DUE for this and children")
@click.option('--interactive-ical/--no-interactive-ical', help="Edit the ical interactively")
@click.option('--interactive-relations/--no-interactive-relations', help="Edit the relationships")
@click.option('--interactive/--no-interactive', help="Interactive edit")
@click.option('--interactive-reprioritize/--no-interactive-reprioritize', help="Interactively reprioritize tasks")
@click.option('--mass-interactive/--no-mass-interactive', help="Interactive edit through editor")
@click.option('--mass-interactive-default', default='ignore', help="default command for interactive mass-edit")
@click.option('--cancel/--uncancel', default=None, help="Mark task(s) as cancelled")
@click.option('--complete/--uncomplete', default=None, help="Mark task(s) as completed")
@click.option('--complete-recurrence-mode', default='safe', help="Completion of recurrent tasks, mode to use - can be 'safe', 'thisandfuture' or '' (see caldav library for details)")
@_set_attr_options(verb='set')
@_set_attr_options(verb='add', desc='append to')
@click.pass_context
def edit(*largs, **kwargs):
    """
    Edits a task/event/journal
    """
    return _edit(*largs, **kwargs)

@select.command()
@click.pass_context
@click.option('--recurrence-mode', default='safe', help="Completion of recurrent tasks, mode to use - can be 'safe', 'thisandfuture' or '' (see caldav library for details)")
def complete(ctx, **kwargs):
    """
    Convenience command, mark tasks as completed

    The same result can be obtained by running this subcommand:

      `edit --complete`
    """
    return _edit(ctx, complete=True, **kwargs)

@select.command()
@click.option('--hours-per-day', help='how many hours per day you expect to be able to dedicate to those tasks/events', default=4)
#@click.option('--limit', help='break after finding this many "panic"-items', default=4096)
@click.option('--timeline-start', help='Timeline starting point (default=now)')
@click.option('--timeline-end', help='Timeline ending point (default=in 1 year)')
@click.option('--include-all-events/--no-extra-events', help='Include all events (and selected tasks)')
@click.option('--print-timeline/--no-print-timeline', help='Print a possible timeline')
@click.option('--fix-timeline/--no-fix-timeline', help='Make events from the tasks and pin them to the calendar')
@click.option('--interactive-fix-timeline/--no-interactive-fix-timeline', help='Make a suggested editable time table')
@click.pass_context
def check_for_panic(ctx, **kwargs):
    """Check if we need to panic

    Assuming we can spend a limited time per day on those tasks
    (because one also needs to sleep and do other things that are not
    included in the calendar, or maybe some tasks can only be done
    while the sun is shining), all tasks/events are processed in order
    (assumed to be ordered by DTSTART).  The algorithm is supposed to
    find if there are tasks that cannot be accomplished before the
    DUE.  In that case, one should either PANIC or move the DUE.

    Eventually it will report the total amount of slack found (time we
    can slack off and still catch all the deadlines) as well as the
    minimum slack (how long one may snooze before starting working on
    those tasks).

    TODO: Only tasks supported so far.  It should also warn on
    overlapping events and substract time spent on events.
    """
    for x in list_type(kwargs.keys()):
        if kwargs[x] is None:
            del kwargs[x]
    return _check_for_panic(ctx, **kwargs)


@select.command()
@click.pass_context
def sum_hours(ctx, **kwargs):
    raise NotImplementedError()

## TODO: all combinations of --first-calendar, --no-first-calendar, --multi-add, --no-multi-add should be tested
@cli.group()
@click.option('-l', '--add-ical-line', multiple=True, help="extra ical data to be injected")
@click.option('--multi-add/--no-multi-add', default=None, help="Add things to multiple calendars")
@click.option('--first-calendar/--no-first-calendar', default=None, help="Add things only to the first calendar found")
@click.pass_context
def add(ctx, **kwargs):
    """
    Save new objects on calendar(s)
    """
    if len(ctx.obj['calendars'])>1 and kwargs['multi_add'] is False:
        _abort("Giving up: Multiple calendars given, but --no-multi-add is given")
    ## TODO: crazy-long if-conditions can be refactored - see delete on how it's done there
    if (kwargs['first_calendar'] or
        (len(ctx.obj['calendars'])>1 and
         not kwargs['multi_add'] and
         not click.confirm(f"Multiple calendars given.  Do you want to duplicate to {len(ctx.obj['calendars'])} calendars? (tip: use option --multi-add or --first-calendar to avoid this prompt in the future)"))):
        calendar = ctx.obj['calendars'][0]
        ## TODO: we need to make sure f"{calendar.name}" will always work or something
        if (kwargs['first_calendar'] is not False and
            (kwargs['first_calendar'] or
            click.confirm(f"First calendar on the list has url {calendar.url} - should we add there? (tip: use --calendar-url={calendar.url} or --first-calendar to avoid this prompt in the future)"))):
            ctx.obj['calendars'] = [ calendar ]
        else:
            _abort("Giving up: Multiple calendars found/given, please specify which calendar you want to use")

    if not ctx.obj['calendars']:
        _abort("Giving up: No calendars given")

    ctx.obj['ical_fragment'] = "\n".join(kwargs['add_ical_line'])

@add.command()
@click.pass_context
@click.option('-d', '--ical-data', '--ical', help="ical object to be added")
@click.option('-f', '--ical-file', type=click.File('rb'), help="file containing ical data")
def ical(ctx, ical_data, ical_file):
    ical = ""
    if (ical_file):
        ical = ical + ical_file.read().decode()
    if (ical_data):
        ical = ical + ical_data
    if not ical:
        ical = sys.stdin.read()
    if ctx.obj['ical_fragment']:
        ical = ical.replace('\nEND:', f"{ctx.obj['ical_fragment']}\nEND:")
    if 'BEGIN:VCALENDAR' in ical:
        _warn_orphaned_overrides(ical)
        if ical.count('BEGIN:VCALENDAR') > 1:
            icals = _split_vcals(ical)
        else:
            icals = _split_vcal(ical)
    else:
        icals = [ ical ]
    for ical in icals:
        for c in ctx.obj['calendars']:
            ## TODO: there is a TODO-comment in add_object that objclass should not be mandatory.
            ## when that one has been fixed, remove this additional logic
            objclass = _caldav_objclass(ical)
            c.add_object(objclass, ical)

@add.command()
@click.argument('summary', nargs=-1)
@_set_attr_options(verb='set')
@click.pass_context
def todo(ctx, **kwargs):
    return _add_todo(ctx, **kwargs)

@add.command()
## TODO
@click.argument('summary')
@click.argument('timespec')
@_set_attr_options(verb='set')
@click.pass_context
def event(ctx, timespec, **kwargs):
    """
    Creates a new event with given SUMMARY at the time specifed through TIMESPEC.

    TIMESPEC is an ISO-formatted date or timestamp, optionally with a postfixed interval
.
    Examples:

    plann add event "final bughunting session" 2004-11-25+5d
    plann add event "release party" 2004-11-30T19:00+2h
    """
    _add_event(ctx, timespec, **kwargs)

@add.command()
@click.argument('summary', nargs=-1)
@_set_attr_options(verb='set')
@click.pass_context
def journal(ctx, **kwargs):
    """
    Creates a new journal entry with given SUMMARY.

    Examples:

    plann add journal "bought new keyboard"
    plann add journal --set-dtstart=2024-01-15 "sick day"
    """
    return _add_journal(ctx, **kwargs)

## CONVENIENCE COMMANDS

@cli.command()
@click.pass_context
def agenda(ctx):
    """
    Convenience command, prints an agenda

    This command is slightly redundant, same results may be obtained by running those two commands in series:

      `select --event --start=now --end=+7d --limit=16 list`

      `select --todo --sort-key '{DTSTART:?{DUE:?(0000)?}?%F %H:%M:%S}' --sort-key '{PRIORITY:?0}' --end=+7d --limit=16 list --bottom-up`

    agenda is for convenience only and takes no options or parameters.
    Use the select command for advanced usage.  See also USAGE.md.
    """
    return _agenda(ctx)


@cli.group()
@click.pass_context
def interactive(ctx):
    """Interactive convenience commands

    Various workflow procedures that will prompt the user for input.

    Disclaimer: This is quite experimental stuff.  The maintainer is
    experimenting with his own task list and testing out daily
    procedures, hence it's also quite optimized towards whatever
    work-flows that seems to work out for the maintainer of the
    plann.  Things are changed rapidly without warnings and the
    interactive stuff is not covered by any test code whatsoever.
    """


@interactive.command()
@click.pass_context
def manage_tasks(ctx):
    """
    This goes through the daily task management procedures:
    * set-task-attribs
    * agenda
    * check-due
    * split-huge-tasks
    * split-high-pri-tasks
    * dismiss-panic
    * interactive-fix-panic
    """
    ## TODO: pinned tasks for the previous week.
    ## * Go through the events ... for each of them, ask if it was done or not
    ## * If the event was done, mark the task as completed
    ## * If the event wasn't done, mark the event as cancelled
    click.echo("Checking if there are any huge tasks that may need to be split")
    _split_huge_tasks(ctx)
    click.echo("Checking if there are any high-priority tasks ... it's adviceable to split them up into subtasks with a shorter due-date")
    _split_high_pri_tasks(ctx)
    click.echo("Checking if there is any missing metadata on your tasks ...")
    _set_task_attribs(ctx)
    click.echo("Checking if we should go in 'panic mode', perhaps it's needed to procrastinate some lower-priority tasks")
    _dismiss_panic(ctx, hours_per_day=24)
    click.echo("New panic check")
    _dismiss_panic(ctx, hours_per_day=14)
    click.echo("Going through your near-due tasks")
    _check_due(ctx)
    click.echo("Stick tasks to your calendar")
    _check_for_panic(ctx, hours_per_day=24, interactive_fix_timeline=True, timeline_end=parse_dt('+5d'), include_all_events=True)
    click.echo("Here is your upcoming agenda, have a quick look through it")
    _agenda(ctx)

@interactive.command()
@click.option('--limit', type=int, help='If more than limit overdue tasks are found, probably we should do a mass procrastination rather than going through one and one task')
@click.option('--lookahead', help='Look-ahead time - check tasks that needs to be completed in the near future', default='+16h')
@click.pass_context
def check_due(ctx, limit, lookahead):
    """
    Go through overdue or near-future-due tasks, one by one, and deal with them
    """
    return _check_due(ctx, limit, lookahead)

@interactive.command()
@click.option('--hours-per-day', help='how many hours per day you expect to be able to dedicate to those tasks/events', default=4)
@click.option('--lookahead', help='timespan to investigate', default='60d')
@click.pass_context
def dismiss_panic(ctx, hours_per_day, lookahead='60d'):
    """Checks workload, procrastinates tasks

    Search for panic points, checks if they can be solved by
    procrastinating tasks, comes up with suggestions
    """
    return _dismiss_panic(ctx, hours_per_day, lookahead)


@interactive.command()
@click.option('--threshold', help='tasks with a higher estimate than this should be split into subtasks', default='4h')
@click.option('--max-lookahead', help='ignore tasks further in the future than this', default='30d')
@click.option('--limit-lookahead', help='only consider the first x tasks', default=32)
@click.pass_context
def split_huge_tasks(ctx, threshold, max_lookahead, limit_lookahead):
    """
    finds tasks in the upcoming future that have a too big estimate and suggests to split it into subtasks
    """
    return _split_huge_tasks(ctx, threshold, max_lookahead, limit_lookahead)

@interactive.command()
@click.option('--max-lookahead', help='ignore tasks further in the future than this', default='30d')
@click.option('--threshold', help='tasks with this or lower priority should always have children', default=2)
@click.option('--limit-lookahead', help='only consider the first x tasks', default=32)
@click.pass_context
def split_high_pri_tasks(ctx, threshold, max_lookahead, limit_lookahead):
    """Tasks with very high priority (1,2) indicates a hard DUE that
    cannot be moved - the actual work should probably be done long
    time before the deadline.  To preserve the deadline, avoid getting
    surprised at the new years eve that there are still high-priority
    tasks that needs to be done this year, and make it possible to
    procrastinate the work itself it's strongly recommended to split
    the high priority tasks - make one or more child tasks for
    actually doing the work, and leave the parent task as a
    placeholder for just storing the hard deadline (rename it to
    something like "verify that the work has been done and/or
    delivered", set the time estimate to some few minutes).
    """
    return _split_high_pri_tasks(ctx, threshold, max_lookahead, limit_lookahead)

@interactive.command()
@click.pass_context
def set_task_attribs(ctx):
    """Interactively populate missing attributes to tasks

    Convenience method for tobixen-style task management.  Assumes
    that all tasks ought to have categories, a due date, a priority
    and a duration (estimated minimum time to do the task) set and ask
    for those if it's missing.

    See also USER_GUIDE.md, TASK_MANAGEMENT.md and NEXT_LEVEL.md
    """
    click.echo("All tasks ought to have categories, due-time, time-estimate and a priority ... checking if anything is missing")
    _set_task_attribs(ctx)


if __name__ == '__main__':
    cli()
