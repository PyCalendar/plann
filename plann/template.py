"""String formatter that allows default values to be passed in the
template string.

This does not really belong in the calendar-cli package.  I was
googling a bit, and didn't find anything like this out there ... but
I'm sure there must exist something like this?"""

import datetime
import re
import string

from plann.timespec import tz


class NoValue:
    def __getattr__(self, attr):
        return self
    def __getitem__(self, attr):
        return self
    def __str__(self):
        return ""
    def __format__(self, spec):
        try:
            return "".__format__(spec)
        except Exception:
            return ""

no_value = NoValue()

class Template(string.Formatter):
    def __init__(self, template):
        self.template = template

    def format(self, *pargs, **kwargs):
        return super().format(self.template, *pargs, **kwargs)

    def format_component(self, comp, **kwargs):
        """Format an icalendar component, with CATEGORIES as a comma-separated list"""
        values = dict(comp)
        if 'CATEGORIES' in comp:
            values['CATEGORIES'] = ",".join(str(c) for c in comp.categories)
        return self.format(**values, **kwargs)

    def get_field(self, field_name, args, kwargs):
        try:
            return super().get_field(field_name, args, kwargs)
        except Exception:
            return (no_value, field_name)

    def get_value(self, key, args, kwds):
        try:
            ret = string.Formatter.get_value(self, key, args, kwds)
        except Exception:
            return no_value
        if hasattr(ret, 'dt'):
            ret = ret.dt
            if not tz.show_native_timezone and isinstance(ret, datetime.datetime):
                ret = ret.astimezone()
        return ret

    def format_field(self, value, format_spec):
        rx = re.match(r'\?([^\?]*)\?(.*)', format_spec)
        if rx:
            format_spec = rx.group(2)
            if value is no_value:
                value = rx.group(1)
        try:
            return string.Formatter.format_field(self, value, format_spec)
        except Exception:
            return string.Formatter.format_field(self, value, "")
