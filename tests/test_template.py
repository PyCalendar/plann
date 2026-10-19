from datetime import date

import icalendar

from plann.lib import tz
from plann.template import Template

"""
Testing the plann templating engine
"""

class TestTemplate:
    def setup_method(self):
        self.date = date(1990, 10, 10)
        tz.implicit_timezone='UTC'

    def test_formatting_with_timespec(self):
        template=Template("This is an ISO date: {date:%F}")
        text = template.format(date=self.date)
        assert text == "This is an ISO date: 1990-10-10"

        text = template.format(foo=self.date)
        assert text == "This is an ISO date: "

    def test_formatting_with_simple_default(self):
        template=Template("This is an ISO date: {date:?(date is missing)?%F}")
        text = template.format(date=self.date)
        assert text == "This is an ISO date: 1990-10-10"

        text = template.format(foo=self.date)
        assert text == "This is an ISO date: (date is missing)"

    def test_subvalue_with_default(self):
        template = Template("This is a year: {date.year:?NA?>5}")
        text = template.format(date=self.date)
        assert text == "This is a year:  1990"
        text = template.format(foo=self.date)
        assert text == "This is a year:    NA"

    def test_missing_replaced_with_advanced_default(self):
        template = Template("Date is maybe {date:?{foo}?%F}")
        text = template.format(date=self.date)
        assert text == "Date is maybe 1990-10-10"
        text = template.format(foo=self.date)
        assert text == "Date is maybe 1990-10-10"
        text = template.format(foo=self.date, date=self.date)
        assert text == "Date is maybe 1990-10-10"

    def test_missing_replaced_with_even_more_advanced_default(self):
        template = Template("Date is maybe {date:?{foo:?bar?}?%F}")
        text = template.format(date=self.date)
        assert text == "Date is maybe 1990-10-10"
        text = template.format(foo=self.date)
        assert text == "Date is maybe 1990-10-10"
        text = template.format(foo=self.date, date=self.date)
        assert text == "Date is maybe 1990-10-10"
        text = template.format()
        assert text == "Date is maybe bar"

    def test_categories_rendered_as_comma_separated_list(self):
        todo = icalendar.Todo()
        todo.add('categories', ['RL', 'claude'])
        assert Template("{CATEGORIES}").format_component(todo) == "RL,claude"
        assert Template("{CATEGORIES:>12}").format_component(todo) == "   RL,claude"

        ## Several CATEGORIES lines in one component
        todo.add('categories', ['keyboard'])
        assert Template("{CATEGORIES}").format_component(todo) == "RL,claude,keyboard"

    def test_missing_categories_gives_default(self):
        todo = icalendar.Todo()
        assert Template("{CATEGORIES:?none?}").format_component(todo) == "none"

    def test_bad_field_lookup_gives_empty_string(self):
        todo = icalendar.Todo()
        todo.add('categories', ['RL'])
        assert Template("[{CATEGORIES.cats}]").format_component(todo) == "[]"

    def test_format_component_takes_extra_keys(self):
        todo = icalendar.Todo()
        todo.add('summary', 'foo')
        assert Template("{SUMMARY} {calendar_name}").format_component(todo, calendar_name="bar") == "foo bar"
