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

from netplan.configmanager import ConfigManager


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
    ports: [[patchx, patcha], [patchy, patchb]]
  bridges:
    ovs0: {openvswitch: {}}
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
      link: eth99
  bridges:
    br3:
      interfaces: [ ethbr1 ]
    br4:
      interfaces: [ ethbr2 ]
      parameters:
        stp: on
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
''', file=fd)
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'w') as fd:
            print("pretend .network", file=fd)
        with open(os.path.join(self.workdir.name, "run/NetworkManager/system-connections/pretend"), 'w') as fd:
            print("pretend NM config", file=fd)

    def test_parse(self):
        self.configmanager.parse()
        self.assertIn('eth0', self.configmanager.ethernets)
        self.assertIn('bond6', self.configmanager.bonds)
        self.assertIn('eth0', self.configmanager.physical_interfaces)
        self.assertNotIn('bond7', self.configmanager.interfaces)
        self.assertNotIn('bond6', self.configmanager.physical_interfaces)
        self.assertNotIn('parameters', self.configmanager.bonds.get('bond5'))
        self.assertIn('parameters', self.configmanager.bonds.get('bond6'))
        self.assertIn('wwan0', self.configmanager.modems)
        self.assertIn('wwan0', self.configmanager.physical_interfaces)
        self.assertIn('apn', self.configmanager.modems.get('wwan0'))
        self.assertIn('he-ipv6', self.configmanager.tunnels)
        self.assertNotIn('he-ipv6', self.configmanager.physical_interfaces)
        self.assertIn('remote', self.configmanager.tunnels.get('he-ipv6'))
        self.assertIn('other-config', self.configmanager.openvswitch)
        self.assertIn('ports', self.configmanager.openvswitch)
        self.assertEquals(2, self.configmanager.version)
        self.assertEquals('networkd', self.configmanager.renderer)

    def test_parse_merging(self):
        self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "newfile_merging.yaml")])
        self.assertIn('eth0', self.configmanager.ethernets)
        self.assertIn('dhcp4', self.configmanager.ethernets['eth0'])
        self.assertEquals(True, self.configmanager.ethernets['eth0'].get('dhcp6'))
        self.assertEquals(True, self.configmanager.ethernets['ethbr1'].get('dhcp4'))

    def test_parse_merging_ovs(self):
        self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "ovs_merging.yaml")])
        self.assertIn('eth0', self.configmanager.ethernets)
        self.assertIn('dhcp4', self.configmanager.ethernets['eth0'])
        self.assertIn('patchx', self.configmanager.ovs_ports)
        self.assertIn('patchy', self.configmanager.ovs_ports)
        self.assertIn('ovs0', self.configmanager.bridges)
        self.assertEqual({}, self.configmanager.ovs_ports['patchx'].get('openvswitch'))
        self.assertEqual({}, self.configmanager.ovs_ports['patchy'].get('openvswitch'))
        self.assertEqual({}, self.configmanager.bridges['ovs0'].get('openvswitch'))

    def test_parse_emptydict(self):
        self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "newfile_emptydict.yaml")])
        self.assertIn('br666', self.configmanager.bridges)
        self.assertEquals(False, self.configmanager.ethernets['eth0'].get('dhcp4'))
        self.assertEquals(False, self.configmanager.ethernets['ethbr1'].get('dhcp4'))

    def test_parse_extra_config(self):
        self.configmanager.parse(extra_config=[os.path.join(self.workdir.name, "newfile.yaml")])
        self.assertIn('ethtest', self.configmanager.ethernets)
        self.assertIn('bond6', self.configmanager.bonds)

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

    def test__copy_tree(self):
        self.configmanager._copy_tree(os.path.join(self.workdir.name, "etc"),
                                      os.path.join(self.workdir.name, "etc2"))
        self.assertTrue(os.path.exists(os.path.join(self.workdir.name, "etc2/netplan/test.yaml")))

    def test__copy_tree_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            self.configmanager._copy_tree(os.path.join(self.workdir.name, "nonexistent"),
                                          os.path.join(self.workdir.name, "nonexistent2"), missing_ok=False)
