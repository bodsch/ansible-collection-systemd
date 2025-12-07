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

DOCUMENTATION = r"""
---
module: systemd_timer
short_description: Manage systemd timer unit files
description:
  - Erstellt, aktualisiert oder entfernt systemd Timer Units (.timer Dateien).
  - Unterstützt generische Optionen für die Abschnitte [Unit], [Timer], [Install].
  - Bietet eine strukturierte, dynamische Definition von OnCalendar über schedule/schedules.
options:
  name:
    description:
      - Basisname der Timer Unit (ohne ".timer").
      - Die Datei wird unter I(path)/<name>.timer geschrieben.
    type: str
    required: true
  state:
    description:
      - Ob die Timer Unit Datei vorhanden sein soll.
    type: str
    choices: [present, absent]
    default: present
  path:
    description:
      - Basisverzeichnis für die .timer Datei.
    type: str
    default: /etc/systemd/system
  unit:
    description:
      - Optionen für den [Unit] Abschnitt als Key/Value Mapping.
      - Werte können Skalare oder Listen sein; Booleans werden in C(true)/C(false) umgewandelt.
    type: dict
  timer:
    description:
      - Optionen für den [Timer] Abschnitt als Key/Value Mapping.
      - Wenn C(OnCalendar) hier gesetzt ist, überschreibt es schedule/schedules.
    type: dict
  install:
    description:
      - Optionen für den [Install] Abschnitt als Key/Value Mapping.
    type: dict
  schedule:
    description:
      - Strukturierte Definition für eine einzelne OnCalendar-Spezifikation.
      - Wird ignoriert, wenn C(timer.OnCalendar) gesetzt ist.
    type: dict
    suboptions:
      raw:
        description:
          - Rohes systemd Calendar-Pattern, das unverändert als OnCalendar geschrieben wird.
        type: str
      special:
        description:
          - Shortcut wie C(hourly), C(daily), C(weekly), C(monthly), C(yearly), C(quarterly), C(semiannually) etc.
        type: str
      year:
        description:
          - Jahr(e), z.B. C(2025) oder Liste/Bereich als String (C(2025,2026), C(2025..2030)).
        type: raw
      month:
        description:
          - Monat(e), z.B. C(1), C(01), C(3,6,9) oder C(*).
        type: raw
      day:
        description:
          - Tag(e) des Monats, z.B. C(1), C(01), C(1,15), C(*/2).
        type: raw
      weekday:
        description:
          - Wochentag(e), z.B. C(Mon), C(Mon,Fri) oder numerisch C(1..7).
        type: raw
      hour:
        description:
          - Stunde(n), z.B. C(2), C(02), C(0..23), C(*/2).
        type: raw
      minute:
        description:
          - Minute(n), z.B. C(0), C(0,30), C(*/15).
        type: raw
      second:
        description:
          - Sekunde(n), Standard ist C(00).
        type: raw
  schedules:
    description:
      - Liste mehrerer strukturierter OnCalendar-Definitionen.
      - Jede Liste wird zu einem eigenen C(OnCalendar=) Eintrag.
    type: list
    elements: dict
  enabled:
    description:
      - Ob der Timer per C(systemctl enable/disable) aktiviert werden soll.
      - C(null) bedeutet, dass der Enable-Status nicht verändert wird.
    type: bool
  daemon_reload:
    description:
      - Ob nach Änderung der Datei C(systemctl daemon-reload) ausgeführt werden soll.
    type: bool
    default: true
  owner:
    description:
      - Besitzer der .timer Datei.
    type: str
    default: root
  group:
    description:
      - Gruppe der .timer Datei.
    type: str
    default: root
  mode:
    description:
      - Dateimodus der .timer Datei.
    type: str
    default: '0644'

author:
  - Your Name (@yourhandle)
"""

EXAMPLES = r"""
- name: Einfacher daily Timer für Certbot
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

- name: Timer zweimal täglich zu festen Uhrzeiten
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

- name: Komplexeres Pattern - Mo und Do um 02:58
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

- name: Rohes Calendar-Pattern direkt verwenden
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

- name: Timer entfernen
  systemd_timer:
    name: certbot
    state: absent
    enabled: false
"""

RETURN = r"""
timer_path:
  description: Pfad zur .timer Datei.
  returned: always
  type: str
on_calendar:
  description: Liste der erzeugten OnCalendar-Ausdrücke.
  returned: success
  type: list
  sample:
    - Mon,Thu *-*-* 02:58:00
changed:
  description: Ob sich etwas geändert hat.
  returned: always
  type: bool
"""


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

        # if weekday is not None:
        #     if isinstance(weekday, (list, tuple, set)):
        #         weekday_str = ",".join(str(w) for w in weekday)
        #     else:
        #         weekday_str = str(weekday)

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
