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
import sys
import unittest

from .base import TestBase


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
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_nm_udev(None)

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
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_nm_udev(None)

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
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_nm_udev(None)

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
    def test_eth_bridge_nm_blacklist(self):  # pragma: nocover
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
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:mybr,interface-name:eth42,interface-name:eth43,''')

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
        self.assert_nm_udev(None)

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
        self.assert_nm_udev(None)

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

[802-3-ethernet]
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
        self.assert_nm_udev(None)

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
slave-type=bridge
master=br0

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
slave-type=bridge
master=br0

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
        self.assert_nm_udev(None)

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
slave-type=bridge
master=br0

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
slave-type=bridge
master=br0

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
        self.assert_nm_udev(None)

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
slave-type=bridge
master=br0

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
slave-type=bridge
master=br0

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
        self.assert_nm_udev(None)


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

