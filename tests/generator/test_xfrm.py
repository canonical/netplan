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

from .base import ND_DHCP4, TestBase


class TestNetworkdXfrm(TestBase):

    def test_xfrm(self):
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

        expected_eth0 = (ND_DHCP4 % 'eth0').replace('LinkLocalAddressing=ipv6\n', 'LinkLocalAddressing=ipv6\nXfrm=xfrm0\n')

        self.assert_networkd({'eth0.network': expected_eth0,
                              'xfrm0.netdev': '''[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=42
Parent=eth0
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

    def test_xfrm_parent_with_set_name(self):
        """Test XFRM interface with parent that has set-name, Parent= should use actual interface name"""
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    myeth:
      match: {macaddress: "00:11:22:33:44:55"}
      set-name: eth0
  xfrm-interfaces:
    xfrm0: {if_id: 42, link: myeth}''')

        # Parent= should use set-name (eth0), not netplan ID (myeth)
        self.assert_networkd({'myeth.link': '''[Match]
PermanentMACAddress=00:11:22:33:44:55

[Link]
Name=eth0
WakeOnLan=off
''',
                              'myeth.network': '''[Match]
PermanentMACAddress=00:11:22:33:44:55
Name=eth0

[Network]
LinkLocalAddressing=ipv6
Xfrm=xfrm0
''',
                              'xfrm0.netdev': '''[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=42
Parent=eth0
'''})

    def test_xfrm_parent_with_match_no_set_name(self):
        """Test XFRM interface with parent using match but no set-name, Parent= should use matched name"""
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    myeth:
      match: {name: eth0}
  xfrm-interfaces:
    xfrm0: {if_id: 42, link: myeth}''')

        # Parent= should use match.original_name (eth0), not netplan ID (myeth)
        self.assert_networkd({'myeth.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
Xfrm=xfrm0
''',
                              'xfrm0.netdev': '''[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=42
Parent=eth0
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
