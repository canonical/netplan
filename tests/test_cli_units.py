#!/usr/bin/python3
# Blackbox tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2021 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
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
import shutil
import unittest
import subprocess
import tempfile

from unittest.mock import patch
from netplan.cli.commands.apply import NetplanApply
from netplan.cli.commands.try_command import NetplanTry


class TestCLI(unittest.TestCase):
    '''Netplan CLI unittests'''

    def setUp(self):
        self.tmproot = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tmproot, 'run'))
        os.environ['DBUS_TEST_NETPLAN_ROOT'] = self.tmproot

    def tearDown(self):
        shutil.rmtree(self.tmproot)

    def test_is_composite_member(self):
        res = NetplanApply.is_composite_member([{'br0': {'interfaces': ['eth0']}}], 'eth0')
        self.assertTrue(res)

    def test_is_composite_member_false(self):
        res = NetplanApply.is_composite_member([
                  {'br0': {'interfaces': ['eth42']}},
                  {'bond0': {'interfaces': ['eth1']}}
              ], 'eth0')
        self.assertFalse(res)

    def test_is_composite_member_with_renderer(self):
        res = NetplanApply.is_composite_member([{'renderer': 'networkd', 'br0': {'interfaces': ['eth0']}}], 'eth0')
        self.assertTrue(res)

    @patch('subprocess.check_call')
    def test_clear_virtual_links(self, mock):
        # simulate as if 'tun3' would have already been delete another way,
        # e.g. via NetworkManager backend
        res = NetplanApply.clear_virtual_links(['br0', 'vlan2', 'bond1', 'tun3'],
                                               ['br0', 'vlan2'],
                                               devices=['br0', 'vlan2', 'bond1', 'eth0'])
        mock.assert_called_with(['ip', 'link', 'delete', 'dev', 'bond1'])
        self.assertIn('bond1', res)
        self.assertIn('tun3', res)
        self.assertNotIn('br0', res)
        self.assertNotIn('vlan2', res)

    @patch('subprocess.check_call')
    def test_clear_virtual_links_failure(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'Cannot find device "br0"')
        res = NetplanApply.clear_virtual_links(['br0'], [], devices=['br0', 'eth0'])
        mock.assert_called_with(['ip', 'link', 'delete', 'dev', 'br0'])
        self.assertIn('br0', res)
        self.assertNotIn('eth0', res)

    @patch('subprocess.check_call')
    def test_clear_virtual_links_no_delta(self, mock):
        res = NetplanApply.clear_virtual_links(['br0', 'vlan2'],
                                               ['br0', 'vlan2'],
                                               devices=['br0', 'vlan2', 'eth0'])
        mock.assert_not_called()
        self.assertEquals(res, [])

    @patch('subprocess.check_call')
    def test_clear_virtual_links_no_devices(self, mock):
        with self.assertLogs('', level='INFO') as ctx:
            res = NetplanApply.clear_virtual_links(['br0', 'br1'],
                                                   ['br0'])
            self.assertEquals(res, [])
            self.assertEqual(ctx.output, ['WARNING:root:Cannot clear virtual links: no network interfaces provided.'])
        mock.assert_not_called()

    def test_netplan_try_ready_stamp(self):
        stamp_file = os.path.join(self.tmproot, 'run', 'netplan', 'netplan-try.ready')
        cmd = NetplanTry()
        self.assertFalse(os.path.isfile(stamp_file))
        # make sure it behaves correctly, if the file doesn't exist
        self.assertFalse(cmd.clear_ready_stamp())
        self.assertFalse(os.path.isfile(stamp_file))
        cmd.touch_ready_stamp()
        self.assertTrue(os.path.isfile(stamp_file))
        self.assertTrue(cmd.clear_ready_stamp())
        self.assertFalse(os.path.isfile(stamp_file))
