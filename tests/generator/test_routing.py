#
# Routing / IP rule tests for netplan generator
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

from .base import TestBase


class TestNetworkd(TestBase):

    def test_route_v4_single(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Metric=100
'''})

    def test_route_v4_multiple(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 8.8.0.0/16
          via: 192.168.1.1
        - to: 10.10.10.8
          via: 192.168.1.2
          metric: 5000
        - to: 11.11.11.0/24
          via: 192.168.1.3
          metric: 9999
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=8.8.0.0/16
Gateway=192.168.1.1

[Route]
Destination=10.10.10.8
Gateway=192.168.1.2
Metric=5000

[Route]
Destination=11.11.11.0/24
Gateway=192.168.1.3
Metric=9999
'''})

    def test_route_v4_onlink(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          on-link: true
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
GatewayOnlink=true
Metric=100
'''})

    def test_route_v4_onlink_no(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          on-link: n
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Metric=100
'''})

    def test_route_v4_scope(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          scope: link
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Scope=link
Metric=100
'''})

    def test_route_v4_scope_redefine(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          scope: host
          via: 192.168.14.20
          scope: link
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Scope=link
Metric=100
'''})

    def test_route_v4_type_blackhole(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          type: blackhole
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Type=blackhole
Metric=100
'''})

    def test_route_v4_type_redefine(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          type: prohibit
          via: 192.168.14.20
          type: unicast
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Metric=100
'''})

    def test_route_v4_table(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          table: 201
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Metric=100
Table=201
'''})

    def test_route_v4_from(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          from: 192.168.14.2
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
PreferredSource=192.168.14.2
Metric=100
'''})

    def test_route_v6_single(self):
        self.generate('''network:
  version: 2
  ethernets:
    enblue:
      addresses: ["192.168.1.3/24"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1''')

        self.assert_networkd({'enblue.network': '''[Match]
Name=enblue

[Network]
LinkLocalAddressing=ipv6
Address=192.168.1.3/24

[Route]
Destination=2001:dead:beef::2/64
Gateway=2001:beef:beef::1
'''})

    def test_route_v6_type(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
          type: prohibit''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=2001:dead:beef::2/64
Gateway=2001:beef:beef::1
Type=prohibit
'''})

    def test_route_v6_scope_host(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
          scope: host''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[Route]
Destination=2001:dead:beef::2/64
Gateway=2001:beef:beef::1
Scope=host
'''})

    def test_route_v6_multiple(self):
        self.generate('''network:
  version: 2
  ethernets:
    enblue:
      addresses: ["192.168.1.3/24"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
        - to: 2001:f00f:f00f::fe/64
          via: 2001:beef:feed::1
          metric: 1024''')

        self.assert_networkd({'enblue.network': '''[Match]
Name=enblue

[Network]
LinkLocalAddressing=ipv6
Address=192.168.1.3/24

[Route]
Destination=2001:dead:beef::2/64
Gateway=2001:beef:beef::1

[Route]
Destination=2001:f00f:f00f::fe/64
Gateway=2001:beef:feed::1
Metric=1024
'''})

    def test_ip_rule_table(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routing-policy:
        - to: 10.10.10.0/24
          table: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[RoutingPolicyRule]
To=10.10.10.0/24
Table=100
'''})

    def test_ip_rule_priority(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routing-policy:
        - to: 10.10.10.0/24
          priority: 99
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[RoutingPolicyRule]
To=10.10.10.0/24
Priority=99
'''})

    def test_ip_rule_fwmark(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routing-policy:
        - from: 10.10.10.0/24
          mark: 50
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[RoutingPolicyRule]
From=10.10.10.0/24
FirewallMark=50
'''})

    def test_ip_rule_tos(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routing-policy:
        - to: 10.10.10.0/24
          type-of-service: 250
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24

[RoutingPolicyRule]
To=10.10.10.0/24
TypeOfService=250
'''})

    def test_use_routes(self):
        """[networkd] Validate config generation when use-routes DHCP override is used"""
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: true
      dhcp4-overrides:
        use-routes: false
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
UseRoutes=false
'''})

    def test_default_metric(self):
        """[networkd] Validate config generation when metric DHCP override is used"""
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: true
      dhcp6: true
      dhcp4-overrides:
        route-metric: 3333
      dhcp6-overrides:
        route-metric: 3333
    enred:
      dhcp4: true
      dhcp6: true
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=yes
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=3333
UseMTU=true
''',
                              'enred.network': '''[Match]
Name=enred

[Network]
DHCP=yes
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})


class TestNetworkManager(TestBase):

    def test_route_v4_single(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          metric: 100
          ''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
route1=10.10.10.0/24,192.168.14.20,100

[ipv6]
method=ignore
'''})

    def test_route_v4_multiple(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 8.8.0.0/16
          via: 192.168.1.1
          metric: 5000
        - to: 10.10.10.8
          via: 192.168.1.2
        - to: 11.11.11.0/24
          via: 192.168.1.3
          metric: 9999
          ''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
route1=8.8.0.0/16,192.168.1.1,5000
route2=10.10.10.8,192.168.1.2
route3=11.11.11.0/24,192.168.1.3,9999

[ipv6]
method=ignore
'''})

    def test_route_v6_single(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enblue:
      addresses: ["2001:f00f:f00f::2/64"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1''')

        self.assert_nm({'enblue': '''[connection]
id=netplan-enblue
type=ethernet
interface-name=enblue

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=manual
address1=2001:f00f:f00f::2/64
route1=2001:dead:beef::2/64,2001:beef:beef::1
'''})

    def test_route_v6_multiple(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enblue:
      addresses: ["2001:f00f:f00f::2/64"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
        - to: 2001:dead:feed::2/64
          via: 2001:beef:beef::2
          metric: 1000''')

        self.assert_nm({'enblue': '''[connection]
id=netplan-enblue
type=ethernet
interface-name=enblue

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=manual
address1=2001:f00f:f00f::2/64
route1=2001:dead:beef::2/64,2001:beef:beef::1
route2=2001:dead:feed::2/64,2001:beef:beef::2,1000
'''})

    def test_routes_mixed(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24", "2001:f00f::2/128"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
          metric: 997
        - to: 8.8.0.0/16
          via: 192.168.1.1
          metric: 5000
        - to: 10.10.10.8
          via: 192.168.1.2
        - to: 11.11.11.0/24
          via: 192.168.1.3
          metric: 9999
        - to: 2001:f00f:f00f::fe/64
          via: 2001:beef:feed::1
          ''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
route1=8.8.0.0/16,192.168.1.1,5000
route2=10.10.10.8,192.168.1.2
route3=11.11.11.0/24,192.168.1.3,9999

[ipv6]
method=manual
address1=2001:f00f::2/128
route1=2001:dead:beef::2/64,2001:beef:beef::1,997
route2=2001:f00f:f00f::fe/64,2001:beef:feed::1
'''})

    def test_route_reject_from(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      renderer: NetworkManager
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          from: 192.168.14.2
          ''', expect_fail=True)
        self.assertIn("NetworkManager does not support routes with 'from'", err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_route_reject_onlink(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      renderer: NetworkManager
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.1.20
          on-link: true
          ''', expect_fail=True)
        self.assertIn('NetworkManager does not support on-link routes', err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_route_reject_table(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      renderer: NetworkManager
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.1.20
          table: 31337
          ''', expect_fail=True)
        self.assertIn('NetworkManager does not support non-default routing tables', err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_route_reject_scope(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      renderer: NetworkManager
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.1.20
          scope: host
          ''', expect_fail=True)
        self.assertIn('NetworkManager only supports global scoped routes', err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_route_reject_type(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      renderer: NetworkManager
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.1.20
          type: blackhole
          ''', expect_fail=True)
        self.assertIn('NetworkManager only supports unicast routes', err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_use_routes_v4(self):
        """[NetworkManager] Validate config when use-routes DHCP4 override is used"""
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: true
      dhcp4-overrides:
        use-routes: false
          ''')
        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
ignore-auto-routes=true
never-default=true

[ipv6]
method=ignore
'''})

    def test_use_routes_v6(self):
        """[NetworkManager] Validate config when use-routes DHCP6 override is used"""
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: true
      dhcp6: true
      dhcp6-overrides:
        use-routes: false
          ''')
        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=auto
ignore-auto-routes=true
never-default=true
'''})

    def test_default_metric_v4(self):
        """[NetworkManager] Validate config when setting a default metric for DHCPv4"""
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: true
      dhcp6: true
      dhcp4-overrides:
        route-metric: 4000
          ''')
        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
route-metric=4000

[ipv6]
method=auto
'''})

    def test_default_metric_v6(self):
        """[NetworkManager] Validate config when setting a default metric for DHCPv6"""
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: true
      dhcp6: true
      dhcp6-overrides:
        route-metric: 5050
          ''')
        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=auto
route-metric=5050
'''})
