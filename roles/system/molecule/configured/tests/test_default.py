from __future__ import annotations, unicode_literals

import os

import pytest
import testinfra.utils.ansible_runner
from helper.molecule import get_vars, infra_hosts, local_facts

testinfra_hosts = infra_hosts(host_name="instance")

# --- tests -----------------------------------------------------------------


@pytest.mark.parametrize(
    "directories",
    [
        "/etc/systemd",
    ],
)
def test_directories(host, directories):
    d = host.file(directories)
    assert d.is_directory


@pytest.mark.parametrize(
    "files",
    [
        "/etc/systemd/system.conf",
    ],
)
def test_systemd_files(host, files):
    """ """
    d = host.file(files)
    assert d.is_file
