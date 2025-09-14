#
# Tests for XFRM interface config generation
#
# Copyright (C) 2024 Canonical, Ltd.
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


class TestNetworkdXfrm(TestBase):

    def test_xfrm_basic(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true
  xfrm-interfaces:
    xfrm0:
      if_id: 42
      link: eth0
      addresses: [192.168.1.10/24]''')

        self.assert_networkd({'xfrm0.netdev': '''[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=42
''',
                              'xfrm0.network': '''[Match]
Name=xfrm0

[Network]
LinkLocalAddressing=no
Address=192.168.1.10/24
'''})

    def test_xfrm_independent(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  xfrm-interfaces:
    xfrm0:
      if_id: 100
      independent: true''')

        self.assert_networkd({'xfrm0.netdev': '''[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=100
Independent=true
'''})


class TestNetworkManagerXfrm(TestBase):

    def test_xfrm_nm_not_supported(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  xfrm-interfaces:
    xfrm0:
      if_id: 42
      independent: true''', expect_fail=True)

        self.assertIn('XFRM interfaces are not supported by NetworkManager', err)

    def test_xfrm_hex_dec_different_values(self):
        self.generate('''network:
  version: 2
  xfrm-interfaces:
    xfrm0:
      if_id: 42
      independent: true
    xfrm1:
      if_id: 0x2B
      independent: true''')

        # Verify both interfaces are generated with correct if_id values
        self.assert_networkd({'xfrm0.netdev': '''[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=42
Independent=true
''',
                             'xfrm1.netdev': '''[NetDev]
Name=xfrm1
Kind=xfrm

[Xfrm]
InterfaceId=43
Independent=true
'''})
