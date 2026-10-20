# Changelog

The format of this file is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and I do try to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

* `plann freebusy-sync`: keeps a copy of the busy time from one set of calendars in another calendar, holding only the time and a fixed summary.  Copies are moved and deleted as the source changes, so it can run from a timer in both directions between a work and a private calendar.  See the user guide.

### Deprecated

* `select --freebusyhack`, superseded by `freebusy-sync`.  It keeps the UID of the original, and it leaves the summary, description and attendees of recurrence exceptions in place.

### Changed

* Completing a task (`edit --complete`, `complete` in the interactive and multi-edit modes, `completed!` in `set-task-attribs`) now also completes its pending child tasks, recursively, and prints a warning for each.  A child has to be done before the parent can be completed.
* `completed!` in `set-task-attribs` moves a recurring task on to its next recurrence, like `edit --complete` does, instead of completing the whole series.
* Shell tab completion scripts (bash, zsh, fish) now ship with the package.  They work without shell configuration for system-wide installs (and for bash user/venv installs with bash-completion 2.12+); see the README for other setups.  The `make install-completion` targets are gone.
* icalendar 6.2.0 or newer is required.
* caldav 3.6 or newer is required.  The config file is now read as caldav 3.6 reads it, so it may also use `kind: caldav` sections with plain keys, `password_command` (a program printing the password) and `password_keyring`, and `~/.config/pycal/calendar.yaml`.

### Fixed

* `interactive set-task-attribs` (also run by `interactive manage-tasks`): a task marked `completed!` at one prompt was asked about again at the next one, and answering `completed!` there crashed on the already-completed task.  Regression in v1.2.0.
* `list-categories` and timewarrior time tracking crashed on a task with more than one CATEGORIES line.  https://github.com/pycalendar/plann/issues/71
* `{CATEGORIES}` in a `list --template` printed the internal `vCategory([...])` representation instead of a comma-separated list.

## v1.2.0 - 2026-09-16

### Added

* `edit --add-categories`, `--add-resource` and `--add-resources` options (alongside the existing `--add-category`).  A single value containing commas is split by the plural forms and kept literal by the singular forms.
* `select ... list --separator=...` to join the listed items with something other than a newline.
* The interactive edit prompt now offers the `start` command (starts time tracking for the task) and asks again afterwards, so a follow-up command can be given for the same task.
* `plann configure`: an interactive configuration mode (EXPERIMENTAL, under-tested) that prompts for connection parameters and writes them to the config file - a new section, or an existing one with its current values offered as defaults.
* Environment variable references - `${VAR}` or `${VAR:-default}` - in the connection settings of a config section (`caldav_url`, `caldav_user`, `caldav_pass`, `caldav_proxy`, ...) are now expanded, so e.g. the password can be kept out of the config file.  See the configuration section of the README.
* `add ical` warns when the imported data holds RECURRENCE-ID overrides with no master event for the same UID - typically left behind when the recurring event was deleted elsewhere, or exported one instance at a time.  They are still imported: merged into the series when the server has the master, stored as detached occurrences otherwise.

### Changed

* `select --uid` now prints a warning to stderr naming uids that match nothing in any calendar, instead of ignoring them silently.  `--no-warn-on-missing-uid` restores the silent behaviour; `--abort-on-missing-uid` still takes precedence.  Ref https://github.com/pycalendar/plann/issues/42
* `edit --set-resources` now splits its value on comma, the same way `--set-categories` always has: `--set-resources a,b` sets two resources rather than one named `a,b`.
* Config file parsing, connection parameter extraction and calendar lookup are now done by the caldav library instead of plann's own copy of that code, and a `features` key is resolved through the caldav library's server profiles.
* Fewer server round-trips: a hierarchical `list --top-down`/`--bottom-up` fetches each related task only once, and `interactive set-task-attribs` fetches the task list once instead of querying per attribute.
* Dependencies: caldav 3.3.0 or newer is now required (was 1.5.0), `python-dateutil` and `icalendar_searcher` are new dependencies, and `tzlocal` is no longer needed.  The package metadata now declares the license as GPL-3.0-or-later.

### Deprecated

* `edit --set-category`: it *appends* rather than replaces, which the name does not convey.  Use `--add-category` to append or `--set-categories` to replace.

### Removed

* `interactive update-config`, which was never implemented and only raised an error.  Use `plann configure`.

### Fixed

* Time tracking through timewarrior did not work at all: the `time_tracking` setting in a config section was never picked up, only the value `timew` was accepted (not `timewarrior`, as the error message suggested), and `select ... add-time-tracking` aborted with "Invalid start character for option" before doing anything.
* `add ical` with several concatenated VCALENDAR objects imported nothing when the data used CRLF line endings (the RFC 5545 canonical form).
* Showing help for a subcommand (e.g. `plann select --help`) no longer connects to every configured calendar.
* A config section with `features` but no `caldav_url` crashed with `KeyError: 'url'`; the URL is now taken from the server profile.
* `select ... delete` now names each item as it is deleted, and says "No items selected for deletion" on an empty selection, instead of printing nothing either way.  Ref https://github.com/pycalendar/plann/issues/42
* Durations were computed wrongly: `1y` came out as roughly 15 days, and a compound duration such as `1h30m` kept only its last component.  Adding a year to a plain date, or to February 29, raised an error.  A fractional number of years (`1.5y`) is now rejected instead of being miscalculated.
* `interactive check-due --limit N` crashed instead of limiting the number of tasks shown.
* `select --no-pinned-tasks` crashed when tasks were included in the selection.
* Splitting a task interactively (the `split` edit command, `interactive split-huge-tasks`, `interactive split-high-pri-tasks`) never postponed the task: the postpone prompt was inverted, so a duration was ignored and only the `0h` default reached the postpone code, where it did nothing.
* `postpone <duration> with parent` in interactive editing silently did nothing.
* The relationship overview showed only the first kind of relation, so e.g. children were listed but parents were not.
* Panic planning (`check-for-panic`, `dismiss-panic`) no longer crashes on all-day events that have relations.
* Adding a category to an object with more than one `CATEGORIES` line crashed.
* Reporting an inconsistent relationship crashed instead of logging what was wrong.
* Postponing a task with a long chain of parents could drop the user into the Python debugger.
* An object whose summary or description contained text like `BEGIN:VEVENT` could be taken for the wrong kind of object - e.g. a task refused by interactive editing as if it were an event.
* Commands that open a text editor (`select --mass-interactive`, `edit --interactive-ical`, `edit --interactive-relations`, ...) now say clearly that no editor could be found, instead of failing confusingly further down.
* `interactive set-task-attribs` could miss tasks lacking an attribute on calendar servers that do not filter searches properly.

## v1.1.1 - 2026-05-28

### Added

* Added possibility to add calendar name and calendar url to the template.  Ref https://github.com/pycalendar/plann/issues/14 by @rjolina at github.
* `now` should be an acceptable timestamp.  Ref https://github.com/pycalendar/plann/issues/16
* Natural language timestamps now supported via `dateparser` — "yesterday", "3 hours ago", "Friday", etc. are accepted wherever a timestamp is expected.
* VJOURNAL support: new `plann add journal` command and `--journal` filter flag on `select`.  Ref https://github.com/pycalendar/plann/issues/29
* Makefile with `install`, `dev`, `test`, `lint`, and `clean` targets, plus shell tab completion install targets.
* `features` config key is now passed to the caldav library, enabling server-specific compatibility workarounds (e.g. `"features": "davical"`).

### Changed

* Various documentation improvements, some of it by @WhyNotHugo at github in https://github.com/pycalendar/plann/pull/15

### Fixed

* `--help` had some wrong information, ref https://github.com/pycalendar/plann/issues/16 by Thomas Maeder
* Importing a VCALENDAR file containing multiple events/tasks failed.
* `procrastinate 0s` (and other zero-delay variants) was not treated as a no-op due to a typo (`'9s'` instead of `'0s'`).
* Timezone was incorrectly applied to all-day dates (`datetime.date`), causing off-by-one errors.
* When selecting by UID, component type (`--event`/`--todo`) no longer needs to be specified, and completed tasks are no longer incorrectly filtered out.

## v1.1.0 - 2026-05-28

Same as v1.1.1, except the publishing workflow was not working

## v1.0.0 - 2024-12-01

Changelogs up until 1.0 has been dropped, as development was going
rather fast-paced and erratic, with the priority of getting a tool the
author can use for his daily planning.  Very little development was
done in 2024 and 2025, but the tool works for me.

The 1.0.0-version probably has plenty of rough edges as it hasn't been
tested much and is lacking some test code, but if nothing else I will
try to stick to better development practices from now on - not
breaking backward compatibility unless I really have to (and then
under a 2.0-release), fewer commits with sane commit messages towards
the main branch, silly commits going to side branches, keep the
changelog up-to-date, make sure new features are sufficiently covered
by test-code, etc.
