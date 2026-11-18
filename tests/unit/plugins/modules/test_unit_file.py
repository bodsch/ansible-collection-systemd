# Unit tests for the unit_file module.

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import hashlib
import os

import pytest

import ansible_collections.bodsch.systemd.plugins.modules.unit_file as uf
from ansible_collections.bodsch.systemd.plugins.modules.unit_file import (
    SystemdUnitFile,
)


class FakeModule:
    def __init__(self, params=None):
        self.params = params or {}
        self.fail_args = None
        self.owner_calls = []
        self.group_calls = []
        self.mode_calls = []

    def log(self, *args, **kwargs):
        pass

    def set_owner_if_different(self, *args):
        self.owner_calls.append(args)

    def set_group_if_different(self, *args):
        self.group_calls.append(args)

    def set_mode_if_different(self, *args):
        self.mode_calls.append(args)

    def fail_json(self, **kwargs):
        self.fail_args = kwargs
        raise SystemExit(kwargs.get("msg", "fail_json"))


def make_unit_file(params=None):
    unit_file = SystemdUnitFile.__new__(SystemdUnitFile)
    unit_file.module = FakeModule(params)
    return unit_file


def test_resolve_scope_system_defaults():
    unit_file = make_unit_file()
    base, owner, group = unit_file.resolve_scope("system", None, None, None, None)

    assert base == "/lib/systemd/system"
    assert owner == "root"
    assert group == "root"


def test_resolve_scope_user_defaults(monkeypatch):
    class _PW:
        pw_dir = "/home/alice"
        pw_gid = 1001

    class _GR:
        gr_name = "alice"

    monkeypatch.setattr(uf.pwd, "getpwnam", lambda name: _PW())
    monkeypatch.setattr(uf.grp, "getgrgid", lambda gid: _GR())

    unit_file = make_unit_file()
    base, owner, group = unit_file.resolve_scope(
        "user", "alice", None, None, None
    )

    assert base == "/home/alice/.config/systemd/user"
    assert owner == "alice"
    assert group == "alice"


def test_resolve_scope_user_explicit_values_win(monkeypatch):
    class _PW:
        pw_dir = "/home/alice"
        pw_gid = 1001

    class _GR:
        gr_name = "alice"

    monkeypatch.setattr(uf.pwd, "getpwnam", lambda name: _PW())
    monkeypatch.setattr(uf.grp, "getgrgid", lambda gid: _GR())

    unit_file = make_unit_file()
    result = unit_file.resolve_scope(
        "user", "alice", "/custom/units", "service-owner", "service-group"
    )

    assert result == ("/custom/units", "service-owner", "service-group")


def test_resolve_scope_unknown_user_fails(monkeypatch):
    def _raise(name):
        raise KeyError(name)

    monkeypatch.setattr(uf.pwd, "getpwnam", _raise)
    unit_file = make_unit_file()

    with pytest.raises(SystemExit):
        unit_file.resolve_scope("user", "ghost", None, None, None)

    assert "ghost" in unit_file.module.fail_args["msg"]


def test_user_scope_uses_home_for_units_and_drop_ins(monkeypatch):
    class _PW:
        pw_dir = "/home/alice"
        pw_gid = 1001

    class _GR:
        gr_name = "alice"

    monkeypatch.setattr(uf.pwd, "getpwnam", lambda name: _PW())
    monkeypatch.setattr(uf.grp, "getgrgid", lambda gid: _GR())

    unit_file = SystemdUnitFile(
        FakeModule(
            {
                "unit_type": "service",
                "name": "backup",
                "scope": "user",
                "user": "alice",
            }
        )
    )

    expected_path = "/home/alice/.config/systemd/user"
    assert unit_file.base_path == expected_path
    assert unit_file.drop_in_base_path == expected_path


def test_ensure_directory_assigns_owner_group_and_mode(tmp_path):
    unit_file = make_unit_file()
    unit_file.owner = "alice"
    unit_file.group = "users"
    directory = tmp_path / "config" / "systemd" / "user"

    unit_file.ensure_directory(str(directory))

    assert directory.is_dir()
    assert [call[1] for call in unit_file.module.owner_calls] == ["alice"] * 3
    assert [call[1] for call in unit_file.module.group_calls] == ["users"] * 3
    assert [call[1] for call in unit_file.module.mode_calls] == ["0755"] * 3


def test_changed_reconciles_ownership_when_content_is_unchanged(monkeypatch, tmp_path):
    class _Checksum:
        def checksum_from_file(self, path):
            with open(path, "rb") as unit_file:
                return hashlib.sha256(unit_file.read()).hexdigest()

    module = FakeModule()

    def set_owner(*args):
        module.owner_calls.append(args)
        return True

    def set_group(*args):
        module.group_calls.append(args)
        return True

    monkeypatch.setattr(module, "set_owner_if_different", set_owner)
    monkeypatch.setattr(module, "set_group_if_different", set_group)

    destination = tmp_path / "backup.service"
    temporary = tmp_path / "backup.service.tmp"
    content = b"[Unit]\nDescription=Backup\n"
    destination.write_bytes(content)
    temporary.write_bytes(content)

    unit_file = make_unit_file()
    unit_file.module = module
    unit_file.owner = "alice"
    unit_file.group = "users"
    unit_file.checksum = _Checksum()

    result = unit_file._SystemdUnitFile__changed(str(temporary), str(destination))

    assert result["changed"]
    assert module.owner_calls == [(str(destination), "alice", False)]
    assert module.group_calls == [(str(destination), "users", False)]
    assert destination.read_bytes() == content


def test_run_writes_user_unit_and_drop_in_with_target_ownership(monkeypatch, tmp_path):
    class _PW:
        pw_dir = str(tmp_path / "home")
        pw_gid = 1001

    class _GR:
        gr_name = "users"

    class _Checksum:
        def __init__(self, module):
            pass

        def checksum_from_file(self, path):
            if not os.path.exists(path):
                return None
            with open(path, "rb") as unit_file:
                return hashlib.sha256(unit_file.read()).hexdigest()

    monkeypatch.setattr(uf.pwd, "getpwnam", lambda name: _PW())
    monkeypatch.setattr(uf.grp, "getgrgid", lambda gid: _GR())
    monkeypatch.setattr(uf, "Checksum", _Checksum)

    base_path = str(tmp_path / "home" / ".config" / "systemd" / "user")
    module = FakeModule(
        {
            "unit_type": "service",
            "name": "backup",
            "state": "present",
            "scope": "user",
            "user": "alice",
            "path": base_path,
            "owner": None,
            "group": None,
            "drop_ins": [
                {
                    "name": "environment",
                    "state": "present",
                    "Service": {"Environment": ["BACKUP=1"]},
                }
            ],
            "unit_file": {"Unit": {"Description": "Per-user backup"}},
        }
    )

    result = SystemdUnitFile(module).run()

    unit_path = os.path.join(base_path, "backup.service")
    drop_in_path = os.path.join(
        base_path, "backup.service.d", "environment.conf"
    )
    assert result["changed"]
    assert os.path.exists(unit_path)
    assert os.path.exists(drop_in_path)
    assert any(call[:2] == (unit_path, "alice") for call in module.owner_calls)
    assert any(call[:2] == (unit_path, "users") for call in module.group_calls)
    assert any(call[:2] == (drop_in_path, "alice") for call in module.owner_calls)
    assert any(call[:2] == (drop_in_path, "users") for call in module.group_calls)
