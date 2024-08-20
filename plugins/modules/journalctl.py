#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2020-2023, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = """
module: journalctl
author:
  - Bodo 'bodsch' Schulz <bodo@boone-schulz.de>
short_description: Query the systemd journal with a very limited number of possible parameters.
version_added: 1.1.0

description:
  - Query the systemd journal with a very limited number of possible parameters.
  - In certain cases there are errors that are not clearly traceable but are logged in the journal.
  - This module is intended to be a tool for error analysis.

options:
  identifier:
    description:
      - Show entries with the specified syslog identifier
    type: str
    required: false
  unit:
    description:
      - Show logs from the specified unit
    type: str
    required: false
  lines:
    description:
      - Number of journal entries to show
    type: int
    required: false
  reverse:
    description:
      - Show the newest entries first
    type: bool
    required: false
  arguments:
    description:
      - A list of custom attributes
    type: list
    required: false
"""

EXAMPLES = """
- name: chrony entries from journalctl
  bodsch.systemd.journalctl:
    identifier: chrony
    lines: 50
  register: journalctl
  when:
    - ansible_service_mgr == 'systemd'

- name: journalctl entries from this module
  bodsch.systemd.journalctl:
    identifier: ansible-journalctl
    lines: 250
  register: journalctl
  when:
    - ansible_service_mgr == 'systemd'
"""

RETURN = """
rc:
  description:
    - Return Value
  type: int
cmd:
  description:
    - journalctl with the called parameters
  type: string
stdout:
  description:
    - The output as a list on stdout
  type: list
stderr:
  description:
    - The output as a list on stderr
  type: list
"""


class JournalCtl(object):
    """
    """
    module = None

    def __init__(self, module):
        """
        """
        self.module = module

        self._journalctl = module.get_bin_path("journalctl", True)

        self.unit = module.params.get("unit")
        self.identifier = module.params.get("identifier")
        self.lines = module.params.get("lines")
        self.reverse = module.params.get("reverse")
        self.arguments = module.params.get("arguments")

        # module.log(msg="----------------------------")
        # module.log(msg=f" journalctl   : {self._journalctl}")
        # module.log(msg=f" unit         : {self.unit}")
        # module.log(msg=f" identifier   : {self.identifier}")
        # module.log(msg=f" lines        : {self.lines}")
        # module.log(msg=f" reverse      : {self.reverse}")
        # module.log(msg=f" arguments    : {self.arguments}")
        # module.log(msg="----------------------------")

    def run(self):
        """
        """
        result = dict(
            rc=1,
            failed=True,
            changed=False,
        )

        result = self.journalctl_lines()

        return result

    def journalctl_lines(self):
        """
            journalctl --help
            journalctl [OPTIONS...] [MATCHES...]

            Query the journal.
        """
        args = []
        args.append(self._journalctl)

        if self.unit:
            args.append("--unit")
            args.append(self.unit)

        if self.identifier:
            args.append("--identifier")
            args.append(self.identifier)

        if self.lines:
            args.append("--lines")
            args.append(str(self.lines))

        if self.reverse:
            args.append("--reverse")

        if len(self.arguments) > 0:
            for arg in self.arguments:
                args.append(arg)

        rc, out, err = self._exec(args)

        return dict(
            rc=rc,
            cmd=" ".join(args),
            stdout=out,
            stderr=err,
        )

    def _exec(self, args):
        """
        """
        rc, out, err = self.module.run_command(args, check_rc=False)

        if rc != 0:
            self.module.log(msg=f"  rc : '{rc}'")
            self.module.log(msg=f"  out: '{out}'")
            self.module.log(msg=f"  err: '{err}'")

        return rc, out, err


def main():
    """
    """
    args = dict(
        identifier=dict(
            required=False,
            type="str"
        ),
        unit=dict(
            required=False,
            type="str"
        ),
        lines=dict(
            required=False,
            type="int"
        ),
        reverse=dict(
            required=False,
            default=False,
            type="bool"
        ),
        arguments=dict(
            required=False,
            default=[],
            type=list
        ),
    )

    module = AnsibleModule(
        argument_spec=args,
        supports_check_mode=False,
    )

    k = JournalCtl(module)
    result = k.run()

    module.log(msg=f"= result: {result}")

    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
