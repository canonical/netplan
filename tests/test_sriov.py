#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
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
import unittest
import tempfile

from subprocess import CalledProcessError
from collections import defaultdict
from unittest.mock import patch, mock_open, call

import netplan.cli.sriov as sriov

from netplan.configmanager import ConfigManager, ConfigurationError


class MockSRIOVOpen():
    def __init__(self):
        # now this is a VERY ugly hack to make mock_open() better
        self.read_state = []
        def sriov_read():
            data = self.read_state.pop(0)
            if isinstance(data, str):
                return data
            else:
                raise data
        self.open = mock_open()
        self.open.return_value.read.side_effect = sriov_read


class TestSRIOV(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.workdir.name, 'etc/netplan'))
        self.configmanager = ConfigManager(prefix=self.workdir.name, extra_files={})

    def _prepare_sysfs_dir_structure(self):
        # prepare a directory hierarchy for testing the matching
        # this might look really scary, but that's how sysfs presents devices
        # such as these
        os.makedirs(os.path.join(self.workdir.name, 'sys/class/net'))

        # first the VF
        vf_iface_path = os.path.join(self.workdir.name, 'sys/devices/pci0000:00/0000:00:1f.6/net/enp2s16f1')
        vf_dev_path = os.path.join(self.workdir.name, 'sys/devices/pci0000:00/0000:00:1f.6')
        os.makedirs(vf_iface_path)
        with open(os.path.join(vf_dev_path, 'vendor'), 'w') as f:
            f.write('0x001f\n')
        with open(os.path.join(vf_dev_path, 'device'), 'w') as f:
            f.write('0xb33f\n')
        os.symlink('../../devices/pci0000:00/0000:00:1f.6/net/enp2s16f1',
                   os.path.join(self.workdir.name, 'sys/class/net/enp2s16f1'))
        os.symlink('../../../0000:00:1f.6', os.path.join(self.workdir.name, 'sys/class/net/enp2s16f1/device'))

        # now the PF
        os.path.join(self.workdir.name, 'sys/class/net/enp2')
        pf_iface_path = os.path.join(self.workdir.name, 'sys/devices/pci0000:00/0000:00:1f.0/net/enp2')
        pf_dev_path = os.path.join(self.workdir.name, 'sys/devices/pci0000:00/0000:00:1f.0')
        os.makedirs(pf_iface_path)
        with open(os.path.join(pf_dev_path, 'vendor'), 'w') as f:
            f.write('0x001f\n')
        with open(os.path.join(pf_dev_path, 'device'), 'w') as f:
            f.write('0x1337\n')
        os.symlink('../../devices/pci0000:00/0000:00:1f.0/net/enp2',
                   os.path.join(self.workdir.name, 'sys/class/net/enp2'))
        os.symlink('../../../0000:00:1f.0', os.path.join(self.workdir.name, 'sys/class/net/enp2/device'))
        # the PF additionally has device links to all the VFs defined for it
        os.symlink('../../../0000:00:1f.4', os.path.join(pf_dev_path, 'virtfn1'))
        os.symlink('../../../0000:00:1f.5', os.path.join(pf_dev_path, 'virtfn2'))
        os.symlink('../../../0000:00:1f.6', os.path.join(pf_dev_path, 'virtfn3'))
        os.symlink('../../../0000:00:1f.7', os.path.join(pf_dev_path, 'virtfn4'))

    @patch('netplan.cli.utils.get_interface_driver_name')
    @patch('netplan.cli.utils.get_interface_macaddress')
    def test_get_vf_count_and_active_pfs(self, gim, gidn):
        # we mock-out get_interface_driver_name and get_interface_macaddress
        # to return useful values for the test
        gim.side_effect = lambda x: '00:01:02:03:04:05' if x == 'enp3' else '00:00:00:00:00:00'
        gidn.side_effect = lambda x: 'foo' if x == 'enp2' else 'bar'
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    enp1:
      mtu: 9000
    enp2:
      match:
        driver: foo
    enp3:
      match:
        macaddress: 00:01:02:03:04:05
    enpx:
      match:
        name: enp[4-5]
    enp0:
      mtu: 9000
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
    enp1s16f2:
      link: enp1
      macaddress: 01:02:03:04:05:01
    enp2s16f1:
      link: enp2
    enp3s16f1:
      link: enp3
    enpxs16f1:
      match:
        name: enp[4-5]s16f1
      link: enpx
''', file=fd)
        self.configmanager.parse()
        interfaces = ['enp1', 'enp2', 'enp3', 'enp5', 'enp0']
        vf_counts = defaultdict(int)
        active_vfs = {}
        active_pfs = defaultdict(list)
        # call function under test
        sriov.get_vf_count_and_active_pfs(interfaces, self.configmanager,
                                          vf_counts, active_vfs, active_pfs)
        # check if the right vf counts have been recorded in vf_counts
        self.assertDictEqual(
            vf_counts,
            {'enp1': 2, 'enp2': 1, 'enp3': 1, 'enp5': 1})
        # also check if the active_vfs and active_pfs got properly set
        # TODO

    def test_set_numvfs_for_pf(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_state = ['1\n', '8\n']

        with patch('builtins.open', sriov_open.open):
            ret =sriov.set_numvfs_for_pf('enp1', 2)

        self.assertTrue(ret)
        self.assertListEqual(sriov_open.open.call_args_list,
                             [call('/sys/class/net/enp1/device/sriov_numvfs'),
                              call('/sys/class/net/enp1/device/sriov_totalvfs'),
                              call('/sys/class/net/enp1/device/sriov_numvfs', 'w')])
        handle = sriov_open.open()
        handle.write.assert_called_once_with('2')

    def test_set_numvfs_for_pf_failsafe(self):
        # TODO
        pass

    def test_set_numvfs_for_pf_over_max(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_state = ['1\n', '8\n']

        with patch('builtins.open', sriov_open.open):
            with self.assertRaises(ConfigurationError) as e:
                sriov.set_numvfs_for_pf('enp1', 9)

            self.assertIn('cannot allocate more VFs for PF enp1 than supported',
                          str(e.exception))

    def test_set_numvfs_for_pf_smaller(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_state = ['4\n', '8\n']
        
        with patch('builtins.open', sriov_open.open):
            ret = sriov.set_numvfs_for_pf('enp1', 3)

        self.assertFalse(ret)
        handle = sriov_open.open()
        self.assertEqual(handle.write.call_count, 0)
            

    def test_set_numvfs_for_pf_read_failed(self):
        sriov_open = MockSRIOVOpen()
        cases = (
            [IOError],
            ['not a number\n'],
            ['1\n', IOError],
            ['1\n', 'not a number\n'],
            )

        with patch('builtins.open', sriov_open.open):
            for case in cases:
                sriov_open.read_state = case
                with self.assertRaises(RuntimeError) as e:
                    sriov.set_numvfs_for_pf('enp1', 3)

    def test_set_numvfs_for_pf_write_failed(self):
        # TODO
        pass

    def test_perform_hardware_specific_quirks(self):
        # for now we have no custom quirks defined, so we just
        # check if the function succeeds
        sriov_open = MockSRIOVOpen()
        sriov_open.read_state = ['0x001f\n', '0x1337\n']

        with patch('builtins.open', sriov_open.open):
            ret = sriov.perform_hardware_specific_quirks('enp1')

        # it's good enough if it did all the matching
        self.assertListEqual(sriov_open.open.call_args_list,
                             [call('/sys/class/net/enp1/device/vendor'),
                              call('/sys/class/net/enp1/device/device'),])

    def test_perform_hardware_specific_quirks_failed(self):
        sriov_open = MockSRIOVOpen()
        cases = (
            [IOError],
            ['0x001f\n', IOError],
            )

        with patch('builtins.open', sriov_open.open):
            for case in cases:
                sriov_open.read_state = case
                with self.assertRaises(RuntimeError) as e:
                    sriov.perform_hardware_specific_quirks('enp1')

                self.assertIn('could not determine vendor and device ID of enp1',
                              str(e.exception))

    @patch('subprocess.check_call')
    def test_apply_vlan_filter_for_vf(self, check_call):
        self._prepare_sysfs_dir_structure()

        sriov.apply_vlan_filter_for_vf('enp2', 'enp2s16f1', 'vlan10', '10', prefix=self.workdir.name)

        self.assertEqual(check_call.call_count, 1)
        self.assertListEqual(check_call.call_args[0][0], 
                             ['ip', 'link', 'set', 'dev', 'enp2',
                              'vf', '3', 'vlan', '10'])

    @patch('subprocess.check_call')
    def test_apply_vlan_filter_for_vf_failed_no_index(self, check_call):
        self._prepare_sysfs_dir_structure()
        # we remove the PF -> VF link, simulating a system error
        os.unlink(os.path.join(self.workdir.name, 'sys/class/net/enp2/device/virtfn3'))

        with self.assertRaises(RuntimeError) as e:
            sriov.apply_vlan_filter_for_vf('enp2', 'enp2s16f1', 'vlan10', '10', prefix=self.workdir.name)

        self.assertIn('could not determine the VF index for enp2s16f1 while configuring vlan vlan10',
                      str(e.exception))
        self.assertEqual(check_call.call_count, 0)

    @patch('subprocess.check_call')
    def test_apply_vlan_filter_for_vf_failed_ip_link_set(self, check_call):
        self._prepare_sysfs_dir_structure()
        check_call.side_effect = CalledProcessError(-1, None)

        with self.assertRaises(RuntimeError) as e:
            sriov.apply_vlan_filter_for_vf('enp2', 'enp2s16f1', 'vlan10', '10', prefix=self.workdir.name)

        self.assertIn('failed setting SR-IOV VLAN filter for vlan vlan10',
                      str(e.exception))

    def test_apply_sriov_config(self):
        # TODO
        pass
