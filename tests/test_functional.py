## This do testing all the way towards (a) calendar server(s)

## TODO: work in progress

## TODO: tests with multiple source calendars.  Some of the interactive edit-through-editor functions will probably break.

import asyncio
import datetime
import os
import re
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import aiohttp
import aiohttp.web
import caldav
import niquests as requests
from caldav.lib.error import PutError
from xandikos.web import SingleUserFilesystemBackend, XandikosApp

from plann.cli import _add_journal, _add_todo, _check_for_panic, _list, _select
from plann.commands import _add_event, _check_pinned, _set_event_status
from plann.interactive import (
    _interactive_edit,
    _interactive_relation_edit,
    _mass_interactive_edit,
    _mass_reprioritize,
    command_edit,
)
from plann.lib import _adjust_ical_relations, _adjust_relations, _summary
from plann.panic_planning import timeline_suggestion
from plann.timespec import _now, tz
from tests.test_panic import datetime_


class InterruptXandikosServer:
    def graceful_exit_with_pdb(self):
        breakpoint()
        self.graceful_exit()
    def graceful_exit_():
        return 1

interrupt_xandikos_server_singleton = InterruptXandikosServer()

## I've made three different attempts on starting up xandikos.
## I should eventually look through this once more, as it's still non-trivial to restart the xandikos-server.

## This function is currently not in use
## TODO: this is how I would like to start the xandikos server, but it didn't quite work out ...
## 1) the run_simple_server method does not work in threads due to signal
## handling (sort of solved, but ...)
## 2) it's difficult to stop the thread
def start_xandikos_server_foobar():
    ## We need to mock up a signal handler
    global interrupt_xandikos_server_singleton
    def add_signal_handler(signal, handler):
        interrupt_xandikos_server_singleton.graceful_exit = handler
    new_signal_handler = add_signal_handler
    _orig_get_event_loop = asyncio.get_event_loop
    def _new_get_event_loop(*largs, **kwargs):
        loop = _orig_get_event_loop(*largs, **kwargs)
        loop.add_signal_handler = new_signal_handler
        return loop
    asyncio.get_event_loop = _new_get_event_loop

    ## Start xandikos in a thread
    thread = threading.Thread(target=run_simple_server, kwargs={'current_user_principal': '/sometestuser', 'directory': '/tmp/xandikos/', 'autocreate': True})  # noqa: F821
    thread.start()
    assert thread.is_alive()
    return {
        'caldav_user': 'sometestuser',
        'caldav_password': 'pass1',
        'caldav_url': 'http://localhost:8080/'
    }

## This function is currently not in use
def start_xandikos_server_fork():
    ## It's simple to fork out a xandikos server, but somehow I can't get it to work with pytest
    pid = os.fork()
    if not pid:
        run_simple_server(current_user_principal='/sometestuser', directory='/tmp/xandikos/', autocreate=True)  # noqa: F821
    else:
        return {
            'caldav_user': 'sometestuser',
            'caldav_password': 'pass1',
            'caldav_url': 'http://localhost:8080/',
            'pid': pid
        }

def start_xandikos_server():
    ## Copying the code from the caldav test suite
    serverdir = tempfile.TemporaryDirectory()
    serverdir.__enter__()
    ## Most of the stuff below is cargo-cult-copied from xandikos.web.main
    ## Later jelmer created some API that could be used for this
    backend = SingleUserFilesystemBackend(serverdir.name)
    backend._mark_as_principal("/sometestuser/")
    backend.create_principal("/sometestuser/", create_defaults=True)
    mainapp = XandikosApp(
        backend, current_user_principal="sometestuser", strict=True
    )

    async def xandikos_handler(request):
        return await mainapp.aiohttp_handler(request, "/")

    xapp = aiohttp.web.Application()
    xapp.router.add_route("*", "/{path_info:.*}", xandikos_handler)
    ## https://stackoverflow.com/questions/51610074/how-to-run-an-aiohttp-server-in-a-thread
    xapp_loop = asyncio.new_event_loop()
    xapp_runner = aiohttp.web.AppRunner(xapp)
    asyncio.set_event_loop(xapp_loop)
    xapp_loop.run_until_complete(xapp_runner.setup())
    xapp_site = aiohttp.web.TCPSite(
        xapp_runner, host='localhost', port=8080
    )
    xapp_loop.run_until_complete(xapp_site.start())

    def aiohttp_server():
        xapp_loop.run_forever()

    xandikos_thread = threading.Thread(target=aiohttp_server)
    xandikos_thread.start()
    server_params = {
        "caldav_url": "http://localhost:8080",
        "caldav_password": "pass1",
        "caldav_user": "sometestuser",
        "xandikos_thread": xandikos_thread,
        "xandikos_app_loop": xapp_loop,
        "serverdir": serverdir,
        "xandikos_app_runner": xapp_runner
    }
    return server_params

def stop_xandikos_server(server_params):
    server_params['xandikos_app_loop'].stop()
    ## ... but the thread may be stuck waiting for a request ...
    def silly_request():
        try:
            requests.get(server_params["caldav_url"]).close()
        except Exception:
            pass
    threading.Thread(target=silly_request).start()
    i = 0
    while server_params['xandikos_app_loop'].is_running():
        time.sleep(0.05)
        i += 1
        assert i < 100
    server_params['xandikos_app_loop'].run_until_complete(server_params['xandikos_app_runner'].cleanup())
    i = 0
    while server_params['xandikos_thread'].is_alive():
        time.sleep(0.05)
        i += 1
        assert i < 100
    server_params['xandikos_app_loop'].close()
    asyncio.set_event_loop(None)

    server_params['serverdir'].__exit__(None, None, None)

def passthrough(x):
    return x

## TODO: Rather than one monolithic test going through various aspects,
## we should make many small tests and reset the calendar server to some known
## state prior to each test.  However, we have some problems with restarting
## xandikos ((interrupt_xandikos_server_singleton.graceful_exit() causes
## locking problem)
## (TODO: why is this not an issue in the caldav ftest?)
def test_plann():
    conn_details = start_xandikos_server()
    try:
        with caldav.get_calendars(
            url=conn_details['caldav_url'],
            username=conn_details['caldav_user'],
            password=conn_details['caldav_password'],
            raise_errors=True,
        ) as calendars:
            _run_plann_tests(calendars)

    finally:
        stop_xandikos_server(conn_details)


def _run_plann_tests(calendars):
    ctx = MagicMock()
    ctx.obj = dict()
    ctx.obj['calendars'] = list(calendars)

    def dag(obj, reltype, observed=None):
        if not hasattr(obj, 'get_relatives'):
            obj = ctx.obj['calendars'][0].object_by_uid(obj)
        else:
            obj.load()
        if not observed:
            observed = set()
        ret = {}
        relatives = obj.get_relatives(reltypes={reltype}, fetch_objects=False)
        for x in relatives[reltype]:
            assert x not in observed
            observed.add(x)
            ret[x] = dag(x, reltype, observed)
        return ret

    ## We create two tasks todo1 and todo2, todo2 being a child of todo1
    todo1 = _add_todo(ctx, summary=['make plann good'], set_due='2012-12-20 23:15:00', set_dtstart='2012-12-20 22:15:00', set_uid='todo1', set_categories='plann,keyboard')
    uid1 = str(todo1.icalendar_component['uid'])
    todo2 = _add_todo(ctx, summary=['fix some bugs in plann'], set_parent=[uid1], set_due='2012-12-21 23:15:00', set_dtstart='2012-12-21 22:15:00', set_uid='todo2', set_categories=('plann', 'keyboard'))
    uid2 = str(todo2.icalendar_component['uid'])

    ## Selecting the tasks should yield ... 2 (but only one if skip_children or skip_parents is used)
    _select(ctx, todo=True)
    assert len(ctx.obj['objs'])==2
    _select(ctx, todo=True, skip_children=True)
    assert len(ctx.obj['objs'])==1
    _select(ctx, todo=True, skip_parents=True)
    assert len(ctx.obj['objs'])==1
    _select(ctx, summary='make plann good')
    ## this breaks with xandikos
    #assert len(ctx.obj['objs'])==1
    _select(ctx, summary='make plann good', todo=True)
    assert len(ctx.obj['objs'])==1
    _select(ctx, event=True)
    assert len(ctx.obj['objs'])==0

    ## Journal tests
    _add_journal(ctx, summary=['bought new keyboard'], set_dtstart='2012-12-20')
    _select(ctx, journal=True)
    assert len(ctx.obj['objs'])==1
    _select(ctx, todo=True)
    assert len(ctx.obj['objs'])==2
    _select(ctx, event=True)
    assert len(ctx.obj['objs'])==0

    ## assert that relations are as expected
    todo1.load()
    todo2.load()
    assert(dag(todo1, 'CHILD') == {uid2: {}})
    assert(dag(todo2, 'PARENT') == {uid1: {}})
    assert(not _adjust_ical_relations(todo1, {'CHILD': {uid2}, 'PARENT': set()}))
    assert(not _adjust_ical_relations(todo2, {'PARENT': {uid1}, 'CHILD': set()}))

    _select(ctx, todo=True)
    ## This should return a list of human-readable strings, with an indented child.
    list_td = _list(ctx.obj['objs'], top_down=True, echo=False)
    assert(list_td[0][0] != ' ')
    assert(list_td[1][0] == ' ')
    assert('good' in list_td[0])

    ## This should return a list of human-readable strings, with an indented parent.
    list_bu = _list(ctx.obj['objs'], bottom_up=True, echo=False)
    assert(list_bu[0][0] != ' ')
    assert(list_bu[1][0] == ' ')
    assert('good' in list_bu[1])

    ## Test that the calendar_name template attribute works
    list_cal = _list(ctx.obj['objs'], template="{calendar_name}", echo=False)
    assert list_cal[0] == todo1.parent.get_display_name()
    assert list_cal[1] == todo2.parent.get_display_name()

    ## panic planning, timeline_suggestion.
    ## We have two tasks in the calendar, each with one hour duration
    timeline = timeline_suggestion(ctx, hours_per_day=24)
    assert(timeline.count() == 2)
    foo = timeline.get(datetime_(year=2012, month=12, day=20, hour=22, minute=35))
    assert foo['begin'] == datetime_(year=2012, month=12, day=20, hour=22, minute=15)
    assert foo['end'] == datetime_(year=2012, month=12, day=20, hour=23, minute=15)

    ## panic planning, timeline_suggestion with timeline_end
    ## Those two tasks should be neatly stacked up
    assert len(ctx.obj['objs'])==2
    timeline = timeline_suggestion(ctx, timeline_end=datetime_(year=2011, month=11, day=11, hour=11, minute=11), hours_per_day=24)
    assert(timeline.count() == 2)
    foo = timeline.get(datetime_(year=2011, month=11, day=11, hour=11, minute=10))
    assert foo['begin'] == datetime_(year=2011, month=11, day=11, hour=10, minute=11)
    assert foo['end'] == datetime_(year=2011, month=11, day=11, hour=11, minute=11)
    foo = timeline.get(datetime_(year=2011, month=11, day=11, hour=10, minute=10))
    assert foo['begin'] == datetime_(year=2011, month=11, day=11, hour=9, minute=11)
    assert foo['end'] == datetime_(year=2011, month=11, day=11, hour=10, minute=11)

    ## fix_timeline feature
    ## This will create events that are children of the tasks.
    ## (Those events contains a suggested timeslot for doing the task
    ## Task contains due date (may be a hard limit) and duration
    with patch('plann.panic_planning._now', new=lambda: datetime_(2010,10,9,23,33,33)) as _now:
        _check_for_panic(ctx, timeline_start='2010-10-10', timeline_end=datetime_(year=2010, month=11, day=11, hour=11, minute=11), hours_per_day=24, fix_timeline=True, include_all_events=True)

    ## Two events should be created by now
    _select(ctx, event=True)
    assert len(ctx.obj['objs'])==2

    ## Re-running it should be a noop
    _select(ctx, todo=True)
    with patch('plann.panic_planning._now', new=lambda: datetime_(2010,10,9,23,33,33)) as _now:
        _check_for_panic(ctx, timeline_start='2010-10-10', timeline_end=datetime_(year=2010, month=11, day=11, hour=11, minute=11), hours_per_day=24, fix_timeline=True, include_all_events=True)
    _select(ctx, event=True)
    assert len(ctx.obj['objs'])==2

    ## We now have one task with one subtask, and both tasks have two children
    ## events.  Let's find the uids
    e1 = [x for x in ctx.obj['objs'] if x.icalendar_component['summary'] == 'make plann good'][0]
    e2 = [x for x in ctx.obj['objs'] if x.icalendar_component['summary'] == 'fix some bugs in plann'][0]
    uide1 = str(e1.icalendar_component['uid'])
    str(e1.icalendar_component['uid'])

    ## Testing the _adjust_relations
    todo1.load()
    ## todo1 has children todo2 and e1.  _adjust_relations over those should be a noop
    with patch.object(todo1, 'save') as _t1save:
        with patch.object(todo2, 'save') as _t2save:
            with patch.object(e1, 'save') as _e1save:
                with patch.object(e2, 'save') as _e2save:
                    _adjust_relations(parent=todo1, children=[todo2, e1])
                    assert not any(x.call_count for x in (_t1save, _t2save, _e1save, _e2save))

    ## Testing to remove todo2 as child of todo1
    _adjust_relations(parent=todo1, children=[e1])
    todo1.load()
    todo2.load()
    e1.load()
    ## _adjust_ical_relations returns a dict if the object was changed
    assert(not _adjust_ical_relations(todo1, {'CHILD': {uide1}}))
    assert(not _adjust_ical_relations(todo2, {'PARENT': set()}))

    ## Testing interactive fix timeline, and checking that past events are ignored in the
    ## panic planning.
    ## We were busy with other things at the scheduled time.  Let's try to reschedule ...
    with patch('plann.commands._editor', new=passthrough) as _editor:
        with patch('plann.panic_planning._now', new=lambda: datetime_(2010,12,9,23,33,33)) as _now:
            _select(ctx, todo=True)
            _check_for_panic(ctx, timeline_start='2010-10-10', timeline_end=datetime_(year=2011, month=11, day=11, hour=11, minute=11), hours_per_day=24, print_timeline=False, interactive_fix_timeline=True, include_all_events=True)
    _select(ctx, event=True)
    assert len(ctx.obj['objs'])==4

    ## Reset ... let's connect todo1 and todo2 again, and remove events
    ## Reload to get fresh ETags — _check_for_panic modified these objects on the server
    todo1.load()
    todo2.load()
    _adjust_relations(todo1, {todo2})
    _adjust_relations(todo2, set())
    todo1.load()
    todo2.load()
    assert(not _adjust_ical_relations(todo1, {'CHILD': {uid2}, 'PARENT': set()}))
    assert(not _adjust_ical_relations(todo2, {'PARENT': {uid1}, 'CHILD': set()}))

    ## Testing the interactive relation edit - if doing nothing in the
    ## editor, the algorithm should change nothing.
    _select(ctx, todo=True)
    cal_pre_interactive_relation_edit = "\n".join([x.data for x in ctx.obj['objs']])
    with patch('plann.interactive._editor', new=passthrough) as _editor:
        _interactive_relation_edit(ctx.obj['objs'])

    for obj in ctx.obj['objs']:
        obj.load()
    cal_post_interactive_relation_edit = "\n".join([x.data for x in ctx.obj['objs']])
    assert cal_post_interactive_relation_edit == cal_pre_interactive_relation_edit

    ## Let's add some more tasks
    todo3 = _add_todo(ctx, summary=['fix some more features in plann'], set_parent=[uid1], set_due='2012-12-21 23:15:00', set_dtstart='2012-12-21 22:15:00', set_uid='todo3', set_category='plann')
    todo4 = _add_todo(ctx, summary=['make plann even better'], set_parent=[uid1], set_due='2012-12-21 23:15:00', set_dtstart='2012-12-21 22:15:00', set_uid='todo4')
    todo5 = _add_todo(ctx, summary=['use plann on a daily basis to find more bugs and missing features'], set_parent=[uid1], set_due='2012-12-21 23:15:00', set_dtstart='2012-12-21 22:15:00', set_uid='todo5')

    ## TODO: testing of set_category / set_categories should be moved to a separate test in test_lib / test_command / test_cli
    assert(set([str(x) for x in todo1.icalendar_component['CATEGORIES'].cats]) == {'plann', 'keyboard'})
    assert(set([str(x) for x in todo2.icalendar_component['CATEGORIES'].cats]) == {'plann', 'keyboard'})
    assert(set([str(x) for x in todo3.icalendar_component['CATEGORIES'].cats]) == {'plann'})

    uid3 = str(todo3.icalendar_component['uid'])
    uid4 = str(todo4.icalendar_component['uid'])
    uid5 = str(todo5.icalendar_component['uid'])

    todo1.load()
    assert(dag(todo1, 'CHILD') == {uid2: {}, uid3: {}, uid4: {}, uid5: {}})
    assert(dag(todo4, 'PARENT') == {uid1: {}})

    ## Let's add some incremental indentation to the last lines.
    ## This one will leave todo1 with two children, then the next lines are indented more.
    def add_indent(text):
        return f"{uid1}: todo1\n {uid2}: todo2\n {uid3}: todo3\n  {uid4}: todo4\n     {uid5}: todo5"
    with patch('plann.interactive._editor', new=add_indent) as _editor:
        _interactive_relation_edit([todo1])

    ## Reload the object list
    for obj in (todo1, todo2, todo3, todo4, todo5):
        obj.load()

    assert(dag(todo1, 'CHILD') == {uid2: {}, uid3: {uid4: {uid5: {}}}})
    assert(dag(todo2, 'PARENT') == {uid1: {}})
    assert(dag(todo5, 'PARENT') == {uid4: {uid3: {uid1: {}}}})

    ## This should not throw one into the debugger
    list_td = _list(ctx.obj['objs'], top_down=True, echo=False)

    def remove_parent(input):
        return f"{uid2}: todo2\n{uid3}: todo3\n  {uid4}: todo4\n     {uid5}: todo5"

    with patch('plann.interactive._editor', new=remove_parent) as _editor:
        _interactive_relation_edit([todo1])

    assert(dag(todo1, 'CHILD') == {})
    assert(dag(todo1, 'PARENT') == {})
    assert(dag(todo2, 'PARENT') == {})
    assert(dag(todo2, 'CHILD') == {})
    assert(dag(todo3, 'CHILD') == {uid4: {uid5: {}}})
    assert(dag(todo5, 'PARENT') == {uid4: {uid3: {}}})

    ## This should not throw one into the debugger
    #list_td = _list(ctx.obj['objs'], top_down=True, echo=False)

    def gen_prompt(ret):
        def prompt(*largs, **kwargs):
            return ret
        return prompt

    ## testing _interactive_edit
    with patch('click.echo') as _echo:
        ## ignore should do nothing
        with patch('click.prompt', new=gen_prompt('ignore')):
            _interactive_edit(todo1)
            ## no asserts needed
        ## complete should complete it
        with patch('click.prompt', new=gen_prompt('complete')):
            _interactive_edit(todo1)
            todo1.load()
            assert(todo1.icalendar_component['STATUS']=='COMPLETED')
            todo1.uncomplete()
        with patch('click.prompt', new=gen_prompt('postpone 1d')):
            _interactive_edit(todo1)
            todo1.load()
            assert(todo1.icalendar_component['DUE'].dt > datetime_(year=2023, month=9, day=19, hour=15))
        with patch('click.prompt', new=gen_prompt('set categories=foo')):
            _interactive_edit(todo1)
            todo1.load()
            assert(set([str(x) for x in todo1.icalendar_component['CATEGORIES'].cats]) == {'foo'})
        with patch('click.prompt', new=gen_prompt('set category=bar')):
            _interactive_edit(todo1)
            todo1.load()
            assert(set([str(x) for x in todo1.icalendar_component['CATEGORIES'].cats]) == {'foo', 'bar'})
        ## TODO: part, split, family
        ## TODO: cancel,

    ## testing mass interactive edit and mass interactive reprioritize
    ## with 0 objects, it would earlier raise an error.
    with patch('plann.interactive._editor', new=passthrough) as _editor:
        _mass_interactive_edit([], default='complete')
    for todo in (todo1, todo2, todo3, todo4, todo5):
        todo.load()
        assert todo.icalendar_component['STATUS'] == 'NEEDS-ACTION'
    with patch('plann.interactive._editor', new=passthrough) as _editor:
        _mass_reprioritize([todo1, todo2, todo3])
    with patch('plann.interactive._editor', new=passthrough) as _editor:
        _mass_interactive_edit([todo1, todo2, todo3], default='complete')
    for todo in (todo1, todo2, todo3, todo4, todo5):
        todo.load()
        assert todo.icalendar_component['STATUS'] == 'COMPLETED'

    ## check that duration won't change if due is moved
    ## TODO: run this for dtend and dtstart on an event as well
    command_edit(todo1, 'set due=2012-12-19 19:15:00', interactive=False)
    assert todo1.icalendar_component['DUE'].dt > todo1.icalendar_component['DTSTART'].dt

def test_check_pinned():
    conn_details = start_xandikos_server()
    try:
        with caldav.get_calendars(
            url=conn_details['caldav_url'],
            username=conn_details['caldav_user'],
            password=conn_details['caldav_password'],
            raise_errors=True,
        ) as calendars:
            _run_check_pinned_tests(calendars)
    finally:
        stop_xandikos_server(conn_details)


def _run_check_pinned_tests(calendars):
    ctx = MagicMock()
    ctx.obj = dict()
    ctx.obj['calendars'] = list(calendars)
    hour = datetime.timedelta(hours=1)
    now = _now()
    ## midnight two days ago - all pins are well in the past, whatever the time of day
    base = (now - 48*hour).replace(hour=0, minute=0, second=0)

    def task(summary, parent=None, rrule=None):
        kwargs = {'set_parent': [parent]} if parent else {}
        if rrule:
            kwargs['set_rrule'] = rrule
        return _add_todo(ctx, summary=[summary], set_due=f"{now + 48*hour:%F %H:%M:%S}", set_duration='1h', set_uid=summary.replace(' ', '-'), **kwargs)

    def uid(obj):
        return str(obj.icalendar_component['UID'])

    def pin(todo, begin, status='TENTATIVE', parents=None, summary=None):
        return _add_event(ctx, summary=summary or _summary(todo), timespec=(begin, begin+hour), set_status=status, set_parent=parents or [uid(todo)])

    def status(obj):
        obj.load()
        return obj.icalendar_component['STATUS']

    done = task('write report')
    not_done = task('fix bike')
    skipped = task('call mom')
    reviewed = task('water plants')
    parent = task('paint house')
    child = task('buy paint', parent=uid(parent))
    partial = task('tidy garage')
    early = task('early')
    late = task('late')
    pack = task('pack bag')
    food = task('buy food')
    edited = task('clean deck')
    weekly = task('weekly backup', rrule='FREQ=WEEKLY')
    screws = task('sort screws')

    ## two past pins of the same task - the first one is asked about
    ev_done_first = pin(done, base)
    ev_done = pin(done, base + 2*hour)
    ev_not_done = pin(not_done, base + 4*hour)
    ev_skipped = pin(skipped, base + 6*hour)
    ## already answered on an earlier run
    ev_reviewed = pin(reviewed, base + 8*hour, status='CONFIRMED')
    ## one event pinning both a task and its subtask
    pin(parent, base + 10*hour, parents=[uid(parent), uid(child)])
    ev_partial = pin(partial, base + 12*hour)
    ev_pack = pin(pack, base + 14*hour)
    ## shared with a task that is not done, so not offered for cancelling
    ev_shared = pin(pack, base + 16*hour, parents=[uid(pack), uid(food)], summary='shared pin')
    ## completed through the edit prompt
    ev_edited = pin(edited, base + 18*hour)
    ev_weekly = pin(weekly, base + 20*hour)
    ev_weekly_future = pin(weekly, now + 24*hour)
    ## partially done, a subtask is split out
    ev_screws = pin(screws, base + 22*hour)
    ## the day before, stored in different timezones.  "early" is 09:00
    ## UTC, but its wall clock time 18:00 sorts after the 10:00 of "late"
    day = (base - 24*hour).date()
    pin(early, datetime.datetime(day.year, day.month, day.day, 18, tzinfo=ZoneInfo('Asia/Tokyo')))
    pin(late, datetime.datetime(day.year, day.month, day.day, 10, tzinfo=ZoneInfo('UTC')))
    ## pinned for later, should not be asked about
    ev_future = pin(done, now + 24*hour)
    ev_not_done_future = pin(not_done, now + 24*hour)
    ## ongoing, should not be asked about
    ev_ongoing = pin(not_done, now - hour/2)
    ## pinned too long ago
    pin(skipped, now - 30*24*hour)

    answers = {'write report': 'y', 'fix bike': 'n', 'paint house': 'y', 'tidy garage': 'p',
               'pack bag': 'y', 'shared pin': 's', 'clean deck': 'e', 'weekly backup': 'y', 'sort screws': 'p'}
    asked = []
    echoed = []
    def prompt(text, default=None, **kwargs):
        if text.startswith('Was it done?'):
            question = [x for x in echoed if re.match(r'\d{4}-\d\d-\d\d \d\d:\d\d - ', x)][-1]
            asked.append(question)
            return answers.get(question.split(': ', 1)[1], 's')
        ## the edit prompt, the questions when splitting out a subtask
        replies = {'postpone': 'complete', 'Name for the subtask': default, 'what is the remaining': '1h',
                   'Summary of the parent': default, 'Should we postpone': '0h'}
        return next(v for k, v in replies.items() if text.startswith(k))

    def confirm_(text, **kwargs):
        if 'working on this' in text:
            ## the user declines to split out the work on the garage
            return not [x for x in echoed if ': estimate is ' in x][-1].startswith('tidy garage')
        return True

    completed = []
    orig_complete = caldav.Todo.complete
    def complete(self, *largs, **kwargs):
        completed.append(uid(self))
        return orig_complete(self, *largs, **kwargs)

    with patch('click.echo', new=lambda x='', **kw: echoed.append(str(x))):
        with patch('click.prompt', new=prompt):
            with patch('click.confirm', side_effect=confirm_) as confirm:
                with patch.object(caldav.Todo, 'complete', new=complete):
                    _check_pinned(ctx, lookback='7d')
    summaries = [x.split(': ', 1)[1] for x in asked]
    ## chronologically, whatever timezone the events are stored in
    assert summaries == ['early', 'late', 'write report', 'fix bike', 'call mom', 'paint house', 'tidy garage',
                         'pack bag', 'shared pin', 'clean deck', 'weekly backup', 'sort screws']
    ## shown in local time
    tokyo_local = datetime.datetime(day.year, day.month, day.day, 18, tzinfo=ZoneInfo('Asia/Tokyo')).astimezone(tz.implicit_timezone)
    assert asked[0].startswith(f"{tokyo_local:%F %H:%M} - ")
    ## asked about the other pins of the completed task, and about the two splits -
    ## not about the pin shared with an open task, nor the pins of a recurring task
    assert [x.args[0][:22] for x in confirm.call_args_list] == ['Cancel 2 other pinned ', "So you've been working", "So you've been working"]

    assert status(done) == 'COMPLETED'
    assert status(ev_done_first) == 'CONFIRMED'
    assert status(ev_done) == 'CANCELLED'
    assert status(ev_future) == 'CANCELLED'
    assert status(not_done) == 'NEEDS-ACTION'
    assert status(ev_not_done) == 'CANCELLED'
    assert status(ev_not_done_future) == 'TENTATIVE'
    assert status(ev_ongoing) == 'TENTATIVE'
    assert status(skipped) == 'NEEDS-ACTION'
    assert status(ev_skipped) == 'TENTATIVE'
    assert status(ev_reviewed) == 'CONFIRMED'
    ## the subtask is completed along with its parent, and only once
    assert status(parent) == 'COMPLETED'
    assert status(child) == 'COMPLETED'
    assert completed.count(uid(child)) == 1
    ## nothing was split out, so it is asked about again
    assert status(partial) == 'NEEDS-ACTION'
    assert status(ev_partial) == 'TENTATIVE'
    assert status(pack) == 'COMPLETED'
    assert status(ev_pack) == 'CONFIRMED'
    assert status(food) == 'NEEDS-ACTION'
    assert status(ev_shared) == 'TENTATIVE'
    assert status(edited) == 'COMPLETED'
    assert status(ev_edited) == 'CONFIRMED'
    ## the recurring task moves on to its next recurrence
    weekly_due = weekly.get_due()
    assert status(weekly) == 'NEEDS-ACTION'
    assert weekly.get_due() > weekly_due
    assert status(ev_weekly) == 'CONFIRMED'
    assert status(ev_weekly_future) == 'TENTATIVE'
    assert status(screws) == 'NEEDS-ACTION'
    assert status(ev_screws) == 'CONFIRMED'
    subtasks = [x for x in screws.get_relatives({'CHILD'})['CHILD'] if isinstance(x, caldav.Todo)]
    assert [_summary(x) for x in subtasks] == ['Work on sort screws']
    assert status(subtasks[0]) == 'COMPLETED'

    ## a second run only asks about the skipped ones
    answers.clear()
    asked.clear()
    with patch('click.echo', new=lambda x='', **kw: echoed.append(str(x))):
        with patch('click.prompt', new=prompt):
            with patch('click.confirm', return_value=False) as confirm:
                _check_pinned(ctx, lookback='7d')
    assert [x.split(': ', 1)[1] for x in asked] == ['early', 'late', 'call mom', 'tidy garage', 'shared pin']
    assert not confirm.called

    ## a server refusing to save does not stop the rest of the questions,
    ## and the other pins of a completed task are still offered for cancelling
    mow = task('mow lawn')
    ev_mow = pin(mow, base + 23*hour)
    ev_mow_future = pin(mow, now + 24*hour)
    answers.update({'early': 'n', 'late': 'n', 'mow lawn': 'y'})
    asked.clear()
    def set_event_status(event, status):
        if status == 'CONFIRMED' or _summary(event) in ('early', 'late'):
            raise PutError('423 Locked')
        return _set_event_status(event, status)
    with patch('click.echo', new=lambda x='', **kw: echoed.append(str(x))):
        with patch('click.prompt', new=prompt):
            with patch('click.confirm', return_value=True) as confirm:
                with patch('plann.commands._set_event_status', new=set_event_status):
                    _check_pinned(ctx, lookback='7d')
    assert [x.split(': ', 1)[1] for x in asked] == ['early', 'late', 'call mom', 'tidy garage', 'shared pin', 'mow lawn']
    assert any('423 Locked' in x for x in echoed)
    assert status(mow) == 'COMPLETED'
    assert status(ev_mow) == 'TENTATIVE'
    assert status(ev_mow_future) == 'CANCELLED'

## TODO:
## Things to be tested: lib._procrastinate, cli._select, cli._cats, cli._list, cli._interactive_edit, cli._set_something, cli._interactive_ical_edit, cli._edit, cli._check_for_panic, _add_todo, _agenda, _check_due,
