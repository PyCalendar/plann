import json
import logging
import os
import time
from getpass import getpass

import calendaring_config

## The config handling logic originated in plann and has been adopted by the
## caldav library - use the caldav implementation rather than carrying a copy.
## (The redundant aliases mark config_section and expand_config_section as
## intentional re-exports, they are used by cli.py)
from caldav.config import config_section as config_section
from caldav.config import expand_config_section as expand_config_section
from caldav.config import read_config as _read_config

## Connection parameters are written caldav_-prefixed; caldav's reader
## (extract_conn_params_from_section) maps caldav_user/caldav_pass to
## username/password.  The list is hand-written, and tests/test_config.py
## checks it against caldav.config.CONNKEYS so the writer cannot drift away
## from the reader unnoticed - the historical bug was writing `ssl_verify_cert`
## without the caldav_ prefix, which the reader silently dropped (code review
## C8).
_CONN_ALIASES = {'user': 'username', 'pass': 'password'}
_CONN_PROMPT_KEYS = ('caldav_url', 'caldav_user', 'caldav_pass', 'caldav_proxy', 'caldav_ssl_verify_cert')

## calendar_url/calendar_name are read directly by find_calendars; features is
## the caldav server-compatibility profile; inherits is the config meta-key
## resolved by config_section.  (language/timezone are intentionally NOT
## prompted for - plann does not read them from the config file.)
CONFIG_PROMPT_KEYS = _CONN_PROMPT_KEYS + ('calendar_url', 'calendar_name', 'features', 'inherits')


def _ssl_verify_cert_value(value):
    """caldav hands a string ssl_verify_cert on to niquests as a CA bundle
    path, so a yes/no typed at the prompt has to be stored as a bool."""
    lowered = value.strip().lower()
    if lowered in ('true', 'yes', 'on', '1'):
        return True
    if lowered in ('false', 'no', 'off', '0'):
        return False
    return value


def _prompt_value(label, current, secret=False):
    if secret:
        print(f"Config option {label} - old value: **HIDDEN**")
        return getpass(prompt="Enter new value (or just enter to keep the old): ")
    print("Config option {} - old value: {}".format(label, current if current is not None else '(None)'))
    return input("Enter new value (or just enter to keep the old): ")


def interactive_config(config, config_file, config_section='default', allow_use=False):
    """Interactively edit a configuration section and optionally save it.

    EXPERIMENTAL / under-tested - see the disclaimer printed at runtime.

    `config` is the parsed config dict (may be empty), `config_file` the path
    to write to, `config_section` the section to edit, and `allow_use` whether
    to offer using the config without saving (only meaningful when a follow-up
    command will consume the returned config).  Returns the modified config.
    """
    section = config_section
    backup = {}
    modified = False

    print("Welcome to the interactive calendar configuration mode")
    print("WARNING - here be dragons: this interactive configuration is under-tested.")
    print("Please raise issues at config-issues@plann.no or the github issue tracker.")
    print("It might be a good idea to read the documentation in parallel if running this for your first time")
    if not config or not hasattr(config, 'keys'):
        config = {}
        print("No valid existing configuration found")
    if config:
        print("The following sections have been found: ")
        print("\n".join(config.keys()))
        if config_section and config_section != 'default':
            section = config_section
        else:
            ## TODO: tab completion
            section = input("Chose one of those, or a new name / no name for a new configuration section: ")
        if section in config:
            backup = config[section].copy()
        print("Using section " + section)
    else:
        section = 'default'

    if section not in config:
        config[section] = {}

    sect = config[section]
    for config_key in CONFIG_PROMPT_KEYS:
        value = _prompt_value(config_key, sect.get(config_key), secret=(config_key == 'caldav_pass'))
        if value:
            if config_key == 'caldav_ssl_verify_cert':
                value = _ssl_verify_cert_value(value)
            sect[config_key] = value
            modified = True

    ## time_tracking is non-connection config; find_calendars passes the whole
    ## extra_config sub-dict through to add_time_tracking (see lib.py)
    tt_current = sect.get('extra_config', {}).get('time_tracking')
    tt_value = _prompt_value('time_tracking (e.g. timewarrior)', tt_current)
    if tt_value:
        sect.setdefault('extra_config', {})['time_tracking'] = tt_value
        modified = True

    if not modified:
        print("No configuration changes have been done")
    else:
        state = 'start'
        while state == 'start':
            options = []
            if section:
                options.append(('save', f'save configuration into section {section}'))
            if backup or not section:
                options.append(('save_other', 'add this new configuration into a new section in the configuration file'))
            if allow_use:
                options.append(('use', 'use this configuration without saving'))
            options.append(('abort', 'abort without saving'))
            print("CONFIGURATION DONE ...")
            for o in options:
                print("Type {} if you want to {}".format(*o))
            cmd = input("Enter a command: ")
            if cmd in ('use', 'abort'):
                state = 'done'
            if cmd in ('save', 'save_other'):
                if cmd == 'save_other':
                    new_section = input("New config section name: ")
                    config[new_section] = config[section]
                    if backup:
                        config[section] = backup
                    else:
                        del config[section]
                    section = new_section
                try:
                    write_config_file(config, config_file)
                except Exception as e:
                    print(e)
                else:
                    print("Saved config")
                    state = 'done'

    if config_section == 'default' and section != 'default':
        config['default'] = config[section]
    return config

def write_config_file(config, config_file):
    """Write `config` to `config_file`, keeping a backup of the old one.  The
    file may hold a password, so it is created readable by its owner only -
    and caldav will only run a password_command from a file nobody else can
    write to."""
    if os.path.isfile(config_file):
        os.rename(config_file, f"{config_file}.{int(time.time())}.bak")
    os.makedirs(os.path.dirname(config_file) or '.', mode=0o700, exist_ok=True)
    fd = os.open(config_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as outfile:
        json.dump(config, outfile, indent=4)

def writable_config_file(given, found):
    """Where `plann configure` saves: the file it read (`found`), unless
    that was picked from the search path and cannot be written - such as
    /etc/calendar.conf - in which case a new file goes first on the path."""
    if given:
        return found
    ## saving renames the old file to a backup, so the directory must be writable
    directory = os.path.dirname(found) or '.'
    if not os.path.exists(directory) or os.access(directory, os.W_OK):
        return found
    return str(calendaring_config.search_path()[0])

def resolve_config_file(config_file):
    """The config file to use: the one given (with ~ expanded), else the
    first that exists on the search path shared with the caldav library and
    other tools (calendaring-config decides it, also from
    CALENDARING_CONFIG_FILE / CALDAV_CONFIG_FILE), else the first path on
    it, where `plann configure` creates a new one."""
    if config_file:
        return os.path.expanduser(config_file)
    found = calendaring_config.find_config_file()
    return str(found if found else calendaring_config.search_path()[0])

def read_config(fn, interactive_error=False):
    """
    Thin wrapper around the caldav library's read_config.  The caldav
    version raises ValueError on a broken config file - plann should
    rather log the problem and carry on.
    """
    try:
        return _read_config(fn) or {}
    except ValueError:
        if interactive_error:
            logging.error("error in config file.  Be aware that the interactive configuration will ignore and overwrite the current broken config file", exc_info=True)
        else:
            logging.error("error in config file.  It will be ignored", exc_info=True)
    return {}
