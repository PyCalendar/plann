# plann

Plann is a command-line CalDAV client, making it possible to add calendar events, browse an agenda and do task management.

This is the "next generation" version of my old [calendar-cli project](https://github.com/pycalendar/calendar-cli/).

Perhaps this work is moot ... or perhaps just 20 years too late.  Considering the recent progress of AI and chatbots, probably soon all calendar queries can be done in natural language.

## Other tools

There is a "competing" project at https://github.com/geier/khal - you may want to check it out - it's more mature but probably more complex.  khal uses a "vdir" backend; a local directory with icalendar files. It is designed to operate offline (while some other tool can optionally synchronise this with a remote server). The philosophy behind plann and calendar-cli is the opposite: interact directly with a caldav server; no synchronisation, no local storage, just client-side operations.

## New vs old interface

Based on user feedback I decided to fork `calendar-cli` into `plann`.  The discussion was held in a github issue in the calendar-cli project.  calendar-cli is the old, mature, production-ready, stable API interface, it will hang around for some time to come, maybe I will spend some time bugfixing it, and I will for sure be accepting pull requests in a long time to come - at least if they primarily address bugfixes.  plann is the new interface, I believe it can do all that calendar-cli is doing as of version 1.0.

## Usage examples

The commands and options will be described further down, however examples often beat documentation.  There is one example directory with some usage examples, and eventually I will also try to write up some test code that can serve as examples.

## Installation

`plann` depends on several python libraries, e.g. [icalendar](https://pypi.org/project/icalendar/), [caldav](https://pypi.org/project/caldav/), etc.

### Systemwide Install

1. Clone this repo, cd to `plann`
2. `sudo make install`

### User Install

Installs `plann` under `~/.local/` (no root required):

1. Clone this repo, cd to `plann`
2. `make install`

### Development Install

An editable install, so changes in the working tree take effect without reinstalling:

1. Clone this repo, cd to `plann`
2. `make dev` (installs with `pip install -e ".[dev]"`, including the test dependencies)
3. Run via `plann`

### Tab completion

The package ships completion scripts for bash, zsh and fish.  For a system-wide install under `/usr` (e.g. a distribution package) they work with no shell configuration - bash needs the `bash-completion` package installed, though.  For bash, a `--user`, venv, pipx or `uv tool` install also works out of the box with bash-completion 2.12 or newer, and fish picks up a `--user` install.  Elsewhere, point the shell at the install prefix:

* zsh: `fpath=(<prefix>/share/zsh/site-functions $fpath)` before `compinit`
* fish: `set -a fish_complete_path <prefix>/share/fish/vendor_completions.d`
* bash: `source <prefix>/share/bash-completion/completions/plann`

## Support

\#calendar-cli at irc.oftc.net (I'm not available 24/7 there), eventually support@plann.no, eventually the issue tracker at https://github.com/pycalendar/plann/issues

Before reaching out, please make sure all the dependencies are installed, and that you've installed the latest version of the caldav python library.  If you're using the master branch of plann, you should also be using the master branch of the caldav python library.

## Rationale

GUIs and Web-UIs are nice for some purposes, but I really find the command line unbeatable when it comes to:

* Minor stuff that is repeated often.  Writing something like "todo add make a calendar-cli system" or "calendar add 'tomorrow 15:40+2h' doctor appointment" is (for me) faster than navigating into some web calendar interface and add an item there.  At least when I'm sitting by the laptop.
* Things that are outside the scope of the UI.  Here is one of many tasks I'd like to do: "go through the work calendar, find all new calendar events that are outside office hours, check up with the personal calendar if there are potential conflicts, add some information at the personal calendar if appropriate", and vice versa - it has to be handled very manually if doing it through any normal calendar application as far as I know, but if having some simple CLI or python library I could easily make some interactive script that would help me doing the operation above.

When I started writing `calendar-cli`, the predecessor to `plann`, all I could find was cadaver and the CalDAVClientLibrary.  Both of those seems to be a bit shortcoming; they seem to miss the iCalendar parsing/generation, and there are things that simply cannot be done through those tools.

## Synopsis

See also [`USER_GUIDE.md`](USER_GUIDE.md)

    plann [global options] [command] [command options] [subcommand] [subcommand options] [subcommand arguments] ...

I'm intending to make it easier by allowing `plann` to be symlinked to the various commands and also to allow the options to be placed wherever.

### Global options

Only long options will be available in the early versions; I don't
want to pollute the short option space before the CLI is reasonably
well-defined.

Always consult --help for up-to-date and complete listings of options.
The list below will only contain the most important options and may
not be up-to-date and may contain features not implemented yet.

* --caldav-url, --caldav-user, --caldav-pass: how to connect to the CalDAV server.  (Fits better into a configuration file)
* --calendar-url: url to the calendar one wants to use.  A relative URL (path) or a calendar-id is also accepted.
* --config-file: use a specific configuration file (default: $HOME/.config/calendar.conf)
* --config-section: use a specific section from the config file (i.e. to select a different caldav-server to connect to)
* --icalendar: Write or read icalendar to/from stdout/stdin
* --nocaldav: don't connect to a caldav server
* --timezone: any "naive" timestamp should be considered to belong to the given time zone, timestamps outputted should be in this time zone, timestamps given through options should be considered to be in this time zone (Olson database identifiers, like UTC or Europe/Helsinki). (default: local timezone)

The caldav URL should be something like i.e. http://some.davical.server/caldav.php/ - it is only supposed to relay the server location, not the user or calendar.  Things will most likely work if you give http://some.davical.server/caldav.php/pycalendar/work-calendar/ - but it will ignore the calendar part of it, and use first calendar it can find - which perhaps may be `tobixen/family-calendar/`.  Use http://some.davical.server/caldav.php/ as the caldav URL, and `/pycalendar/family-calendar` as the calendar-url.

### Commands

The list may not be complete.  `--help` should give a more complete overview.

* list-calendars: lists the calendars that plann can see
* configure: interactive configuration mode (EXPERIMENTAL/under-tested) - prompts for connection parameters and writes them to the config file
* agenda: Convenience command, lists upcoming events and tasks
* add: adds new events/items to todo lists/calendars
* select: select/search/filter tasks/events to list/modify/mark complete and so forth
* interactive: a collection of interactive convenience commands

### Event time specification

Supported since `calendar_cli` (predecessor to `plann`) v0.12:

* anything recognized by dateutil.parser.parse()
* An iso time stamp, followed with the duration, using either + or space as separator.  Duration is a number postfixed by s for seconds, m for minutes, h for hours, d for days, w for weeks and y for years (i.e. 2013-09-10T13:37+30d)
* ISO dates.  For full day events, make sure to specify the duration in days.

Some of those may already be implemented, all should eventually work in some future version of plann:

* Two ISO timestamps separated by a dash (-)
* "tomorrow" instead of an ISO date
* weekday instead of an ISO date (this seems supported already by dateutil.parser.parse)
* clock time without the date; event will be assumed to start within 24 hours.

Alternatively, endtime or duration can be given through options

### Getting out customized information through --todo-template and --event-template

This is a string containing variables enclosed in curly braces, like "uid: {uid}".  Full documentation of the available variables will be given in version 1.0.

Particularly the uid can be useful, as one may want to use the uid for things like deleting events and postponing tasks.

In the examples folder there is a task management script which will use the --todo-template to create a new shell script for postponing all overdue tasks.  This shell script can then be edited interactively and run.

### Task management

With the todo-command, there are quite some options available (i.e. --categories, --limit, --todo-uid, etc) to select or filter tasks.  Those are used by the commands list, edit, postpone, complete and delete.  A typical use-case scenario is to first use the "list" command, tweak the filtering options to get a list containing the tasks one wants to operate with, and then use either edit, postpone, complete or delete.

The file TASK_MANAGEMENT.md contains some thoughts on how to organize tasks.

## Configuration file

Configuration file is by default located in $HOME/.config/calendar.conf.  `plann` supports both json and yaml.

(I considered .ini, but I was told that it's actually not a standard.  I'd like any calendar application to be able to access the file, hence calendar.conf and not plann.conf)

The file may look like this:

```json
{ "default":
  { "caldav_url": "http://foo.bar.example.com/caldav/",
    "caldav_user": "luser",
    "caldav_pass": "insecure"
  }
}
```

The file can be written by hand, or created and updated interactively with `plann configure` (experimental/under-tested - here be dragons).

The connection settings (`caldav_url`, `caldav_user`, `caldav_pass`, `caldav_proxy`, ...) may refer to environment variables as `${VAR}`, or as `${VAR:-default}` with a fallback value.  This keeps secrets such as the password out of the file:

```json
{ "default":
  { "caldav_url": "http://foo.bar.example.com/caldav/",
    "caldav_user": "luser",
    "caldav_pass": "${CALDAV_PASSWORD}"
  }
}
```

Instead of a password in the file or the environment, `caldav_password_command` may name a program (as a list of the program and its arguments) whose output is the password, and `caldav_password_keyring` a service name to look up in the system keyring:

```yaml
default:
  caldav_url: http://foo.bar.example.com/caldav/
  caldav_user: luser
  caldav_password_command: [pass, show, dav/work]
```

The command is only run when the config file is writable by nobody but its owner (`chmod 600`); `plann configure` writes the file with your umask, so check it after configuring.  A section may also be written as `kind: caldav` with plain keys (`url`, `username`, `password_command`, ...).  The file format is shared with the caldav library and other tools, and is specified in [calendaring-config](https://github.com/pycalendar/calendaring-config/blob/main/docs/format.md).

A `features` key may be given to enable server-specific compatibility workarounds, referring to a server profile in the caldav library's `compatibility_hints` module (e.g. `"features": "ecloud"`).  For servers with a known profile, `caldav_url` may even be omitted - the caldav library will derive the URL from the profile.

A configuration with multiple sections may look like this:

```json
{
"default":
  { "caldav_url": "http://foo.bar.example.com/caldav/",
    "caldav_user": "luser",
    "caldav_pass": "insecure"
  },
"baz":
  { "caldav_url": "http://foo.baz.example.com/caldav/",
    "caldav_user": "luser2",
    "caldav_pass": "insecure2"
  }
}
```

Sections may also include calendar urls or ids, and sections may inherit other sections:

```json
{
"default":
  { "caldav_url": "http://foo.bar.example.com/caldav/",
    "caldav_user": "luser",
    "caldav_pass": "insecure"
  },
"baz":
  { "caldav_url": "http://foo.baz.example.com/caldav/",
    "caldav_user": "luser2",
    "caldav_pass": "insecure2"
  }
},
"bazimportant":
  { "inherits": "baz",
    "calendar_url": "important"
  }
```

* `plann` will accept a parameter `calendar_name`, which should match with the display name of the calendar.

* YAML seems to have more traction than JSON when it comes to configuration that is supposed to be read and edited by humans, hence `plann` will accept configuration files in yaml as well as json.

* Since `plann` may operate at many calendars at one time, I decided to add the keyword "contains" to have one config section refer to multiple other config sections.

Example:

```yaml
---
work-calendar:
  caldav_url: "http://acme.example.com/caldav/"
  caldav_user: drjekyll
  caldav_pass: pencilin
  calendar_url: mycalendar
work-appointments:
  inherits: work-calendar
  calendar_url: mypatients
private-calendar:
  caldav_url: "https://ecloud.global/remote.php/dav/"
  caldav_user: mrhyde
  caldav_pass: hunter2
  calendar_name: goodgames
brothel-appointments:
  inherits: private-calendar
  calendar_name: badgames
work:
  contains: [ 'work-calendar', 'work-appointments' ]
private:
  contains: [ 'private-calendar', 'brothel-appointments' ]
```

## Usage example

Add a calendar item "testevent" at 2013-10-01:

    ./plann --calendar-url=http://calendar.bekkenstenveien53c.oslo.no/caldav.php/tobias/calendar/ --caldav-server=http://calendar.bekkenstenveien53c.oslo.no/caldav.php --caldav-user=myusername --caldav-pass=mypassphrase add event testevent 2013-10-01

Add a todo item "change oil":

    ./plann --calendar-url=http://calendar.bekkenstenveien53c.oslo.no/caldav.php/tobias/calendar/ --caldav-server=http://calendar.bekkenstenveien53c.oslo.no/caldav.php --caldav-user=myusername --caldav-pass=mypassphrase add todo "change oil"

See USAGE.MD for further instructions on how to use `plann`.

## Objectives

* It should be really easy and quick to add a todo-list item from the command line.
* It should be really easy and quick to add a calendar item from the command line.
* It should be possible to get out lists ("agenda") of calendar items and todo-items.
* Interface for copying calendar items between calendars, even between calendars on distinct caldav servers

## Roadmap

See [`NEXT_LEVEL.md`](NEXT_LEVEL.md) for the direction the project is heading.
