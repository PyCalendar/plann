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


@pytest.fixture(autouse=True)
def _no_real_config(tmp_path, monkeypatch):
    """Keep the developer's own config files and CALDAV_*/CALENDARING_*
    variables out of every test: plann looks the config file up on the
    shared search path when no -c is given."""
    import os

    import calendaring_config.discovery
    for name in list(os.environ):
        if name.startswith(("CALDAV_", "CALENDARING_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(calendaring_config.discovery, "SYSTEM_PATHS", (tmp_path / "etc.conf",))
