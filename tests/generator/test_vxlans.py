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


from .base import TestBase


class TestNetworkd(TestBase):

    def test_vxlan_set_bridge(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      bridge: br1005
      neigh-suppress: false
      vni: 1005''')
        self.assert_networkd({
          'vxlan1005.network':
          '[Match]\nName=vxlan1005\n\n[Network]\nLinkLocalAddressing=ipv6\nConfigureWithoutCarrier=yes\nBridge=br1005\n',
          'vxlan1005.netdev':
          '[NetDev]\nName=vxlan1005\nKind=vxlan\n\n[VXLAN]\nVNI=1005'})

    def test_vxlan_destinaton_port(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      vni: 1005
      neigh-suppress: false''')
        self.assert_networkd({'vxlan1005.network': '''[Match]
Name=vxlan1005

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'vxlan1005.netdev': '[NetDev]\nName=vxlan1005\nKind=vxlan\n\n[VXLAN]\nVNI=1005'})

    def test_vxlan_empty(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      vni: 1005
      neigh-suppress: false''')

        self.assert_networkd({'vxlan1005.netdev': '[NetDev]\nName=vxlan1005\nKind=vxlan\n\n[VXLAN]\nVNI=1005',
                              'vxlan1005.network': '''[Match]
Name=vxlan1005

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
'''})


class TestNetplanYAMLv2(TestBase):
    '''No asserts are needed.

    The generate() method implicitly checks the (re-)generated YAML.
    '''

    def test_neigh_suppress(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      vni: 1005
      neigh-suppress: true''')


class TestConfigErrors(TestBase):

    def test_vxlan_missing_vni(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      neigh-suppress: true''', expect_fail=True)

    def test_vxlan_oob_vni(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      vni: 9999999999999999''', expect_fail=True)

    def test_vxlan_oob_ttl(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      vni: 1005
      parameters:
        ttl: 500''', expect_fail=True)

    def test_vxlan_oob_flow_label(self):
        self.generate('''network:
  version: 2
  vxlans:
    vxlan1005:
      vni: 1005
      parameters:
        flow_label: 9999999999''', expect_fail=True)
