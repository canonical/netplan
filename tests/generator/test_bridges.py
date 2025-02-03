#
# Tests for bridge devices config generated via netplan
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel.lapierre@canonical.com>
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

from .base import TestBase, NM_UNMANAGED, NM_MANAGED


class TestNetworkd(TestBase):

    def test_bridge_set_mac(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'br0.network': '''[Match]
Name=br0

[Link]
MACAddress=00:01:02:03:04:05

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'br0.netdev': '[NetDev]\nName=br0\nMACAddress=00:01:02:03:04:05\nKind=bridge\n'})

    def test_bridge_dhcp6_no_accept_ra(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: no
      dhcp6: no
      accept-ra: no
  bridges:
    br0:
      interfaces: [engreen]
      dhcp6: true
      accept-ra: no''')
        self.assert_networkd({'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'br0.netdev': '''[NetDev]
Name=br0
Kind=bridge
''',
                              'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=no
IPv6AcceptRA=no
Bridge=br0
'''})

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'br0')

    def test_bridge_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    renderer: networkd
    br0:
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'br0')

    def test_bridge_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    renderer: NetworkManager
    br0:
      renderer: networkd
      addresses: [1.2.3.4/12]
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
Address=1.2.3.4/12
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'br0')

    def test_bridge_forward_declaration(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: [eno1, switchports]
      dhcp4: true
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBridge=br0\n'})

    @unittest.skipIf("CODECOV_TOKEN" in os.environ, "Skip on codecov.io: GLib changed hashtable sorting")
    def test_eth_bridge_nm_denylist(self):  # pragma: nocover
        self.generate('''network:
  renderer: networkd
  ethernets:
    eth42:
      dhcp4: yes
    ethbr:
      match: {name: eth43}
  bridges:
    mybr:
      interfaces: [ethbr]
      dhcp4: yes''')
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'eth42' + NM_UNMANAGED % 'eth43' + NM_UNMANAGED % 'mybr')

    def test_bridge_components(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bridges:
    br0:
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBridge=br0\n'})

    def test_bridge_params(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bridges:
    br0:
      interfaces: [eno1, switchports]
      parameters:
        ageing-time: 50
        forward-delay: 12
        hello-time: 6
        max-age: 24
        priority: 1000
        stp: true
        path-cost:
          eno1: 70
        port-priority:
          eno1: 14
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n\n'
                                            '[Bridge]\nAgeingTimeSec=50\n'
                                            'Priority=1000\n'
                                            'ForwardDelaySec=12\n'
                                            'HelloTimeSec=6\n'
                                            'MaxAgeSec=24\n'
                                            'STP=true\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBridge=br0\n\n'
                                              '[Bridge]\nCost=70\nPriority=14\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBridge=br0\n'})


class TestNetworkManager(TestBase):

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br0:
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'br0')

    def test_bridge_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  bridges:
    renderer: NetworkManager
    br0:
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'br0')

    def test_bridge_set_mac(self):
        self.generate('''network:
  version: 2
  bridges:
    renderer: NetworkManager
    br0:
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ethernet]
cloned-mac-address=00:01:02:03:04:05

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

    def test_bridge_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  bridges:
    renderer: networkd
    br0:
      renderer: NetworkManager
      addresses: [1.2.3.4/12]
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
address1=1.2.3.4/12

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'br0')

    def test_bridge_forward_declaration(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br0:
      interfaces: [eno1, switchport]
      dhcp4: true
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'br0' + NM_MANAGED % 'eno1' + NM_MANAGED % 'enp2s1')

    def test_bridge_components(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bridges:
    br0:
      interfaces: [eno1, switchport]
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'eno1' + NM_MANAGED % 'enp2s1' + NM_MANAGED % 'br0')

    def test_bridge_params(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bridges:
    br0:
      interfaces: [eno1, switchport]
      parameters:
        ageing-time: 50
        priority: 1000
        forward-delay: 12
        hello-time: 6
        max-age: 24
        path-cost:
          eno1: 70
        port-priority:
          eno1: 61
        stp: true
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[bridge-port]
path-cost=70
priority=61

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[bridge]
ageing-time=50
priority=1000
forward-delay=12
hello-time=6
max-age=24
stp=true

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'eno1' + NM_MANAGED % 'enp2s1' + NM_MANAGED % 'br0')


class TestNetplanYAMLv2(TestBase):
    '''No asserts are needed.

    The generate() method implicitly checks the (re-)generated YAML.
    '''

    def test_bridge_stp(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      parameters:
        stp: no
      dhcp4: true''')

    def test_bridge_vlans(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport: {}
  bridges:
    br0:
      interfaces: [eno1, switchport]
      parameters:
        vlan-filtering: true
        vlans: [1-100 pvid untagged, 42 untagged, 13, 1 pvid, 2-100 pvid untagged]
        port-vlans:
          eno1: [99-999 pvid untagged, 1 untagged, 42 pvid]
          switchport: [4000-4094, 1 pvid, 13 untagged]''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[bridge]
stp=true
vlan-filtering=true
vlans=1-100 pvid untagged, 42 untagged, 13, 1 pvid, 2-100 pvid untagged

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[bridge-port]
vlans=99-999 pvid untagged, 1 untagged, 42 pvid

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=switchport
slave-type=bridge # wokeignore:rule=slave
master=br0 # wokeignore:rule=master

[bridge-port]
vlans=4000-4094, 1 pvid, 13 untagged

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})


class TestConfigErrors(TestBase):

    def test_bridge_unknown_iface(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: ['foo']''', expect_fail=True)
        self.assertIn("br0: interface 'foo' is not defined", err)

    def test_bridge_multiple_assignments(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bridges:
    br0:
      interfaces: [eno1]
    br1:
      interfaces: [eno1]''', expect_fail=True)
        self.assertIn("br1: interface 'eno1' is already assigned to bridge br0", err)

    def test_bridge_invalid_dev_for_path_cost(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        path-cost:
          eth0: 50
      dhcp4: true''', expect_fail=True)

    def test_bridge_path_cost_already_defined(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        path-cost:
          eno1: 50
          eno1: 40
      dhcp4: true''', expect_fail=True)

    def test_bridge_invalid_path_cost(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        path-cost:
          eno1: aa
      dhcp4: true''', expect_fail=True)

    def test_bridge_invalid_dev_for_port_prio(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-priority:
          eth0: 50
      dhcp4: true''', expect_fail=True)

    def test_bridge_port_prio_already_defined(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-priority:
          eno1: 50
          eno1: 40
      dhcp4: true''', expect_fail=True)

    def test_bridge_invalid_port_prio(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-priority:
          eno1: 257
      dhcp4: true''', expect_fail=True)

    def test_bridge_no_vlan(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      parameters:
        vlans: [99-999 pvid untagged, 1 untagged, 42 pvid]''', expect_fail=True)
        self.assertIn("ERROR: br0: networkd does not support bridge vlans", err)

    def test_bridge_no_port_vlan(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-vlans:
          eno1: [99-999 pvid untagged, 1 untagged, 42 pvid]''', expect_fail=True)
        self.assertIn("ERROR: eno1: networkd does not support bridge port-vlans", err)

    def test_bridge_invalid_vlan(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      parameters:
        vlans: [1 unmapped INVALID]''', expect_fail=True)
        self.assertIn("Error in network definition: malformed vlan '1 unmapped INVALID', must be: $vid [pvid] [untagged] \
[, $vid [pvid] [untagged]]", err)

    def test_bridge_invalid_vlan_vid(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      parameters:
        vlans: [0]''', expect_fail=True)
        self.assertIn("Error in network definition: malformed vlan vid '0', must be in range [1..4094]", err)

    def test_bridge_invalid_port_vlan_vid_to(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-vlans:
          eno1: [1-4095]''', expect_fail=True)
        self.assertIn("Error in network definition: malformed vlan vid '4095', must be in range [1..4094]", err)

    def test_bridge_port_vlan_already_defined(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-vlans:
          eno1: [1]
          eno1: [1]''', expect_fail=True)
        self.assertIn("Error in network definition: br0: interface 'eno1' already has port vlans", err)

    def test_bridge_invalid_vlan_vid_range(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      parameters:
        vlans: [100-1]''', expect_fail=True)
        self.assertIn("Error in network definition: malformed vlan vid range '100-1': 100 > 1!", err)

    def test_bridge_port_vlan_add_missing_node(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-vlans:
          eth0: [1]''', expect_fail=True)
        self.assertIn("Error in network definition: br0: interface 'eth0' is not defined", err)
