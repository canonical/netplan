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

from .base import TestBase, ND_EMPTY, ND_WITHIP, ND_DHCP4, ND_DHCP6, OVS_PHYSICAL, OVS_VIRTUAL


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
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 other-config:disable-in-band=true
'''},
                         'eth1.service': OVS_PHYSICAL % {'iface': 'eth1', 'extra': '''
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl set Interface eth1 other-config:disable-in-band=false
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth0.network': ND_DHCP6 % 'eth0',
                              'eth1.network': ND_DHCP4 % 'eth1'})

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
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . other-config:disable-in-band=true
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})

    def test_global_set_protocols(self):
        self.generate('''network:
  version: 2
  openvswitch:
    protocols: [OpenFlow10, OpenFlow11, OpenFlow12]
  ethernets:
    eth0:
      dhcp4: yes
''')
        self.assert_ovs({'global.service': OVS_VIRTUAL % {'iface': 'global', 'extra': '''
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-ofctl -O OpenFlow10,OpenFlow11,OpenFlow12
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
      openvswitch:
        external-ids:
          iface-id: myhostname
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
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-bond br0 bond0 eth1 eth2
ExecStop=/usr/bin/ovs-vsctl del-port bond0
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:iface-id=myhostname
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24'),
                              'bond0.network': ND_EMPTY % ('bond0', 'no')})

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

    def test_bond_lacp(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      openvswitch:
        lacp: active
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
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-bond br0 bond0 eth1 eth2
ExecStop=/usr/bin/ovs-vsctl del-port bond0
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=active
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24'),
                              'bond0.network': ND_EMPTY % ('bond0', 'no')})

    def test_bond_lacp_invalid(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      openvswitch:
        lacp: invalid
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [bond0]
      openvswitch: {}
''', expect_fail=True)
        self.assertIn("Value of 'lacp' needs to be 'active', 'passive' or 'off", err)

    def test_bond_lacp_wrong_type(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1:
      openvswitch:
        lacp: passive
''', expect_fail=True)
        self.assertIn("Key 'lacp' is only valid for iterface type 'openvswitch bond'", err)

    def test_bond_mode_implicit_params(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      parameters:
        mode: balance-tcp # Sets OVS backend implicitly
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
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-bond br0 bond0 eth1 eth2
ExecStop=/usr/bin/ovs-vsctl del-port bond0
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 bond_mode=balance-tcp
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24'),
                              'bond0.network': ND_EMPTY % ('bond0', 'no')})

    def test_bond_mode_explicit_params(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      parameters:
        mode: active-backup
      openvswitch: {}
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
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-bond br0 bond0 eth1 eth2
ExecStop=/usr/bin/ovs-vsctl del-port bond0
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 bond_mode=active-backup
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24'),
                              'bond0.network': ND_EMPTY % ('bond0', 'no')})

    def test_bond_mode_ovs_invalid(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bonds:
    bond0:
      interfaces: [eth1, eth2]
      parameters:
        mode: balance-rr
      openvswitch: {}
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [bond0]
      openvswitch: {}
''', expect_fail=True)
        self.assertIn("bond0: bond mode 'balance-rr' not supported by openvswitch", err)

    def test_bridge_setup(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [eth1, eth2]
      openvswitch: {}
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra':
                        '''
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-br br0
ExecStart=/usr/bin/ovs-vsctl add-port br0 eth1
ExecStop=/usr/bin/ovs-vsctl del-port br0 eth1
ExecStart=/usr/bin/ovs-vsctl add-port br0 eth2
ExecStop=/usr/bin/ovs-vsctl del-port br0 eth2
ExecStop=/usr/bin/ovs-vsctl del-br br0
ExecStart=/usr/bin/ovs-vsctl set Port br0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set-fail-mode br0 standalone
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 mcast_snooping_enable=false
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 rstp_enable=false
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24')})

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
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra': '''
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-br br0
ExecStop=/usr/bin/ovs-vsctl del-br br0
ExecStart=/usr/bin/ovs-vsctl set Port br0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set-fail-mode br0 standalone
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 mcast_snooping_enable=false
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 rstp_enable=false
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 other-config:disable-in-band=true
'''}})
        # Confirm that the bridge has been only configured for OVS
        self.assert_networkd({'br0.network': ND_EMPTY % ('br0', 'ipv6')})

    def test_bridge_non_default_parameters(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1: {}
    eth2: {}
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [eth1, eth2]
      openvswitch:
        fail-mode: secure
        mcast-snooping: true
        rstp: true
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra':
                        '''
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-br br0
ExecStart=/usr/bin/ovs-vsctl add-port br0 eth1
ExecStop=/usr/bin/ovs-vsctl del-port br0 eth1
ExecStart=/usr/bin/ovs-vsctl add-port br0 eth2
ExecStop=/usr/bin/ovs-vsctl del-port br0 eth2
ExecStop=/usr/bin/ovs-vsctl del-br br0
ExecStart=/usr/bin/ovs-vsctl set Port br0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set-fail-mode br0 secure
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 mcast_snooping_enable=true
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 rstp_enable=true
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24')})

    def test_bridge_set_protocols(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        protocols: [OpenFlow10, OpenFlow11, OpenFlow15]
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra':
                        '''
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ovs-vsctl add-br br0
ExecStop=/usr/bin/ovs-vsctl del-br br0
ExecStart=/usr/bin/ovs-vsctl set Port br0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set-fail-mode br0 standalone
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 mcast_snooping_enable=false
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 rstp_enable=false
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 protocols=OpenFlow10,OpenFlow11,OpenFlow15
'''}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'br0.network': ND_EMPTY % ('br0', 'ipv6')})

    def test_bridge_set_protocols_invalid(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        protocols: [OpenFlow10, OpenFooBar13, OpenFlow15]
''', expect_fail=True)
        self.assertIn("Unsupported OVS 'protocol' value: OpenFooBar13", err)

    def test_set_protocols_invalid_interface(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        protocols: [OpenFlow10, OpenFlow15]
''', expect_fail=True)
        self.assertIn("Key 'protocols' is only valid for iterface type 'openvswitch bridge'", err)
