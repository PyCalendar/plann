import pytest

from plann.lib import tz


@pytest.fixture(autouse=True)
def _reset_tz():
    ## tz is a process-wide singleton and its setters ignore None, so a
    ## test assigning tz.implicit_timezone would otherwise leak into
    ## whatever pytest-randomly happens to run next.  Dropping the
    ## instance attributes falls back to the class defaults.
    tz.__dict__.clear()
    yield
    tz.__dict__.clear()
