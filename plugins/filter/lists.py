# python 3 headers, required if submitting to Ansible
from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible.utils.display import Display

display = Display()


class FilterModule(object):
    """ """

    def filters(self):
        return {
            "valid_list": self.valid_list,
        }

    def valid_list(self, data, valid_entries):
        """ """
        # display.v(f"valid_list(self, {data}, {valid_entries})")
        result = []
        if isinstance(data, list):
            data.sort()
            valid_entries.sort()
            result = list(set(data).intersection(valid_entries))
            result.sort()
        # display.v(f"=result: {result}")
        return result
