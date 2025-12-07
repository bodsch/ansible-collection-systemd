#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2025, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
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
  state:
    description:
      - Whether the timer unit file should be present.
    type: str
    choices: [present, absent]
    default: present
  path:
    description:
      - Base directory for the .timer file.
    type: str
    default: /lib/systemd/system
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
    type: bool
  daemon_reload:
    description:
      - Whether to run C(systemctl daemon-reload) after changing the file.
    type: bool
    default: true
  owner:
    description:
      - Owner of the .timer file.
    type: str
    default: root
  group:
    description:
      - Group of the .timer file.
    type: str
    default: root
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

- name: Remove timer
  systemd_timer:
    name: certbot
    state: absent
    enabled: false
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
        self.description: str = module.params.get("description")
        self.base_path: str = module.params.get("path")

        self.unit_options: Dict[str, Any] = module.params.get("unit")
        self.timer_options: Dict[str, Any] = module.params.get("timer")
        self.timer_validation: bool = module.params.get("timer_validation")
        self.install_options: Dict[str, Any] = module.params.get("install")

        self.schedule: Optional[Dict[str, Any]] = module.params.get("schedule")
        self.schedules_param: Optional[List[Dict[str, Any]]] = module.params.get(
            "schedules"
        )

        self.owner: str = module.params.get("owner")
        self.group: str = module.params.get("group")
        self.mode: str = module.params.get("mode")

    def run(self):
        """ """
        self.module.log("SystemdTimer::run()")

        timer_path = os.path.join(self.base_path, f"{self.name}.timer")

        result: Dict[str, Any] = {
            "changed": False,
            "timer_path": timer_path,
            "on_calendar": [],
        }

        # Absent: Datei löschen, optional disable
        if self.state == "absent":
            changed = self.remove_file(timer_path)
            result["changed"] = changed

            return result

        # state == present: Datei erzeugen/aktualisieren
        validator = SystemdValidator(module=self.module)

        unit_options = validator.validate_unit_options(self.unit_options)
        timer_options = validator.validate_timer_options(self.timer_options)
        install_options = validator.validate_install_options(self.install_options)

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
        if on_calendar_values and "OnCalendar" not in self.timer_options:
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
                os.makedirs(os.path.dirname(path), exist_ok=True)

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
        path=dict(type="str", default="/lib/systemd/system"),
        unit=dict(type="dict", default=None),
        timer=dict(type="dict", default=None),
        timer_validation=dict(type="bool", default=True),
        install=dict(type="dict", default=None),
        schedule=dict(type="dict", default=None),
        schedules=dict(type="list", elements="dict", default=None),
        owner=dict(type="str", default="root"),
        group=dict(type="str", default="root"),
        mode=dict(type="str", default="0644"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    t = SystemdTimer(module)
    result = t.run()

    module.log(msg=f"= result: {result}")

    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
