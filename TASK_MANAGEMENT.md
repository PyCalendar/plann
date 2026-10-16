# Managing tasks through plann

plann is a flexible cli tool for accessing, adding and editing events, tasks and journals - you should be able to do just anything with it (and if not, raise an issue).  However, it is also quite much optimized towards what the author consider to be good task management procedures.  There now exists an "interactive mode" for supporting this.  In this document I will give recommendations for what I consider is "good practice" as well as guide you through those task management procedures.

## What is a task?

In my paradigm, a task is a planned activity that should be done, possibly within some specific time interval, but there is some flexibility as to exactly when it should be done.  When the task is done - or when it is deemed irrelevant to do it - it can be striken out from the list.

## What's in a "task" ...

By using standards, plann should interoperate well with other calendaring and task management tools.  The icalendar standard (RFC 5545) sets some limits on what data we can store in a task on a calendar - unfortunately the standard leaves quite much up to the users and implementations - it lacks guidelines on how to use the standard, and there are frequently multiple ways of achieving the same means.  One often gets into dilemmas ... when to use the category field vs when to use the location field vs when to branch out a completely distinct calendar, etc.  Here are some information about what can and cannot go into a task, how plann is dealing with it today, and a bit information on the future plans.

### List of properties and subcomponents

While not a property in itself, every task belongs to one or more calendars.  I do have some considerations below on when it makes sense to split tasks onto different calendars.

RFC5545 defines the following properties and subcomponents for a task (aka a VTODO calendar component):

* alarm
* uid
* dtstamp
* dtstart
* duration
* due
* class
* completed
* created
* summary
* description
* geo
* last-mod
* location
* organizer
* percent
* priority
* recurid
* seq
* status
* summary
* url
* rrule
* attach
* attendee
* categories
* comment
* contact
* exdate
* rstatus
* related
* resources
* rdate

RFC7986 adds those:

* color
* image
* conference

RFC9073 adds those:

* vlocation
* participant
* vresource
* styled-description
* structured-data

RFC9253 adds those:

* concept
* link
* refid

... and in addition, a task may belong to one or more calendars.

(It's also possible for a program like plann to add custom properties)

Almost all of the properties above are mentioned below.


### Calendar scope

**TLDR**: split tasks out on different calendars if different people should have access to read/edit/add tasks.

Calendars (aka "task lists" when used for tasks) aren't a part of RFC 5545, but most likely you will be using a calendar server that allows a user to have multiple calendars.  plann also allows the user to connect to several calendar servers.  Does it make sense to create several calendars?

In some calendaring solutions every person is supposed to have a calendar, and in addition every shared resource (i.e. meeting room, car, etc) that may need to be booked should have a separate calendar.  This may be fine - but keep in mind that it may not always be trivial to move, copy or synchronize tasks forth and back between two calendars (it is on the roadmap to allow synchronizing of two calendars through plann), so if it makes sense to reassign a task to a different person, then perhaps it's not a good idea to have one task list per person.

I believe it's best to keep as few calendars as possible, and rather use i.e. the categories/resources/refid/concept fields for splitting different types of tasks.  

As you can give access rights to other people for a whole caldav calendar (or "task list"), it makes sense to use the calendar level to control access rights.  You would typically like to have one calendar where your family can view/add tasks, other for work, perhaps separate calendars for separate projects at work if different projects involves different people, etc.

I have a boat, and it requires a lot of maintenance and attention.  Should I create a separate calendar for boat maintenance tasks?  Considering the thoughts above, what matters is whomelse should have the rights to view and add tasks.  I consider the boat to be a family project, so I use the same calendar as for other family/home-related todo-tasks.

Plann is able to collect data from multiple calendars and show it side by side.  Plann is (as of 2023-04) not optimized to display what calendar the task is coming from.  It's also not optimized for easily put different tasks to different calendars. 

### Location

A named location.

**TLDR**: plann is not optimzed towards using this property.

With events, the location field is frequently used for which meeting room the meeting should be at, or the address of an appointment.  It's often checked up just before the meeting, or copied to the navigator when one is heading for the appointment.  Tasks are different, if you are at some specific location you would typically like to check up all tasks at that location or in the neighbourhood and see if you can do some of them.

I had an idea that some tasks are only possible to do at a specific location (i.e. as a boat owner, there are lots of tasks that can only be done "at the boat", some work can be done from home, some work has to be done from the office, some work should be done in the garden, etc), and when being at that location, one would like to list out the pending tasks that applies for that location.  However, practical experience shows that "boat", "office", "home", "garden", "grocery store", "hardware store", etc are possibly better suited as a category than as a location.  Generally, if you have a lot of tasks connected to the same address, probably it's better to do it as a category rather than location.  If the location is a single-off thing used only for that specific task (or, perhaps, some very few tasks) then obviously it's better to use location than category.

Location is a free-text field; RFC9073 adds a VLOCATION subcomponent for a more structured way of adding location information.

### Geo

TLDR: plann is not optimized towards using this property

A geo is a location given by coordinates.  It probably makes great sense to use geo ...

* if you want to stick the tasks to a map.  Probably very useful if your tasks have to be done on lots of different locations (i.e. if you are a travelling salesman or a plumber).
* if you want to set up the phone to automatically remind you about tasks i.e. when you are close to the supermarked, etc.  (however, most of us probably have several supermarkets we can go to, so geo doesn't make sense for that)

### Categories, resources, concept, refid

**TLDR:** this is considered to be an important property

I'd like to think of categories as tags that can be stuck to tasks, and then used to filter out relevant tasks.  This only works well if one is consistently using the same tags - so think carefully about this one; make a list of keywords to be used for filtering and grouping tasks, so that you can easily retrieve a list of tasks when you're in the appropriate location, when you're in the appropriate mood, when you have the right tools available, when the weather allows for the task to be performed, etc.

Some tasks should be done while sitting by the keyboard.  Some tasks are related to a particular project.  Some tasks are best done when the weather is good.  Some tasks (i.e. visit some office) has to be done in the "business day time".  Add tags for this and other relevant stuff.  When the sun is shining and you want to do some outdoor tasks, filter out the tasks with categories "sunny" or "garden".

When to use location or geo, and when to use a category?  I ended up with an easy answer to that: just use categories for everything!  I think that for the super market example, geo is not really fitting because it can only be one geo coordinate related to a vtodo, but there are many super markeds that can be visited.  One could also think that "supermarked" is not a good location for the same reason.  In practice, I've never used location and geo, always been sticking such information into the categories instead.

While the categories field is a freetext field, it's important that the same categories are used consistently - and to keep consistent, it's important to know what categories are already in use, you may use `cli select --todo list-categories`.

My usage of categories may be slightly superceded by "concept", "link" and "refid", as defined in RFC9253.  I should look into that and consider if it's useful for plann.

After some thinking, I've considered that quite much of what I use "categories" for would possibly be more appropriate to put in the "resources"-field.  "Good weather" may be considered as a resource rather than a category, "keyboard" may be considered a resource, "supermarked" may be considered to be a resource.  When having a certain set of resources available it makes sense to do as many tasks as possible with the given set of resources.  Resources may be missing, then the alternatives are to find the missing resources (or travel to them ... or try to make without them) or to postpone the task until the resources are available.  Resources can now be edited just like categories (`edit --add-resource`/`--add-resources`/`--set-resources`), but plann has no resource-aware planning logic yet.

RFC9073 also defines vresource, which is a more structured way of specifying resources.

### Related

There are multiple kinds of relationships that may be useful for task management.  RFC5545 only supports PARENT-CHILD and SIBLING.  RFC9253 expands a bit on this to make more complex task management supported.  RFC9253 is (as of writing) reasonably fresh, and I got aware of it only today (2023-02-02).  All my prior thinking has been around how to (ab)use the PARENT-CHILD relationships - but I will definitively look into better support for the different relationship types listed in RFC9253 soon.

Here are three different ways to think of relationships:

#### Pending-Dependent

If task A cannot be done without task B being done first, we say that A depends on B.  We may want to construct a bikeshed, then paint it red.  Obviously the painting depends on the construction.  It may make sense to hide the paint job from the todolists, or maybe fade it away - when checking the list of immediate tasks to be executed, "painting the bikeshed" is just noise.  It may also make sense to ensure the due date for the construction is before the due date for the painting.

Within RFC5545 one can try to use parent-child-relationships for this purpose - think of the parent as the dependent and the child as the pending.  "Paint the bikeshed" would then be a parent of "construct a bikeshed".  That makes perfect sense, doesn't it?

RFC9253 has explicit support for dependencies, but it also supports "temporal relationships" - i.e. task A needs to be finished 3 hours before it's possible to start working with task B, task C needs to be finished before task D can be finished, etc.  I should definitively make this supported by plann.

#### Parent-child relationship

With the parent-child relationship one can make a hierarchical task list.  It makes a lot of sense when having a big task that can be split up in subtasks.  Say, the task may be "build a bicycle shed".  That does take quite some planning, purchases and work, so one will definitively want to break it up in subtasks.

A shopping list may also be considered to be a parent-child relationship.  "Buy cucumber" seems to be a subtask of "buy vegetables" which again may be a subtask of "go shopping at the supermarket".

Every parent-child relationship can also be seen as a dependency relationship, but it's a bit in reverse.  One cannot build the bike shed without first buying planks.  One cannot tick the checkbox for "go shopping" if the cucumber was not bought.  (or is it the other way around?  One cannot "buy cucumber" before one has started the procedure of "go shopping"?)

There is a bit of a difference between the typical pending-dependent and the typical parent-child relationship.  In a typical "parent-child"-relationship one may want to take out hierarchical lists with the parent first, or take out simple overviews where all the details (i.e. grandchildren) are hidden.  In a typical "pending-dependent"-relationship one may want to hide the dependent (parent) and emphasize on what's needed to be done first (child).  plann supports three kind of lists, it's "top-down", "bottom-up" or simply flat (the default).

#### Purpose-means

Another kind of relationship that is neither supported by RFC5545 nor RFC9253.

The purpose of the shopping trip is to buy cucumber - but the purpose of building the biking shed is not to buy planks (unless the owner of the planks shop used some clever marketing for tricking you into building the bike shed).

The purpose for buying sugar could be "bake a cake".  I would then start by adding "bake a cake" to the task list, then "buy sugar", and only then I would eventually add "go shopping" to the todo-list. (That's maybe just me.  My wife would go to the shop to buy a cucumber, and then come home with everything needed for baking a cake and more).

From my practical experience, "supermarket" and "hardware shopping" can as well be categories.  So eventually when I really need that cucumber, I can check up the full list for the category "supermarket" and come home with all ingrediences needed for making a cake.  I've never felt a compelling need to group the shopping list inside the calendar.

### RRULE, recurid, exdate, rdate

**TLDR:** plann takes care to handle recurrent tasks in the "best possible way" when a task is completed, but plann v1.0 does not allow easy addition of recurrent task.  One either have to write up the RRULE "by hand" or use some other calendaring tool to edit the RRULE parameter.

The standard allows for recurring tasks, but doesn't really flesh out what it means that a task is recurring - except that it should show up on date searches if any of the recurrances are within the date search range.  Date searches for future recurrances of tasks is ... quite exotic, why would anyone want to do that?

From a "user perspective", I think there are two kind of task recurrences:

* Specified intervals - say, the floor should be cleaned every week.  You usually do it every Monday, but one week everything is so hectic that you postpone it all until late Sunday evening.  It would be irrational to wash it again the next day.  And if you missed the due date with more than a week - then obviously the next recurrence is not "previous week".  (Except, one may argue that the status of previous week should be set to "CANCELLED")
* Fixed-time.  If you have some contract stating that you should be washing the floor weekly, then maybe you would want to wash the floor again on Monday, even if it was just done Sunday.  Or perhaps one of the children is having swimming at school every Tuesday, so sometime during Monday (with a hard due set to Tuesday early morning) a gym bag with swimwear and a fresh towel should be prepared for the child.  Or the yearly income tax statement, should be delivered before a hard due date - every year.

I choose to interpret a `RRULE` with `BY*`-attributes set (like `BYDAY=MO`) as a recurring task with "fixed" due times, while a `RRULE` without `BY*`-attributes should be considered as a "interval"-style of recurring task.

There can be only one status and one complete-date for a vtodo, no matter if it's recurring or not.

Based on my interpretation of the standards, possibly the correct way to mark once recurrence of a recurring task as complete, is to use the RECURRENCE-ID parameter and make several instances of the same UID.  However, based on my understanding of the RFC, the timestamps in a "recurrence set" is strictly defined by the RRULE and the original DTSTART.  This does probably fit well with the fixed-time recurrences (at least if one markes a missed recurrence with CANCELLED), but it does not fit particularly well with interval-based recurrences.

The current default logic is to duplicate/split the completed task into a completely separate task, and editing the new task with a moved DTSTART/DUE on the recurring event.  This should be a safe and compatible way of doing it.  The caldav library also supports combining the completed recurrences and the recurring uncomplete in a recurrence-set, which is probably more like the way the RFC intends things to be, but probably less compatible/safe when accessed by other software.

There is not so much support for recurrences outside the task completion code, as for now the rrule has to be manually added when creating or editing the task, or the recurrence has to be set through some another caldav client tool.  I believe recurring tasks is an important functionality, so I will implement better support for this at some point.

#### Recurring task trees

A recurring job is often a tree - "varnish the boat every spring and autumn" breaks down into areas, and each area into layers that have to be done in order.  Putting an `RRULE` on every node of the tree works with the completion logic above, but it breaks the rule that a parent is due after its children: once a child is completed it advances to its next occurrence, while the parent is still pending.  `RELATED-TO` points to a UID, not to a single occurrence, so the `RECURRENCE-ID` model cannot link the right occurrences to each other either.

The prior art (OmniFocus repeating projects and action groups; Todoist re-adding the sub-tasks of a recurring parent, one level deep; see the task model survey in calendaring-client) puts the recurrence on the root only.  The plan for plann is the same: an `RRULE` only on the root.  Completing the root completes its pending descendants (plann does that already) and splits the completed occurrence off as a copy with a new UID, as the "safe" completion mode does.  Then the subtree is regenerated for the next occurrence: every descendant is copied with a new UID, its `DTSTART`/`DUE` is shifted by the same delta as the root, and each copy is linked to the copy of its own parent, so deeper trees keep their shape.  Copying carries every `RELATED-TO` along, and plann stores the parent/child links on both ends (`PARENT` on the child, `CHILD` on the parent), so every link - ordering links such as RFC 9253 `DEPENDS-ON` between descendants included - is rewritten to the corresponding copy, or dropped when there is none.  After copying, the completed copy of the root already lists the old children as `CHILD`, and the regenerated first-level copies already say `PARENT` to the root; the old children's `PARENT` must be pointed at the completed copy, the root's `CHILD` set replaced by the new copies, and deeper copies remapped within their generation.  If the root has a parent of its own, the completed copy drops that `PARENT` link, rather than piling up one child per occurrence on the grandparent.  The caldav library builds the completed copy in the private `_build_recurring_safe_completed()`, but `complete()` returns nothing, so it has to expose that copy first.  This is not implemented yet.

### Timestamps
**TLDR:** Timestamps are important.  DUE should indicate when we need or want to be done with the task, DURATION should be the estimated time for doing the task.  Since DURATION and DUE cannot be combined, let rather DTSTART indicate the last possible time one can start working with the task and still have a hope to get done before the DUE timestamp.

For a task, I would like to record:

* A rough (or refined) time estimate (how long do I think it will take to do the task?)
* Timestamp for when I plan to start working on the task
* Timestamp for when I actually started working
* Timestamp for when I hope to be finished with the task
* Hard deadline for the task (and also: should the task be cancelled or procrastinated if the hard deadline was not met?)
* Timestamp for when I completed
* Actual time efficiently spent (possibly, billable time)

#### dtstamp, created, last-mod

RFC5545 offers those three parameters which may be important, but does not cover anything from my wishlist:

* DTSTAMP - mandatory and quite technical.  Should indicate the creation or last-modified timestamp, the RFC specifies the details.
* CREATED - non-mandatory.  It doesn't say in the RFC, but I suppose that if you found some old stone tablets from 43BC containing some important but long-forgotten task ("create a tunnel under the English channel"?  No, that one was completed already), then 43BC should be used as the creation timestamp, while DTSTAMP should be the time it was rewritten into the icalendar format.  At the other hand, the RFC says that the timestamp should be when the "user agent" creates the task ... so ... then it should be the same as DTSTAMP?  Hm.
* LAST-MODIFIED - non-mandatory.

#### dtstart, due, duration, completion

Four attributes:

* DTSTART
* DUE
* COMPLETED
* DURATION

... but only three of them can be set (DURATION and DUE is mutually exclusive - I think that's a bad idea, for compatibility and simple coding it would be better to leave out one of them from the standard).  So only three out of the seven things on my wishlist can be recorded.  Which three?

"Timestamp for when I completed" is obviously covered in the COMPLETED attribute.

DUE could be either "timestamp for when I hope to be finished with the task" or "hard deadline for the task".  RFC5545 does not allow for the extra bit of information to be stored: "is the DUE timestamp a hard or a soft deadline"?  I've decided that the priority field is to be used for this purpose.

Then it's DTSTART remaining.  It's not very well defined what information the DTSTART should convey.  It's quite obvious for events, but for tasks - not so much.  It's reasonable to assume DTSTART should be either the time I expect to be able to start working on the task (that's how I used to set DTSTART some years ago) or the time I actually started working with the task.  And yet, plann is optimized for a different usage ...

If the duration field was in use - what should it be used for?  The two most obvious things would be either the actual time spent on the task or the estimated time the task would require.  I think the latter is most obvious (after all, the purpose behind the VTODO and VEVENT components are first of all to plan the future, not to track the past) and also most useful, so I choose to define the DURATION as the time estimate for the task.  This information is probably more useful to store than the time one expects to be able to start with it.  I assume DTSTART+DURATION should be equivalent with DUE, meaning that I advice setting DTSTART such that the duration of the task equals to the time one would estimate that is needed doing the task.  The new meaning of DTSTART is then ... "the time when you need to drop everything else you may have in your hands and start working with the task".

Two examples: Some bureaucracy work (expected to take three hours) needs to be done "this year", and you consider it would be a good idea to start looking into it around the 15th of December.  And your daughter has swimming lessons at school every Tuesday, and need a gymbag containing towel, swimwear etc in the early morning.  It takes 5 minutes to pack usually - except every now and then things are not in their proper place, then it may take 15 minutes searching.  Since mornings are quite stressful at your house (YMMV) you consider it to be a good idea to prepare it Monday evening.

DUE should obviously be set to 1st of January at 00:00 for the admin task, and 08:10 Tuesday for the gym bag (that's when your daughter is running out the door).  It may seem to be a good idea to set DTSTART to the 15th of December and to Monday evening - to be sure the deadline is met - but then the information about the time estimates aren't recorded.  Instead we set DTSTART to new years eve, 21:00, and Tuesday 08:05.  Now that may seem silly, you really don't want to stress with paperworks at the new years eve, and at 08:05 there is the parallell task of helping her to pack the rucksack and help her to get out of the door, you may not have time fixing the gym bag.

I have made a rule for myself now.  Those tasks should be added to the calendar with priority set to 1 and the real DUE time, so that we have those recorded - but with slightly different wording, like "verify that the documents have been sent" and "check that she takes the gymbag to school".  Then there is the dependency (child tasks) "produce the documents" with deadline 16th of December and priority 4, as well as "pack the gym bag" with priority 3 and due-time in the evening.  Since it's in my nature to procrastinate the admin task, it will probably not be done before or at the 16th of December, but at least it will show up in good time before the new years eve, and I will have ample time to prepare mentally for doing it.  When the documents are produced, of course I will also proceed to complete the parent/dependent task while I'm at it, eliminating the need for doing this at the new years eve, but still keeping the relevant information (the hard deadline and the time estimate) in the calendaring system.

Another rule of mine, no task should have too high estimation - if a task has more than some 3-4 hour estimate, it should also be split into subtasks.  For one thing, otherwise I may end up working constantly for several days on one task without checking the calendar and hence missing important deadlines.

I have some more thoughts on project management and time tracking in the other document, [NEXT_LEVEL](NEXT_LEVEL.md).

### Priority

**TLDR:** this is considered to be an important property.  Use 1 or 2 if the deadline is very hard, and 3-9 if the task may be procrastinated.

The RFC defines priority as a number between 0 and 9.

0 means the priority is undefined, 1-4 means the priority is "high", 5 that it's "medium high" and 6-9 means the priority is "low".

Should tasks be done in the order of their priority?  Probably not, as there is also the DUE-date to consider.  I do have some ideas on how to sort and organize tasks in the [NEXT_LEVEL](NEXT_LEVEL.md) document.  To follow the thoughts there, let priority be defined as such:

* 1: The DUE timestamp MUST be met, come hell or high water.
* 2: The DUE timestamp SHOULD be met, if we lose it the task becomes irrelevant and should be cancelled.
* 3: The DUE timestamp SHOULD be met, but worst case we can probably procrastinate it, perhaps we can apply for an extended deadline.
* 4: The deadline SHOULD NOT be pushed too much
* 5: If the deadline approaches and we have higher-priority tasks that needs to be done, then this task can be procrastinated.
* 6: The DUE is advisory only and expected to be pushed - but it would be nice if the task gets done within reasonable time.
* 7-9: Low-priority task, it would be nice if the task gets done at all ... but the DUE is overly optimistic and expected to be pushed several times.

### Alarm

**TLDR:** I do not use alarms, but I'm considering to implement some sort of support for it

The point with alarms is to give some sort of push-alerts to the user, reminding him about an event or a task.  Like, those documents that should be delivered before the new year, one could make an alarm go off 14 days before new year.  But, no ... I don't think that is a good idea.  My idea of splitting it into two tasks is probably better.

I can see the usefulness of having alarms for events.  When working hard on some issue from the task list, it can be very useful to get a nudge in the side at 12:55, reminding one about the work meeting at 13:00 sharp.  Or perhaps already at 12:00 if the meeting is in another building ... but for tasks, not so much.  Well, I have had deadlines slip because I've been working for a full day on some less-imporant task without checking the task list - but I believe the solution to that is to split up tasks and to check the task list relatively frequently.

RFC9074 expands a bit on the alarms, for one thing it adds proximy-alarms that may be useful for tasks - theoretically, it could be used for things like getting push-notifications on all the shopping errainds when being nearby the shop - though the details seems rather complicated.  Alarm components are usually found inside a task or event, but from the RFC it seems like such alarms are to be stored directly on the calendar as first-class component citizens.  I'm also a bit surprised on the CONNECT and DISCONNECT proximy values - they are exclusively meant to be used when using the bluetooth protocol towards automobiles, hence limiting the usefulness quite a lot.

Another problem - how to implement push-alarms from a command line tool?  Well, I do have some ideas on that - but the very nature of plann is to deliver information on demand - pull, not push.

Except for the pull/push paradigm - from my perspective, alarms may in some cases be replaced by more events and tasks.  Like that new year paperwork - rather than having an alarm go off 14 days before the due, better to have a subtask with a due date in the middle of December.  Having a meeting at the other side of town?  Should probably add "travel across the town" in the calendar rather than putting an alarm one hour before the meeting.  Need time to prepare for the meeting?  That should be added as a task, not as an alarm.  Etc.  Same goes with proximity alarms, it's possible to add both geo and location to a task (and now even vlocation ref RFC9073).  If following this line of thought, "alarm" could have been a simple binary property rather than a (sub)component, "do you need a push-alert at DTSTART/proximity or not?".

### Class

**TLDR:** Don't use it.

A task or event may be classified as PUBLIC, PRIVATE or CONFIDENTIAL.  This may be used for access control on the component level, though most calendar server only have access control levels for the whole calendar - and not always even that - hence, you cannot trust the classification to be respected.

plann can filter/select/set this property, but it does not care about the value.  Plann does not implement any access control, that is considered to be up to the server.

### Summary, description, comment, and various other metadata - url, attach, styled-description, uid, contact

**TLDR:** Summary is considered important in plann

The only attribute that is mandatory is the uid.  As plann is a command line tool optimized for printing lists, it relies on the summary to be present - but with fallback to description and uid.

Summary is supposed to be a one-liner representing the task, and then the description is supposed to give further details.  Comment seems to be meant to add comments from other people than the organizer, I don't believe this property is much in use in the wild.  attach can be used to add documents (or URLs to documents), styled-description is for giving a more aesthetic description (not much relevant for plann, probably).  URLs can also be attached, and with RFC9253, a link property is defined - which is basically an URL with some extra metadata.

All those should be supported by plann, like, possible to show it or filter by it if one knows how to use plann, but it's only optimized towards the summary field.

### People (organizer, attendee, participant)

**TLDR:** May be considered important in a future version of plann

Like, the attendee field can be used for assigning a task to someone.  plann version 1.0 will be optimized for single-user-usage.

### Status, percent

**TLDR:** Status field is considered important, but plann v1.0 is not optimized for utilizing the "IN-PROCESS" status.

Vaid values for the status field is NEEDS-ACTION (considred by plann to be the default, if no status is given, and COMPLETED is not set), IN-PROCESS, COMPLETED and CANCELLED.  By default, plann will only show tasks that is in the NEEDS-ACTION state - hence, IN-PROCESS may easily fall out of the radar.  This will be changed at some point in the future (v1.1 perhaps?)

The PERCENT-COMPLETE (quote RFC) is used by an assignee or delegatee of a to-do to convey the percent completion of a to-do to the "Organizer".  Hence, it's only relevant for the "IN-PROCESS"-tasks.

My recommendation ... never work with a single task for several days, split it up into tasks that are completed and tasks that are remaining.  That also makes it possible to track the progress in a more accurate, reliable and accountable way than relying on a "percentage complete"-estimate.

### rstatus

RSTATUS is used for scheduling.  plann 1.0 does not support scheduling.

### color, image, conference

Those are not much relevant wrg of task handling in plann

## Daily task management and interactive mode

This is specifically directed towards using plann for daily task management.  See also the [USER GUIDE](USER_GUIDE.md) for more generic user guide.  I will assume that your calendar server needs to support advanced CalDAV queries (see [CALENDAR SERVER RECOMMENDATIONS](docs/CALENDAR_SERVER_RECOMMENDATIONS.md)).

### Adding tasks

Currently there is no interactive mode for adding tasks, but it's pretty simple to quickly add a task, `plann add todo "water the flowers"`.

If the configuration specifies multiple calendars or calendar servers, it may be needed to either explicitly use `--config-section` or use the `--first-calendar` option to specify what calendar to use.  I'm considering simpler ways to select what calendar to add the task to.  While `--config-section` is a global option,`--first-calendar` is an option to the `add` command.

Properties can be set by using options like `--set-priority`.  Those options goes to the `todo` subcommand.  Mixing up what options goes where is a big annoyance, I'm considering to find some solution to this.

### Set "mandatory" attributes

In my task management routines, this information is required for all tasks:

* summary (gets set on task creation)
* categories
* due date
* priority
* time estimate

It is possible to add those on the command line while adding tasks.  My idea is that one can do so if having time - but whenever some thoughts like "I need to remember ..." passes through the head, or whenever one notices something that needs to be repaired, etc, one should immediately spend the least possible time to just add it to the calendar - and then later when having better time and sitting by the keyboard one should flesh out the details.

To interactively find and set the missing properties, it's possible to do `plann interactive set-task-attribs`.

### Listing tasks

The `select`-command can be used to list tasks.  The `--todo`-flag will ensure that only pending tasks are listed.  Say that it's a nice day for garden work, then `plann select --todo --category garden list` would probably be the right thing to do.

There exists some other ways too.  `plann agenda` will list out events and tasks with `DTSTART` in the near-term future.  `plann interactive check-due` will go through overdue and near-due tasks and interactively ask the user what to do with them.  Then there is also the "panic planning mode" available, for instance `plann interactive dismiss-panic` - it will list overdue tasks and tasks that you probably won't have time to do within the planned `DUE`.  More on that below.

### Splitting tasks

It's a good idea to split tasks into subtasks ...

* Whenever the task is too big.  Any task taking more than a day should be split up into subtasks (the default is that any task estimated to take more than four hours should be split)
* If the task has a very strict deadline.  Split it up to actually doing the task (with an "artificial" due date in the near future, a due date that most likely will be pushed) and then "verify that the task was done" with the real due date and the highest (1 or 2) priority.  Otherwise you risk getting the notice at 22:00 on new years eve that you need to do some bureaucraziness "this year".
* Whenever one doesn't really know how to start working on a task, or whenever a task is procrastinated over and over again simply because the other tasks looks "more interessting".

There are two interactive commands for splitting, `plann interactive split-huge-tasks` and `plann interactive split-high-pri-tasks`. The interactive edit (more on that below) will also support splitting.

### Editing tasks

Tasks can be edited through the `select` command.  When adding the task an UID is printed, and it can be used for selecting: `plann select --uid 264185c0-c51b-11ed-a500-982cbcdd642c edit --interactive-ical`.  `--interactive-ical` will open up an editor (remember to set and export the `$EDITOR` environment variable), and the ical data can be edited by hand.

Other selectors can be used, like category and summary.  The RFC says that subtext search should be done, but different calendar servers may do things in different ways.  Properties can also be set by using set-options, like `--set-priority`.  Say you want to start using the location property, and set location to `home` for all tasks that have the category `home` set, it may be done like this: `plann select --category home edit --set-location home`.

There is another interactive edit function, `plann select --summary 'clean' edit --interactive` will give a small menu for each task selected.

### Manage-tasks

`plann interactive manage-tasks` will do the following:

* `plann interactive split-huge-tasks`
* `plan interactive split-high-pri-tasks`
* `plann interactive set-task-attribs`
* `plann agenda`
* `plann interactive dismiss-panic --hours-per-day=24`
* `plann interactive check-due`
* `plann interactive dismiss-panic --hours-per-day=8`

### Completing tasks

Tasks can be completed through interactive edits, but also through the select command.

Interactive select may be useful - say, you've been working in the garden: `plann select --category garden --interactive complete`, and you should select the tasks to complete.

### "Panic planning"

The "panic planning mode" is available as an interactive command (`plann interactive dismiss-panic`) and through select (`plann --config-section=workcalendar select --to +30d check-for-panic`)

The panic planning will try to figure out if it's still possible to perform all the tasks, and if not it will suggest to procrastinate the lowest-priority tasks.

TODO: write more about the panic planning algorithm.

