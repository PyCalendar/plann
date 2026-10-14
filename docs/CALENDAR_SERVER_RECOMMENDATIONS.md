# What CalDAV-server to choose?

Most caldav clients out there sync the calendar locally and operate on the local copy.  Plann is a thin client.  Some features in plann are dependent on the server having good CalDAV support.  Unfortunately the server supporting everything perfectly simply does not exist as of 2026.  At least not as far as I'm aware.

## TLDR-summary

**Xandikos** and **Radicale** are python-based calendaring servers for small, typically single-user setups.  They are easy to set up and get started with, and they are also actively developed.  I'd go with Xandikos, but YMMV.

**DAViCal** and **Cyrus** are solid choices if you need multi-user support and scheduling.  The author used DAViCal for many years and has since moved to Xandikos.  Cyrus is a full IMAP+CalDAV server with good scheduling support and only minor CalDAV quirks.

For Cloud/SaaS, there is no obvious winner — most tested providers have significant limitations for heavy plann use.  GMX is the least bad, and Purelymail may be worth checking out.  I have no idea about Google - it hasn't been tested for ages, it should probably be checked out.  iCloud should be avoided.

## Requirements

`plann` can be used towards any server offering some support for CalDAV - but to be able to efficiently use `plann` for planning, you will need a calendar server that supports ...

* Tasks (VTODO component type)
* Recurring events
* Recurring tasks
* Relationships (RELATED-TO property type)

Earlier this list included lots of requirements on how well the server supports searches.  The CalDAV library now supports doing client-side filtering when the server doesn't do the job well enough.  However, for a huge calendar with lots of obsoleted tasks and events, client-side filtering may involve quite a lot of network overhead.  **Also, it may be needed to specify buggy server-side behaviour in the configuration to enforce client-side filtration** - this is done with the `features` key in the config section, e.g. `"features": "davical"`.

Journals (VJOURNAL component type) are useful for logging completed work, and scheduling support is useful if you want to send and respond to meeting invitations.

## Different servers tested (self-hosting)

### Xandikos

https://www.xandikos.org/

Server written in Python, storing all data in a local git repository.  Super-easy to set up and get started with.  Quite standard-compliant and well-exercised, as it is included in the python caldav library test suite.  Lack of support for recurrences was a show-stopper until 2025; recurring tasks have been expanded properly since 0.3.7.  Basic scheduling support is present.

This is what the author uses.  **Recommended**.

Xandikos also supports address books (VCARD).

### DAViCal

DAViCal seems to be one of the most standard-compliant caldav servers out there, and it has been around for a decade or two.  It supports everything we need, including scheduling and multi-user access control.  It has a basic WebUI for administrating access rights, users, etc.  It also supports address books (VCARD).

It's written in PHP, needs a database backend (PostgreSQL) and a webserver frontend (Apache is probably easiest — though nginx + php-fpm also works).

Known limitations:
- Fragile sync tokens (may be important if you want to sync calendar changes to a local calendar - but plann doesn't support that yet).
- VTODOs without DTSTART may be skipped in some date searches

These are manageable, and DAViCal remains a solid choice when you need multi-user calendaring with scheduling.  **Recommended**.

### Radicale

https://radicale.org/

A server written in Python.  Very easy to set up.  It's included in the test suite of the python caldav library, so it's reasonably well-tested.  Relatively actively developed and as of 2026, relatively few issues remaining.

It does support multiple users with some permission settings, but it does not support the scheduling RFC.

Radicale also supports address books (VCARD).

### Baikal

https://sabre.io/baikal/

PHP-based application built on the sabre/dav library.

Recurring task support remains incomplete, and it has some issues with searches.  If you don't need recurring tasks, Baikal is otherwise quite usable.

Journals cannot be stored on the same calendar as events (mixed-calendar journal is unsupported).

Baikal also supports address books (VCARD).

### Davis

https://github.com/tchapi/davis

Another sabre/dav-based server (same backend as Baikal).  Has essentially the same compatibility profile as Baikal.

### Nextcloud

https://nextcloud.com/

Nextcloud has many components, including a calendar that appears to be based on sabre/dav.  The list of CalDAV limitations is similar to Baikal.

Be aware that Nextcloud applies fairly aggressive rate limits, which can break automated test runs and heavy API usage.

### Cyrus

https://www.cyrusimap.org/

A mature IMAP/CalDAV server with good scheduling support (both inbox delivery and auto-scheduling).  One of the better options in the compatibility matrix with few plann-relevant issues.  One of the minor issues worth mentioning is that recurring events/tasks are not found in time-range searches arbitrarily far into the future (same limitation as Baikal/Nextcloud).  **Recommended** for multi-user setups with scheduling.

### SOGo

https://www.sogo.nu/

"Groupware" supporting mail with a rich web interface.  Has been around for as long as the python caldav library.

SOGo does **not** support text search (category search, case-sensitive/insensitive search all unsupported or broken).  It does not support journals.  Recurrence search is fragile.  This makes it unsuitable for the advanced search features that plann relies on.

SOGo is probably very good if you want a web-based email and calendaring tool for syncing across many devices, but it is not adequate when a thin client like plann needs to search for specific events or tasks.

### Zimbra

"Groupware" supporting mail with a rich web interface.  The CalDAV support has many limitations and issues.  (A couple of happenings from production: 30 participants invited for a recurring meeting, one of the participants removing one instance from their calendar (using other CalDAV clients), whoosh, the whole recurring event cancelled for all the 30 participants.  Reloading a calendar from backup using plann, and whoosh, Zimbra sent out hundreds of meeting invites by email reminding attendees to come to meetings that happened ten years back in time).  It also drops RELATED-TO, so task hierarchies do not work, and tasks have to be kept on separate task lists.  **Not recommended**.

### Bedework

https://github.com/Bedework/bedework

Java-based enterprise calendar system, still maintained (5.0.0 was released in 2025).  Through CalDAV, a client cannot create a task or journal list, text search does not work, and all but the first RELATED-TO line are stripped.  **Not recommended** for plann.

### Robur

https://github.com/robur-coop/caldav  (cloud: https://calendar.robur.coop/)

Does not support relationship attributes, text search is non-functional (returns all elements regardless of filter), journals are rejected (ungraceful), sync-tokens are ungraceful, `get-supported-components` is unsupported.  **Not suitable for heavy plann usage**.

### Stalwart

https://stalw.art/

All-in-one mail and collaboration server with CalDAV support added in 2024/2025.  Actively developed.  From the known limitations, it's worth mentioning that it still has some issues with recurring events and tasks.  Worth watching as it matures.

### OX App Suite

https://ox.io/

OX rejects recurring tasks, mangles RELATED-TO, does not support journals, needs tasks in a calendar of their own and ignores several search filters (including time-range on tasks).  Searches only reach a sliding window around today: old events and tasks, and those far in the future, are not found.  **Not recommended**.

### Apple CalendarServer (CCS)

**Not maintained** - archived in 2019 (Python 2 / Twisted).  It has many issues.  It's mentioned for completeness only — do not use for new deployments.

## Calendar-as-a-service providers

### ecloud.global

Offers Nextcloud — see the Nextcloud section above.  Additionally requires aggressive rate limiting when running automated tests due to cache/trashbin behaviour.

### Posteo

https://posteo.de has many issues.  **Not recommended**

### GMX

CalDAV at `caldav.gmx.net`.

It has many issues, but most of them are not very relevant for "heavy plann usage".  One quirk worth knowing: a completed task cannot be un-completed.  If you want a service provider, GMX is definitely not the worst choice.

### Purelymail

https://purelymail.com

From the name it appears their selling point is that they focus on emails and nothing else - but they do have a CalDAV-compliant calendar service.

The server has memory indexes that are "lazily" populated — in practice there can be several minutes of delay between making a change and it appearing in the search results.  The compatibility matrix currently shows that quite many features are "fragile", possibly due to this.  If using plann first for doing changes and directly afterward trying to take out a fresh list, it will fail to show the updated data.  The developers are friendly enough, it could be worth investigating more and also report issues found upstream.

Scheduling is reported to be "work in progress".

### Fastmail

Does not support tasks and has various other issues.  The customer service denied me a free testing account, so no testing has been done for quite a while.  **Not recommended**.

### Google Calendar

Has not been tested for ages.  **TODO**.

### iCloud

Does not officially support CalDAV.  Tasks work only in a separate task calendar, journals and time-range searches on tasks are unsupported, old objects are invisible to searches, and recurrence searches came back unsupported (possibly an artefact of the search window).  **Not recommended**.

### Infomaniak

Hosted calendar based on sabre/dav.  Saving and most searches work well.  Journals, searches for recurring tasks and AND-combined searches are unsupported.  Usable if you don't need journals or recurring tasks.

### Yahoo

Events with a timezone are accepted but cannot be read back, RELATED-TO is refused (400 Bad Request), tasks need a calendar of their own, journals are refused, and recurrence searches are unsupported.  **Not recommended**.

## Non-free solutions

### Synology

Synology's calendar is a modified DAViCal, and its compatibility matrix matches DAViCal's except that calendars cannot be deleted.  It looks relatively decent; the problems should not be very relevant for heavy plann usage.

## Conclusion

In 2013, all I wanted to do was to set up a personal calendar and access it easily through the command line ... and I fell down a rabbit hole and have been fighting with the CalDAV protocol and iCalendar format for more than a decade.

Let me be completely honest: I'm not happy, neither about the CalDAV standard nor the iCalendar standard.  The protocols seem not very well thought-through, particularly when it comes to the task support (and using those standards for time tracking - forget about it!).  But this is what we have as of now.

The CalDAV protocol is designed so that the client can be relatively simple while most of the work is done on the server side (expansions, complex searches, etc).  Unfortunately server support for this is often broken.  My original plan for plann was always to leave all the complexity to the server, but in practice the client ends up doing a lot of client-side filtering and expansion to paper over server deficiencies.

The best current recommendation for self-hosting is **Xandikos** (version 0.3.7+, and the author's own choice) or **Radicale** if you need a simple setup, or **DAViCal** or **Cyrus** if you need multi-user and scheduling.
