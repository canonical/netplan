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

import unittest

from unittest.mock import patch
import subprocess
from netplan.cli.commands.apply import NetplanApply


class TestCLI(unittest.TestCase):
    '''Netplan CLI unittests'''

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
                                               ['br0', 'vlan2', 'bond1', 'eth0'])
        mock.assert_any_call(['ip', 'link', 'delete', 'dev', 'bond1'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertIn('bond1', res)
        self.assertIn('tun3', res)
        self.assertNotIn('br0', res)
        self.assertNotIn('vlan2', res)

    @patch('subprocess.check_call')
    def test_clear_virtual_links_no_delta(self, mock):
        res = NetplanApply.clear_virtual_links(['br0', 'vlan2'],
                                               ['br0', 'vlan2'],
                                               ['br0', 'vlan2', 'eth0'])
        mock.assert_not_called()
        self.assertEquals(res, [])
