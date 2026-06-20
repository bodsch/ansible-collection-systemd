#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2020-2026, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

"""
Ansible module: bodsch.systemd.journalctl

Query the systemd journal from Ansible playbooks. Read-only; supports unit
and identifier filtering, time/priority/grep filters, cursor-based
pagination, JSON parsing and pass-through of arbitrary extra arguments.
"""

from __future__ import absolute_import, division, print_function

import json
import shlex
from typing import Any, Dict, List, Optional, Tuple

from ansible.module_utils.basic import AnsibleModule

__metaclass__ = type

# ---------------------------------------------------------------------------------------

DOCUMENTATION = """
module: journalctl
author:
  - Bodo 'bodsch' Schulz (@bodsch)
short_description: Query the systemd journal.
version_added: 1.1.0

description:
  - Wraps the ``journalctl`` binary and returns matching entries.
  - Read-only; safe in check mode.
  - All filters are AND-combined the way ``journalctl`` does it natively.
  - When ``output=json``/``json-pretty`` is selected, every entry is
    additionally parsed into ``entries`` and the journal cursor of the
    last entry is exposed as ``cursor``.

options:
  unit:
    description:
      - Show logs from the specified unit (``-u``).
      - Scalar variant kept for backwards compatibility.
    type: str
  units:
    description:
      - List of units to query. Combined with ``unit`` if both are given.
      - Each entry produces a separate ``-u`` flag.
    type: list
    elements: str
  identifier:
    description:
      - Show entries with the specified syslog identifier (``-t``).
      - Scalar variant kept for backwards compatibility.
    type: str
  identifiers:
    description:
      - List of identifiers. Combined with ``identifier`` if both are given.
      - Each entry produces a separate ``-t`` flag.
    type: list
    elements: str
  lines:
    description:
      - Number of journal entries to show (``-n``).
    type: int
  reverse:
    description:
      - Show the newest entries first (``-r``).
    type: bool
    default: false
  since:
    description:
      - Start of the time window (``--since``).
      - Anything ``journalctl`` accepts works (e.g. ``"2026-06-20 07:00:00"``,
        ``"1 hour ago"``, ``"yesterday"``).
    type: str
  until:
    description:
      - End of the time window (``--until``).
    type: str
  priority:
    description:
      - Filter by syslog priority (``-p``).
      - Accepts a level name (C(emerg), C(alert), C(crit), C(err),
        C(warning), C(notice), C(info), C(debug)), an integer 0-7, or a
        range like C("0..3").
    type: str
  grep:
    description:
      - Filter messages by PCRE pattern (``-g``).
    type: str
  boot:
    description:
      - Restrict to a specific boot (``-b``).
      - Use C("0") for the current boot, negative offsets like C("-1") for
        previous boots, or a full 32-character boot ID.
    type: str
  output:
    description:
      - Output format (``-o``). When omitted, ``journalctl``'s built-in
        default (C(short)) is used.
      - When set to C(json) or C(json-pretty), every entry is additionally
        parsed into the C(entries) return value.
    type: str
    choices:
      - short
      - short-iso
      - short-iso-precise
      - short-precise
      - short-monotonic
      - short-unix
      - short-full
      - verbose
      - export
      - json
      - json-pretty
      - cat
  cursor:
    description:
      - Start from the journal entry with this cursor (``--cursor``).
    type: str
  after_cursor:
    description:
      - Start after the journal entry with this cursor (``--after-cursor``).
      - Useful for incremental polling.
    type: str
  no_pager:
    description:
      - Pass ``--no-pager`` (default C(true)).
      - Has no effect under ``run_command`` but is exposed for completeness.
    type: bool
    default: true
  arguments:
    description:
      - Extra CLI arguments appended verbatim to the ``journalctl`` call.
      - ``--follow``/``-f`` is rejected because it would block the Ansible
        task forever.
    type: list
    elements: str
    default: []
"""

EXAMPLES = """
- name: last 50 chrony entries, newest first
  bodsch.systemd.journalctl:
    identifier: chrony
    lines: 50
    reverse: true
  register: chrony_log

- name: errors from systemd-networkd in the last hour, as parsed entries
  bodsch.systemd.journalctl:
    unit: systemd-networkd.service
    priority: err
    since: "1 hour ago"
    output: json
  register: networkd_errors

- name: query several units at once
  bodsch.systemd.journalctl:
    units:
      - nginx.service
      - php-fpm.service
    priority: warning
    lines: 200

- name: incremental tail using a cursor
  bodsch.systemd.journalctl:
    unit: my-app.service
    after_cursor: "{{ previous.cursor | default(omit) }}"
    output: json
  register: my_app_log
"""

RETURN = """
rc:
  description: Return code of the ``journalctl`` invocation.
  type: int
  returned: always
cmd:
  description: The full command line, shell-quoted for readability.
  type: str
  returned: always
stdout:
  description: Raw stdout (kept identical to the legacy behaviour).
  type: str
  returned: always
stdout_lines:
  description: ``stdout`` split on newlines.
  type: list
  elements: str
  returned: always
stderr:
  description: Raw stderr.
  type: str
  returned: always
entries:
  description:
    - Parsed journal entries.
    - Only populated when ``output`` is ``json`` or ``json-pretty``.
  type: list
  elements: dict
  returned: when output is JSON
cursor:
  description:
    - Cursor of the last returned journal entry, suitable for chaining
      subsequent calls via ``after_cursor``.
    - Only populated when ``output`` is ``json`` or ``json-pretty``.
  type: str
  returned: when output is JSON and at least one entry was found
changed:
  description: Always ``false``; the module is read-only.
  type: bool
  returned: always
"""

# ---------------------------------------------------------------------------------------

_FORBIDDEN_EXTRA_ARGS: Tuple[str, ...] = ("-f", "--follow")
_JSON_FORMATS: Tuple[str, ...] = ("json", "json-pretty")


class JournalCtl:
    """
    Query the systemd journal.

    Builds a ``journalctl`` argument vector from a structured set of options
    and exposes a single :meth:`run` entry point that returns a dict
    suitable for :func:`AnsibleModule.exit_json`.
    """

    def __init__(self, module: AnsibleModule) -> None:
        """
        :param module: The active AnsibleModule instance.
        """
        self.module: AnsibleModule = module
        self._journalctl: str = module.get_bin_path("journalctl", required=True)

        params: Dict[str, Any] = module.params

        self.units: List[str] = self._merge_scalar_and_list(
            params.get("unit"), params.get("units")
        )
        self.identifiers: List[str] = self._merge_scalar_and_list(
            params.get("identifier"), params.get("identifiers")
        )

        self.lines: Optional[int] = params.get("lines")
        self.reverse: bool = bool(params.get("reverse"))
        self.since: Optional[str] = params.get("since")
        self.until: Optional[str] = params.get("until")
        self.priority: Optional[str] = params.get("priority")
        self.grep: Optional[str] = params.get("grep")
        self.boot: Optional[str] = params.get("boot")
        self.output: Optional[str] = params.get("output")
        self.cursor: Optional[str] = params.get("cursor")
        self.after_cursor: Optional[str] = params.get("after_cursor")
        self.no_pager: bool = bool(params.get("no_pager"))
        self.arguments: List[str] = list(params.get("arguments") or [])

    # -- public API ----------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """
        Build the command line, invoke ``journalctl`` and assemble the
        result dict.

        :returns: Result dict (``rc``, ``cmd``, ``stdout``, ``stdout_lines``,
                  ``stderr``, ``changed``, optionally ``entries`` and
                  ``cursor``).
        """
        self._reject_forbidden_args()

        args: List[str] = self._build_args()
        rc, out, err = self._exec(args)

        out = out or ""
        err = err or ""

        result: Dict[str, Any] = dict(
            rc=rc,
            cmd=self._quote_cmd(args),
            stdout=out,
            stdout_lines=out.splitlines(),
            stderr=err,
            changed=False,
        )

        if self.output in _JSON_FORMATS:
            entries = self._parse_json_entries(out)
            result["entries"] = entries
            last_cursor = self._extract_cursor(entries)
            if last_cursor:
                result["cursor"] = last_cursor

        if rc != 0:
            self.module.fail_json(
                msg=(
                    f"journalctl exited with rc={rc}: "
                    f"{(err.strip() or out.strip() or 'no diagnostic output')}"
                ),
                **result,
            )

        return result

    # -- internals -----------------------------------------------------------------------

    @staticmethod
    def _merge_scalar_and_list(
        scalar: Optional[str],
        plural: Optional[List[str]],
    ) -> List[str]:
        """
        Merge a scalar and a list-valued variant of the same logical option.

        Order-preserving and de-duplicating.

        :param scalar: Single value or ``None``.
        :param plural: List of values or ``None``.
        :returns: List of values.
        """
        out: List[str] = []
        seen: set = set()
        if scalar:
            out.append(scalar)
            seen.add(scalar)
        if plural:
            for item in plural:
                if item and item not in seen:
                    out.append(item)
                    seen.add(item)
        return out

    def _reject_forbidden_args(self) -> None:
        """
        Fail fast if the caller injects flags that would break the module
        (``--follow`` would block the Ansible run indefinitely).
        """
        for arg in self.arguments:
            if arg in _FORBIDDEN_EXTRA_ARGS:
                self.module.fail_json(
                    msg=f"Argument {arg!r} is not allowed in 'arguments'"
                )

    def _build_args(self) -> List[str]:
        """
        Assemble the ``journalctl`` argument vector from instance state.

        :returns: Argument vector suitable for :func:`run_command`.
        """
        args: List[str] = [self._journalctl]

        if self.no_pager:
            args.append("--no-pager")

        for unit in self.units:
            args += ["--unit", unit]

        for ident in self.identifiers:
            args += ["--identifier", ident]

        if self.lines is not None:
            args += ["--lines", str(self.lines)]

        if self.reverse:
            args.append("--reverse")

        if self.since:
            args += ["--since", self.since]

        if self.until:
            args += ["--until", self.until]

        if self.priority:
            args += ["--priority", self.priority]

        if self.grep:
            args += ["--grep", self.grep]

        if self.boot:
            args += ["--boot", self.boot]

        if self.cursor:
            args += ["--cursor", self.cursor]

        if self.after_cursor:
            args += ["--after-cursor", self.after_cursor]

        if self.output:
            args += ["--output", self.output]

        args.extend(self.arguments)
        return args

    def _exec(self, args: List[str]) -> Tuple[int, str, str]:
        """
        Run ``journalctl`` and capture rc/stdout/stderr.

        :param args: Argument vector.
        :returns: Tuple ``(rc, stdout, stderr)``.
        """
        rc, out, err = self.module.run_command(args, check_rc=False)
        if rc != 0:
            self.module.log(msg=f"journalctl rc={rc}")
            if err:
                self.module.log(msg=f"journalctl stderr: {err.strip()}")
        return rc, out, err

    @staticmethod
    def _quote_cmd(args: List[str]) -> str:
        """
        Shell-quote an argument vector for display purposes.

        Equivalent to :func:`shlex.join` but works on Python < 3.8.

        :param args: Argument vector.
        :returns: Quoted command string.
        """
        return " ".join(shlex.quote(a) for a in args)

    @staticmethod
    def _parse_json_entries(out: str) -> List[Dict[str, Any]]:
        """
        Parse ``journalctl --output=json`` NDJSON stdout into a list.

        Lines that fail to parse are skipped rather than aborting the task;
        this keeps the module robust against stray non-JSON lines from
        journald edge cases.

        :param out: Raw stdout from ``journalctl``.
        :returns: List of parsed entries.
        """
        entries: List[Dict[str, Any]] = []
        for raw in out.splitlines():
            line = raw.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                entries.append(json.loads(line))
            except (ValueError, TypeError):
                continue
        return entries

    @staticmethod
    def _extract_cursor(entries: List[Dict[str, Any]]) -> Optional[str]:
        """
        Return the ``__CURSOR`` of the chronologically last entry, if any.

        Walks the list in reverse to honour ``--reverse`` callers cheaply.

        :param entries: List of parsed JSON entries.
        :returns: Cursor string or ``None``.
        """
        for entry in reversed(entries):
            cursor = entry.get("__CURSOR")
            if isinstance(cursor, str) and cursor:
                return cursor
        return None


# ---------------------------------------------------------------------------------------


def main() -> None:
    """
    Module entry point. Wires up the argument spec and delegates to
    :class:`JournalCtl`.
    """
    argument_spec: Dict[str, Any] = dict(
        unit=dict(required=False, type="str"),
        units=dict(required=False, type="list", elements="str"),
        identifier=dict(required=False, type="str"),
        identifiers=dict(required=False, type="list", elements="str"),
        lines=dict(required=False, type="int"),
        reverse=dict(required=False, type="bool", default=False),
        since=dict(required=False, type="str"),
        until=dict(required=False, type="str"),
        priority=dict(required=False, type="str"),
        grep=dict(required=False, type="str"),
        boot=dict(required=False, type="str"),
        output=dict(
            required=False,
            type="str",
            choices=[
                "short",
                "short-iso",
                "short-iso-precise",
                "short-precise",
                "short-monotonic",
                "short-unix",
                "short-full",
                "verbose",
                "export",
                "json",
                "json-pretty",
                "cat",
            ],
        ),
        cursor=dict(required=False, type="str"),
        after_cursor=dict(required=False, type="str"),
        no_pager=dict(required=False, type="bool", default=True),
        arguments=dict(required=False, type="list", elements="str", default=[]),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    worker = JournalCtl(module)
    result = worker.run()
    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
