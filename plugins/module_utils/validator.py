from __future__ import absolute_import, division, print_function

import subprocess
from typing import Any, Dict, List, Tuple

from ansible_collections.bodsch.systemd.plugins.module_utils.helper import (
    bool_to_systemd,
    snake_to_systemd,
)
from ansible_collections.bodsch.systemd.plugins.module_utils.static import (
    TIMER_BOOL_KEYS,
    TIMER_BOOL_PARAM_KEYS,
    TIMER_TIMESPAN_KEYS,
    TIMER_TIMESPAN_PARAM_KEYS,
    VALID_INSTALL_KEYS,
    VALID_TIMER_KEYS,
    VALID_UNIT_KEYS,
)


class SystemdValidator:
    """
    Validator and mapper for systemd [Unit], [Timer] and [Install] sections.

    Can be used inside an Ansible module (with an AnsibleModule instance) as well
    as from plain Python code. Errors are reported either via module.fail_json()
    (if available) or by raising ValueError.
    """

    def __init__(
        self,
        module: Any,
        *,
        strict_unit: bool = False,
        strict_timer: bool = False,
        strict_install: bool = False,
        validate_timespans: bool = True,
        systemd_analyze_cmd: str = "systemd-analyze",
    ) -> None:
        """
        Initialize a SystemdValidator.

        Args:
            module:
                AnsibleModule-like object.
            strict_unit:
                If True, only keys from VALID_UNIT_KEYS are allowed in [Unit].
            strict_timer:
                If True, only keys from VALID_TIMER_KEYS are allowed in [Timer].
            strict_install:
                If True, only keys from VALID_INSTALL_KEYS are allowed in [Install].
            validate_timespans:
                If True, timespans are validated using "systemd-analyze timespan".
            systemd_analyze_cmd:
                Command name or path to the systemd-analyze binary.
        """
        self.module = module
        self.strict_unit = strict_unit
        self.strict_timer = strict_timer
        self.strict_install = strict_install
        self.validate_timespans = validate_timespans
        self.systemd_analyze_cmd = systemd_analyze_cmd

    # -------------------------------------------------------------------------
    # öffentliche Validierungs-/Mapping-Funktionen
    # -------------------------------------------------------------------------

    def validate_unit_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize options for the [Unit] section.

        Behavior:
          * snake_case keys are mapped to systemd-style keys where appropriate.
          * known convenience keys are mapped via an explicit table.
          * in strict mode, resulting keys are validated against VALID_UNIT_KEYS.

        Args:
            options: Raw option dictionary as provided by the caller.

        Returns:
            A new dictionary with normalized keys, e.g. 'Description', 'After', ...
        """
        self.module.log(f"SystemdValidator::validate_unit_options(options={options})")

        unit_section: Dict[str, Any] = {}

        unit_map = {
            "description": "Description",
            "documentation": "Documentation",
            "requires": "Requires",
            "wants": "Wants",
            "binds_to": "BindsTo",
            "part_of": "PartOf",
            "conflicts": "Conflicts",
            "before": "Before",
            "after": "After",
            "on_failure": "OnFailure",
        }

        for key, value in options.items():
            if value is None:
                continue

            # existing systemd name or convenience key?
            if key in unit_map:
                sd_key = unit_map[key]
            elif key in VALID_UNIT_KEYS:
                sd_key = key
            elif "_" in key and key.lower() == key:
                sd_key = snake_to_systemd(key)
            else:
                sd_key = key

            unit_section[sd_key] = value

        if self.strict_unit:
            invalid = [k for k in unit_section.keys() if k not in VALID_UNIT_KEYS]
            if invalid:
                self._fail(
                    "Unsupported [Unit] options",
                    invalid_keys=invalid,
                    section="Unit",
                )

        return unit_section

    def validate_timer_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize options for the [Timer] section.

        Behavior:
          * convenience options (e.g. 'randomized_delay_sec', 'time_zone') are
            mapped via an explicit table.
          * snake_case keys are converted using snake_to_systemd().
          * timespan-like options are validated via validate_timespan().
          * boolean-like options are converted to 'true'/'false'.
          * in strict mode, resulting keys are validated against VALID_TIMER_KEYS.

        Args:
            options: Raw option dictionary as provided by the caller.

        Returns:
            A new dictionary with normalized keys (e.g. 'RandomizedDelaySec',
            'OnBootSec', ...).
        """
        self.module.log(f"SystemdValidator::validate_timer_options(options={options})")

        timer_section: Dict[str, Any] = {}

        # Komfort-Optionen aus options mappen
        option_map = {
            "persistent": "Persistent",
            "randomized_delay_sec": "RandomizedDelaySec",
            "accuracy_sec": "AccuracySec",
            "on_active_sec": "OnActiveSec",
            "on_boot_sec": "OnBootSec",
            "on_unit_active_sec": "OnUnitActiveSec",
            "on_unit_inactive_sec": "OnUnitInactiveSec",
            "unit": "Unit",
            "wake_system": "WakeSystem",
            "remain_after_elapse": "RemainAfterElapse",
            "timezone": "TimeZone",
            "time_zone": "TimeZone",  # alias
        }

        for key, value in options.items():
            if value is None:
                continue

            orig_key = key

            # 1) translate key to systemd key
            if key in option_map:
                sd_key = option_map[key]
            elif key in VALID_TIMER_KEYS:
                sd_key = key
            elif "_" in key and key.lower() == key:
                sd_key = snake_to_systemd(key)
            else:
                sd_key = key

            # 2) validate timespans (use original parameter name for error messages)
            if sd_key in TIMER_TIMESPAN_KEYS or orig_key in TIMER_TIMESPAN_PARAM_KEYS:
                ok, normalized = self.validate_timespan(value, orig_key)
                if not ok:
                    self._fail(
                        f"Invalid timespan for {orig_key}",
                        value=value,
                    )
                value = normalized

            # 3) map booleans
            if sd_key in TIMER_BOOL_KEYS or orig_key in TIMER_BOOL_PARAM_KEYS:
                if isinstance(value, bool):
                    value = bool_to_systemd(value)
                # strings like "true"/"false" are accepted as-is

            timer_section[sd_key] = value

        if self.strict_timer:
            invalid = [k for k in timer_section.keys() if k not in VALID_TIMER_KEYS]
            if invalid:
                self._fail(
                    "Unsupported [Timer] options",
                    invalid_keys=invalid,
                    section="Timer",
                )

        return timer_section

    def validate_install_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize options for the [Install] section.

        Behavior:
          * snake_case keys are mapped to well-known systemd install keys.
          * in strict mode, resulting keys are validated against VALID_INSTALL_KEYS.

        Args:
            options: Raw option dictionary as provided by the caller.

        Returns:
            A new dictionary with normalized keys (e.g. 'WantedBy', 'Alias', ...).
        """
        self.module.log(
            f"SystemdValidator::validate_install_options(options={options})"
        )

        install_section: Dict[str, Any] = {}

        install_map = {
            "wanted_by": "WantedBy",
            "required_by": "RequiredBy",
            "also": "Also",
            "alias": "Alias",
            "default_instance": "DefaultInstance",
        }

        for key, value in options.items():
            if value is None:
                continue

            if key in install_map:
                sd_key = install_map[key]
            elif key in VALID_INSTALL_KEYS:
                sd_key = key
            elif "_" in key and key.lower() == key:
                sd_key = snake_to_systemd(key)
            else:
                sd_key = key

            install_section[sd_key] = value

        if self.strict_install:
            invalid = [k for k in install_section.keys() if k not in VALID_INSTALL_KEYS]
            if invalid:
                self._fail(
                    "Unsupported [Install] options",
                    invalid_keys=invalid,
                    section="Install",
                )

        return install_section

    def validate_timespan(self, value: Any, param_name: str) -> Tuple[bool, str]:
        """
        Validate a systemd timespan value.

        Accepted forms:
          * int -> seconds (normalized to "<value>s")
          * str -> passed through and, optionally, validated via systemd-analyze

        If validate_timespans is False, only a minimal check (non-empty string)
        is performed and the value is returned unchanged.

        Args:
            value: Value to validate (int or str).
            param_name: Original parameter name for error reporting.

        Returns:
            (True, normalized_string) on success or
            (False, error_message) on failure.
        """
        self.module.log(
            f"SystemdValidator::validate_timespan(value={value}, param_name={param_name})"
        )

        if value is None:
            msg = f"{param_name} must not be None"
            self.module.log(msg)
            return (False, msg)

        if isinstance(value, int):
            return (True, f"{value}s")

        if not isinstance(value, str):
            msg = (
                f"{param_name} must be int (seconds) or str (systemd timespan), "
                f"got {type(value).__name__}"
            )
            self.module.log(msg)
            return (False, msg)

        val = value.strip()
        if not val:
            msg = f"{param_name} must not be empty"
            self.module.log(msg)
            return (False, msg)

        if not self.validate_timespans:
            # minimal check only
            return (True, val)

        # use systemd-analyze timespan for validation
        rc, out, err = self._run_command([self.systemd_analyze_cmd, "timespan", val])
        if rc != 0:
            msg = f"Invalid systemd timespan for {param_name!r}: {val!r}"
            self.module.log(f"{msg}; rc={rc}, stdout={out!r}, stderr={err!r}")
            return (False, msg)

        return (True, val)

    # -------------------------------------------------------------------------
    # internal helpers: logging / error signaling / command wrapper
    # -------------------------------------------------------------------------

    def _fail(self, msg: str, **kwargs: Any) -> None:
        """
        Report a validation error.

        If a module with fail_json() is available, fail_json() is called, otherwise
        a ValueError is raised.
        """
        self._log(f"ERROR: {msg} ({kwargs})")
        if self.module is not None and hasattr(self.module, "fail_json"):
            self.module.fail_json(msg=msg, **kwargs)
        raise ValueError(f"{msg}: {kwargs}")

    def _run_command(self, args: List[str]) -> Tuple[int, str, str]:
        """
        Execute an external command.

        Behavior:
          * with an AnsibleModule: use module.run_command()
          * otherwise: use subprocess.run()

        Returns:
            (returncode, stdout, stderr)
        """
        self.module.log(f"SystemdValidator::_run_command(args={args})")

        if self.module is not None and hasattr(self.module, "run_command"):
            rc, out, err = self.module.run_command(args, check_rc=False)
            return rc, out, err

        cp = subprocess.run(args, capture_output=True, text=True)

        return cp.returncode, cp.stdout, cp.stderr
