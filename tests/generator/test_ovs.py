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

from .base import TestBase, ND_EMPTY, ND_WITHIP, ND_DHCP4, ND_DHCP6, \
                            OVS_PHYSICAL, OVS_VIRTUAL, \
                            OVS_BR_EMPTY, OVS_BR_DEFAULT, \
                            OVS_CLEANUP


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
  bridges:
    ovs0:
      interfaces: [eth0, eth1]
      openvswitch: {}
''')
        self.assert_ovs({'ovs0.service': OVS_VIRTUAL % {'iface': 'ovs0', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br ovs0
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port ovs0 eth1
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port ovs0 eth0
''' + OVS_BR_DEFAULT % {'iface': 'ovs0'}},
                         'eth0.service': OVS_PHYSICAL % {'iface': 'eth0', 'extra': '''\
Requires=netplan-ovs-ovs0.service
After=netplan-ovs-ovs0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 external-ids:netplan/external-ids/iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 other-config:disable-in-band=true
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 external-ids:netplan/other-config/disable-in-band=true
'''},
                         'eth1.service': OVS_PHYSICAL % {'iface': 'eth1', 'extra': '''\
Requires=netplan-ovs-ovs0.service
After=netplan-ovs-ovs0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface eth1 other-config:disable-in-band=false
ExecStart=/usr/bin/ovs-vsctl set Interface eth1 external-ids:netplan/other-config/disable-in-band=false
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'ovs0.network': ND_EMPTY % ('ovs0', 'ipv6'),
                              'eth0.network': (ND_DHCP6 % 'eth0')
                              .replace('LinkLocalAddressing=ipv6', 'LinkLocalAddressing=no\nBridge=ovs0'),
                              'eth1.network': (ND_DHCP4 % 'eth1')
                              .replace('LinkLocalAddressing=ipv6', 'LinkLocalAddressing=no\nBridge=ovs0')})

    def test_interface_invalid_external_ids_other_config(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        external-ids:
          iface-id: myhostname
        other-config:
          disable-in-band: true''', expect_fail=True)
        self.assertIn('eth0: Interface needs to be assigned to an OVS bridge/bond to carry external-ids/other-config', err)

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
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:netplan/external-ids/iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . other-config:disable-in-band=true
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:netplan/other-config/disable-in-band=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})

    def test_global_set_protocols(self):
        self.generate('''network:
  version: 2
  openvswitch:
    protocols: [OpenFlow10, OpenFlow11, OpenFlow12]
  bridges:
    ovs0:
      openvswitch: {}''')
        self.assert_ovs({'ovs0.service': OVS_VIRTUAL % {'iface': 'ovs0', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br ovs0
''' + OVS_BR_DEFAULT % {'iface': 'ovs0'} + '''\
ExecStart=/usr/bin/ovs-vsctl set Bridge ovs0 protocols=OpenFlow10,OpenFlow11,OpenFlow12
ExecStart=/usr/bin/ovs-vsctl set Bridge ovs0 external-ids:netplan/protocols=OpenFlow10,OpenFlow11,OpenFlow12
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'ovs0.network': ND_EMPTY % ('ovs0', 'ipv6')})

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
        self.assert_ovs({'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-bond br0 bond0 eth1 eth2
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/external-ids/iface-id=myhostname
'''},
                         'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-bond br0 bond0 eth1 eth2
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=active
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/lacp=active
'''},
                         'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-bond br0 bond0 eth1 eth2
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 bond_mode=balance-tcp
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/bond_mode=balance-tcp
'''},
                         'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-bond br0 bond0 eth1 eth2
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 bond_mode=active-backup
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/bond_mode=active-backup
'''},
                         'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br0 eth1
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br0 eth2
''' + OVS_BR_DEFAULT % {'iface': 'br0'}},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
''' + OVS_BR_DEFAULT % {'iface': 'br0'} + '''\
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/external-ids/iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 other-config:disable-in-band=true
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/other-config/disable-in-band=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br0 eth1
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br0 eth2
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set-fail-mode br0 secure
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/global/set-fail-mode=secure
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 mcast_snooping_enable=true
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/mcast_snooping_enable=true
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 rstp_enable=true
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/rstp_enable=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'eth2.network': '[Match]\nName=eth2\n\n[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24')})

    def test_bridge_fail_mode_invalid(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        fail-mode: glorious
''', expect_fail=True)
        self.assertIn("Value of 'fail-mode' needs to be 'standalone' or 'secure'", err)

    def test_fail_mode_non_bridge(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        fail-mode: glorious
''', expect_fail=True)
        self.assertIn("Key 'fail-mode' is only valid for iterface type 'openvswitch bridge'", err)

    def test_rstp_non_bridge(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        rstp: true
''', expect_fail=True)
        self.assertIn("Key is only valid for iterface type 'openvswitch bridge'", err)

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
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
''' + OVS_BR_DEFAULT % {'iface': 'br0'} + '''\
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 protocols=OpenFlow10,OpenFlow11,OpenFlow15
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/protocols=OpenFlow10,OpenFlow11,OpenFlow15
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
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

    def test_bridge_controller(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        controller:
          addresses: ["ptcp:", "ptcp:1337", "ptcp:1337:[fe80::1234%eth0]", "pssl:1337:[fe80::1]", "ssl:10.10.10.1",\
                      tcp:127.0.0.1:1337, "tcp:[fe80::1234%eth0]", "tcp:[fe80::1]:1337", unix:/some/path, punix:other/path]
          connection-mode: out-of-band
  openvswitch:
    ssl:
      ca-cert: /another/path
      certificate: /some/path
      private-key: /key/path
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra':
                        '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
''' + OVS_BR_DEFAULT % {'iface': 'br0'} + '''\
ExecStart=/usr/bin/ovs-vsctl set-controller br0 ptcp: ptcp:1337 ptcp:1337:[fe80::1234%eth0] pssl:1337:[fe80::1] ssl:10.10.10.1 \
tcp:127.0.0.1:1337 tcp:[fe80::1234%eth0] tcp:[fe80::1]:1337 unix:/some/path punix:other/path
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:netplan/global/set-controller=ptcp:,ptcp:1337,\
ptcp:1337:[fe80::1234%eth0],pssl:1337:[fe80::1],ssl:10.10.10.1,tcp:127.0.0.1:1337,tcp:[fe80::1234%eth0],tcp:[fe80::1]:1337,\
unix:/some/path,punix:other/path
ExecStart=/usr/bin/ovs-vsctl set Controller br0 connection-mode=out-of-band
ExecStart=/usr/bin/ovs-vsctl set Controller br0 external-ids:netplan/connection-mode=out-of-band
'''},
                         'global.service': OVS_VIRTUAL % {'iface': 'global', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set-ssl /key/path /some/path /another/path
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:netplan/global/set-ssl=/key/path,/some/path,/another/path
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'br0.network': ND_EMPTY % ('br0', 'ipv6')})

    def test_bridge_controller_invalid_target(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        controller:
          addresses: [ptcp]
''', expect_fail=True)
        self.assertIn("Unsupported OVS controller target: ptcp", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_controller_invalid_target_ip(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        controller:
          addresses: ["tcp:[fe80:1234%eth0]"]
''', expect_fail=True)
        self.assertIn("Unsupported OVS controller target: tcp:[fe80:1234%eth0]", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_controller_invalid_target_port(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        controller:
          addresses: [ptcp:65536]
''', expect_fail=True)
        self.assertIn("Unsupported OVS controller target: ptcp:65536", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_controller_invalid_connection_mode(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        controller:
          connection-mode: INVALID
''', expect_fail=True)
        self.assertIn("Value of 'connection-mode' needs to be 'in-band' or 'out-of-band'", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_controller_connection_mode_invalid_interface_type(self):
        err = self.generate('''network:
  version: 2
  bonds:
    mybond:
      openvswitch:
        controller:
          connection-mode: in-band
''', expect_fail=True)
        self.assertIn("Key 'controller.connection-mode' is only valid for iterface type 'openvswitch bridge'", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_controller_addresses_invalid_interface_type(self):
        err = self.generate('''network:
  version: 2
  bonds:
    mybond:
      openvswitch:
        controller:
          addresses: [unix:/some/socket]
''', expect_fail=True)
        self.assertIn("Key 'controller.addresses' is only valid for iterface type 'openvswitch bridge'", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_global_ssl(self):
        self.generate('''network:
  version: 2
  openvswitch:
    ssl:
      ca-cert: /another/path
      certificate: /some/path
      private-key: /key/path
''')
        self.assert_ovs({'global.service': OVS_VIRTUAL % {'iface': 'global', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set-ssl /key/path /some/path /another/path
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:netplan/global/set-ssl=/key/path,/some/path,/another/path
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({})

    def test_missing_ssl(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        controller:
          addresses: [ssl:10.10.10.1]
  openvswitch:
    ssl: {}
''', expect_fail=True)
        self.assertIn("ERROR: openvswitch bridge controller target 'ssl:10.10.10.1' needs SSL configuration, but global \
'openvswitch.ssl' settings are not set", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_global_ports(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
''', expect_fail=True)
        self.assertIn('patch0-1: OpenVSwitch patch port needs to be assigned to a bridge/bond', err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_few_ports(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    ports:
      - [patch0-1]
''', expect_fail=True)
        self.assertIn("An openvswitch peer port sequence must have exactly two entries", err)
        self.assertIn("- [patch0-1]", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_many_ports(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    ports:
      - [patch0-1, "patchx", patchy]
''', expect_fail=True)
        self.assertIn("An openvswitch peer port sequence must have exactly two entries", err)
        self.assertIn("- [patch0-1, \"patchx\", patchy]", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_ovs_invalid_port(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    ports:
      - [patchx, patchy]
      - [patchx, patchz]
''', expect_fail=True)
        self.assertIn("openvswitch port 'patchx' is already assigned to peer 'patchy'", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_ovs_invalid_peer(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    ports:
      - [patchx, patchy]
      - [patchz, patchx]
''', expect_fail=True)
        self.assertIn("openvswitch port 'patchx' is already assigned to peer 'patchy'", err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_auto_ovs_backend(self):
        self.generate('''network:
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
''')
        self.assert_ovs({'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'bond0.service': OVS_VIRTUAL % {'iface': 'bond0', 'extra':
                                                         '''Requires=netplan-ovs-br0.service
After=netplan-ovs-br0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-bond br0 bond0 eth1 eth2
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/lacp=off
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        self.assert_networkd({'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24'),
                              'bond0.network': ND_EMPTY % ('bond0', 'no'),
                              'eth1.network':
                              '''[Match]
Name=eth1

[Network]
LinkLocalAddressing=no
Bond=bond0
''',
                              'eth2.network':
                              '''[Match]
Name=eth2

[Network]
LinkLocalAddressing=no
Bond=bond0
'''})

    def test_bond_auto_ovs_backend(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {}
  bonds:
    bond0:
      interfaces: [eth0, patchy]
  bridges:
    br0:
      addresses: [192.170.1.1/24]
      interfaces: [bond0]
    br1:
      addresses: [2001:FFfe::1/64]
      interfaces: [patchx]
  openvswitch:
    ports:
      - [patchx, patchy]
''')
        self.assert_ovs({'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'br1.service': OVS_VIRTUAL % {'iface': 'br1', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br1
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br1 patchx -- set Interface patchx type=patch options:peer=patchy
''' + OVS_BR_DEFAULT % {'iface': 'br1'}},
                         'bond0.service': OVS_VIRTUAL % {'iface': 'bond0', 'extra':
                                                         '''Requires=netplan-ovs-br0.service
After=netplan-ovs-br0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-bond br0 bond0 patchy eth0 -- set Interface patchy type=patch options:peer=patchx
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan=true
ExecStart=/usr/bin/ovs-vsctl set Port bond0 lacp=off
ExecStart=/usr/bin/ovs-vsctl set Port bond0 external-ids:netplan/lacp=off
'''},
                         'patchx.service': OVS_VIRTUAL % {'iface': 'patchx', 'extra':
                                                          '''Requires=netplan-ovs-br1.service
After=netplan-ovs-br1.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Port patchx external-ids:netplan=true
'''},
                         'patchy.service': OVS_VIRTUAL % {'iface': 'patchy', 'extra':
                                                          '''Requires=netplan-ovs-bond0.service
After=netplan-ovs-bond0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface patchy external-ids:netplan=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        self.assert_networkd({'br0.network': ND_WITHIP % ('br0', '192.170.1.1/24'),
                              'br1.network': ND_WITHIP % ('br1', '2001:FFfe::1/64'),
                              'bond0.network': ND_EMPTY % ('bond0', 'no'),
                              'patchx.network': ND_EMPTY % ('patchx', 'no'),
                              'patchy.network': ND_EMPTY % ('patchy', 'no'),
                              'eth0.network': '[Match]\nName=eth0\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n'})

    def test_patch_ports(self):
        self.generate('''network:
  version: 2
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
  bridges:
    br0:
      addresses: [192.168.1.1/24]
      interfaces: [patch0-1]
    br1:
      addresses: [192.168.1.2/24]
      interfaces: [patch1-0]
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br0 patch0-1 -- set Interface patch0-1 type=patch options:peer=patch1-0
''' + OVS_BR_DEFAULT % {'iface': 'br0'}},
                         'br1.service': OVS_VIRTUAL % {'iface': 'br1', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br1
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port br1 patch1-0 -- set Interface patch1-0 type=patch options:peer=patch0-1
''' + OVS_BR_DEFAULT % {'iface': 'br1'}},
                         'patch0-1.service': OVS_VIRTUAL % {'iface': 'patch0-1', 'extra':
                                                            '''Requires=netplan-ovs-br0.service
After=netplan-ovs-br0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Port patch0-1 external-ids:netplan=true
'''},
                         'patch1-0.service': OVS_VIRTUAL % {'iface': 'patch1-0', 'extra':
                                                            '''Requires=netplan-ovs-br1.service
After=netplan-ovs-br1.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Port patch1-0 external-ids:netplan=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        self.assert_networkd({'br0.network': ND_WITHIP % ('br0', '192.168.1.1/24'),
                              'br1.network': ND_WITHIP % ('br1', '192.168.1.2/24'),
                              'patch0-1.network': ND_EMPTY % ('patch0-1', 'no'),
                              'patch1-0.network': ND_EMPTY % ('patch1-0', 'no')})

    def test_fake_vlan_bridge_setup(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      addresses: [192.168.1.1/24]
      openvswitch: {}
  vlans:
    br0.100:
      id: 100
      link: br0
      openvswitch: {}
''')
        self.assert_ovs({'br0.service': OVS_VIRTUAL % {'iface': 'br0', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0
''' + OVS_BR_DEFAULT % {'iface': 'br0'}},
                         'br0.100.service': OVS_VIRTUAL % {'iface': 'br0.100', 'extra':
                                                           '''Requires=netplan-ovs-br0.service
After=netplan-ovs-br0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0.100 br0 100
ExecStart=/usr/bin/ovs-vsctl set Interface br0.100 external-ids:netplan=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'br0.network': ND_WITHIP % ('br0', '192.168.1.1/24'),
                              'br0.100.network': ND_EMPTY % ('br0.100', 'ipv6')})

    def test_implicit_fake_vlan_bridge_setup(self):
        # Test if, when a VLAN is added to an OVS bridge, netplan will
        # implicitly assume the vlan should be done via OVS as well
        self.generate('''network:
  version: 2
  bridges:
    br0:
      addresses: [192.168.1.1/24]
      openvswitch: {}
  vlans:
    br0.100:
      id: 100
      link: br0
''')
        self.assert_ovs({'br0.service': OVS_BR_EMPTY % {'iface': 'br0'},
                         'br0.100.service': OVS_VIRTUAL % {'iface': 'br0.100', 'extra':
                                                           '''Requires=netplan-ovs-br0.service
After=netplan-ovs-br0.service

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br br0.100 br0 100
ExecStart=/usr/bin/ovs-vsctl set Interface br0.100 external-ids:netplan=true
'''},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'br0.network': ND_WITHIP % ('br0', '192.168.1.1/24'),
                              'br0.100.network': ND_EMPTY % ('br0.100', 'ipv6')})

    def test_invalid_device_type(self):
        err = self.generate('''network:
    version: 2
    ethernets:
        eth0:
            openvswitch: {}
''', expect_fail=True)
        self.assertIn('eth0: This device type is not supported with the OpenVSwitch backend', err)
        self.assert_ovs({})
        self.assert_networkd({})

    def test_bridge_non_ovs_bond(self):
        self.generate('''network:
    version: 2
    ethernets:
        eth0: {}
        eth1: {}
    bonds:
        non-ovs-bond:
            interfaces: [eth0, eth1]
    bridges:
        ovs-br:
            interfaces: [non-ovs-bond]
            openvswitch: {}
''')
        self.assert_ovs({'ovs-br.service': OVS_VIRTUAL % {'iface': 'ovs-br', 'extra': '''
[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl --may-exist add-br ovs-br
ExecStart=/usr/bin/ovs-vsctl --may-exist add-port ovs-br non-ovs-bond
''' + OVS_BR_DEFAULT % {'iface': 'ovs-br'}},
                         'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'non-ovs-bond.network': ND_EMPTY % ('non-ovs-bond', 'no') + 'Bridge=ovs-br\n',
                              'eth1.network': (ND_EMPTY % ('eth1', 'no')).replace('ConfigureWithoutCarrier=yes',
                              'Bond=non-ovs-bond'),
                              'eth0.network': (ND_EMPTY % ('eth0', 'no')).replace('ConfigureWithoutCarrier=yes',
                              'Bond=non-ovs-bond'),
                              'ovs-br.network': ND_EMPTY % ('ovs-br', 'ipv6'),
                              'non-ovs-bond.netdev': '[NetDev]\nName=non-ovs-bond\nKind=bond\n'})
