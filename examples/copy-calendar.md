# Copy everything from one calendar to another

## Use cases

* Migrating from one calendar server to another
* Copy "freebusy"-information from one calendar to another: Your family is not allowed to know all the details about your agenda at work, but they need to know when you will be busy with meetings etc.  Your colleagues does not need to know weather you have an appointment at the doctor, a job interview with a potential new employer or a meeting with your childrens teacher, but they do need to know that you're not avaiable for work in that period.

## Full commands

Copy from your default calendar to a calendar marked up as "new calendar" in the config:

```bash
plann select print-ical | plann --config-section new-calendar add ical
```

**Caveat**: If exporting calendar data from Zimbra, and then importing it into another Zimbra calendar (probably any calendar that supports scheduling, the bug is at the export side of things), then there is a risk that meeting invitations and RSVP-replies are resent by email to participants and organizers of events.

Take the events from the work calendar and mark up in your default calendar that you will be busy with work events at those times:

```
 plann --config-section work select --event --begin 2023-10-01 --freebusyhack 'event from work calendar' print-ical | plann add ical
```

**Caveats**:

* The `--freebusyhack` option may be replaced with something different in a future version of `plann`.
* You probably should not do this if you work at some very secret military facility or as an undercover police agent or anything like that - even the start- and end times of your events may be confidential information, and there may potentially be other confidential information leaking over.

## Sub-task: take out all data in raw ical from the calendar

`plann` without any options will select the default calendar from the configuration file (`~/.config/pycal/calendar.yaml` or another file on the shared search path, see the README).

`plann select` without any options will select everything.

`plann select print-ical` will print all the data to STDOUT.

## Sub-task: insert all the data into the new calendar

`plann add ical` will add raw ical data to a calendar.  You would typically like to add options like `--ical-data=...` or `--ical-file=...`, but if it's not given, then it will default to collect data from STDIN.

## Variants

(None of this was tested)

Copy all events, ignore tasks:

```bash
plann select --events print-ical | plann --config-section new-calendar add ical
```

Copy only uncompleted tasks:

```bash
plann select --todo print-ical | plann --config-section new-calendar add ical
```

Copy only future events:

```bash
plann select --event print-ical --from=$(date +%F) | plann --config-section new-calendar add ical
```

Copy everything, but without a config files:

```
plann --caldav-url=https://example.com/dav/ --caldav-user=peter --caldav-pass=hunter2 --caldav-proxy=socks5://localhost:1080 --calendar-name='Calendar' select print-ical |
  plann --caldav-url=https://newcal.example.com/ --caldav-user=peter --caldav-pass=hunter3 add ical
```
