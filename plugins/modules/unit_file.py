#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# (c) 2020-2023, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, division, print_function

import os
from ansible_collections.bodsch.core.plugins.module_utils.directory import create_directory
from ansible_collections.bodsch.core.plugins.module_utils.checksum import Checksum

from ansible.module_utils.basic import AnsibleModule


class SystemdUnitFile(object):
    """
    """
    module = None

    def __init__(self, module):
        """
        """
        self.module = module

        # self._journalctl = module.get_bin_path("journalctl", True)

        self.unit_type = module.params.get("unit_type")
        self.name = module.params.get("name")
        self.overwrite = module.params.get("overwrite")
        self.drop_ins = module.params.get("drop_ins")
        self.unit = module.params.get("unit")
        self.service = module.params.get("service")
        self.install = module.params.get("install")

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

        if len(self.drop_ins) > 0:
            self.module.log(msg="----------------------------")
            service_name = f"/etc/systemd/system/{self.name}.d"
            self.module.log(msg=f" service name   : {service_name}")

            if not os.path.exists(service_name):
                create_directory(service_name)

            for drop_in in self.drop_ins:


                self.module.log(msg=f" drop in name   : {drop_in}")

                file_name = f"{service_name}/{drop_in.get('name')}.conf"
                if not os.path.exists(file_name):
                    with open(file_name, "w") as f:
                        f.write("# ansible controlled")

            self.module.log(msg="----------------------------")


        # result = self.journalctl_lines()

        return result


def main():
    """
    """
    args = dict(
        unit_type=dict(
            required=True,
            choose=[
                "service",
                "socket",
                "timer"
            ],
            type="str"
        ),
        name=dict(
            required=True,
            type="str"
        ),
        overwrite=dict(
            required=False,
            default=False,
            type="bool"
        ),
        drop_ins=dict(
            required=False,
            default=[],
            type=list
        ),
        unit=dict(
            required=False,
            default={},
            type=dict
        ),
        service=dict(
            required=False,
            default={},
            type=dict
        ),
        install=dict(
            required=False,
            default={},
            type=dict
        ),
    )

    module = AnsibleModule(
        argument_spec=args,
        supports_check_mode=False,
    )

    k = SystemdUnitFile(module)
    result = k.run()

    module.log(msg=f"= result: {result}")

    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
