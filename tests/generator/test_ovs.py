#
# Common tests for netplan OpenVSwitch support
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@ubuntu.com>
#         Lukas 'slyon' Märdian <lukas.maerdian@canonical.com>
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

from .base import TestBase, ND_DHCP4, OVS_PHYSICAL, OVS_VIRTUAL


class TestOpenVSwitch(TestBase):
    '''OVS output'''

    def test_interface_external_ids_other_config(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        external-ids:
          iface-id: myhostname
        other-config:
          disable-in-band: true
      dhcp6: true
    eth1:
      dhcp4: true
      openvswitch:
        other-config:
          disable-in-band: false
''')
        self.assert_ovs({'eth0.service': OVS_PHYSICAL % {'iface': 'eth0', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 other-config:disable-in-band=true
'''},
                         'eth1.service': OVS_PHYSICAL % {'iface': 'eth1', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface eth1 other-config:disable-in-band=false
'''}})
        # Confirm that networkd does not touch the OVS interfaces
        self.assert_networkd({})

    def test_bridge_external_ids_other_config(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        external-ids:
          iface-id: myhostname
        other-config:
          disable-in-band: true
      dhcp4: yes
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 other-config:disable-in-band=true
'''}})
        # Confirm that networkd does not touch the OVS interfaces
        self.assert_networkd({})

    def test_global_external_ids_other_config(self):
        self.generate('''network:
  version: 2
  openvswitch:
    external-ids:
      iface-id: myhostname
    other-config:
      disable-in-band: true
  ethernets:
    eth0:
      dhcp4: yes
''')
        self.assert_ovs({'global.service': OVS_VIRTUAL % {'iface': 'global', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . other-config:disable-in-band=true
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})

    def test_duplicate_map_entry(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    external-ids:
      iface-id: myhostname
      iface-id: foobar
  ethernets:
    eth0:
      dhcp4: yes
''', expect_fail=True)
        self.assertIn("duplicate map entry 'iface-id'", err)

    def test_no_ovs_config(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: yes
''')
        self.assert_ovs(None)
        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})

    def test_bond_setup(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      #parameters:
      #  mode: balance-tcp # this is a bond mode only supported on openvswitch
      openvswitch: {}
      #  lacp: active
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [bond0]
      openvswitch: {}
''')
        self.assert_ovs({'bond0.service': OVS_VIRTUAL % {'iface': 'bond0', 'extra':
                        '''Requires=netplan-ovs-br0.service
After=netplan-ovs-br0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl add-bond br0 bond0 eth1 eth2
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n'})

    def test_bond_no_bridge(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      openvswitch: {}
''', expect_fail=True)
        self.assertIn("Bond bond0 needs to be a slave of an OpenVSwitch bridge", err)

    def test_bond_invalid_bridge(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      openvswitch: {}
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [bond0]
''', expect_fail=True)
        self.assertIn("Bond bond0: br0 needs to be handled by OpenVSwitch", err)

    def test_bond_not_enough_interfaces(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
  bonds:
    bond0:
      interfaces: [eth1]
      openvswitch: {}
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [bond0]
      openvswitch: {}
''', expect_fail=True)
        self.assertIn("Bond bond0 needs to have at least 2 slave interfaces", err)
