#!/usr/bin/python3
# Tests of some internal netplan logic that isn't exposed by the CLI
# but is worth testing outside of the integration tests. These are run
# during "make check" and don't touch the system configuration at all.
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Daniel Axtens <daniel.axtens@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import unittest
import tempfile
import logging

# for tests of replug logic, we want to import utils from netplan directly
# as there's no command you can run
sys.path.append(".")
from netplan.cli import utils  # noqa: E402 (must import after updating path)


class TestGatherReplugYAML(unittest.TestCase):
    """We want to unit test the replug parsing code as the shadowing and
    updating is easy to get wrong. We can't test the actual replug
    here.
    """

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        for yaml_dir in ['etc', 'lib', 'run']:
            os.makedirs(os.path.join(self.workdir.name, yaml_dir, 'netplan'))

    def test_noop(self):
        result = utils.gather_replug_yaml(self.workdir.name)
        self.assertFalse(result['disable_all_replug'])
        self.assertEqual(result['blacklist'], [])

    def test_no_replug_data(self):
        fname = os.path.join(self.workdir.name, 'etc', 'netplan', '10-network.yaml')
        with open(fname, 'w') as f:
            f.write('network:\n version: 2\n ethernets:\n  enlol: {dhcp4: yes}')

        result = utils.gather_replug_yaml(self.workdir.name)
        self.assertFalse(result['disable_all_replug'])
        self.assertEqual(result['blacklist'], [])

    def test_kill_switch(self):
        fname = os.path.join(self.workdir.name, 'etc', 'netplan', '10-killall.yaml')
        with open(fname, 'w') as f:
            f.write("replug:\n disable_all_replug: true")

        result = utils.gather_replug_yaml(self.workdir.name)
        self.assertTrue(result['disable_all_replug'])

    def test_broken_yaml(self):
        # we silence logging to suppress the error printed in the function
        old_level = logging.getLogger().getEffectiveLevel()
        logging.getLogger().setLevel(logging.CRITICAL)
        fname = os.path.join(self.workdir.name, 'etc', 'netplan', '10-broken.yaml')
        with open(fname, 'w') as f:
            f.write('\n]}?x*')

        with self.assertRaises(SystemExit):
            utils.gather_replug_yaml(self.workdir.name)

        logging.getLogger().setLevel(old_level)

    def test_shadowing(self):
        fname_lib = os.path.join(self.workdir.name, 'lib', 'netplan', 'file.yaml')
        with open(fname_lib, 'w') as f:
            f.write('replug:\n blacklist:\n  - driver: fish')

        fname_etc = os.path.join(self.workdir.name, 'etc', 'netplan', 'file.yaml')
        with open(fname_etc, 'w') as f:
            f.write('replug:\n blacklist:\n  - driver: seal')

        result = utils.gather_replug_yaml(self.workdir.name)

        self.assertEqual(result['blacklist'], [{'driver': 'seal'}])

    def test_updating(self):
        fname_lib = os.path.join(self.workdir.name, 'lib', 'netplan', 'lib.yaml')
        with open(fname_lib, 'w') as f:
            f.write('replug:\n blacklist:\n  - driver: fish')

        fname_etc = os.path.join(self.workdir.name, 'run', 'netplan', 'run.yaml')
        with open(fname_etc, 'w') as f:
            f.write('replug:\n blacklist:\n  - driver: seal')

        result = utils.gather_replug_yaml(self.workdir.name)

        self.assertTrue(any([x['driver'] == 'seal' for x in result['blacklist']]))
        self.assertTrue(any([x['driver'] == 'fish' for x in result['blacklist']]))


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
