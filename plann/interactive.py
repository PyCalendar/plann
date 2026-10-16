"""Functions allowing one to manage calendaring and tasks
interactively through a text console

Are interactive prompts silly or useful?  Are edit-screens practical
or non-comprehensible?  Are interactivity compatible with the mission
statement of creating a cli tool?  A tui tool is something quite
different, isn't it?  And the "interactivity" here is not really tui
as it's based on simple prompts and sending the user off to a text
editor every now and then.

Anyway, I believe at least some of the methods here do help me to get
better organized.  Or perhaps it's just getting in the way, I'm
spending lots of efforts micro-managing my tasks rather than actually
doing them.
"""

import os
import re
import shutil
import subprocess
import tempfile

import click
from icalendar.prop import vRecur

from plann.lib import (
    _adjust_relations,
    _complete,
    _component_type,
    _list,
    _now,
    _process_set_arg,
    _procrastinate,
    _relationship_text,
    _set_something,
    _split_vcal,
    _summary,
    add_time_tracking,
)
from plann.template import Template
from plann.timespec import DURATION_UNITS, _ensure_ts, parse_add_dur


def _pdb_edit(obj, interactive=True):
    comp = obj.icalendar_component  # noqa: F841 — visible in pdb session
    if interactive:
        click.echo("icalendar component available as comp")
        click.echo("caldav object available as obj")
        click.echo("do the necessary changes and press c to continue normal code execution")
        click.echo("happy hacking")
    breakpoint()

def command_edit(obj, command, interactive=True, complete_cache=None, completed=None):
    if command == 'ignore':
        return
    elif command in ('part', 'partially-complete'):
        interactive_split_task(obj, partially_complete=True, too_big=False)
    elif command == 'split':
        interactive_split_task(obj, too_big=False)
    elif command.startswith('postpone'):
        with_params = {}
        commands = command.split(' ')
        if interactive:
            with_params['confirm_callback'] = click.confirm
            with_params['err_callback'] = click.echo
            true = 'interactive'
            with_params['check_dependent'] = 'interactive'
        else:
            true = True
        if len(commands)>2:
            if 'with family' in command:
                with_params['with_family'] = true
            if 'with children' in command:
                with_params['with_children'] = true
            if 'with parent' in command:
                with_params['with_parent'] = true
        ## TODO: we probably shouldn't be doing this interactively here?
        _procrastinate([obj], command.split(' ')[1], **with_params)
    elif command == 'complete':
        _complete(obj, handle_rrule=True, err_callback=click.echo, cache=complete_cache, _seen=completed)
    elif command == 'cancel':
        obj.icalendar_component['STATUS'] = 'CANCELLED'
    elif command.lower().startswith('set rrule='):
        ## TODO: does this work from the cli?  (...) edit --set-rrule=FREQ=YEARLY as well as add (...) --set-rrule=FREQ=YEARLY ?  Write test code and check!
        rrule = vRecur.from_ical(command[10:])
        _set_something(obj, 'RRULE', rrule)
    elif command.startswith('set '):
        command = command[4:].split('=')
        assert len(command) == 2
        parsed = _process_set_arg(*command, keep_category=True)
        for x in parsed:
            _set_something(obj, x, parsed[x])
    elif command == 'edit':
        _interactive_ical_edit([obj])
    elif command == 'family':
        _interactive_relation_edit([obj])
    elif command == 'start':
        ## TODO - experimental and very incomplete!
        add_time_tracking(obj)
    elif command == 'pdb':
        _pdb_edit(obj, interactive=interactive)
    else:
        if interactive:
            click.echo(f"unknown instruction '{command}' - ignoring")
        else:
            raise NameError(f"unknown instruction '{command}' - ignoring")
        return
    obj.save()

def _interactive_ical_edit(objs):
    ical = "\n".join([x.data for x in objs])
    data = _editor(ical)
    data = data.strip()
    icals = _split_vcal(data)
    assert len(icals) == len(objs)
    for new,obj in zip(icals, objs):
        ## Should probably assert that the UID is the same ...
        ## ... or, leave it to the calendar server to handle changed UIDs
        obj.data = new
        obj.save()

def _interactive_relation_edit(objs):
    if not objs:
        return
    indented_family = "\n".join(_list(
        objs, top_down=True, echo=False,
        template="{UID}: {SUMMARY:?{DESCRIPTION:?(no summary given)?}?} (STATUS={STATUS:-})"))
    edited = _editor(indented_family)
    _set_relations_from_text_list(objs[0].parent, edited.split("\n"))

def _set_relations_from_text_list(calendar, some_list, parent=None, indent=0):
    """
    Takes a list of indented strings identifying some relationships,
    ensures parent and child is

    Caveats:
    * Currently it does not support RFC 9253 and enforces RELTYPE to be PARENT or CHILD
    * Currently it also lacks support for multiple parents
    * Relation type SIBLING is ignored
    """
    ## Logic:
    ## * If a parent is not set and indent is 0, make sure the item has either no parents or multiple parents
    ## * For all following lines where the indent is higher than the expected indent, recurse over the lines that are indented
    ## * If a parent is set, collect all children (all lines with expected indent), then make sure all children has parent correctly set, and make sure the parent has those and no more children.
    ## * Return a list of changes done.

    ## Internal methods
    def count_indent(line):
        """count the left hand spaces on a line"""
        j = 0
        while j<len(line):
            if line[j] == '\t':
                j+=8
            elif line[j] == ' ':
                j+=1
            else:
                return j
        return None

    i=0
    children = []
    while i<len(some_list):
        line = some_list[i]
        line_indent = count_indent(line)

        ## empty line
        if line_indent is None:
            i += 1
            continue

        ## unexpected - indentation going backwards
        if line_indent < indent:
            raise NotImplementedError("unexpected indentation 0")

        ## indentation going forward - recurse over the indented section
        #if line_indent > indent or (line_indent == indent and i>0): # TODO: think this more through?  The last is supposed to rip existing children from lines without a following indented sublist
        if line_indent > indent:
            if not i:
                raise NotImplementedError("unexpected indentation 1")
            j=i
            while j<len(some_list):
                new_indent = count_indent(some_list[j])
                if new_indent is None or new_indent==indent:
                    break
                if new_indent < line_indent and new_indent != indent:
                    raise NotImplementedError("unexpected indentation 2")
                j+=1
            ## _get_obj_from_line returns None for a blank or comment line.
            ## Passing that on as the parent would make _adjust_relations
            ## strip the PARENT relation off every child below it, so abort
            ## rather than silently mutating the user's data.
            parent_obj = _get_obj_from_line(some_list[i-1], calendar)
            if parent_obj is None:
                raise NotImplementedError(f"no task found on the line above the indented section: {some_list[i-1]!r}")
            _set_relations_from_text_list(calendar, some_list[i:j], parent=parent_obj, indent=line_indent)
            i=j
            continue

        ## Unindented line.  Should be a direct child under parent
        if line_indent == indent:
            obj = _get_obj_from_line(some_list[i], calendar)
            if obj is not None:
                children.append(obj)
            i+=1
            continue

        ## TODO: look through all the conditions above.  should we ever be here?
        raise NotImplementedError("We should not be here - please raise an issue at https://github.com/pycalendar/plann or reach out to bugs@plann.no")
    for c in children:
        c.load()
    _adjust_relations(parent, children)

def _abort(message):
    click.echo(message)
    raise click.Abort(message)

def _interactive_edit(obj, complete_cache=None, completed=None):
    if _component_type(obj) != 'VTODO':
        raise NotImplementedError("interactive editing only implemented for tasks")
    comp = obj.icalendar_component
    summary = _summary(comp)
    dtstart = comp.get('DTSTART')
    pri = comp.get('PRIORITY', 0)
    due = obj.get_due()
    if not dtstart or not due:
        click.echo(f"task without dtstart or due found, please run set-task-attribs subcommand.  Ignoring {summary}")
        return
    dtstart = _ensure_ts(dtstart)
    click.echo(f"pri={pri} {dtstart:%F %H:%M:%S %Z} - {due:%F %H:%M:%S %Z}: {summary}")
    input = click.prompt("postpone <n>d / ignore / part(ially-complete) / complete / split / cancel / set foo=bar / edit / family / start / pdb?", default='ignore')
    try:
        command_edit(obj, input, interactive=True, complete_cache=complete_cache, completed=completed)
    except NotImplementedError as e:
        ## e.g. `start` when extra_config.time_tracking is not configured -
        ## the prompt advertises the command, so report why it did not work
        ## rather than tearing down the rest of the session with a traceback
        click.echo(f"Could not run '{input}': {e}")
        return
    if input == 'start':
        ## time tracking has been started - re-prompt so a follow-up command can be given for the same task
        _interactive_edit(obj, complete_cache, completed)

def _mass_reprioritize(objs):
    text = """\
## Keep the section headers.
## Lines may be moved up or down to the relevant section.
## Tasks with correct priority set may be deleted.
## Higher numbers means lower priority, lowest possible is 9
## Priority 0 means undefined priority.

"""
    if not objs:
        click.echo("Nothing to reprioritize!")
        return
    objs.sort(key=lambda x: (x.icalendar_component.get('PRIORITY',0), _now()-_ensure_ts(x.get_due())))
    current_pri = -1
    template = Template(" {UID}: due={DUE} Pri={PRIORITY:?0?} {SUMMARY:?{DESCRIPTION:?(no summary given)?}?} (STATUS={STATUS:-})")
    for obj in objs:
        while obj.icalendar_component.get('PRIORITY', 0)>current_pri:
            current_pri += 1
            text += f"\n=== PRIORITY {current_pri}\n"
        text += template.format(**obj.icalendar_component) + "\n"
    edited = _editor(text)
    current_pri = 0
    for line in edited.split('\n'):
        line = line.strip()
        if line.startswith('#'):
            continue
        if not line:
            continue
        if line.startswith('=== PRIORITY '):
            current_pri=int(line[13:])
            continue
        ## TODO: need to make some efforts to fix multi-calendar support.  Keep a uid -> obj dict.  Fix in the other mass editing functions.
        _command_line_edit(f"set priority={current_pri} " + line, interactive=True, calendar=objs[0].parent)

def _mass_interactive_edit(objs, default='ignore'):
    """send things through the editor, and expect commands back"""
    instructions = """\
## Prepend a line with one of the following commands:
# postpone <n>d
# ignore
# part(ially-complete)
# complete
# split
# cancel
# set foo=bar
# edit
# family
# pdb

"""
    if not objs:
        click.echo("Nothing to edit!")
        return
    text = instructions + "\n".join(_list(
        objs, top_down=True, echo=False,
        ## We only deal with tasks so far, and only tasks that needs action
        ## TODO: this is bad design
        template=default + " {UID}: due={DUE} Pri={PRIORITY:?0?} {SUMMARY:?{DESCRIPTION:?(no summary given)?}?} (STATUS={STATUS:-})", filter=lambda obj: obj.icalendar_component.get('STATUS', 'NEEDS-ACTION')=='NEEDS-ACTION'))
    edited = _editor(text)
    for line in edited.split('\n'):
        ## TODO: BUG: does not work if the source data comes from multiple calendars!
        ## (possible fix: make a dict from uid to calendar(s))
        _command_line_edit(line, interactive=True, calendar=objs[0].parent)

def interactive_split_task(obj, partially_complete=False, too_big=True):
    comp = obj.icalendar_component
    summary = _summary(obj)
    estimate = obj.get_duration()
    tbm = ""
    if too_big:
        tbm = ", which is too big."
    click.echo(f"{summary}: estimate is {estimate}{tbm}")
    click.echo("Relationships:\n")
    click.echo(_relationship_text(obj))
    if partially_complete:
        splitout_msg = "So you've been working on this?"
    else:
        splitout_msg = "Do you want to fork out some subtasks?"
    if click.confirm(splitout_msg):
        cnt = 1
        if partially_complete:
            default = f"Work on {summary}"
        else:
            default = f"Plan how to do {summary}"
        while True:
            summary = click.prompt("Name for the subtask", default=default)
            default=""
            if not summary:
                break
            cnt += 1
            todo = obj.parent.save_todo(summary=summary, parent=[comp['uid']])
            obj.load()
            if partially_complete:
                todo.complete()
                break
        new_estimate_suggestion = f"{estimate.total_seconds()//3600//cnt+1}h"
        new_estimate = click.prompt("what is the remaining estimate for the parent task?", default=new_estimate_suggestion)
        obj.set_duration(parse_add_dur(None, new_estimate), movable_attr='DTSTART') ## TODO: verify
        new_summary = click.prompt("Summary of the parent task?", default=obj.icalendar_component['SUMMARY'])
        obj.icalendar_component['SUMMARY'] = new_summary
        postpone = click.prompt("Should we postpone the parent task?", default='0h')
        if postpone not in ('0h', '0'): ## TODO: regexp?
            _procrastinate([obj], postpone, check_dependent='interactive', err_callback=click.echo, confirm_callback=click.confirm)
        obj.save()

def _editor(sometext):
    with tempfile.NamedTemporaryFile(mode='w', encoding='UTF-8', delete=False) as tmpfile:
        tmpfile.write(sometext)
        fn = tmpfile.name
    candidates = (os.environ.get("VISUAL"), os.environ.get("EDITOR"),
                  'vim', 'vi', 'emacs', 'nano', 'pico')
    ed = next((found for c in candidates if c and (found := shutil.which(c))), None)
    if not ed:
        os.unlink(fn)
        raise FileNotFoundError("no usable editor found; set the EDITOR or VISUAL environment variable")
    subprocess.run([ed, fn])
    with open(fn) as tmpfile:
        ret = tmpfile.read()
    os.unlink(fn)
    return ret

def _strip_line(line):
    strip1 = re.compile("#.*$")
    line = strip1.sub('', line)
    line = line.strip()
    return line

def _get_obj_from_line(line, calendar):
    ## TODO: the calendar we get here may be invalid.
    ## We need to map uids to objects when fetching events
    ## this should be done globally to reduce code duplication
    uid_re = re.compile("^(.+?)(: .*)?$")
    line = _strip_line(line)
    if not line:
        return None
    found = uid_re.match(line)
    assert found
    uid = found.group(1)
    obj = calendar.object_by_uid(uid)
    return obj

def _command_line_edit(line, calendar, interactive=True):
    regexp = re.compile(rf"((?:set [^ ]*=[^ ]*)|(?:postpone (?:[0-9]+[{DURATION_UNITS}]|20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]))|[^ ]*) (.*)$")
    line = _strip_line(line)
    if not line:
        return
    splitted = regexp.match(line)
    assert splitted
    command = splitted.group(1)
    obj = _get_obj_from_line(splitted.group(2), calendar)
    assert obj
    command_edit(obj, command, interactive)

