# python 3 headers, required if submitting to Ansible
from __future__ import absolute_import, division, print_function

import re

from ansible.utils.display import Display

__metaclass__ = type

display = Display()


class FilterModule(object):
    """ """

    def filters(self):
        return {
            "service": self.get_service,
        }

    def get_service(self, data, search_for, unit_type="service", state="running"):
        """ """
        name = None
        regex_list_compiled = re.compile(f"^{search_for}.*")

        match = {k: v for k, v in data.items() if re.match(regex_list_compiled, k)}

        # display.vv(f"found: {match}  {type(match)} {len(match)}")

        if isinstance(match, dict) and len(match) > 0:
            values = list(match.values())[0]
            if values.get("state") == state:
                name = values.get("name", search_for).replace(f".{unit_type}", "")

        # display.vv(f"= result {name}")
        return name
