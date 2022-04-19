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

    def test_vrf_set_table(self):
        self.generate('''network:
  version: 2
  vrfs:
    vrf1005:
      table: 1005''')

        self.assert_networkd({'vrf1005.network': '''[Match]
Name=vrf1005

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'vrf1005.netdev': '''[NetDev]
Name=vrf1005
Kind=vrf

[VRF]
Table=1005
'''})


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


class TestConfigErrors(TestBase):

    def test_vrf_missing_table(self):
        self.generate('''network:
  version: 2
  vrfs:
    vrf1005:''', expect_fail=True)
