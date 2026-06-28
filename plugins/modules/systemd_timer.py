#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2025, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import grp
import os
import pwd
from typing import Any, Dict, List, Optional, Tuple

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.systemd.plugins.module_utils.helper import (
    normalize_weekday_token,
    timer_component,
)
from ansible_collections.bodsch.systemd.plugins.module_utils.validator import (
    SystemdValidator,
)

# ---------------------------------------------------------------------------------------

DOCUMENTATION = r"""
---
module: systemd_timer
version_added: 1.4.0
author: "Bodo Schulz (@bodsch) <bodo@boone-schulz.de>"

short_description: Manage systemd timer unit files
description:
  - Create, update, or remove systemd timer units (.timer files).
  - Support generic options for the [Unit], [Timer], and [Install] sections.
  - Provide a structured, dynamic definition of OnCalendar via schedule/schedules.

options:
  name:
    description:
      - Base name of the timer unit (without ".timer").
      - The file is written to I(path)/<name>.timer.
    type: str
    required: true
  description:
    description:
      - Convenience shortcut for the C(Description) key of the [Unit] section.
      - Only applied when C(unit.Description) is not set explicitly.
    type: str
  state:
    description:
      - Whether the timer unit file should be present.
    type: str
    choices: [present, absent]
    default: present
  scope:
    description:
      - Defines whether a system-wide or a per-user timer unit is managed.
      - C(system) writes the unit into the system manager directory (see I(path)).
      - C(user) writes the unit into the C(.config/systemd/user) directory of the
        user given in I(user), owned by that user.
    type: str
    choices: [system, user]
    default: system
  user:
    description:
      - Target user when I(scope=user).
      - The .timer file is written to C(~<user>/.config/systemd/user/<name>.timer)
        and the file (including any directories created below the user's home) is
        owned by this user.
      - Required when I(scope=user), ignored when I(scope=system).
    type: str
  path:
    description:
      - Base directory for the .timer file.
      - When unset, defaults to C(/lib/systemd/system) for I(scope=system) and to
        C(~<user>/.config/systemd/user) for I(scope=user).
      - When set explicitly, it overrides the scope-based default.
    type: str
  unit:
    description:
      - Options for the [Unit] section as a key/value mapping.
      - Values can be scalars or lists; booleans are converted to C(true)/C(false).
    type: dict
  timer:
    description:
      - Options for the [Timer] section as a key/value mapping.
      - If C(OnCalendar) is set here, it overrides schedule/schedules.
    type: dict
  timer_validation:
    description:
      - Whether timespan-like [Timer] options are validated via
        C(systemd-analyze timespan).
      - When C(false), timespans are only checked for being non-empty.
    type: bool
    default: true
  install:
    description:
      - Options for the [Install] section as a key/value mapping.
    type: dict
  schedule:
    description:
      - Structured definition for a single OnCalendar specification.
      - Ignored when C(timer.OnCalendar) is set.
    type: dict
    suboptions:
      raw:
        description:
          - Raw systemd calendar pattern written as-is to OnCalendar.
        type: str
      special:
        description:
          - Shortcut like C(hourly), C(daily), C(weekly), C(monthly), C(yearly), C(quarterly), C(semiannually), etc.
        type: str
      year:
        description:
          - Year(s), for example C(2025) or list/range as string (C(2025,2026), C(2025..2030)).
        type: raw
      month:
        description:
          - Month(s), for example C(1), C(01), C(3,6,9) or C(*).
        type: raw
      day:
        description:
          - Day(s) of month, for example C(1), C(01), C(1,15), C(*/2).
        type: raw
      weekday:
        description:
          - Weekday(s), for example C(Mon), C(Mon,Fri) or numeric C(1..7).
        type: raw
      hour:
        description:
          - Hour(s), for example C(2), C(02), C(0..23), C(*/2).
        type: raw
      minute:
        description:
          - Minute(s), for example C(0), C(0,30), C(*/15).
        type: raw
      second:
        description:
          - Second(s), default is C(00).
        type: raw
  schedules:
    description:
      - List of multiple structured OnCalendar definitions.
      - Each list item becomes its own C(OnCalendar=) entry.
    type: list
    elements: dict
  enabled:
    description:
      - Whether the timer should be enabled or disabled using C(systemctl enable/disable).
      - C(null) means the enable state is not changed.
      - For I(scope=user) the target user's service manager is used
        (C(systemctl --user --machine=<user>@.host)), which must be running.
    type: bool
  daemon_reload:
    description:
      - Whether to run C(systemctl daemon-reload) after the unit file has changed.
      - For I(scope=user) the reload is issued against the target user's service manager.
    type: bool
    default: true
  owner:
    description:
      - Owner of the .timer file.
      - When unset, defaults to C(root) for I(scope=system) and to I(user) for I(scope=user).
    type: str
  group:
    description:
      - Group of the .timer file.
      - When unset, defaults to C(root) for I(scope=system) and to the primary group
        of I(user) for I(scope=user).
    type: str
  mode:
    description:
      - File mode of the .timer file.
    type: str
    default: '0644'
"""

EXAMPLES = r"""
- name: Simple daily timer for Certbot
  systemd_timer:
    name: certbot
    unit:
      Description: Run Certbot daily
    timer:
      Persistent: true
      RandomizedDelaySec: 12h
    schedule:
      special: daily
    install:
      WantedBy: timers.target
    enabled: true

- name: Timer twice a day at fixed times
  systemd_timer:
    name: certbot
    unit:
      Description: Run Certbot twice daily
    timer:
      Persistent: true
      RandomizedDelaySec: 12h
    schedules:
      - hour: 2
        minute: 58
      - hour: 14
        minute: 58
    install:
      WantedBy: timers.target
    enabled: true

- name: More complex pattern - Mon and Thu at 02:58
  systemd_timer:
    name: certbot
    unit:
      Description: Run Certbot on specific weekdays
    timer:
      Persistent: true
    schedule:
      weekday: [Mon, Thu]
      hour: 2
      minute: 58
    install:
      WantedBy: timers.target

- name: Use raw calendar pattern directly
  systemd_timer:
    name: custom
    unit:
      Description: Custom raw OnCalendar
    timer:
      Persistent: true
    schedule:
      raw: '*-*-* 00/12:00:00'
    install:
      WantedBy: timers.target

- name: Per-user timer for backups in alice's ~/.config/systemd/user
  systemd_timer:
    name: backup
    scope: user
    user: alice
    unit:
      Description: Run user backup every morning
    timer:
      Persistent: true
    schedule:
      hour: 7
      minute: 0
    install:
      WantedBy: timers.target

- name: Remove timer
  systemd_timer:
    name: certbot
    state: absent
    enabled: false

- name: Remove a per-user timer
  systemd_timer:
    name: backup
    scope: user
    user: alice
    state: absent
"""

RETURN = r"""
timer_path:
  description: Path to the .timer file.
  returned: always
  type: str
on_calendar:
  description: List of generated OnCalendar expressions.
  returned: success
  type: list
  sample:
    - Mon,Thu *-*-* 02:58:00
enabled:
  description: The requested enable state, only present when I(enabled) was set.
  returned: when enabled is not null
  type: bool
changed:
  description: Whether anything changed.
  returned: always
  type: bool
"""

# ---------------------------------------------------------------------------------------


class SystemdTimer:
    """ """

    module = None

    def __init__(self, module):
        """ """
        self.module = module

        self.name: str = module.params.get("name")
        self.state: str = module.params.get("state")
        self.enabled: Optional[bool] = module.params.get("enabled")
        self.daemon_reload: bool = module.params.get("daemon_reload")
        self.description: str = module.params.get("description")
        self.scope: str = module.params.get("scope")
        self.user: Optional[str] = module.params.get("user")

        self.unit_options: Dict[str, Any] = module.params.get("unit")
        self.timer_options: Dict[str, Any] = module.params.get("timer")
        self.timer_validation: bool = module.params.get("timer_validation")
        self.install_options: Dict[str, Any] = module.params.get("install")

        self.schedule: Optional[Dict[str, Any]] = module.params.get("schedule")
        self.schedules_param: Optional[List[Dict[str, Any]]] = module.params.get(
            "schedules"
        )

        self.mode: str = module.params.get("mode")

        # Lazily created D-Bus client for the system manager (system scope only).
        self._sd_client = None

        # Resolve base path, owner and group depending on the scope.
        # Explicitly provided values always win over the scope-based defaults.
        self.base_path, self.owner, self.group = self.resolve_scope(
            scope=self.scope,
            user=self.user,
            path=module.params.get("path"),
            owner=module.params.get("owner"),
            group=module.params.get("group"),
        )

    def resolve_scope(
        self,
        scope: str,
        user: Optional[str],
        path: Optional[str],
        owner: Optional[str],
        group: Optional[str],
    ) -> Tuple[str, str, str]:
        """
        Resolve the effective base directory, owner and group for the unit file.

        For ``scope == "user"`` the target user is looked up in the password
        database to derive the home directory and the primary group. The unit is
        placed below ``~<user>/.config/systemd/user`` unless an explicit I(path)
        is given. Explicitly provided owner/group/path values always take
        precedence over the scope-based defaults.

        Returns:
            A tuple of (base_path, owner, group).
        """
        self.module.log(
            f"SystemdTimer::resolve_scope(scope={scope}, user={user}, "
            f"path={path}, owner={owner}, group={group})"
        )

        if scope == "user":
            try:
                pw = pwd.getpwnam(user)
            except KeyError:
                self.module.fail_json(
                    msg=f"scope=user requires an existing user, but '{user}' was not found."
                )

            try:
                primary_group = grp.getgrgid(pw.pw_gid).gr_name
            except KeyError:
                # Fall back to the gid as string if the group is not resolvable.
                primary_group = str(pw.pw_gid)

            base_path = path or os.path.join(pw.pw_dir, ".config", "systemd", "user")
            owner = owner or user
            group = group or primary_group
        else:
            base_path = path or "/lib/systemd/system"
            owner = owner or "root"
            group = group or "root"

        return base_path, owner, group

    def ensure_directory(self, directory: str, owner: str, group: str) -> None:
        """
        Create ``directory`` (including missing parents) and apply owner/group to
        every directory that had to be created.

        Existing directories are left untouched. This keeps the system scope
        behaviour unchanged (the target directory already exists) while making
        sure that directories created below a user's home (e.g. ``.config`` or
        ``.config/systemd``) are owned by the user instead of root.
        """
        to_create: List[str] = []
        current = directory

        while current and not os.path.isdir(current):
            to_create.append(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

        # Create from the top-most missing parent downwards.
        for new_dir in reversed(to_create):
            os.makedirs(new_dir, exist_ok=True)
            self.module.set_owner_if_different(new_dir, owner, False)
            self.module.set_group_if_different(new_dir, group, False)
            self.module.set_mode_if_different(new_dir, "0755", False)

    def _systemctl(self, args: List[str]) -> Tuple[int, str, str]:
        """
        Run ``systemctl`` via the CLI for I(scope=user).

        The call is routed to the target user's service manager via
        ``--user --machine=<user>@.host`` so that an arbitrary user's units can
        be managed even when the module itself runs as root. This requires the
        target user's systemd instance to be running (an active session or
        C(loginctl enable-linger <user>)).

        For I(scope=system) the D-Bus :class:`SystemdClient` helper is used
        instead (see :meth:`_system_client`), therefore this is only reached for
        the user scope.

        Returns:
            A tuple of (rc, stdout, stderr).
        """
        cmd = [self.module.get_bin_path("systemctl", required=True)]

        if self.scope == "user":
            cmd += ["--user", f"--machine={self.user}@.host"]

        cmd += list(args)

        self.module.log(f"SystemdTimer::_systemctl(cmd={cmd})")

        return self.module.run_command(cmd, check_rc=False)

    def _load_systemd(self):
        """
        Import the D-Bus helper classes lazily.

        The import is deferred so that the pure file-rendering use of this
        module does not require ``python3-dbus`` to be installed; the dependency
        only matters when daemon-reload / enable / disable is requested for
        I(scope=system). Fails cleanly when the library is unavailable.

        Returns:
            A tuple of (SystemdClient, SystemdError, UnitNotFoundError).
        """
        try:
            from ansible_collections.bodsch.systemd.plugins.module_utils.systemd import (
                SystemdClient,
                SystemdError,
                UnitNotFoundError,
            )
        except ImportError as e:
            self.module.fail_json(
                msg="The python3-dbus library is required to manage system units "
                f"via D-Bus (enabled / daemon_reload with scope=system): {e}"
            )

        return SystemdClient, SystemdError, UnitNotFoundError

    def _system_client(self, systemd_client_cls):
        """
        Lazily create and cache a D-Bus client bound to the system manager.
        """
        if self._sd_client is None:
            try:
                self._sd_client = systemd_client_cls(user_manager=False)
            except Exception as e:
                self.module.fail_json(
                    msg=f"could not connect to the system manager via D-Bus: {e}"
                )

        return self._sd_client

    def _close_client(self) -> None:
        """Close a previously opened D-Bus client, if any."""
        if self._sd_client is not None:
            try:
                self._sd_client.close()
            except Exception:
                pass
            self._sd_client = None

    def systemd_daemon_reload(self) -> None:
        """
        Trigger a daemon-reload for the configured scope.

        I(scope=system) uses the D-Bus helper, I(scope=user) the CLI routed to
        the target user's manager. On failure the module fails.
        """
        if self.scope == "user":
            rc, out, err = self._systemctl(["daemon-reload"])
            if rc != 0:
                self.module.fail_json(
                    msg=f"systemctl daemon-reload failed (scope=user): "
                    f"{(err or out).strip()}"
                )
            return

        systemd_client_cls, systemd_error, _ = self._load_systemd()
        client = self._system_client(systemd_client_cls)
        try:
            client.daemon_reload()
        except systemd_error as e:
            self.module.fail_json(msg=f"daemon-reload failed (scope=system): {e}")

    def unit_enabled_state(self, unit: str) -> str:
        """
        Return the install state of a unit (e.g. C(enabled), C(disabled),
        C(static), C(masked), C(not-found)).

        For I(scope=system) the state is queried via the D-Bus helper
        (``GetUnitFileState``); for I(scope=user) via ``systemctl is-enabled``,
        whose non-zero exit for several normal states (e.g. C(disabled)) is
        ignored - only the textual state is evaluated.
        """
        if self.scope == "user":
            _rc, out, _err = self._systemctl(["is-enabled", unit])
            return (out or "").strip()

        systemd_client_cls, systemd_error, unit_not_found = self._load_systemd()
        client = self._system_client(systemd_client_cls)
        try:
            return client.get_unit_file_state(unit)
        except unit_not_found:
            return "not-found"
        except systemd_error as e:
            self.module.fail_json(
                msg=f"querying enable state of {unit} failed (scope=system): {e}"
            )

    def _set_unit_enabled(self, unit: str, enable: bool) -> Optional[str]:
        """
        Enable or disable ``unit`` using the transport for the configured scope.

        Returns:
            None on success, otherwise an error message string.
        """
        action = "enable" if enable else "disable"

        if self.scope == "user":
            rc, out, err = self._systemctl([action, unit])
            return None if rc == 0 else (err or out).strip()

        systemd_client_cls, systemd_error, _ = self._load_systemd()
        client = self._system_client(systemd_client_cls)
        try:
            if enable:
                client.enable([unit])
            else:
                client.disable([unit])
            return None
        except systemd_error as e:
            return str(e)

    def apply_enabled(self, unit: str, want_enabled: bool) -> bool:
        """
        Ensure ``unit`` is enabled or disabled according to I(want_enabled).

        Returns:
            True if a change was made (or would be made in check mode),
            otherwise False.
        """
        state = self.unit_enabled_state(unit)
        enabled_now = state in ("enabled", "enabled-runtime", "alias")

        if want_enabled:
            # static/indirect/generated units carry no install information and
            # cannot be enabled; treat them as already in the desired state.
            if enabled_now or state in ("static", "indirect", "generated"):
                return False
            if self.module.check_mode:
                return True
            err = self._set_unit_enabled(unit, True)
            if err:
                self.module.fail_json(
                    msg=f"enabling {unit} failed (scope={self.scope}): {err}"
                )
            return True

        # want_enabled is False -> disable if currently enabled
        if not enabled_now:
            return False
        if self.module.check_mode:
            return True
        err = self._set_unit_enabled(unit, False)
        if err:
            self.module.fail_json(
                msg=f"disabling {unit} failed (scope={self.scope}): {err}"
            )
        return True

    def run(self):
        """
        Public entry point. Wraps :meth:`_run` to guarantee the D-Bus client is
        closed regardless of how the run terminates.
        """
        try:
            return self._run()
        finally:
            self._close_client()

    def _run(self):
        """ """
        self.module.log("SystemdTimer::run()")

        timer_path = os.path.join(self.base_path, f"{self.name}.timer")

        result: Dict[str, Any] = {
            "changed": False,
            "timer_path": timer_path,
            "on_calendar": [],
        }

        unit_name = f"{self.name}.timer"

        # Absent: optional disable, Datei löschen, daemon-reload
        if self.state == "absent":
            # Only talk to the service manager when the caller opted into enable
            # management via enabled=false: then the unit is disabled before the
            # file is removed so its install symlinks are cleaned up while the
            # unit is still known. A plain "state: absent" never touches the
            # manager for this step (best effort - the user manager may not be
            # reachable).
            if (
                self.enabled is False
                and not self.module.check_mode
                and os.path.exists(timer_path)
            ):
                state = self.unit_enabled_state(unit_name)
                if state in ("enabled", "enabled-runtime", "alias"):
                    err = self._set_unit_enabled(unit_name, False)
                    if err:
                        self.module.warn(
                            f"Could not disable {unit_name} (scope={self.scope}): {err}"
                        )

            changed = self.remove_file(timer_path)
            result["changed"] = changed

            if self.daemon_reload and changed and not self.module.check_mode:
                self.systemd_daemon_reload()

            return result

        # state == present: Datei erzeugen/aktualisieren
        validator = SystemdValidator(
            module=self.module,
            validate_timespans=self.timer_validation,
        )

        unit_options = validator.validate_unit_options(self.unit_options or {})
        timer_options = validator.validate_timer_options(self.timer_options or {})
        install_options = validator.validate_install_options(self.install_options or {})

        # Convenience: map the top-level "description" to [Unit] Description
        # unless it was already provided via unit.Description.
        if self.description and "Description" not in unit_options:
            unit_options["Description"] = self.description

        # schedule / schedules -> OnCalendar
        on_calendar_values: List[str] = []

        if self.schedule:
            spec = self.build_calendar_spec(self.schedule)

            if spec:
                on_calendar_values.append(spec)

        if self.schedules_param:
            for sch in self.schedules_param:
                spec = self.build_calendar_spec(sch)
                if spec:
                    on_calendar_values.append(spec)

        # Nur setzen, wenn nicht explizit über timer.OnCalendar überschrieben
        if on_calendar_values and "OnCalendar" not in timer_options:
            if len(on_calendar_values) == 1:
                timer_options["OnCalendar"] = on_calendar_values[0]
            else:
                timer_options["OnCalendar"] = on_calendar_values

        result["on_calendar"] = on_calendar_values

        # Sections rendern
        sections: List[str] = []

        sections.append(self.render_section("Unit", unit_options or {}))
        sections.append(self.render_section("Timer", timer_options or {}))

        if install_options:
            sections.append(self.render_section("Install", install_options))

        self.module.log(f"  - sections: {sections}")

        content = "\n\n".join(sections) + "\n"

        # validator.validate_timer_options(content)

        # Datei schreiben, falls nötig
        changed, diff = self.write_file(
            timer_path, content, self.owner, self.group, self.mode
        )
        result["changed"] = changed
        result["diff"] = diff

        # daemon-reload only when the unit file actually changed
        if self.daemon_reload and changed and not self.module.check_mode:
            self.systemd_daemon_reload()

        # enable / disable the timer if requested (enabled=None -> leave as is)
        if self.enabled is not None:
            enabled_changed = self.apply_enabled(unit_name, self.enabled)
            result["changed"] = result["changed"] or enabled_changed
            result["enabled"] = self.enabled

        return result

    def build_calendar_spec(self, schedule: Dict[str, Any]) -> Optional[str]:
        """
        Wandelt einen schedule-Dict in einen systemd Calendar String um.
        Unterstützt:
          - raw: komplett vorgegebenes Pattern
          - special: shortcuts (daily, weekly, ...)
          - year, month, day, weekday, hour, minute, second
        """
        self.module.log(f"SystemdTimer::build_calendar_spec(schedule={schedule})")

        if not schedule:
            return None

        raw = schedule.get("raw")
        if raw:
            return str(raw)

        special = schedule.get("special")
        if special:
            return str(special)

        # weekday separat, weil optionaler führender Block
        weekday = schedule.get("weekday")
        weekday_str = ""

        if weekday is not None:
            if isinstance(weekday, (list, tuple, set)):
                normalized = [normalize_weekday_token(w, self.module) for w in weekday]
                weekday_str = ",".join(normalized)
            else:
                weekday_str = normalize_weekday_token(weekday, self.module)

        year = timer_component(schedule.get("year"), default="*")
        month = timer_component(schedule.get("month"), default="*", pad_width=2)
        day = timer_component(schedule.get("day"), default="*", pad_width=2)

        hour = timer_component(schedule.get("hour"), default="*", pad_width=2)
        minute = timer_component(schedule.get("minute"), default="*", pad_width=2)
        second = timer_component(schedule.get("second"), default="00", pad_width=2)

        date_part = f"{year}-{month}-{day}"
        time_part = f"{hour}:{minute}:{second}"

        if weekday_str:
            return f"{weekday_str} {date_part} {time_part}"

        return f"{date_part} {time_part}"

    def render_section(self, name, options):
        """
        Rendert einen Abschnitt im systemd-Unit-Format.
        options: dict[str, str|list[str]]
        """
        self.module.log(f"SystemdTimer::render_section(name={name}, options={options})")

        lines = [f"[{name}]"]
        for key, value in options.items():
            if value is None:
                continue
            # sd_key = snake_to_systemd(key)
            # Mehrere Werte -> mehrere Zeilen
            if isinstance(value, (list, tuple, set)):
                for v in value:
                    lines.append(f"{key} = {v}")
            else:
                lines.append(f"{key} = {value}")

        return "\n".join(lines)

    def write_file(
        self, path: str, content: str, owner: str, group: str, mode: str
    ) -> Tuple[bool, Dict]:
        """
        Schreibt eine Datei nur dann, wenn sich der Inhalt geändert hat.

        Setzt bei aktiviertem diff-Modus before/after in module.result["diff"].
        Außerdem werden Besitzer, Gruppe und Modus über Ansible-Helfer gesetzt.
        """
        self.module.log(
            f"SystemdTimer::write_file(path={path}, content, owner={owner}, group={group}, mode={mode}"
        )

        changed = False
        before = ""
        result = {}

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    before = f.read()
            except OSError:
                # ignore read problems, treat as changed
                before = ""

        self.module.log(f"  - before: {before}")
        self.module.log(f"  - content: {content}")
        self.module.log(f"  - check_mode: {self.module.check_mode}")

        if before != content:
            changed = True

            if not self.module.check_mode:
                self.ensure_directory(os.path.dirname(path), owner, group)

                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

                # Dateirechte setzen
                self.module.set_owner_if_different(path, owner, False)
                self.module.set_group_if_different(path, group, False)
                self.module.set_mode_if_different(path, mode, False)

            # if self.module._diff:

            result["diff"] = {}
            result["diff"]["before"] = before
            result["diff"]["after"] = content

        return (changed, result)

    def remove_file(self, path: str) -> bool:
        """
        Entfernt die angegebene Datei, falls sie existiert.

        Gibt True zurück, wenn die Datei entfernt wurde, sonst False.
        Bei Fehlern beim Entfernen schlägt das Modul mit fail_json fehl.
        """
        self.module.log(f"SystemdTimer::remove_file(path={path}")

        if os.path.exists(path):
            if not self.module.check_mode:
                try:
                    os.remove(path)
                except OSError as e:
                    self.module.fail_json(msg=f"Failed to remove {path}: {e}")
            return True
        return False

    # ---- FRIEDHOF ---


def main():

    argument_spec = dict(
        name=dict(type="str", required=True),
        description=dict(type="str", required=False),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        enabled=dict(type="bool", default=None),
        daemon_reload=dict(type="bool", default=True),
        scope=dict(type="str", default="system", choices=["system", "user"]),
        user=dict(type="str", required=False, default=None),
        path=dict(type="str", default=None),
        unit=dict(type="dict", default=None),
        timer=dict(type="dict", default=None),
        timer_validation=dict(type="bool", default=True),
        install=dict(type="dict", default=None),
        schedule=dict(type="dict", default=None),
        schedules=dict(type="list", elements="dict", default=None),
        owner=dict(type="str", default=None),
        group=dict(type="str", default=None),
        mode=dict(type="str", default="0644"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ("scope", "user", ("user",)),
        ],
    )

    t = SystemdTimer(module)
    result = t.run()

    module.log(msg=f"= result: {result}")

    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
