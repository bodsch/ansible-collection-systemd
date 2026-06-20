#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2020-2026, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

"""
Ansible module: bodsch.systemd.networkd_profiles

Manages a whole set of systemd-networkd profile files (.link / .netdev /
.network) in a single module invocation. Avoids the per-iteration fork
overhead of Ansible ``loop`` constructs.

Supports repeatable sections (e.g. multiple [Address], [Route], [WireGuardPeer]),
empty-value reset semantics (``Key=``) and an optional validation step that
performs ``networkctl reload`` and rolls back only the offending profiles on
failure.
"""

from __future__ import absolute_import, division, print_function

import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.checksum import Checksum
from ansible_collections.bodsch.core.plugins.module_utils.directory import (
    create_directory,
)

from ansible_collections.bodsch.systemd.plugins.module_utils.networkd.renderer import NetworkdRenderer
from ansible_collections.bodsch.systemd.plugins.module_utils.networkd.validator import NetworkdValidator

__metaclass__ = type

# ---------------------------------------------------------------------------------------

DOCUMENTATION = """
module: networkd_profiles
author:
  - Bodo 'bodsch' Schulz (@bodsch)
short_description: Manage a set of systemd-networkd profile files in one call.
version_added: 1.3.0

description:
  - Creates, updates and removes systemd-networkd profile files
    (C(.link), C(.netdev), C(.network)) in a single module invocation.
  - Designed as a batch alternative to per-profile ``loop`` constructs to
    avoid per-iteration fork and SSH overhead.
  - Supports repeatable sections by accepting either a dict (single
    occurrence) or a list of dicts (multiple occurrences) per section.
  - Optionally validates the configuration after writing via
    ``networkctl reload`` and rolls back individual offending profiles.

options:
  profiles:
    description:
      - Mapping of profile categories to profile definitions.
      - Top-level keys C(link), C(netdev), C(network) are optional;
        unknown keys are ignored.
      - Each category maps profile basenames to a definition dict with
        the keys C(state) (C(present)/C(absent), default C(present)),
        C(description) (optional comment block) and C(config) (dict of
        sections with options).
      - A section value may be a dict (single occurrence) or a list of
        dicts (multiple occurrences, e.g. several C([Address]) blocks).
      - List values inside a section dict expand to repeated
        C(Key=Value) lines (required for keys like C(DNS)).
      - An empty string C("") renders as C(Key=) to reset a list value
        in drop-ins. C(None)/null is skipped entirely.
      - Booleans are rendered lower-case (C(true)/C(false)).
      - Section and option names are written verbatim - systemd is
        case-sensitive (e.g. C(NetDev), not C(Netdev)).
    type: dict
    required: true
  directory:
    description:
      - Target directory where profile files are written.
    type: path
    default: /etc/systemd/network
  mode:
    description:
      - File mode of the resulting profile files (octal string).
    type: str
    default: "0644"
  purge:
    description:
      - Remove profile files in C(directory) that are not managed by this
        invocation. Only files with the managed extensions
        (C(.link), C(.netdev), C(.network)) are considered.
    type: bool
    default: false
  validate:
    description:
      - If C(true), run ``networkctl reload`` after writing and roll back
        any profile that appears in the resulting error output. A second
        reload is performed with the cleaned-up set.
      - Has no effect in check mode.
    type: bool
    default: false
  validate_timeout:
    description:
      - Timeout (seconds) for the ``networkctl reload`` invocation.
    type: int
    default: 30
  validate_strict:
    description:
      - Only relevant when ``validate=true``.
      - When the environment cannot run ``networkctl reload`` at all
        (e.g. inside a container without D-Bus, or when
        ``systemd-networkd.service`` is not active), validation is
        normally skipped with a warning so that container-based tests
        (Molecule, Docker) do not fail spuriously.
      - Set this to ``true`` to fail the task in that situation instead.
    type: bool
    default: false
"""

EXAMPLES = """
- name: manage networkd profiles with validation
  bodsch.systemd.networkd_profiles:
    profiles:
      network:
        wg0:
          state: present
          config:
            Match:
              Name: wg0
            Network:
              Address: 10.10.0.1/24
            Address:
              - Address: 10.10.0.1/24
                Label: primary
              - Address: 10.10.0.2/24
            Route:
              - Gateway: 10.10.0.254
                Destination: 10.20.0.0/16
              - Gateway: 10.10.0.253
                Destination: 10.30.0.0/16
    validate: true
    purge: false
"""

RETURN = """
changed:
  description: True if at least one profile was created, modified or removed.
  type: bool
  returned: always
failed:
  description: Whether the module run failed.
  type: bool
  returned: always
profiles:
  description: Per-profile result list.
  type: list
  elements: dict
  returned: always
purged:
  description: Paths removed by ``purge``.
  type: list
  elements: str
  returned: when purge=true
validation:
  description: Result of the validation step.
  type: dict
  returned: when validate=true
  contains:
    ok:
      description: True if ``networkctl reload`` ultimately succeeded.
      type: bool
    rolled_back:
      description: Profile paths that were rolled back to their previous state.
      type: list
      elements: str
    journal:
      description: Relevant journal lines collected during validation.
      type: list
      elements: str
    skipped:
      description: True if validation could not run in this environment.
      type: bool
    skip_reason:
      description: Human readable reason; only set when ``skipped`` is True.
      type: str
"""

# ---------------------------------------------------------------------------------------

VALID_TYPES: Tuple[str, ...] = ("link", "netdev", "network")


class NetworkdProfiles:
    """
    Batch worker that processes all networkd profiles in a single run.

    The class owns one temporary working directory shared by all profiles.
    ``run()`` is the only public entry point and returns a dict suitable
    for ``module.exit_json``.
    """

    def __init__(self, module: AnsibleModule) -> None:
        """
        :param module: Active AnsibleModule instance.
        """
        self.module: AnsibleModule = module

        self.profiles: Dict[str, Dict[str, Any]] = module.params["profiles"] or {}
        self.directory: str = module.params["directory"]
        self.mode: str = module.params["mode"]
        self.purge: bool = bool(module.params["purge"])
        self.validate: bool = bool(module.params["validate"])
        self.validate_strict: bool = bool(module.params["validate_strict"])
        self.validate_timeout: int = int(module.params["validate_timeout"])

        self.tmp_directory: str = os.path.join(
            "/run/.ansible", f"networkd_profiles.{os.getpid()}"
        )
        self.backup_directory: str = os.path.join(self.tmp_directory, "backup")

        self.checksum: Optional[Checksum] = None
        self._mode_octal: int = 0o644

        # Per-target backup metadata used for rollback.
        # path -> dict(existed=bool, backup=Optional[str])
        self._backups: Dict[str, Dict[str, Any]] = {}

    # -- public API ----------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """
        Process every profile, optionally purge unmanaged files and validate.

        :returns: Aggregated result dict.
        """
        try:
            self._mode_octal = int(self.mode, 8)
        except ValueError as exc:
            self.module.fail_json(msg=f"Invalid mode {self.mode!r}: {exc}")

        self.checksum = Checksum(self.module)

        if not self.module.check_mode:
            create_directory(directory=self.directory, mode="0755")
            create_directory(directory=self.tmp_directory, mode="0750")
            create_directory(directory=self.backup_directory, mode="0750")

        per_profile: List[Dict[str, Any]] = []
        managed_paths: List[str] = []

        try:
            for profile_type in VALID_TYPES:
                bucket = self.profiles.get(profile_type) or {}
                if not isinstance(bucket, dict):
                    self.module.fail_json(
                        msg=f"profiles.{profile_type} must be a dict, "
                        f"got {type(bucket).__name__}"
                    )
                for name, spec in bucket.items():
                    result = self._process_one(profile_type, name, spec or {})
                    per_profile.append(result)
                    managed_paths.append(result["path"])

            purged: List[str] = []
            if self.purge:
                purged = self._purge(managed_paths)

            validation: Optional[Dict[str, Any]] = None
            if self.validate and not self.module.check_mode:
                validation = self._validate(per_profile, purged)

        finally:
            if os.path.exists(self.tmp_directory):
                shutil.rmtree(self.tmp_directory, ignore_errors=True)

        any_changed: bool = any(p["changed"] for p in per_profile) or bool(purged)

        result: Dict[str, Any] = dict(
            changed=any_changed,
            failed=False,
            profiles=per_profile,
        )
        if self.purge:
            result["purged"] = purged
        if validation is not None:
            result["validation"] = validation
            if not validation["ok"]:
                # Surface a clean failure to the user.
                self.module.fail_json(
                    msg="networkctl reload reported errors after rollback.",
                    **result,
                )
        return result

    # -- per-profile ---------------------------------------------------------------------

    def _process_one(
        self,
        profile_type: str,
        name: str,
        spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a single profile entry.

        :param profile_type: One of ``link``/``netdev``/``network``.
        :param name: Profile basename (without extension).
        :param spec: Definition dict (``state``, ``description``, ``config``).
        :returns: Result dict.
        """
        self._validate_name(name)

        state: str = spec.get("state", "present")
        if state not in ("present", "absent"):
            self.module.fail_json(msg=f"profile {name!r}: invalid state {state!r}")

        target: str = os.path.join(self.directory, f"{name}.{profile_type}")
        base: Dict[str, Any] = dict(
            name=name, type=profile_type, path=target, state=state
        )

        if state == "absent":
            self._snapshot(target)
            base.update(self._remove(target))
            return base

        config: Dict[str, Any] = spec.get("config") or {}
        if not config:
            self.module.fail_json(
                msg=f"profile {name!r}: 'config' must not be empty when state=present"
            )

        description: Optional[str] = spec.get("description")
        try:
            rendered: str = NetworkdRenderer.render(config, description)
        except ValueError as exc:
            self.module.fail_json(msg=f"profile {name!r}: {exc}")
            return base  # unreachable

        if self.module.check_mode:
            base.update(self._diff_only(rendered, target))
            return base

        self._snapshot(target)

        tmp_file: str = os.path.join(self.tmp_directory, f"{name}.{profile_type}")
        with open(tmp_file, "w", encoding="utf-8") as fh:
            fh.write(rendered)

        base.update(self._move_if_changed(tmp_file, target))
        return base

    def _validate_name(self, name: str) -> None:
        """
        Reject path traversal in a profile name.

        :param name: Profile basename to validate.
        """
        invalid = not name or "/" in name or "\x00" in name or name in (".", "..")
        if invalid:
            self.module.fail_json(msg=f"Invalid profile name: {name!r}")

    def _diff_only(self, rendered: str, target: str) -> Dict[str, Any]:
        """
        Determine whether ``rendered`` matches the file at ``target``.

        Used in check mode; never touches the filesystem.

        :param rendered: Newly rendered content.
        :param target: Absolute destination path.
        :returns: Partial result dict (``changed`` + ``msg``).
        """
        if not os.path.exists(target):
            return dict(changed=True, msg="Profile would be created.")
        try:
            with open(target, "r", encoding="utf-8") as fh:
                current = fh.read()
        except OSError as exc:
            self.module.fail_json(msg=f"Cannot read {target}: {exc}")
            return dict()  # unreachable
        if current == rendered:
            return dict(changed=False, msg="Profile is unchanged.")
        return dict(changed=True, msg="Profile would be updated.")

    def _move_if_changed(self, tmp_file: str, target: str) -> Dict[str, Any]:
        """
        Replace ``target`` with ``tmp_file`` iff checksums differ.

        :param tmp_file: Freshly rendered file.
        :param target: Final destination path.
        :returns: Partial result dict (``changed`` + ``msg``).
        """
        assert self.checksum is not None
        old_checksum: Optional[str] = self.checksum.checksum_from_file(target)
        new_checksum: Optional[str] = self.checksum.checksum_from_file(tmp_file)

        if new_checksum == old_checksum:
            return dict(changed=False, msg="Profile is unchanged.")

        new_file: bool = old_checksum is None
        shutil.move(tmp_file, target)
        os.chmod(target, self._mode_octal)

        msg = "Profile was created." if new_file else "Profile was updated."
        return dict(changed=True, msg=msg)

    def _remove(self, target: str) -> Dict[str, Any]:
        """
        Remove ``target`` if it exists; respect check mode.

        :param target: Absolute path to remove.
        :returns: Partial result dict (``changed`` + ``msg``).
        """
        if os.path.exists(target):
            if not self.module.check_mode:
                os.remove(target)
            return dict(changed=True, msg=f"Profile '{target}' was removed.")
        return dict(changed=False, msg=f"Profile '{target}' is already absent.")

    def _purge(self, managed_paths: List[str]) -> List[str]:
        """
        Remove unmanaged profile files from ``self.directory``.

        :param managed_paths: Paths managed by this invocation.
        :returns: Sorted list of paths that were removed.
        """
        if not os.path.isdir(self.directory):
            return []

        managed: set = set(managed_paths)
        suffixes: Tuple[str, ...] = tuple(f".{t}" for t in VALID_TYPES)
        removed: List[str] = []

        for entry in os.listdir(self.directory):
            path: str = os.path.join(self.directory, entry)
            if not os.path.isfile(path):
                continue
            if not entry.endswith(suffixes):
                continue
            if path in managed:
                continue
            self._snapshot(path)
            if not self.module.check_mode:
                os.remove(path)
            removed.append(path)

        return sorted(removed)

    # -- backup / rollback ---------------------------------------------------------------

    def _snapshot(self, path: str) -> None:
        """
        Create a backup of ``path`` for later rollback.

        Recorded only once per path - the first snapshot is the pre-run state.

        :param path: Absolute file path.
        """
        if path in self._backups or self.module.check_mode:
            return

        if os.path.exists(path):
            backup_file = os.path.join(
                self.backup_directory,
                path.replace("/", "_").lstrip("_"),
            )
            shutil.copy2(path, backup_file)
            self._backups[path] = dict(existed=True, backup=backup_file)
        else:
            self._backups[path] = dict(existed=False, backup=None)

    def _restore(self, path: str) -> bool:
        """
        Restore ``path`` from its snapshot.

        :param path: Absolute file path to restore.
        :returns: True if a rollback actually happened, False otherwise.
        """
        meta = self._backups.get(path)
        if not meta:
            return False

        if meta["existed"]:
            shutil.copy2(meta["backup"], path)
            os.chmod(path, self._mode_octal)
            return True

        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    # -- validation ----------------------------------------------------------------------

    def _validate(
        self,
        per_profile: List[Dict[str, Any]],
        purged: List[str],
    ) -> Dict[str, Any]:
        """
        Run ``networkctl reload`` and roll back offending profiles per-file.

        Pre-flights the environment (D-Bus, unit state) before any side
        effect. If validation is not possible:

        - with ``validate_strict=False`` (default), validation is skipped,
          a warning is emitted and ``validation.skipped=True`` is returned;
        - with ``validate_strict=True``, the task fails with the captured
          reason.

        Otherwise the normal reload + journal-cursor flow runs and offending
        profiles (identified from parsed errors) are rolled back per-file.

        :param per_profile: Per-profile result entries (mutated on rollback).
        :param purged: Paths removed by ``purge``.
        :returns: ``validation`` dict.
        """
        validator = NetworkdValidator(self.module, timeout=self.validate_timeout)

        # -- pre-flight ------------------------------------------------------
        can_run, skip_reason = validator.can_validate()
        if not can_run:
            if self.validate_strict:
                self.module.fail_json(
                    msg=f"Validation requested but not possible: {skip_reason}",
                    profiles=per_profile,
                    purged=purged,
                    validation=dict(
                        ok=False,
                        skipped=True,
                        skip_reason=skip_reason,
                        rolled_back=[],
                        errors=[],
                        journal=[],
                        reload={},
                    ),
                )
            self.module.warn(
                f"Skipping networkd validation: {skip_reason}. "
                "Set validate_strict=true to fail instead."
            )
            return dict(
                ok=True,
                skipped=True,
                skip_reason=skip_reason,
                rolled_back=[],
                errors=[],
                journal=[],
                reload={},
            )

        # -- first reload ---------------------------------------------------
        cursor: Optional[str] = validator.cursor()
        rc1, out1, err1 = validator.reload()

        time.sleep(0.5)
        journal1: List[str] = validator.collect_journal(cursor)
        errors1, failing_basenames = validator.parse_errors(journal1)
        unit_failed: bool = validator.is_failed()

        reload_failed: bool = (rc1 != 0) or bool(errors1) or unit_failed

        first_attempt: Dict[str, Any] = dict(
            rc=rc1,
            stdout=out1.strip(),
            stderr=err1.strip(),
            unit_failed=unit_failed,
        )

        if not reload_failed:
            return dict(
                ok=True,
                skipped=False,
                rolled_back=[],
                errors=[],
                journal=journal1,
                reload=first_attempt,
            )

        # -- determine rollback targets -------------------------------------
        touched_paths: List[str] = [
            entry["path"] for entry in per_profile if entry["changed"]
        ] + list(purged)

        targets: List[str] = []
        if failing_basenames:
            fail_set = set(failing_basenames)
            targets = [p for p in touched_paths if os.path.basename(p) in fail_set]
        if not targets:
            # Defensive: reload failed but we cannot pin it down to a file.
            targets = list(touched_paths)

        rolled_back: List[str] = [p for p in targets if self._restore(p)]

        rolled_back_set = set(rolled_back)
        for entry in per_profile:
            if entry["path"] in rolled_back_set:
                entry["changed"] = False
                base_msg = (entry.get("msg") or "").rstrip(".")
                entry["msg"] = (
                    f"{base_msg} (rolled back after validation failure)."
                ).strip()

        # -- second reload --------------------------------------------------
        cursor2: Optional[str] = validator.cursor()
        rc2, out2, err2 = validator.reload()
        time.sleep(0.5)
        journal2: List[str] = validator.collect_journal(cursor2)
        errors2, _ = validator.parse_errors(journal2)
        unit_failed2: bool = validator.is_failed()

        ok2: bool = (rc2 == 0) and not errors2 and not unit_failed2

        second_attempt: Dict[str, Any] = dict(
            rc=rc2,
            stdout=out2.strip(),
            stderr=err2.strip(),
            unit_failed=unit_failed2,
        )

        return dict(
            ok=ok2,
            skipped=False,
            rolled_back=sorted(rolled_back),
            errors=errors1 + errors2,
            journal=journal1 + journal2,
            reload=first_attempt,
            reload_after_rollback=second_attempt,
        )


# ---------------------------------------------------------------------------------------


def main() -> None:
    """
    Module entry point. Wires up the argument spec and delegates to
    :class:`NetworkdProfiles`.
    """
    argument_spec: Dict[str, Any] = dict(
        profiles=dict(required=True, type="dict"),
        directory=dict(required=False, type="path", default="/etc/systemd/network"),
        mode=dict(required=False, type="str", default="0644"),
        purge=dict(required=False, type="bool", default=False),
        validate=dict(required=False, type="bool", default=False),
        validate_strict=dict(required=False, type="bool", default=False),
        validate_timeout=dict(required=False, type="int", default=30),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    worker = NetworkdProfiles(module)
    result = worker.run()
    module.exit_json(**result)


if __name__ == "__main__":
    main()
