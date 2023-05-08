#!/usr/bin/python3
# Functional tests of netplan CLI. These are run during "make check" and don't
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
import sys
import unittest
import subprocess
import tempfile

from unittest.mock import patch
from netplan.cli.commands.apply import NetplanApply
from netplan.cli.commands.try_command import NetplanTry
from netplan.cli.core import Netplan


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
        self.assertEqual(res, [])

    @patch('subprocess.check_call')
    def test_clear_virtual_links_no_devices(self, mock):
        with self.assertLogs('', level='INFO') as ctx:
            res = NetplanApply.clear_virtual_links(['br0', 'br1'],
                                                   ['br0'])
            self.assertEqual(res, [])
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

    def test_raises_exception_main_function(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: nothanks''')

        # The idea was to capture stderr here but for some reason
        # my attempts to mock sys.stderr didn't work with pytest
        # This will get the error message passed to logging.warning
        # as a parameter
        with patch('logging.warning') as log:
            old_argv = sys.argv
            args = ['get', '--root-dir', self.tmproot]
            sys.argv = [old_argv[0]] + args
            Netplan().main()
            sys.argv = old_argv

            args = log.call_args.args
            self.assertIn('Error in network definition: invalid boolean value', args[0])

    def test_raises_exception_main_function_permission_denied(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: nothanks''')

        os.chmod(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 0)

        with patch('logging.warning') as log:
            old_argv = sys.argv
            args = ['get', '--root-dir', self.tmproot]
            sys.argv = [old_argv[0]] + args
            Netplan().main()
            sys.argv = old_argv

            args = log.call_args.args
            self.assertIn('Permission denied', args[0])

    def test_get_validation_error_exception(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
  ethernets:
    eth0:
      set-name: abc''')

        with patch('logging.warning') as log:
            old_argv = sys.argv
            args = ['get', '--root-dir', self.tmproot]
            sys.argv = [old_argv[0]] + args
            Netplan().main()
            sys.argv = old_argv
            args = log.call_args.args
            self.assertIn('etc/netplan/test.yaml: Error in network definition', args[0])

    def test_set_generic_validation_error_exception(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
  vrfs:
    vrf0:
      table: 100
      routes:
        - table: 200
          to: 1.2.3.4''')

        with patch('logging.warning') as log:
            old_argv = sys.argv
            args = ['get', '--root-dir', self.tmproot]
            sys.argv = [old_argv[0]] + args
            Netplan().main()
            sys.argv = old_argv
            args = log.call_args.args
            self.assertIn("VRF routes table mismatch", args[0])
