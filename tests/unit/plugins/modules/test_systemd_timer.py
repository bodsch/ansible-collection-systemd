# -*- coding: utf-8 -*-
# Unit tests for the pure helpers of the systemd_timer module.
#
# These exercise the calendar/scope logic without touching systemd, D-Bus or
# the filesystem. Run with:
#
#   ansible-test units tests/unit/plugins/modules/test_systemd_timer.py
#
# or directly with pytest (collection must be importable):
#
#   PYTHONPATH=/path/to/collections python3 -m pytest \
#       tests/unit/plugins/modules/test_systemd_timer.py

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

import ansible_collections.bodsch.systemd.plugins.modules.systemd_timer as st
from ansible_collections.bodsch.systemd.plugins.modules.systemd_timer import (
    SystemdTimer,
)


class FakeModule:
    """Minimal AnsibleModule stand-in for testing pure helpers."""

    def __init__(self):
        self.fail_args = None

    def log(self, *args, **kwargs):
        pass

    def fail_json(self, **kwargs):
        # mirror AnsibleModule.fail_json by aborting control flow
        self.fail_args = kwargs
        raise SystemExit(kwargs.get("msg", "fail_json"))


def make_timer():
    """Create a SystemdTimer instance without running __init__."""
    timer = SystemdTimer.__new__(SystemdTimer)
    timer.module = FakeModule()
    return timer


# ---------------------------------------------------------------------------
# resolve_scope
# ---------------------------------------------------------------------------

def test_resolve_scope_system_defaults():
    timer = make_timer()
    base, owner, group = timer.resolve_scope("system", None, None, None, None)
    assert base == "/lib/systemd/system"
    assert owner == "root"
    assert group == "root"


def test_resolve_scope_system_explicit_overrides():
    timer = make_timer()
    base, owner, group = timer.resolve_scope(
        "system", None, "/etc/systemd/system", "www-data", "www-data"
    )
    assert base == "/etc/systemd/system"
    assert owner == "www-data"
    assert group == "www-data"


def test_resolve_scope_user_defaults(monkeypatch):
    class _PW:
        pw_dir = "/home/alice"
        pw_gid = 1001

    class _GR:
        gr_name = "alice"

    monkeypatch.setattr(st.pwd, "getpwnam", lambda name: _PW())
    monkeypatch.setattr(st.grp, "getgrgid", lambda gid: _GR())

    timer = make_timer()
    base, owner, group = timer.resolve_scope("user", "alice", None, None, None)
    assert base == "/home/alice/.config/systemd/user"
    assert owner == "alice"
    assert group == "alice"


def test_resolve_scope_user_explicit_path_keeps_owner(monkeypatch):
    class _PW:
        pw_dir = "/home/alice"
        pw_gid = 1001

    class _GR:
        gr_name = "alice"

    monkeypatch.setattr(st.pwd, "getpwnam", lambda name: _PW())
    monkeypatch.setattr(st.grp, "getgrgid", lambda gid: _GR())

    timer = make_timer()
    base, owner, group = timer.resolve_scope(
        "user", "alice", "/custom/dir", None, None
    )
    # explicit path wins, owner/group still derived from the user
    assert base == "/custom/dir"
    assert owner == "alice"
    assert group == "alice"


def test_resolve_scope_unknown_user_fails(monkeypatch):
    def _raise(name):
        raise KeyError(name)

    monkeypatch.setattr(st.pwd, "getpwnam", _raise)

    timer = make_timer()
    with pytest.raises(SystemExit):
        timer.resolve_scope("user", "ghost", None, None, None)

    assert "ghost" in timer.module.fail_args["msg"]


# ---------------------------------------------------------------------------
# build_calendar_spec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "schedule,expected",
    [
        ({"raw": "*-*-* 00/12:00:00"}, "*-*-* 00/12:00:00"),
        ({"special": "daily"}, "daily"),
        ({"hour": 2, "minute": 58}, "*-*-* 02:58:00"),
        ({"hour": 2, "minute": 58, "second": 30}, "*-*-* 02:58:30"),
        ({"weekday": "Mon", "hour": 2, "minute": 58}, "Mon *-*-* 02:58:00"),
        ({"weekday": ["Mon", "Thu"], "hour": 2}, "Mon,Thu *-*-* 02:*:00"),
        ({"month": 3, "day": 15}, "*-03-15 *:*:00"),
    ],
)
def test_build_calendar_spec(schedule, expected):
    timer = make_timer()
    assert timer.build_calendar_spec(schedule) == expected


def test_build_calendar_spec_empty_returns_none():
    timer = make_timer()
    assert timer.build_calendar_spec({}) is None
