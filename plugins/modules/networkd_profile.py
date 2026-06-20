#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2020-2026, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

"""
Ansible module: bodsch.systemd.networkd_profile

Manages a single systemd-networkd profile file (.link / .netdev / .network).
Content is rendered from a structured dict and written atomically through a
temporary file so the ``changed`` flag is only set when the on-disk content
actually differs.
"""

from __future__ import absolute_import, division, print_function

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.checksum import Checksum
from ansible_collections.bodsch.core.plugins.module_utils.directory import (
    create_directory,
)

__metaclass__ = type

# ---------------------------------------------------------------------------------------

DOCUMENTATION = """
module: networkd_profile
author:
  - Bodo 'bodsch' Schulz (@bodsch)
short_description: Creates a systemd-networkd profile file (.link / .netdev / .network).
version_added: 1.3.0

description:
  - Creates, updates or removes a single systemd-networkd profile file.
  - Supports the three profile types C(link), C(netdev) and C(network).
  - The INI/unit-style content is rendered from a plain dict and written
    atomically through a temporary file so that the C(changed) flag is only
    set when the on-disk content actually differs.

options:
  name:
    description:
      - Base name of the profile file (without extension).
      - Must not contain path separators.
    type: str
    required: true
  profile_type:
    description:
      - Type of profile. Selects the file extension appended to C(name).
    type: str
    choices: [ link, netdev, network ]
    required: true
  state:
    description:
      - Whether the profile should exist (C(present)) or not (C(absent)).
    type: str
    choices: [ absent, present ]
    default: present
  description:
    description:
      - Free-form header placed at the top of the file.
      - Lines without a leading C(#) are auto-prefixed so the result is
        always a valid comment block.
    type: str
  config:
    description:
      - The profile configuration.
      - Top-level keys are section names (C(Match), C(Network), C(NetDev) ...)
        and are written verbatim - casing matters.
      - Values may be scalars (string, int, bool) or lists of scalars.
      - List values are expanded to repeated C(Key=Value) lines as required
        by systemd-networkd (e.g. multiple C(DNS) entries).
      - Booleans are rendered lower-case (C(true)/C(false)).
      - C(None)/null values are skipped, allowing optional placeholders.
    type: dict
    default: {}
  directory:
    description:
      - Target directory where profile files are written.
    type: path
    default: /etc/systemd/network
  mode:
    description:
      - File mode of the resulting profile (octal string).
    type: str
    default: "0644"
"""

EXAMPLES = """
- name: Create a .network profile
  bodsch.systemd.networkd_profile:
    name: etx0
    profile_type: network
    state: present
    description: Static configuration for etx0
    config:
      Match:
        Name: etx0
      Network:
        DHCP: false
        IPv6AcceptRouterAdvertisements: false
        Domains: your.tld
        DNS:
          - 1.1.1.1
          - 141.1.1.1
        Address:
          - "192.0.2.176/24"
          - "2001:db8::302/64"
        Gateway:
          - "192.0.2.1"
          - "2001:db8::1"

- name: Create a bridge .netdev profile
  bodsch.systemd.networkd_profile:
    name: br0
    profile_type: netdev
    config:
      NetDev:
        Name: br0
        Kind: bridge

- name: Remove an obsolete profile
  bodsch.systemd.networkd_profile:
    name: legacy0
    profile_type: network
    state: absent
"""

RETURN = """
changed:
  description: Whether the on-disk file was modified.
  type: bool
  returned: always
failed:
  description: Whether the module run failed.
  type: bool
  returned: always
msg:
  description: Human-readable status message.
  type: str
  returned: always
path:
  description: Absolute path of the target profile file.
  type: str
  returned: always
"""

# ---------------------------------------------------------------------------------------


class NetworkdProfile:
    """
    Generate and manage a single systemd-networkd profile file.

    The class is stateless beyond the parameters passed in by the
    ``AnsibleModule``. ``run()`` is the only public entry point and yields a
    dict that is suitable as input for ``module.exit_json``.
    """

    VALID_TYPES: Tuple[str, ...] = ("link", "netdev", "network")

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the worker.

        :param module: The active AnsibleModule instance.
        """
        self.module: AnsibleModule = module

        self.name: str = module.params["name"]
        self.profile_type: str = module.params["profile_type"]
        self.state: str = module.params["state"]
        self.description: Optional[str] = module.params.get("description")
        self.config: Dict[str, Any] = module.params.get("config") or {}
        self.directory: str = module.params["directory"]
        self.mode: str = module.params["mode"]

        self.tmp_directory: str = os.path.join(
            "/run/.ansible", f"networkd_profile.{os.getpid()}"
        )

        self.checksum: Optional[Checksum] = None

    # -- public API ----------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """
        Execute the requested action (``present``/``absent``).

        :returns: Dict with ``changed``, ``failed``, ``msg`` and ``path``.
        """
        self._validate_name()

        self.checksum = Checksum(self.module)
        target: str = os.path.join(self.directory, f"{self.name}.{self.profile_type}")

        try:
            if self.state == "absent":
                result = self._remove(target)
            else:
                result = self._create(target)
        finally:
            if os.path.exists(self.tmp_directory):
                shutil.rmtree(self.tmp_directory, ignore_errors=True)

        result.setdefault("path", target)
        result.setdefault("failed", False)
        return result

    # -- internals -----------------------------------------------------------------------

    def _validate_name(self) -> None:
        """
        Reject path traversal in ``name`` to avoid writing outside ``directory``.
        """
        invalid = (
            not self.name
            or "/" in self.name
            or "\x00" in self.name
            or self.name in (".", "..")
        )
        if invalid:
            self.module.fail_json(msg=f"Invalid profile name: {self.name!r}")

    def _create(self, target: str) -> Dict[str, Any]:
        """
        Render the profile and replace the target file when content differs.

        :param target: Absolute path of the destination file.
        :returns: Result dict.
        """
        if not self.config:
            self.module.fail_json(
                msg="parameter 'config' must not be empty when state=present"
            )

        if not self.module.check_mode:
            create_directory(directory=self.directory, mode="0755")
            create_directory(directory=self.tmp_directory, mode="0750")

        tmp_file: str = os.path.join(
            self.tmp_directory, f"{self.name}.{self.profile_type}"
        )
        rendered: str = self._render()

        if self.module.check_mode:
            return self._diff_only(rendered, target)

        with open(tmp_file, "w", encoding="utf-8") as fh:
            fh.write(rendered)

        return self._move_if_changed(tmp_file, target)

    def _remove(self, target: str) -> Dict[str, Any]:
        """
        Remove the profile file if it exists.

        :param target: Absolute path of the destination file.
        :returns: Result dict.
        """
        if os.path.exists(target):
            if not self.module.check_mode:
                os.remove(target)
            return dict(
                changed=True,
                msg=f"Profile '{target}' was removed.",
            )
        return dict(
            changed=False,
            msg=f"Profile '{target}' is already absent.",
        )

    def _diff_only(self, rendered: str, target: str) -> Dict[str, Any]:
        """
        Compute changed-state without touching the filesystem (check mode).

        :param rendered: Newly rendered content.
        :param target: Absolute destination path.
        :returns: Result dict.
        """
        if not os.path.exists(target):
            return dict(changed=True, msg="Profile would be created.")
        try:
            with open(target, "r", encoding="utf-8") as fh:
                current = fh.read()
        except OSError as exc:
            self.module.fail_json(msg=f"Cannot read {target}: {exc}")
            return dict()  # unreachable, satisfies type checkers
        if current == rendered:
            return dict(changed=False, msg="Profile is unchanged.")
        return dict(changed=True, msg="Profile would be updated.")

    def _move_if_changed(self, tmp_file: str, target: str) -> Dict[str, Any]:
        """
        Compare temporary file to target by checksum; move only on diff.

        :param tmp_file: Path of the freshly rendered file.
        :param target: Final destination path.
        :returns: Result dict.
        """
        assert self.checksum is not None  # set in run()
        old_checksum: Optional[str] = self.checksum.checksum_from_file(target)
        new_checksum: Optional[str] = self.checksum.checksum_from_file(tmp_file)

        if new_checksum == old_checksum:
            return dict(changed=False, msg="Profile is unchanged.")

        new_file: bool = old_checksum is None
        shutil.move(tmp_file, target)
        try:
            os.chmod(target, int(self.mode, 8))
        except ValueError as exc:
            self.module.fail_json(msg=f"Invalid mode {self.mode!r}: {exc}")

        msg = "Profile was created." if new_file else "Profile was updated."
        return dict(changed=True, msg=msg)

    def _render(self) -> str:
        """
        Render the profile content as a UTF-8 string in systemd INI style.

        :returns: Fully rendered file content (terminated with a newline).
        """
        lines: List[str] = ["# Generated by Ansible - do not edit manually."]

        if self.description:
            lines.append("")
            lines.append(self._normalize_comment(self.description))

        for section, options in self.config.items():
            lines.append("")
            lines.append(f"[{section}]")
            for option, value in (options or {}).items():
                lines.extend(self._render_option(option, value))

        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def _render_option(cls, option: str, value: Any) -> List[str]:
        """
        Render a single ``Key=Value`` (or repeated keys for lists).

        :param option: The option key.
        :param value: Scalar, list of scalars, or ``None``.
        :returns: A list of zero or more rendered lines.
        """
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            out: List[str] = []
            for item in value:
                if item is None:
                    continue
                out.append(f"{option}={cls._render_scalar(item)}")
            return out
        return [f"{option}={cls._render_scalar(value)}"]

    @staticmethod
    def _render_scalar(value: Any) -> str:
        """
        Convert a single value to its systemd-networkd representation.

        :param value: The raw value (bool, int, str, ...).
        :returns: String representation suitable for an INI value field.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _normalize_comment(text: str) -> str:
        """
        Ensure every line of ``text`` starts with ``#``.

        Lines that already start with ``#`` are kept verbatim, others get a
        leading ``# ``. Blank lines are emitted as ``#``.

        :param text: The raw description string (multi-line allowed).
        :returns: A valid comment block.
        """
        out: List[str] = []
        for raw in text.splitlines():
            stripped = raw.rstrip()
            if not stripped.strip():
                out.append("#")
            elif stripped.lstrip().startswith("#"):
                out.append(stripped)
            else:
                out.append(f"# {stripped}")
        return "\n".join(out)


# ---------------------------------------------------------------------------------------


def main() -> None:
    """
    Module entry point. Wires up the argument spec and delegates to
    :class:`NetworkdProfile`.
    """
    argument_spec: Dict[str, Any] = dict(
        name=dict(required=True, type="str"),
        profile_type=dict(
            required=True,
            type="str",
            choices=list(NetworkdProfile.VALID_TYPES),
        ),
        state=dict(
            required=False,
            type="str",
            default="present",
            choices=["absent", "present"],
        ),
        description=dict(required=False, type="str", default=None),
        config=dict(required=False, type="dict", default={}),
        directory=dict(required=False, type="path", default="/etc/systemd/network"),
        mode=dict(required=False, type="str", default="0644"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    worker = NetworkdProfile(module)
    result = worker.run()
    module.exit_json(**result)


if __name__ == "__main__":
    main()
