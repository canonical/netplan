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
        os.makedirs(os.path.join(self.tmproot, 'etc/netplan'))
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

    @patch('subprocess.run')
    def test_get_alt_names(self, mock):
        stdout_mock = mock.Mock()
        stdout_mock.stdout = '[{"ifindex":3,"ifname":"ens4","flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],'\
                             '"mtu":8958,"qdisc":"fq_codel","operstate":"UP","linkmode":"DEFAULT","group":"default",'\
                             '"txqlen":1000,"link_type":"ether","address":"xx:xx:xx:xx:xx:xx",'\
                             '"broadcast":"ff:ff:ff:ff:ff:ff","altnames":["enp0s4","enp0s41"]}]'.encode('utf-8')
        mock.return_value = stdout_mock
        res = NetplanApply.get_alt_names('ens4')
        mock.assert_called_with(['ip', '-j', 'link', 'show', 'ens4'], capture_output=True)
        self.assertEquals(res, ['enp0s4', 'enp0s41'])

        mock.reset_mock()
        stdout_mock.stdout = ''.encode('utf-8')
        res = NetplanApply.get_alt_names('ens4')
        mock.assert_called_with(['ip', '-j', 'link', 'show', 'ens4'], capture_output=True)
        self.assertEquals(res, [])

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

    def test_netplan_try_is_revertable(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
  bridges:
    br54:
      dhcp4: false
''')
        cmd = NetplanTry()
        self.assertTrue(cmd.is_revertable())

    def test_netplan_try_is_revertable_fail(self):
        extra_config = os.path.join(self.tmproot, 'extra.yaml')
        with open(extra_config, 'w') as f:
            f.write('''network:
  bridges:
    br54:
      INVALID: kaputt
''')
        cmd = NetplanTry()
        cmd.config_file = extra_config
        self.assertRaises(SystemExit, cmd.is_revertable)

    def test_netplan_try_is_not_revertable(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: true
  bonds:
    bn0:
      interfaces: [eth0]
      parameters:
        mode: balance-rr
''')
        cmd = NetplanTry()
        self.assertFalse(cmd.is_revertable())
