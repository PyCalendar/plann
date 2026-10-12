## Check https://click.palletsprojects.com/en/8.1.x/testing/

from datetime import datetime, timedelta
from unittest.mock import patch

import caldav
from caldav import Todo
from click.testing import CliRunner

import plann.cli as cli_mod
import plann.commands as commands_mod
from plann.cli import _LazyCalendars, cli, delete, edit
from plann.commands import _process_add_args, _set_task_attribs, _sort_key_function, _todos_missing
from tests.test_freebusy import FakeCalendar, _event, oslo


def _make_todo(uid, *, category=False, due=False, priority=False, dtstart=False):
    lines = ["UID:" + uid, "SUMMARY:task " + uid, "STATUS:NEEDS-ACTION"]
    if category:
        lines.append("CATEGORIES:work")
    if dtstart:
        lines.append("DTSTART:20250101T100000Z")
    if due:
        lines.append("DUE:20250102T100000Z")
    if priority:
        lines.append("PRIORITY:5")
    obj = Todo()
    obj.data = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Example Corp.//CalDAV Client//EN\n"
        "BEGIN:VTODO\n" + "\n".join(lines) + "\nEND:VTODO\nEND:VCALENDAR"
    )
    return obj


class _FakeCtx:
    def __init__(self):
        self.obj = {'calendars': [], 'objs': []}


def test_todos_missing():
    """_todos_missing keeps only the tasks where the property is absent."""
    with_cat = _make_todo('a', category=True)
    without_cat = _make_todo('b')
    result = _todos_missing([with_cat, without_cat], 'categories')
    assert [str(o.icalendar_component['UID']) for o in result] == ['b']


def test_set_task_attribs_fetches_once():
    """set-task-attribs must fetch the task list once and filter client-side
    per attribute, not issue a fresh server select per attribute (code review
    E4)."""
    ## fully-specified todos => nothing is missing => no interactive prompting
    todos = [_make_todo(uid, category=True, due=True, priority=True, dtstart=True)
             for uid in ('a', 'b', 'c')]
    calls = []

    def fake_select(ctx, **kwargs):
        calls.append(kwargs)
        ctx.obj['objs'] = list(todos)

    ctx = _FakeCtx()
    with patch.object(commands_mod, '_select', fake_select):
        _set_task_attribs(ctx)
    assert len(calls) == 1, f"expected a single fetch, got {len(calls)}"


def test_set_task_attribs_prompts_missing_attribute():
    """A task missing only a category is prompted for it (and only it), and
    the entered category is saved - the single-fetch refactor still drives the
    interactive flow."""
    ## has due/priority/dtstart, lacks only a category
    todo = _make_todo('a', due=True, priority=True, dtstart=True)

    def fake_select(ctx, **kwargs):
        ctx.obj['objs'] = [todo]

    ctx = _FakeCtx()
    with patch.object(commands_mod, '_select', fake_select), \
         patch.object(todo, 'save') as save, \
         patch('plann.commands.click.echo'), \
         patch('plann.commands.click.prompt', return_value='work') as prompt:
        _set_task_attribs(ctx)

    ## exactly one prompt (the missing category), and it got persisted
    assert prompt.call_count == 1
    save.assert_called_once()
    assert 'work' in todo.data


def test_set_task_attribs_skips_completed():
    """A task marked "completed!" at the category prompt must not be
    prompted for again for due/priority/duration - the task list is fetched
    once, so the completed task must be dropped from it."""
    todo = _make_todo('a')

    def fake_select(ctx, **kwargs):
        ctx.obj['objs'] = [todo]

    ctx = _FakeCtx()
    with patch.object(commands_mod, '_select', fake_select), \
         patch.object(todo, 'save'), \
         patch('plann.commands.click.echo'), \
         patch('plann.commands.click.prompt', return_value='completed!') as prompt:
        _set_task_attribs(ctx)

    assert prompt.call_count == 1
    assert todo.icalendar_component['STATUS'] == 'COMPLETED'


def test_set_task_attribs_skips_completed_at_duration():
    """A task given a due date, then marked "completed!" at the priority
    prompt, must not come back at the duration prompt via the due step's
    returned list."""
    todo = _make_todo('a', category=True)

    def fake_select(ctx, **kwargs):
        ctx.obj['objs'] = [todo]

    def fake_procrastinate(objs, due, **kwargs):
        objs[0].icalendar_component.add('DUE', due)

    ctx = _FakeCtx()
    with patch.object(commands_mod, '_select', fake_select), \
         patch.object(commands_mod, '_procrastinate', fake_procrastinate), \
         patch.object(todo, 'save'), \
         patch('plann.commands.click.echo'), \
         patch('plann.commands.click.prompt', side_effect=['+2d', 'completed!']) as prompt:
        _set_task_attribs(ctx)

    assert prompt.call_count == 2

_TODO = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//CalDAV Client//EN
BEGIN:VTODO
UID:{uid}
DTSTAMP:19970901T130000Z
SUMMARY:task {uid}
PRIORITY:{priority}
END:VTODO
END:VCALENDAR"""


def _todo(uid, priority):
    obj = Todo()
    obj.data = _TODO.format(uid=uid, priority=priority)
    return obj


def test_sort_key_function_priority():
    """A bare property name sorts on that icalendar property."""
    reverse, fkey = _sort_key_function('PRIORITY')
    assert reverse is False
    objs = [_todo('a', 3), _todo('b', 1), _todo('c', 2)]
    objs.sort(key=fkey)
    assert [str(o.icalendar_component['UID']) for o in objs] == ['b', 'c', 'a']


def test_sort_key_function_reverse():
    """A leading '-' reverses the sort."""
    reverse, fkey = _sort_key_function('-PRIORITY')
    assert reverse is True
    objs = [_todo('a', 3), _todo('b', 1), _todo('c', 2)]
    objs.sort(key=fkey, reverse=reverse)
    assert [str(o.icalendar_component['UID']) for o in objs] == ['a', 'c', 'b']


def test_sort_key_function_compiles_template_once():
    """A template sort key must be compiled once, not rebuilt on every
    comparison during the sort (code review E2)."""
    objs = [_todo(uid, p) for uid, p in (('a', 3), ('b', 1), ('c', 2), ('d', 5), ('e', 4))]
    with patch('plann.commands.Template', wraps=commands_mod.Template) as template_cls:
        reverse, fkey = _sort_key_function('{PRIORITY}')
        objs.sort(key=fkey, reverse=reverse)
    assert template_cls.call_count == 1
    assert [str(o.icalendar_component['UID']) for o in objs] == ['b', 'c', 'a', 'e', 'd']


def test_configure_command_registered():
    """The interactive configuration is wired into the click CLI as
    `plann configure` (code review C8 re-wiring)."""
    assert 'configure' in cli.commands


def test_update_config_command_dropped():
    """`interactive update-config` never did anything but raise
    NotImplementedError; `plann configure` is the configuration command."""
    assert 'update-config' not in cli.commands['interactive'].commands


def test_lazy_calendars_resolves_once():
    """_LazyCalendars defers discovery until first use, then caches it."""
    calls = []

    def discover():
        calls.append(1)
        return ['a', 'b']

    lazy = _LazyCalendars(discover)
    assert calls == []          ## not resolved just by constructing
    assert len(lazy) == 2       ## first access triggers discovery
    assert list(lazy) == ['a', 'b']
    assert lazy[0] == 'a'
    assert bool(lazy) is True
    assert calls == [1]         ## resolved exactly once


def test_calendar_discovery_deferred_for_help():
    """Showing subcommand --help must not trigger calendar discovery (which
    talks to the network), even with a caldav_url given (code review E1)."""
    calls = []
    orig = cli_mod.find_calendars

    def spy(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    cli_mod.find_calendars = spy
    try:
        res = CliRunner().invoke(
            cli, ['--skip-config', '--caldav-url', 'http://example.invalid/', 'select', '--help'])
        assert res.exit_code == 0, res.output
        assert calls == [], "discovery should be deferred when only showing help"
    finally:
        cli_mod.find_calendars = orig


def _option_names(cmd):
    names = set()
    for param in cmd.params:
        names.update(param.opts)
    return names


def _find_option(cmd, name):
    for param in cmd.params:
        if name in param.opts:
            return param
    return None


def test_edit_exposes_comma_list_options():
    """categories and resources are both exposed in singular + plural for both
    add (append) and the existing set (replace) verbs - so the user does not
    have to remember which form to use."""
    names = _option_names(edit)
    for opt in (
        '--add-category',
        '--add-categories',
        '--add-resource',
        '--add-resources',
        '--set-category',
        '--set-categories',
        '--set-resources',
    ):
        assert opt in names, f"missing {opt}"


def test_no_set_resource_singular():
    """There is deliberately no --set-resource (singular replace)."""
    assert '--set-resource' not in _option_names(edit)


def test_set_category_marked_deprecated():
    """--set-category keeps working (it appends) but its help flags it as
    deprecated in favour of --add-category / --set-categories."""
    opt = _find_option(edit, '--set-category')
    assert opt is not None
    assert 'deprecat' in (opt.help or '').lower()


def test_process_add_args():
    """--add-* options are collected as (canonical_property, tokens) to append:
    plural splits on comma, singular keeps it literal."""
    kwargs = {
        'add_category': ('a,b',),
        'add_categories': ('x,y',),
        'add_resource': ('R1,R2',),
        'add_resources': ('S1,S2',),
        'set_summary': 'unrelated',
    }
    result = _process_add_args(kwargs)
    assert ('categories', ['a,b']) in result
    assert ('categories', ['x', 'y']) in result
    assert ('resources', ['R1,R2']) in result
    assert ('resources', ['S1', 'S2']) in result
    ## add_* keys are consumed; unrelated keys are left untouched
    assert not any(k.startswith('add_') for k in kwargs)
    assert 'set_summary' in kwargs


class _FakeCalNotFound:
    """A calendar that never has the requested uid."""
    def get_object_by_uid(self, uid):
        raise caldav.error.NotFoundError(uid)


def test_select_warns_on_missing_uid():
    """By default, a --uid that matches nothing in any calendar produces a
    warning naming the missing uid (https://github.com/tobixen/plann/issues/42)."""
    ctx = _FakeCtx()
    ctx.obj['calendars'] = [_FakeCalNotFound()]
    with patch('plann.commands.click.echo') as echo:
        commands_mod._select(ctx, uid=('asdf',))
    assert any('asdf' in str(c.args[0]) for c in echo.call_args_list), \
        "expected a warning naming the missing uid"
    ## warnings go to stderr so they do not pollute scriptable stdout
    assert all(c.kwargs.get('err') for c in echo.call_args_list)


def test_select_no_warn_on_missing_uid():
    """--no-warn-on-missing-uid restores the old silent behaviour."""
    ctx = _FakeCtx()
    ctx.obj['calendars'] = [_FakeCalNotFound()]
    with patch('plann.commands.click.echo') as echo:
        commands_mod._select(ctx, uid=('asdf',), warn_on_missing_uid=False)
    assert echo.call_count == 0


def test_select_no_warn_when_uid_found():
    """A uid that is found produces no missing-uid warning."""
    todo = _make_todo('a')

    class _FakeCalFound:
        def get_object_by_uid(self, uid):
            return todo

    ctx = _FakeCtx()
    ctx.obj['calendars'] = [_FakeCalFound()]
    with patch('plann.commands.click.echo') as echo:
        commands_mod._select(ctx, uid=('a',))
    assert echo.call_count == 0
    assert ctx.obj['objs'] == [todo]


def test_delete_reports_deleted_item():
    """delete must tell the user what it did - deleting a selected item should
    name it and actually call .delete()
    (https://github.com/tobixen/plann/issues/42)."""
    todo = _make_todo('a')
    with patch.object(todo, 'delete') as deleted:
        res = CliRunner().invoke(delete, obj={'objs': [todo]})
    assert res.exit_code == 0, res.output
    deleted.assert_called_once()
    assert 'task a' in res.output


def test_delete_reports_empty_selection():
    """delete on an empty selection (e.g. --uid matched nothing) must say so
    rather than silently producing no output
    (https://github.com/tobixen/plann/issues/42)."""
    res = CliRunner().invoke(delete, obj={'objs': []})
    assert res.exit_code == 0, res.output
    assert res.output.strip(), "expected some feedback on an empty selection"


def test_freebusyhack_marked_deprecated():
    """--freebusyhack is superseded by the freebusy-sync command."""
    opt = _find_option(cli.commands['select'], '--freebusyhack')
    assert 'deprecat' in (opt.help or '').lower()


def test_freebusy_sync_command():
    """freebusy-sync copies from the selected calendars into the first
    calendar of --to-section, clipping with --hours and --weekdays-only."""
    day = (datetime.now(oslo) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day.weekday() > 4:
        day += timedelta(days=1)
    source = FakeCalendar([_event(start=day.replace(hour=7), end=day.replace(hour=10))])
    target = FakeCalendar()
    sections = []

    def section_calendars(ctx, section):
        sections.append(section)
        return [target]

    ## --implicit-timezone sets the process-wide tz; restore it for later tests
    with patch.object(cli_mod, '_discover_calendars', lambda kwargs: [source]), \
         patch.object(cli_mod, '_section_calendars', section_calendars), \
         patch.object(cli_mod.tz, '_implicit_timezone', cli_mod.tz.implicit_timezone), \
         patch.object(cli_mod.tz, '_store_timezone', cli_mod.tz.store_timezone):
        res = CliRunner().invoke(cli, [
            '--implicit-timezone', 'Europe/Oslo', 'freebusy-sync', '--to-section', 'work',
            '--summary', 'event from the personal calendar', '--hours', '9-16', '--weekdays-only'])
    assert res.exit_code == 0, res.output
    assert sections == ['work']
    assert 'added 1' in res.output
    assert 'dry run' not in res.output
    [copy] = target.components()
    assert copy['DTSTART'].dt == day.replace(hour=9)
    assert copy['DTEND'].dt == day.replace(hour=10)
    assert str(copy['X-PLANN-FREEBUSY-SOURCE']) == 'default'


def _run_freebusy_sync(source_calendars, target_calendars, *args, config=None):
    config = config or {'work': {}}
    with patch.object(cli_mod, '_discover_calendars', lambda kwargs: list(source_calendars)), \
         patch.object(cli_mod, 'read_config', lambda *a, **k: config), \
         patch.object(cli_mod, 'find_calendars', lambda *a, **k: list(target_calendars)), \
         patch.object(cli_mod.tz, '_implicit_timezone', cli_mod.tz.implicit_timezone), \
         patch.object(cli_mod.tz, '_store_timezone', cli_mod.tz.store_timezone):
        return CliRunner().invoke(cli, ['freebusy-sync', '--to-section', 'work', '--summary', 'x', *args])


def test_freebusy_sync_needs_exactly_one_target():
    res = _run_freebusy_sync([FakeCalendar()], [FakeCalendar(), FakeCalendar()])
    assert res.exit_code != 0
    assert 'exactly one' in res.output


def test_freebusy_sync_aborts_without_source_calendars():
    target = FakeCalendar()
    res = _run_freebusy_sync([], [target])
    assert res.exit_code != 0
    assert target.objects == []


def test_freebusy_sync_rejects_bad_hours():
    res = _run_freebusy_sync([FakeCalendar()], [FakeCalendar()], '--hours', '9-25')
    assert res.exit_code != 0
    assert '--hours' in res.output


def test_freebusy_sync_dry_run_wording():
    res = _run_freebusy_sync([FakeCalendar()], [FakeCalendar()], '--dry-run')
    assert res.exit_code == 0, res.output
    assert res.output.startswith('dry run, nothing changed: added 0')


def test_freebusy_sync_discovers_with_raise_errors():
    """A source that fails to load must abort the run, not count as empty."""
    seen = {}

    def discover(kwargs):
        seen['raise_errors'] = kwargs['raise_errors']
        return [FakeCalendar()]

    with patch.object(cli_mod, '_discover_calendars', discover), \
         patch.object(cli_mod, '_section_calendars', lambda ctx, section: [FakeCalendar()]):
        res = CliRunner().invoke(cli, ['freebusy-sync', '--to-section', 'work', '--summary', 'x'])
    assert res.exit_code == 0, res.output
    assert seen['raise_errors'] is True


def test_freebusyhack_warns(caplog):
    ctx = _FakeCtx()
    commands_mod._select(ctx, freebusyhack='busy')
    assert 'deprecated' in caplog.text
