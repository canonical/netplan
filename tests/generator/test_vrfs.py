#
# Tests for bridge devices config generated via netplan
#
# Copyright (C) 2018 Canonical, Ltd.
# Copyright (C) 2022 Datto, Inc.
# Author: Anthony Timmins <atimmins@datto.com>
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


from .base import TestBase, ND_EMPTY, ND_DHCP, ND_VRF


class NetworkManager(TestBase):

    def test_vrf_set_table(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0: { dhcp4: true }
  vrfs:
    vrf1005:
      table: 1005
      interfaces: [eth0]
      routes:
      - to: default
        via: 1.2.3.4
      routing-policy:
      - from: 2.3.4.5''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0
slave-type=vrf
master=vrf1005

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
''',
                        'vrf1005': '''[connection]
id=netplan-vrf1005
type=vrf
interface-name=vrf1005

[vrf]
table=1005

[ipv4]
route1=0.0.0.0/0,1.2.3.4
route1_options=table=1005
method=link-local

[ipv6]
method=ignore
'''})


class TestNetworkd(TestBase):

    def test_vrf_set_table(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: { dhcp4: true }
  vrfs:
    vrf1005:
      table: 1005
      interfaces: [eth0]
      routes:
      - to: default
        via: 1.2.3.4
      routing-policy:
      - from: 2.3.4.5''')

        self.assert_networkd({'eth0.network': ND_DHCP % ('eth0', 'ipv4', '\nVRF=vrf1005', 'true'),
                              'vrf1005.network': ND_EMPTY % ('vrf1005', 'ipv6') + '''
[Route]
Destination=0.0.0.0/0
Gateway=1.2.3.4
Table=1005

[RoutingPolicyRule]
From=2.3.4.5
Table=1005
''',
                              'vrf1005.netdev': ND_VRF % ('vrf1005', 1005)})


class TestNetplanYAMLv2(TestBase):
    '''No asserts are needed.

    The generate() method implicitly checks the (re-)generated YAML.
    '''

    def test_vrf_table(self):
        self.generate('''network:
  version: 2
  vrfs:
    vrf1005:
      table: 1005''')

    def test_vrf_routes(self):
        self.generate('''network:
  version: 2
  vrfs:
    vrf1005:
      table: 1005
      routes:
      - to: default
        via: 1.2.3.4
      routing-policy:
      - from: 1.2.3.4''')


class TestConfigErrors(TestBase):

    def test_vrf_missing_table(self):
        err = self.generate('''network:
  version: 2
  vrfs:
    vrf1005: {}''', expect_fail=True)

        self.assertIn("vrf1005: missing 'table' property", err)

    def test_vrf_already_assigned(self):
        err = self.generate('''network:
  version: 2
  vrfs:
    vrf0:
      table: 42
      interfaces: [eno1]
    vrf1:
      table: 43
      interfaces: [eno1]
  ethernets:
    eno1: {}''', expect_fail=True)
        self.assertIn("vrf1: interface 'eno1' is already assigned to vrf vrf0", err)

    def test_vrf_routes_table_mismatch(self):
        err = self.generate('''network:
  version: 2
  vrfs:
    vrf0:
      table: 42
      routes:
      - table: 42 # pass
        to: default
        via: 1.2.3.4
      - table: 43 # mismatch
        to: 99.88.77.66
        via: 2.3.4.5
''', expect_fail=True)
        self.assertIn("vrf0: VRF routes table mismatch (42 != 43)", err)

    def test_vrf_policy_table_mismatch(self):
        err = self.generate('''network:
  version: 2
  vrfs:
    vrf0:
      table: 45
      routes:
      - to: default
        via: 3.4.5.6
      routing-policy:
      - table: 45 # pass
        from: 1.2.3.4
      - table: 46 # mismatch
        from: 2.3.4.5
''', expect_fail=True)
        self.assertIn("vrf0: VRF routing-policy table mismatch (45 != 46)", err)
