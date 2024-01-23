#!/usr/bin/python3
#
# Copyright (C) 2020-2022 Canonical, Ltd.
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
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
import tempfile
import unittest

from subprocess import CalledProcessError
from collections import defaultdict
from unittest.mock import patch, mock_open, call

import netplan
import netplan_cli.cli.sriov as sriov

from netplan_cli.configmanager import ConfigManager, ConfigurationError
from generator.base import TestBase
from tests.test_utils import call_cli


class MockSRIOVOpen():
    def __init__(self):
        # now this is a VERY ugly hack to make mock_open() better
        self.read_queue = []
        self.write_queue = []

        def sriov_read():
            action = self.read_queue.pop(0)
            if isinstance(action, str):
                return action
            else:
                raise action

        def sriov_write(data):
            if not self.write_queue:
                return
            action = self.write_queue.pop(0)
            if isinstance(action, Exception):
                raise action

        self.open = mock_open()
        self.open.return_value.read.side_effect = sriov_read
        self.open.return_value.write.side_effect = sriov_write


def mock_set_counts(interfaces, config_manager, vf_counts, active_vfs, active_pfs):
    counts = {'enp1': 2, 'enp2': 1}
    vfs = {'enp1s16f1': None, 'enp1s16f2': None, 'customvf1': None}
    pfs = {'enp1': 'enp1', 'enpx': 'enp2'}
    vf_counts.update(counts)
    active_vfs.update(vfs)
    active_pfs.update(pfs)


class TestSRIOV(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.workdir.name, 'etc/netplan'))
        self.configmanager = ConfigManager(prefix=self.workdir.name, extra_files={})

    def _prepare_sysfs_dir_structure(self, pf=('enp2', '0000:00:1f.0'),
                                     vfs=[('enp2s16f1', '0000:00:1f.6')], pf_driver='fake_driver'):
        """
        Setup sysfs mock for reading certain SR-IOV related files and symlinks

        :param tuple pf: A tuple descibing the physical function (iterface_name, pci_address)
        :param list vfs: A list of tuples describing the virtual functions related to this PF
        :param str pf_driver: The driver name to be mocked for this PF
        """
        pf_iface, pf_pci_addr = pf
        # prepare a directory hierarchy for testing the matching
        # this might look really scary, but that's how sysfs presents devices
        # such as these
        sysfs = os.path.join(self.workdir.name, 'sys')
        sys_devices = os.path.join(sysfs, 'devices/pci0000:00')
        pci_devices = os.path.join(sysfs, 'bus/pci/devices')
        pci_driver = os.path.join(sysfs, 'bus/pci/drivers', pf_driver)
        os.makedirs(os.path.join(sysfs, 'class/net'), exist_ok=True)
        os.makedirs(pci_devices, exist_ok=True)
        os.makedirs(pci_driver, exist_ok=True)  # access to 'bind' and 'unbind' files must be mocked

        # create the PF (enp2) dir
        # syfs mock in:
        # sys/devices/pci0000:00/PCI_ADDR
        # sys/devices/pci0000:00/PCI_ADDR/net/IFACE
        pf_iface_path = os.path.join(sys_devices, pf_pci_addr, 'net', pf_iface)
        pf_dev_path = os.path.join(sys_devices, pf_pci_addr)
        os.makedirs(pf_iface_path)
        # symlink it to /sys/bus/pci/devices
        os.symlink(os.path.join('../../../devices/pci0000:00', pf_pci_addr),
                   os.path.join(pci_devices, pf_pci_addr))

        # create VF (enp2s16f1, ...) dirs
        # sysfs mock in:
        # sys/devices/pci0000:00/PCI_ADDR and
        # sys/devices/pci0000:00/PCI_ADDR/net/IFACE
        for vf_iface, vf_pci_addr in vfs:
            vf_iface_path = os.path.join(sys_devices, vf_pci_addr, 'net', vf_iface)
            vf_dev_path = os.path.join(sys_devices, vf_pci_addr)
            os.makedirs(vf_iface_path)
            # symlink it to /sys/bus/pci/devices
            os.symlink(os.path.join('../../../devices/pci0000:00', vf_pci_addr),
                       os.path.join(pci_devices, vf_pci_addr))

            # populate the VF data
            with open(os.path.join(vf_dev_path, 'vendor'), 'w') as f:
                f.write('0x001f\n')
            with open(os.path.join(vf_dev_path, 'device'), 'w') as f:
                f.write('0xb33f\n')
            os.symlink(os.path.join('../../devices/pci0000:00', vf_pci_addr, 'net', vf_iface),
                       os.path.join(sysfs, 'class/net', vf_iface))
            os.symlink(os.path.join('../../..', vf_pci_addr),
                       os.path.join(sysfs, 'class/net', vf_iface, 'device'))
            # the VFs additionally have a device link to the PF
            os.symlink(os.path.join('../../..', pf_pci_addr), os.path.join(vf_dev_path, 'physfn'))

        # populate the PF data
        with open(os.path.join(pf_dev_path, 'vendor'), 'w') as f:
            f.write('0x001f\n')
        with open(os.path.join(pf_dev_path, 'device'), 'w') as f:
            f.write('0x1337\n')
        with open(os.path.join(pf_dev_path, 'sriov_numvfs'), 'w') as f:
            f.write(str(len(vfs))+'\n')
        os.symlink(os.path.join('../../../bus/pci/drivers', pf_driver), os.path.join(pf_dev_path, 'driver'))
        os.symlink(os.path.join('../../devices/pci0000:00', pf_pci_addr, 'net', pf_iface),
                   os.path.join(sysfs, 'class/net', pf_iface))
        os.symlink(os.path.join('../../..', pf_pci_addr), os.path.join(sysfs, 'class/net', pf_iface, 'device'))
        # the PF additionally has device links to all the VFs defined for it
        for i in range(len(vfs)):
            os.symlink(os.path.join('../../..', vfs[i][1]), os.path.join(pf_dev_path, 'virtfn'+str(i)))

    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_get_vf_count_and_functions(self, gim, gidn):
        # we mock-out get_interface_driver_name and get_interface_macaddress
        # to return useful values for the test
        gim.side_effect = lambda x: '00:01:02:03:04:05' if x == 'enp3' else '00:00:00:00:00:00'
        gidn.side_effect = lambda x: 'foo' if x == 'enp2' else 'bar'
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: networkd
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
    enp8:
      virtual-function-count: 7
    enp9: {}
    wlp6s0: {}
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
    enp1s16f2:
      link: enp1
      macaddress: 01:02:03:04:05:01
    enp2s16f1:
      link: enp2
    enp2s16f2: {link: enp2}
    enp3s16f1:
      link: enp3
    enpxs16f1:
      match:
        name: enp[4-5]s16f1
      link: enpx
    enp9s16f1:
      link: enp9
''', file=fd)
        self.configmanager.parse()
        interfaces = ['enp1', 'enp2', 'enp3', 'enp5', 'enp0', 'enp8']
        vf_counts = defaultdict(int)
        vfs = {}
        pfs = {}

        # call the function under test
        sriov.get_vf_count_and_functions(interfaces, self.configmanager.np_state,
                                         vf_counts, vfs, pfs)
        # check if the right vf counts have been recorded in vf_counts
        self.assertDictEqual(
            vf_counts,
            {'enp1': 2, 'enp2': 2, 'enp3': 1, 'enp5': 1, 'enp8': 7})
        # also check if the vfs and pfs dictionaries got properly set
        self.assertDictEqual(
            vfs,
            {'enp1s16f1': None, 'enp1s16f2': None, 'enp2s16f1': None,
             'enp2s16f2': None, 'enp3s16f1': None, 'enpxs16f1': None})
        self.assertDictEqual(
            pfs,
            {'enp1': 'enp1', 'enp2': 'enp2', 'enp3': 'enp3',
             'enpx': 'enp5', 'enp8': 'enp8'})

    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_get_vf_count_and_functions_set_name(self, gim, gidn):
        # we mock-out get_interface_driver_name and get_interface_macaddress
        # to return useful values for the test
        gim.side_effect = lambda x: '00:01:02:03:04:05' if x == 'enp3' else '00:00:00:00:00:00'
        gidn.side_effect = lambda x: 'foo' if x == 'enp1' else 'bar'
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: networkd
    enp1:
      match:
        driver: foo
      set-name: pf1
    enp8:
      match:
        name: enp[3-8]
      set-name: pf2
      virtual-function-count: 7
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
''', file=fd)
        self.configmanager.parse()
        interfaces = ['pf1', 'enp8']
        vf_counts = defaultdict(int)
        vfs = {}
        pfs = {}

        # call the function under test
        sriov.get_vf_count_and_functions(interfaces, self.configmanager.np_state,
                                         vf_counts, vfs, pfs)
        # check if the right vf counts have been recorded in vf_counts -
        # we expect netplan to take into consideration the renamed interface
        # names here
        self.assertDictEqual(
            vf_counts,
            {'pf1': 1, 'enp8': 7})
        # also check if the vfs and pfs dictionaries got properly set
        self.assertDictEqual(
            vfs,
            {'enp1s16f1': None})
        self.assertDictEqual(
            pfs,
            {'enp1': 'pf1', 'enp8': 'enp8'})

    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_get_vf_count_and_functions_many_match(self, gim, gidn):
        # we mock-out get_interface_driver_name and get_interface_macaddress
        # to return useful values for the test
        gim.side_effect = lambda x: '00:01:02:03:04:05' if x == 'enp3' else '00:00:00:00:00:00'
        gidn.side_effect = lambda x: 'foo' if x == 'enp2' else 'bar'
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: networkd
    enpx:
      match:
        name: enp*
      mtu: 9000
    enpxs16f1:
      link: enpx
''', file=fd)
        self.configmanager.parse()
        interfaces = ['enp1', 'wlp6s0', 'enp2', 'enp3']
        vf_counts = defaultdict(int)
        vfs = {}
        pfs = {}

        # call the function under test
        with self.assertRaises(ConfigurationError) as e:
            sriov.get_vf_count_and_functions(interfaces, self.configmanager.np_state,
                                             vf_counts, vfs, pfs)

        self.assertIn('matched more than one interface for a PF device: enpx',
                      str(e.exception))

    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_get_vf_count_and_functions_not_enough_explicit(self, gim, gidn):
        # we mock-out get_interface_driver_name and get_interface_macaddress
        # to return useful values for the test
        gim.side_effect = lambda x: '00:01:02:03:04:05' if x == 'enp3' else '00:00:00:00:00:00'
        gidn.side_effect = lambda x: 'foo' if x == 'enp2' else 'bar'
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: networkd
    enp1:
      virtual-function-count: 2
      mtu: 9000
    enp1s16f1:
      link: enp1
    enp1s16f2:
      link: enp1
    enp1s16f3:
      link: enp1
''', file=fd)
        self.configmanager.parse()
        interfaces = ['enp1', 'wlp6s0']
        vf_counts = defaultdict(int)
        vfs = {}
        pfs = {}

        # call the function under test
        with self.assertRaises(ConfigurationError) as e:
            sriov.get_vf_count_and_functions(interfaces, self.configmanager.np_state,
                                             vf_counts, vfs, pfs)

        self.assertIn('more VFs allocated than the explicit size declared: 3 > 2',
                      str(e.exception))

    def test_set_numvfs_for_pf(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_queue = ['8\n']

        with patch('builtins.open', sriov_open.open):
            ret = sriov.set_numvfs_for_pf('enp1', 2)

        self.assertTrue(ret)
        self.assertListEqual(sriov_open.open.call_args_list,
                             [call('/sys/class/net/enp1/device/sriov_totalvfs'),
                              call('/sys/class/net/enp1/device/sriov_numvfs', 'w')])
        handle = sriov_open.open()
        handle.write.assert_called_once_with('2')

    def test_set_numvfs_for_pf_failsafe(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_queue = ['8\n']
        sriov_open.write_queue = [IOError(16, 'Error'), None, None]

        with patch('builtins.open', sriov_open.open):
            ret = sriov.set_numvfs_for_pf('enp1', 2)

        self.assertTrue(ret)
        handle = sriov_open.open()
        self.assertEqual(handle.write.call_count, 3)

    def test_set_numvfs_for_pf_over_max(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_queue = ['8\n']

        with patch('builtins.open', sriov_open.open):
            with self.assertRaises(ConfigurationError) as e:
                sriov.set_numvfs_for_pf('enp1', 9)

            self.assertIn('cannot allocate more VFs for PF enp1 than supported',
                          str(e.exception))

    def test_set_numvfs_for_pf_over_theoretical_max(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_queue = ['1337\n']

        with patch('builtins.open', sriov_open.open):
            with self.assertRaises(ConfigurationError) as e:
                sriov.set_numvfs_for_pf('enp1', 345)

            self.assertIn('cannot allocate more VFs for PF enp1 than the SR-IOV maximum',
                          str(e.exception))

    def test_set_numvfs_for_pf_read_failed(self):
        sriov_open = MockSRIOVOpen()
        cases = (
            [IOError],
            ['not a number\n'],
            )

        with patch('builtins.open', sriov_open.open):
            for case in cases:
                sriov_open.read_queue = case
                with self.assertRaises(RuntimeError):
                    sriov.set_numvfs_for_pf('enp1', 3)

    def test_set_numvfs_for_pf_write_failed(self):
        sriov_open = MockSRIOVOpen()
        sriov_open.read_queue = ['8\n']
        sriov_open.write_queue = [IOError(16, 'Error'), IOError(16, 'Error')]

        with patch('builtins.open', sriov_open.open):
            with self.assertRaises(RuntimeError) as e:
                sriov.set_numvfs_for_pf('enp1', 2)

            self.assertIn('failed setting sriov_numvfs to 2 for enp1',
                          str(e.exception))

    def test_perform_hardware_specific_quirks(self):
        # for now we have no custom quirks defined, so we just
        # check if the function succeeds
        sriov_open = MockSRIOVOpen()
        sriov_open.read_queue = ['0x001f\n', '0x1337\n']

        with patch('builtins.open', sriov_open.open):
            sriov.perform_hardware_specific_quirks('enp1')

        # it's good enough if it did all the matching
        self.assertListEqual(sriov_open.open.call_args_list,
                             [call('/sys/class/net/enp1/device/vendor'),
                              call('/sys/class/net/enp1/device/device'), ])

    def test_perform_hardware_specific_quirks_failed(self):
        sriov_open = MockSRIOVOpen()
        cases = (
            [IOError],
            ['0x001f\n', IOError],
            )

        with patch('builtins.open', sriov_open.open):
            for case in cases:
                sriov_open.read_queue = case
                with self.assertRaises(RuntimeError) as e:
                    sriov.perform_hardware_specific_quirks('enp1')

                self.assertIn('could not determine vendor and device ID of enp1',
                              str(e.exception))

    @patch('subprocess.check_call')
    def test_apply_vlan_filter_for_vf(self, check_call):
        self._prepare_sysfs_dir_structure()

        sriov.apply_vlan_filter_for_vf('enp2', 'enp2s16f1', 'vlan10', 10, prefix=self.workdir.name)

        self.assertEqual(check_call.call_count, 1)
        self.assertListEqual(check_call.call_args[0][0],
                             ['ip', 'link', 'set', 'dev', 'enp2',
                              'vf', '0', 'vlan', '10'])

    @patch('subprocess.check_call')
    def test_apply_vlan_filter_for_vf_failed_no_index(self, check_call):
        self._prepare_sysfs_dir_structure(vfs=[('enp2s14f1', '0000:00:1f.4'),
                                               ('enp2s15f1', '0000:00:1f.5'),
                                               ('enp2s16f1', '0000:00:1f.6'),
                                               ('enp2s17f1', '0000:00:1f.7')])
        # we remove the PF -> VF link, simulating a system error
        os.unlink(os.path.join(self.workdir.name, 'sys/class/net/enp2/device/virtfn2'))

        with self.assertRaises(RuntimeError) as e:
            sriov.apply_vlan_filter_for_vf('enp2', 'enp2s16f1', 'vlan10', 10, prefix=self.workdir.name)

        self.assertIn('could not determine the VF index for enp2s16f1 while configuring vlan vlan10',
                      str(e.exception))
        self.assertEqual(check_call.call_count, 0)

    @patch('subprocess.check_call')
    def test_apply_vlan_filter_for_vf_failed_ip_link_set(self, check_call):
        self._prepare_sysfs_dir_structure()
        check_call.side_effect = CalledProcessError(-1, None)

        with self.assertRaises(RuntimeError) as e:
            sriov.apply_vlan_filter_for_vf('enp2', 'enp2s16f1', 'vlan10', 10, prefix=self.workdir.name)

        self.assertIn('failed setting SR-IOV VLAN filter for vlan vlan10',
                      str(e.exception))

    @patch('netifaces.interfaces')
    @patch('netplan_cli.cli.sriov.get_vf_count_and_functions')
    @patch('netplan_cli.cli.sriov.set_numvfs_for_pf')
    @patch('netplan_cli.cli.sriov.perform_hardware_specific_quirks')
    @patch('netplan_cli.cli.sriov.apply_vlan_filter_for_vf')
    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_apply_sriov_config(self, gim, gidn, apply_vlan, quirks,
                                set_numvfs, get_counts, netifs):
        # set up the environment
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    enp1:
      mtu: 9000
    enpx:
      match:
        name: enp[2-3]
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
    enp1s16f2:
      link: enp1
    customvf1:
      match:
        name: enp[2-3]s16f[1-4]
      link: enpx
  vlans:
    vf1.15:
      renderer: sriov
      id: 15
      link: customvf1
''', file=fd)
        # set up all the mock objects
        netifs.return_value = ['enp1', 'enp2', 'enp5', 'wlp6s0',
                               'enp1s16f1', 'enp1s16f2', 'enp2s16f1']
        get_counts.side_effect = mock_set_counts
        set_numvfs.side_effect = lambda pf, _: False if pf == 'enp2' else True
        gidn.return_value = 'foodriver'
        gim.return_value = '00:01:02:03:04:05'

        # call method under test
        sriov.apply_sriov_config(self.configmanager, rootdir=self.workdir.name)

        # make sure config_manager.parse() has been called
        self.assertTrue(self.configmanager.np_state)
        # check if the config got applied as expected
        # we had 2 PFs, one having two VFs and the other only one
        self.assertEqual(set_numvfs.call_count, 2)
        self.assertListEqual(set_numvfs.call_args_list,
                             [call('enp1', 2),
                              call('enp2', 1)])
        # one of the pfs already had sufficient VFs allocated, so only enp1
        # changed the vf count and only that one should trigger quirks
        quirks.assert_called_once_with('enp1')
        # only one had a hardware vlan
        apply_vlan.assert_called_once_with('enp2', 'enp2s16f1', 'vf1.15', 15)

    @patch('netifaces.interfaces')
    @patch('netplan_cli.cli.sriov.get_vf_count_and_functions')
    @patch('netplan_cli.cli.sriov.set_numvfs_for_pf')
    @patch('netplan_cli.cli.sriov.perform_hardware_specific_quirks')
    @patch('netplan_cli.cli.sriov.apply_vlan_filter_for_vf')
    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_apply_sriov_config_invalid_vlan(self, gim, gidn, apply_vlan, quirks,
                                             set_numvfs, get_counts, netifs):
        # set up the environment
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    enp1:
      mtu: 9000
    enpx:
      match:
        name: enp[2-3]
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
    enp1s16f2:
      link: enp1
    customvf1:
      match:
        name: enp[2-3]s16f[1-4]
      link: enpx
  vlans:
    vf1.15:
      renderer: sriov
      link: customvf1
''', file=fd)
        # set up all the mock objects
        netifs.return_value = ['enp1', 'enp2', 'enp5', 'wlp6s0',
                               'enp1s16f1', 'enp1s16f2', 'enp2s16f1']
        get_counts.side_effect = mock_set_counts
        set_numvfs.side_effect = lambda pf, _: False if pf == 'enp2' else True
        gidn.return_value = 'foodriver'
        gim.return_value = '00:01:02:03:04:05'

        # call method under test
        with self.assertRaises(netplan.NetplanValidationException) as e:
            sriov.apply_sriov_config(self.configmanager, rootdir=self.workdir.name)

        self.assertIn('vf1.15: missing \'id\' property', str(e.exception))
        self.assertEqual(apply_vlan.call_count, 0)

    def test_apply_sriov_invalid_link_no_vf(self):
        # set up the environment
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  ethernets:
    enp1: {}
  vlans:
    vf1.15:
      renderer: sriov
      id: 15
      link: enp1
''', file=fd)
        # call method under test
        with self.assertLogs() as logs:
            sriov.apply_sriov_config(self.configmanager, rootdir=self.workdir.name)
            self.assertIn('SR-IOV vlan defined for vf1.15 but link enp1 is '
                          'either not a VF or has no matches',
                          logs.output[0])

    @patch('netifaces.interfaces')
    @patch('netplan_cli.cli.sriov.get_vf_count_and_functions')
    @patch('netplan_cli.cli.sriov.set_numvfs_for_pf')
    @patch('netplan_cli.cli.sriov.perform_hardware_specific_quirks')
    @patch('netplan_cli.cli.sriov.apply_vlan_filter_for_vf')
    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_apply_sriov_config_too_many_vlans(self, gim, gidn, apply_vlan, quirks,
                                               set_numvfs, get_counts, netifs):
        # set up the environment
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    enp1:
      mtu: 9000
    enpx:
      match:
        name: enp[2-3]
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
    enp1s16f2:
      link: enp1
    customvf1:
      match:
        name: enp[2-3]s16f[1-4]
      link: enpx
  vlans:
    vf1.15:
      renderer: sriov
      id: 15
      link: customvf1
    vf1.16:
      renderer: sriov
      id: 16
      link: customvf1
''', file=fd)
        # set up all the mock objects
        netifs.return_value = ['enp1', 'enp2', 'enp5', 'wlp6s0',
                               'enp1s16f1', 'enp1s16f2', 'enp2s16f1']
        get_counts.side_effect = mock_set_counts
        set_numvfs.side_effect = lambda pf, _: False if pf == 'enp2' else True
        gidn.return_value = 'foodriver'
        gim.return_value = '00:01:02:03:04:05'

        # call method under test
        with self.assertRaises(ConfigurationError) as e:
            sriov.apply_sriov_config(self.configmanager, rootdir=self.workdir.name)

        self.assertIn('interface enp2s16f1 for netplan device customvf1 (vf1.16) already has an SR-IOV vlan defined',
                      str(e.exception))
        self.assertEqual(apply_vlan.call_count, 1)

    @patch('netifaces.interfaces')
    @patch('netplan_cli.cli.sriov.get_vf_count_and_functions')
    @patch('netplan_cli.cli.sriov.set_numvfs_for_pf')
    @patch('netplan_cli.cli.sriov.perform_hardware_specific_quirks')
    @patch('netplan_cli.cli.sriov.apply_vlan_filter_for_vf')
    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    def test_apply_sriov_config_many_match(self, gim, gidn, apply_vlan, quirks,
                                           set_numvfs, get_counts, netifs):
        # set up the environment
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    enp1:
      mtu: 9000
    enpx:
      match:
        name: enp[2-3]
    enp1s16f1:
      link: enp1
      macaddress: 01:02:03:04:05:00
    enp1s16f2:
      link: enp1
    customvf1:
      match:
        name: enp*s16f[1-4]
      link: enpx
''', file=fd)
        # set up all the mock objects
        netifs.return_value = ['enp1', 'enp2', 'enp5', 'wlp6s0',
                               'enp1s16f1', 'enp1s16f2', 'enp2s16f1']
        get_counts.side_effect = mock_set_counts
        set_numvfs.side_effect = lambda pf, _: False if pf == 'enp2' else True
        gidn.return_value = 'foodriver'
        gim.return_value = '00:01:02:03:04:05'

        # call method under test
        with self.assertRaises(ConfigurationError) as e:
            sriov.apply_sriov_config(self.configmanager, rootdir=self.workdir.name)

        self.assertIn('matched more than one interface for a VF device: customvf1',
                      str(e.exception))

    def test_unit_get_pci_slot_name(self):
        # test error case
        with self.assertRaises(RuntimeError) as e:
            sriov._get_pci_slot_name('notAnetdev0')
        self.assertIn('failed parsing PCI slot name for notAnetdev0:', str(e.exception))
        # test success case
        with patch('builtins.open', mock_open(read_data='''DRIVER=e1000e
PCI_CLASS=20000
PCI_ID=8086:156F
PCI_SUBSYS_ID=17AA:2245
PCI_SLOT_NAME=0000:00:1f.6
MODALIAS=pci:v00008086d0000156Fsv000017AAsd00002245bc02sc00i00
''')) as mock_file:
            self.assertEqual(sriov._get_pci_slot_name('eth99'), '0000:00:1f.6')
        mock_file.assert_called_with('/sys/class/net/eth99/device/uevent')

    def test_unit_class_PCIDevice(self):
        pcidev = sriov.PCIDevice('0000:00:1f.6')
        self.assertEqual('/sys', pcidev.sys)
        self.assertLessEqual('/sys/bus/pci/devices/0000:00:1f.6', pcidev.path)
        with patch('netplan_cli.cli.sriov.PCIDevice.sys', new_callable=unittest.mock.PropertyMock) as sys_mock:
            sys_mock.return_value = os.path.join(self.workdir.name, 'sys_mock')
            os.makedirs(os.path.join(self.workdir.name, 'sys_mock/bus/pci/devices/0000:00:1f.6/driver'))
            self.assertTrue(pcidev.bound)
            open(os.path.join(self.workdir.name, 'sys_mock/bus/pci/devices/0000:00:1f.6/physfn'), 'a').close()
            self.assertTrue(pcidev.is_vf)

    @patch('netifaces.interfaces')
    @patch('netplan_cli.cli.sriov.get_vf_count_and_functions')
    @patch('netplan_cli.cli.sriov.set_numvfs_for_pf')
    @patch('netplan_cli.cli.sriov.perform_hardware_specific_quirks')
    @patch('subprocess.check_call')
    @patch('netplan_cli.cli.sriov.PCIDevice.bound', new_callable=unittest.mock.PropertyMock)
    @patch('netplan_cli.cli.sriov.PCIDevice.sys', new_callable=unittest.mock.PropertyMock)
    @patch('netplan_cli.cli.sriov._get_pci_slot_name')
    def test_apply_sriov_config_eswitch_mode(self, gpsn, pcidevice_sys, pcidevice_bound,
                                             scc, quirks, set_numvfs, get_counts, netifs):
        handle = mock_open()
        builtin_open = open  # save the unpatched version of open()

        def driver_mock_open(*args, **kwargs):
            # mock only writes/opens to the mlx5_core driver's un-/bind files
            if args[0].endswith('mlx5_core/bind') or args[0].endswith('mlx5_core/unbind'):
                return handle(*args, **kwargs)
            # unpatched version for every other path
            return builtin_open(*args, **kwargs)  # pragma: nocover

        # set up the mock sysfs environment
        self._prepare_sysfs_dir_structure(pf=('enp1', '0000:03:00.0'),
                                          vfs=[('enp1s16f1', '0000:03:00.2'),
                                               ('enp1s16f2', '0000:03:00.3')],
                                          pf_driver='mlx5_core')
        self._prepare_sysfs_dir_structure(pf=('enp2', '0000:03:00.1'),
                                          vfs=[('enp2s14f1', '0000:03:08.2'),
                                               ('enp2s15f1', '0000:03:08.3'),
                                               ('enp2s16f1', '0000:03:08.4'),
                                               ('enp2s17f1', '0000:03:08.5')],
                                          pf_driver='mlx5_core')
        enp1_pci_addr = '0000:03:00.0'
        enp2_pci_addr = '0000:03:00.1'
        gpsn.side_effect = lambda iface: enp1_pci_addr if iface == 'enp1' else enp2_pci_addr
        sys_path = os.path.join(self.workdir.name, 'sys')
        pcidevice_sys.return_value = sys_path
        pcidevice_bound.side_effect = [
            True, True,  # 2x unbind (enp1 VFs)
            True, True, True, True,  # 4x unbind (enpx/enp2 VFs)
            False, False, False, False]  # 4x re-bind (enpx/enp2 VFs)

        # YAML config
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  ethernets:
    enp1:
      embedded-switch-mode: "legacy"
      delay-virtual-functions-rebind: true
    enpx:
      match:
        name: enp[2-3]
      embedded-switch-mode: "switchdev"
    enp1s16f1:
      link: enp1
    enp1s16f2:
      link: enp1
    customvf1:
      match:
        name: enp[2-3]s16f[1-4]
      link: enpx
''', file=fd)

        # set up all the mock objects
        netifs.return_value = ['enp1', 'enp2', 'enp5', 'wlp6s0',
                               'enp1s16f1', 'enp1s16f2', 'enp2s16f1']
        get_counts.side_effect = mock_set_counts
        writes = [
            ('/sys/bus/pci/drivers/mlx5_core/unbind', '0000:03:00.2'),
            ('/sys/bus/pci/drivers/mlx5_core/unbind', '0000:03:00.3'),
            ('/sys/bus/pci/drivers/mlx5_core/unbind', '0000:03:08.2'),
            ('/sys/bus/pci/drivers/mlx5_core/unbind', '0000:03:08.3'),
            ('/sys/bus/pci/drivers/mlx5_core/unbind', '0000:03:08.4'),
            ('/sys/bus/pci/drivers/mlx5_core/unbind', '0000:03:08.5'),
            ('/sys/bus/pci/drivers/mlx5_core/bind', '0000:03:08.2'),
            ('/sys/bus/pci/drivers/mlx5_core/bind', '0000:03:08.3'),
            ('/sys/bus/pci/drivers/mlx5_core/bind', '0000:03:08.4'),
            ('/sys/bus/pci/drivers/mlx5_core/bind', '0000:03:08.5')]

        # test success case
        with patch('builtins.open', driver_mock_open):
            sriov.apply_sriov_config(self.configmanager, rootdir=self.workdir.name)
        self.assertEqual(len(writes), handle.call_count)
        self.assertEqual(handle.call_args_list, [call(elem[0], 'wt') for elem in writes])
        self.assertEqual(len(writes), handle().write.call_count)
        self.assertEqual(handle().write.call_args_list, [call(elem[1]) for elem in writes])

        self.assertEqual(2, scc.call_count)
        scc.assert_has_calls([
            call(['/sbin/devlink', 'dev', 'eswitch', 'set', 'pci/0000:03:00.0', 'mode', 'legacy']),
            call(['/sbin/devlink', 'dev', 'eswitch', 'set', 'pci/0000:03:00.1', 'mode', 'switchdev'])
        ])

    @patch('netplan_cli.cli.sriov.PCIDevice.bound', new_callable=unittest.mock.PropertyMock)
    @patch('netplan_cli.cli.sriov.PCIDevice.sys', new_callable=unittest.mock.PropertyMock)
    @patch('netplan_cli.cli.commands.sriov_rebind._get_pci_slot_name')
    def test_cli_rebind(self, gpsn, sys_mock, bound_mock):
        self._prepare_sysfs_dir_structure(pf=('enp3s0f0', '0000:03:00.0'),
                                          vfs=[('enp3s0f0v0', '0000:03:00.2'),
                                               ('enp3s0f0v1', '0000:03:00.3')],
                                          pf_driver='some_driver')
        sys_path = os.path.join(self.workdir.name, 'sys')
        sys_mock.return_value = sys_path
        enp3s0f0_pci_addr = '0000:03:00.0'
        not_a_pf_pci_addr = '0000:00:99.9'
        gpsn.side_effect = lambda iface: enp3s0f0_pci_addr if iface == 'enp3s0f0' else not_a_pf_pci_addr
        bound_mock.side_effect = [False, False]  # 0000:03:00.2 and 0000:03:00.3 are unbound

        with patch('builtins.open', mock_open(read_data='')) as mock_file:
            out = call_cli(['rebind', 'enp3s0f0', 'not_a_pf'])
            self.assertEqual(out, '', msg='netplan rebind returned unexpected output')
            self.assertEqual(2, mock_file.call_count)
            self.assertEqual(mock_file.call_args_list, [
                call('/sys/bus/pci/drivers/some_driver/bind', 'wt'),
                call('/sys/bus/pci/drivers/some_driver/bind', 'wt')])
            self.assertEqual(2, mock_file.return_value.write.call_count)
            self.assertEqual(mock_file.return_value.write.call_args_list, [
                call('0000:03:00.2'),
                call('0000:03:00.3')])


class TestParser(TestBase):
    def test_eswitch_mode(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      embedded-switch-mode: switchdev
      delay-virtual-functions-rebind: true
    enblue:
      match: {driver: fake_driver}
      set-name: enblue
      embedded-switch-mode: legacy
      delay-virtual-functions-rebind: true
      virtual-function-count: 4
    sriov_vf0:
      link: engreen''')
        self.assert_sriov({'rebind.service': '''[Unit]
Description=(Re-)bind SR-IOV Virtual Functions to their driver
After=network.target
After=sys-subsystem-net-devices-enblue.device
After=sys-subsystem-net-devices-engreen.device

[Service]
Type=oneshot
ExecStart=/usr/sbin/netplan rebind enblue engreen
'''})

    def test_rebind_service_generation(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      embedded-switch-mode: switchdev
      delay-virtual-functions-rebind: true
    enblue:
      match: {driver: fake_driver}
      set-name: enblue
      embedded-switch-mode: legacy
      delay-virtual-functions-rebind: true
      virtual-function-count: 4
    sriov_blue_vf0:
      link: enblue
    sriov_blue_vf1:
      link: enblue
    sriov_blue_vf1:
      link: enblue
    sriov_green_vf0:
      link: engreen
    sriov_green_vf1:
      link: engreen
    sriov_green_vf2:
      link: engreen''')
        self.assert_sriov({'rebind.service': '''[Unit]
Description=(Re-)bind SR-IOV Virtual Functions to their driver
After=network.target
After=sys-subsystem-net-devices-enblue.device
After=sys-subsystem-net-devices-engreen.device

[Service]
Type=oneshot
ExecStart=/usr/sbin/netplan rebind enblue engreen
'''})

    def test_rebind_not_delayed(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      embedded-switch-mode: switchdev
      delay-virtual-functions-rebind: false
    sriov_vf:
      link: engreen''')
        self.assert_sriov({})

    def test_rebind_no_iface(self):
        out = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      match: {name: 'enp4f[1-3]'}
      embedded-switch-mode: switchdev
      delay-virtual-functions-rebind: true
    sriov_vf:
      link: engreen''')
        self.assert_sriov({})
        self.assertIn('engreen: Cannot rebind SR-IOV virtual functions, unknown interface name.', out)

    def test_invalid_not_a_pf(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      embedded-switch-mode: legacy''', expect_fail=True)
        self.assertIn("This is not a SR-IOV PF", err)

    def test_invalid_eswitch_mode(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      embedded-switch-mode: invalid''', expect_fail=True)
        self.assertIn("needs to be 'switchdev' or 'legacy'", err)
