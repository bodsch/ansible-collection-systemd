#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2020-2026, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, division, print_function

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ansible.module_utils.basic import AnsibleModule


class NetworkdValidator:
    """
    Trigger ``networkctl reload`` and collect rich diagnostic context.

    The validator captures stdout/stderr of ``networkctl reload`` directly,
    tracks the systemd journal via a cursor (more reliable than timestamp
    filtering), retries journal collection a few times to defeat journald
    buffering, and parses error lines into a structured list.
    """

    # Lines that indicate a parse or load failure. We match on the full line
    # and then extract any profile basenames or full paths separately, so
    # localized variants still surface as raw errors even when no file can
    # be pinned down.
    _ERROR_KEYWORDS: Tuple[str, ...] = (
        "Failed to parse",
        "Failed to load",
        "Could not load",
        "Could not parse",
        "Invalid ",
        "invalid ",
        "Cannot ",
        "assertion failed",
        "Unknown ",
        "unknown ",
        "syntax error",
    )

    # Captures profile filenames or full paths anywhere in a line.
    _FILE_RX: re.Pattern = re.compile(
        r"(?:/(?:etc|run|usr/lib)/systemd/network/)?"
        r"([A-Za-z0-9._@:+-]+\.(?:link|netdev|network))"
    )

    # Captures ``filename:lineno`` so we can surface line numbers too.
    _LINE_RX: re.Pattern = re.compile(
        r"([A-Za-z0-9._@:+-]+\.(?:link|netdev|network)):(\d+)"
    )

    def __init__(
        self,
        module: AnsibleModule,
        timeout: int,
        journal_retries: int = 6,
        journal_retry_sleep: float = 0.5,
    ) -> None:
        """
        :param module: Active AnsibleModule (for ``run_command``).
        :param timeout: Timeout (seconds) for ``networkctl reload``.
        :param journal_retries: How often to poll the journal for new entries.
        :param journal_retry_sleep: Sleep between journal polls (seconds).
        """
        self.module: AnsibleModule = module
        self.timeout: int = timeout
        self.journal_retries: int = journal_retries
        self.journal_retry_sleep: float = journal_retry_sleep

        self._networkctl: str = module.get_bin_path("networkctl", required=True)
        self._journalctl: str = module.get_bin_path("journalctl", required=True)
        self._systemctl: str = module.get_bin_path("systemctl", required=True)

    # -- public API ----------------------------------------------------------------------

    def cursor(self) -> Optional[str]:
        """
        Capture the current journald cursor as a reference point.

        :returns: Cursor string or ``None`` if it could not be obtained.
        """
        rc, out, _err = self.module.run_command(
            [
                self._journalctl,
                "--unit",
                "systemd-networkd.service",
                "--no-pager",
                "--lines",
                "1",
                "--show-cursor",
                "--output",
                "cat",
            ],
            check_rc=False,
        )
        if rc != 0 or not out:
            return None
        for line in out.splitlines():
            if line.startswith("-- cursor: "):
                return line.removeprefix("-- cursor: ").strip()
        return None

    def reload(self) -> Tuple[int, str, str]:
        """
        Invoke ``networkctl reload`` and capture full output.

        :returns: Tuple ``(rc, stdout, stderr)``.
        """
        rc, out, err = self.module.run_command(
            [self._networkctl, "reload"],
            check_rc=False,
        )
        return rc, (out or ""), (err or "")

    def can_validate(self) -> Tuple[bool, Optional[str]]:
        """
        Pre-flight: determine whether ``networkctl reload`` can run at all.

        Checks the D-Bus system bus socket, the loaded/active state of
        ``systemd-networkd.service`` and probes ``networkctl status`` once
        to surface D-Bus or PID1 problems before any write side effect.

        :returns: Tuple ``(can_validate, reason)``. ``reason`` is ``None``
                  when validation is possible, otherwise a short human
                  readable explanation.
        """
        # 1. D-Bus socket present?
        dbus_sockets: Tuple[str, ...] = (
            "/run/dbus/system_bus_socket",
            "/var/run/dbus/system_bus_socket",
        )
        if not any(os.path.exists(p) for p in dbus_sockets):
            return False, "D-Bus system bus socket is not present"

        # 2. systemd-networkd unit loaded?
        rc, out, _err = self.module.run_command(
            [self._systemctl, "is-enabled", "systemd-networkd.service"],
            check_rc=False,
        )
        state = (out or "").strip()
        if state == "not-found":
            return False, "systemd-networkd.service is not installed"

        # 3. systemd-networkd unit active?
        rc, out, _err = self.module.run_command(
            [self._systemctl, "is-active", "systemd-networkd.service"],
            check_rc=False,
        )
        active = (out or "").strip()
        if active in ("inactive", "failed", "unknown", "deactivating"):
            return False, f"systemd-networkd.service is '{active}'"

        # 4. Probe networkctl for the actual D-Bus path.
        rc, out, err = self.module.run_command(
            [self._networkctl, "list", "--no-pager", "--no-legend"],
            check_rc=False,
        )
        combined = ((err or "") + " " + (out or "")).lower()
        if rc != 0 and (
            "system bus" in combined
            or "dbus" in combined
            or "connection refused" in combined
        ):
            return False, (err or out or "networkctl cannot reach D-Bus").strip()

        return True, None

    def is_failed(self) -> bool:
        """
        Check whether the systemd-networkd unit is in a failed state.

        :returns: True if the service unit reports ``failed``.
        """
        rc, out, _err = self.module.run_command(
            [self._systemctl, "is-failed", "systemd-networkd.service"],
            check_rc=False,
        )
        return (out or "").strip() == "failed"

    def collect_journal(
        self,
        cursor: Optional[str],
        fallback_lines: int = 200,
    ) -> List[str]:
        """
        Collect journal entries written after ``cursor``, with retry.

        Falls back to the most recent ``fallback_lines`` entries if no cursor
        is available. Retries until entries appear or attempts are exhausted.

        :param cursor: Journal cursor captured before the reload.
        :param fallback_lines: Number of recent lines to fetch when no cursor.
        :returns: List of journal lines (raw, unfiltered).
        """
        for _ in range(self.journal_retries):
            lines = self._fetch_journal(cursor, fallback_lines)
            if lines:
                return lines
            time.sleep(self.journal_retry_sleep)
        return self._fetch_journal(cursor, fallback_lines)

    def parse_errors(
        self,
        lines: List[str],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Extract structured error records from journal lines.

        :param lines: Raw journal lines.
        :returns: Tuple of ``(error_records, failing_basenames)``.
                  ``error_records`` is a list of dicts with the keys
                  ``message``, ``file`` (basename or ``None``) and ``line``
                  (line number or ``None``).
        """
        errors: List[Dict[str, Any]] = []
        basenames: set = set()

        for raw in lines:
            text = raw.strip()
            if not text:
                continue
            if not any(kw in text for kw in self._ERROR_KEYWORDS):
                continue

            message = self._strip_journal_prefix(text)

            file_name: Optional[str] = None
            line_no: Optional[int] = None

            m_line = self._LINE_RX.search(text)
            if m_line:
                file_name = m_line.group(1)
                try:
                    line_no = int(m_line.group(2))
                except ValueError:
                    line_no = None
            else:
                m_file = self._FILE_RX.search(text)
                if m_file:
                    file_name = m_file.group(1)

            if file_name:
                basenames.add(file_name)

            errors.append(dict(message=message, file=file_name, line=line_no))

        return errors, sorted(basenames)

    # -- internals -----------------------------------------------------------------------

    def _fetch_journal(
        self,
        cursor: Optional[str],
        fallback_lines: int,
    ) -> List[str]:
        """
        Single journal fetch (no retry).

        :param cursor: Optional after-cursor.
        :param fallback_lines: Used when ``cursor`` is None.
        :returns: Journal lines (without journalctl headers).
        """
        cmd: List[str] = [
            self._journalctl,
            "--unit",
            "systemd-networkd.service",
            "--no-pager",
            "--output",
            "short-iso",
        ]
        if cursor:
            cmd += ["--after-cursor", cursor]
        else:
            cmd += ["--lines", str(fallback_lines)]

        rc, out, _err = self.module.run_command(cmd, check_rc=False)
        if rc != 0 or not out:
            return []

        result: List[str] = []
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Drop journalctl headers like "-- No entries --",
            # "-- Boot 12ab... --", "-- cursor: s=... --".
            if stripped.startswith("-- ") and stripped.endswith(" --"):
                continue
            result.append(stripped)
        return result

    @staticmethod
    def _strip_journal_prefix(line: str) -> str:
        """
        Remove the timestamp/host/unit prefix from a short-iso journal line.

        Example::

            "2026-06-20T07:24:18+0200 host systemd-networkd[123]: Failed ..."

        becomes::

            "Failed ..."

        :param line: A single journal line.
        :returns: Message portion only.
        """
        # short-iso format: <ts> <host> <unit>[<pid>]: <message>
        # Conservative split: take everything after the first ": " that comes
        # after a "]" or the third whitespace token.
        idx = line.find("]: ")
        if idx >= 0:
            return line[idx + 3:].strip()

        # Fallback: drop first three whitespace tokens (ts host ident:).
        parts = line.split(" ", 3)
        if len(parts) == 4:
            return parts[3].lstrip(": ").strip()
        return line
