#!/usr/bin/python3
# Validate ConfigManager methods
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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
import tempfile
import unittest

from netplan.configmanager import ConfigManager, ConfigurationError


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.configmanager = ConfigManager(prefix=self.workdir.name, extra_files={})
        os.makedirs(os.path.join(self.workdir.name, "etc/netplan"))
        os.makedirs(os.path.join(self.workdir.name, "run/systemd/network"))
        os.makedirs(os.path.join(self.workdir.name, "run/NetworkManager/system-connections"))
        with open(os.path.join(self.workdir.name, "newfile.yaml"), 'w') as fd:
            print('''network:
  version: 2
  ethernets:
    ethtest:
      dhcp4: yes
''', file=fd)
        with open(os.path.join(self.workdir.name, "newfile_merging.yaml"), 'w') as fd:
            print('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: on
    eth42:
      dhcp4: on
    ethbr1:
      dhcp4: on
''', file=fd)
        with open(os.path.join(self.workdir.name, "newfile_emptydict.yaml"), 'w') as fd:
            print('''network:
  version: 2
  ethernets:
    eth0: {}
  bridges:
    br666: {}
''', file=fd)
        with open(os.path.join(self.workdir.name, "ovs_merging.yaml"), 'w') as fd:
            print('''network:
  version: 2
  openvswitch:
    ports: [[patchx, patchc], [patchy, patchd]]
  bridges:
    ovs0: {openvswitch: {}}
''', file=fd)
        with open(os.path.join(self.workdir.name, "invalid.yaml"), 'w') as fd:
            print('''network:
  version: 2
  vlans:
    vlan78:
      id: 78
      link: ethinvalid
''', file=fd)
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print('''network:
  version: 2
  renderer: networkd
  openvswitch:
    ports: [[patcha, patchb]]
    other-config:
      disable-in-band: true
  ethernets:
    eth0:
      dhcp4: false
    ethbr1:
      dhcp4: false
    ethbr2:
      dhcp4: false
    ethbond1:
      dhcp4: false
    ethbond2:
      dhcp4: false
  wifis:
    wlan1:
      access-points:
        testAP: {}
  modems:
    wwan0:
      apn: internet
      pin: 1234
      dhcp4: yes
      addresses: [1.2.3.4/24, 5.6.7.8/24]
  vlans:
    vlan2:
      id: 2
      link: eth0
  bridges:
    br3:
      interfaces: [ ethbr1 ]
    br4:
      interfaces: [ ethbr2 ]
      parameters:
        stp: on
  vrfs:
    vrf1005:
      table: 1005
      interfaces:
        - br3
        - br4
    vrf1006:
      table: 1006
      interfaces: []
  bonds:
    bond5:
      interfaces: [ ethbond1 ]
    bond6:
      interfaces: [ ethbond2 ]
      parameters:
        mode: 802.3ad
  tunnels:
    he-ipv6:
      mode: sit
      remote: 2.2.2.2
      local: 1.1.1.1
      addresses:
        - "2001:dead:beef::2/64"
      gateway6: "2001:dead:beef::1"
  nm-devices:
    fallback:
      renderer: NetworkManager
      networkmanager:
        passthrough:
          connection.id: some-nm-id
          connection.uuid: some-uuid
          connection.type: ethernet
''', file=fd)
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'w') as fd:
            print("pretend .network", file=fd)
        with open(os.path.join(self.workdir.name, "run/NetworkManager/system-connections/pretend"), 'w') as fd:
            print("pretend NM config", file=fd)

    def test_parse(self):
        self.configmanager.parse()
        state = self.configmanager.np_state
        assert state
        self.assertIn('eth0',   state.ethernets)
        self.assertIn('bond6',  state.bonds)
        self.assertIn('eth0',   self.configmanager.physical_interfaces)
        self.assertNotIn('bond7', self.configmanager.all_defs)
        self.assertNotIn('bond6', self.configmanager.physical_interfaces)
        self.assertIn('wwan0', state.modems)
        self.assertIn('wwan0', self.configmanager.physical_interfaces)
        # self.assertIn('apn', self.configmanager.modems.get('wwan0'))
        self.assertIn('he-ipv6',    state.tunnels)
        self.assertNotIn('he-ipv6', self.configmanager.physical_interfaces)
        # self.assertIn('remote', self.configmanager.tunnels.get('he-ipv6'))
        self.assertIn('patcha', state.ovs_ports)
        self.assertIn('patchb', state.ovs_ports)

        self.assertEqual('networkd', state.backend)
        self.assertIn('fallback',    state.nm_devices)

        self.assertIn('vrf1005', self.configmanager.virtual_interfaces)
        self.assertIn('vlan2',   self.configmanager.virtual_interfaces)
        self.assertIn('br3',     self.configmanager.virtual_interfaces)
        self.assertIn('br4',     self.configmanager.virtual_interfaces)
        self.assertIn('bond5',   self.configmanager.virtual_interfaces)
        self.assertIn('bond6',   self.configmanager.virtual_interfaces)
        self.assertIn('he-ipv6', self.configmanager.virtual_interfaces)

    def test_parse_merging(self):
        state = self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "newfile_merging.yaml")])
        self.assertIn('eth0',    state.ethernets)
        self.assertIn('eth42',   state.ethernets)

    def test_parse_merging_ovs(self):
        state = self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "ovs_merging.yaml")])
        self.assertIn('eth0',   state.ethernets)
        # self.assertIn('dhcp4',  state.ethernets['eth0'])
        self.assertIn('patchx', state.ovs_ports)
        self.assertIn('patchy', state.ovs_ports)
        self.assertIn('ovs0',   state.bridges)
        self.assertEqual('OpenVSwitch', state['ovs0'].backend)
        self.assertEqual('OpenVSwitch', state['patchx'].backend)
        self.assertEqual('OpenVSwitch', state['patchy'].backend)

    def test_parse_emptydict(self):
        state = self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "newfile_emptydict.yaml")])
        self.assertIn('br666',   state.bridges)
        self.assertIn('eth0',    state.ethernets)

    def test_parse_invalid(self):
        with self.assertRaises(ConfigurationError):
            self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "invalid.yaml")])

    def test_parse_extra_config(self):
        state = self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "newfile.yaml")])
        self.assertIn('ethtest', state.ethernets)
        self.assertIn('bond6',   state.bonds)

    def test_add(self):
        self.configmanager.add({os.path.join(self.workdir.name, "newfile.yaml"):
                                os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")})
        self.assertIn(os.path.join(self.workdir.name, "newfile.yaml"),
                      self.configmanager.extra_files)
        self.assertTrue(os.path.exists(os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")))

    def test_backup_missing_dirs(self):
        backup_dir = self.configmanager.tempdir
        shutil.rmtree(os.path.join(self.workdir.name, "run/systemd/network"))
        self.configmanager.backup(backup_config_dir=False)
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/NetworkManager/system-connections/pretend")))
        # no source dir means no backup as well
        self.assertFalse(os.path.exists(os.path.join(backup_dir, "run/systemd/network/01-pretend.network")))
        self.assertFalse(os.path.exists(os.path.join(backup_dir, "etc/netplan/test.yaml")))

    def test_backup_without_config_file(self):
        backup_dir = self.configmanager.tempdir
        self.configmanager.backup(backup_config_dir=False)
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/NetworkManager/system-connections/pretend")))
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/systemd/network/01-pretend.network")))
        self.assertFalse(os.path.exists(os.path.join(backup_dir, "etc/netplan/test.yaml")))

    def test_backup_with_config_file(self):
        backup_dir = self.configmanager.tempdir
        self.configmanager.backup(backup_config_dir=True)
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/NetworkManager/system-connections/pretend")))
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/systemd/network/01-pretend.network")))
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "etc/netplan/test.yaml")))

    def test_revert(self):
        self.configmanager.backup()
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'a+') as fd:
            print("CHANGED", file=fd)
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'r') as fd:
            lines = fd.readlines()
            self.assertIn("CHANGED\n", lines)
        self.configmanager.revert()
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'r') as fd:
            lines = fd.readlines()
            self.assertNotIn("CHANGED\n", lines)

    def test_revert_extra_files(self):
        self.configmanager.add({os.path.join(self.workdir.name, "newfile.yaml"):
                                os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")})
        self.assertIn(os.path.join(self.workdir.name, "newfile.yaml"),
                      self.configmanager.extra_files)
        self.assertTrue(os.path.exists(os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")))
        self.configmanager.revert()
        self.assertNotIn(os.path.join(self.workdir.name, "newfile.yaml"),
                         self.configmanager.extra_files)
        self.assertFalse(os.path.exists(os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")))

    def test_cleanup(self):
        backup_dir = self.configmanager.tempdir
        self.assertTrue(os.path.exists(backup_dir))
        self.configmanager.cleanup()
        self.assertFalse(os.path.exists(backup_dir))

    def test_destruction(self):
        backup_dir = self.configmanager.tempdir
        self.assertTrue(os.path.exists(backup_dir))
        del self.configmanager
        self.assertFalse(os.path.exists(backup_dir))

    def test_cleanup_and_destruction(self):
        backup_dir = self.configmanager.tempdir
        self.assertTrue(os.path.exists(backup_dir))
        self.configmanager.cleanup()
        self.assertFalse(os.path.exists(backup_dir))
        # This tests that the rmtree in the destructor does not throw an error
        # if cleanup was already called
        del self.configmanager
        self.assertFalse(os.path.exists(backup_dir))

    def test__copy_tree(self):
        self.configmanager._copy_tree(os.path.join(self.workdir.name, "etc"),
                                      os.path.join(self.workdir.name, "etc2"))
        self.assertTrue(os.path.exists(os.path.join(self.workdir.name, "etc2/netplan/test.yaml")))

    def test__copy_tree_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            self.configmanager._copy_tree(os.path.join(self.workdir.name, "nonexistent"),
                                          os.path.join(self.workdir.name, "nonexistent2"), missing_ok=False)
