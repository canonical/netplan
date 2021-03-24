#
# Tests for VLAN devices config generated via netplan
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
import re
import unittest

from .base import TestBase, ND_VLAN, ND_EMPTY, ND_WITHIP, ND_DHCP6_WOCARRIER


class TestNetworkd(TestBase):

    @unittest.skipIf("CODECOV_TOKEN" in os.environ, "Skipping on codecov.io: GLib changed hashtable elements order")
    def test_vlan(self):  # pragma: nocover
        self.generate('''network:
  version: 2
  ethernets:
    en1: {}
  vlans:
    enblue:
      id: 1
      link: en1
      addresses: [1.2.3.4/24]
    enred:
      id: 3
      link: en1
      macaddress: aa:bb:cc:dd:ee:11
    engreen: {id: 2, link: en1, dhcp6: true}''')

        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
VLAN=enblue
VLAN=enred
VLAN=engreen
''',
                              'enblue.netdev': ND_VLAN % ('enblue', 1),
                              'engreen.netdev': ND_VLAN % ('engreen', 2),
                              'enred.netdev': '''[NetDev]
Name=enred
MACAddress=aa:bb:cc:dd:ee:11
Kind=vlan

[VLAN]
Id=3
''',
                              'enblue.network': ND_WITHIP % ('enblue', '1.2.3.4/24'),
                              'enred.network': (ND_EMPTY % ('enred', 'ipv6'))
                              .replace('[Network]', '[Link]\nMACAddress=aa:bb:cc:dd:ee:11\n\n[Network]'),
                              'engreen.network': (ND_DHCP6_WOCARRIER % 'engreen')})

        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:en1,interface-name:enblue,interface-name:enred,interface-name:engreen,''')
        self.assert_nm_udev(None)

    def test_vlan_sriov(self):
        # we need to make sure renderer: sriov vlans are not saved as part of
        # the NM/networkd config
        self.generate('''network:
  version: 2
  ethernets:
    en1: {}
  vlans:
    enblue:
      id: 1
      link: en1
      renderer: sriov
    engreen: {id: 2, link: en1, dhcp6: true}''')

        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
VLAN=engreen
''',
                              'engreen.netdev': ND_VLAN % ('engreen', 2),
                              'engreen.network': (ND_DHCP6_WOCARRIER % 'engreen')})

        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:en1,interface-name:enblue,interface-name:engreen,''')
        self.assert_nm_udev(None)

    # see LP: #1888726
    def test_vlan_parent_match(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    lan:
      match: {macaddress: "11:22:33:44:55:66"}
      set-name: lan
      mtu: 9000
  vlans:
    vlan20: {id: 20, link: lan}''')

        self.assert_networkd({'lan.network': '''[Match]
MACAddress=11:22:33:44:55:66
Name=lan
Type=!vlan bond bridge

[Link]
MTUBytes=9000

[Network]
LinkLocalAddressing=ipv6
VLAN=vlan20
''',
                              'lan.link': '''[Match]
MACAddress=11:22:33:44:55:66
Type=!vlan bond bridge

[Link]
Name=lan
WakeOnLan=off
MTUBytes=9000
''',
                              'vlan20.network': ND_EMPTY % ('vlan20', 'ipv6'),
                              'vlan20.netdev': ND_VLAN % ('vlan20', 20)})

        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=mac:11:22:33:44:55:66,interface-name:lan,interface-name:vlan20,''')
        self.assert_nm_udev(None)


class TestNetworkManager(TestBase):

    def test_vlan(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    en1: {}
  vlans:
    enblue:
      id: 1
      link: en1
      addresses: [1.2.3.4/24]
    engreen: {id: 2, link: en1, dhcp6: true}''')

        self.assert_networkd({})
        self.assert_nm({'en1': '''[connection]
id=netplan-en1
type=ethernet
interface-name=en1

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'enblue': '''[connection]
id=netplan-enblue
type=vlan
interface-name=enblue

[vlan]
id=1
parent=en1

[ipv4]
method=manual
address1=1.2.3.4/24

[ipv6]
method=ignore
''',
                        'engreen': '''[connection]
id=netplan-engreen
type=vlan
interface-name=engreen

[vlan]
id=2
parent=en1

[ipv4]
method=link-local

[ipv6]
method=auto
'''})
        self.assert_nm_udev(None)

    def test_vlan_parent_match(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    en-v:
      match: {macaddress: "11:22:33:44:55:66"}
  vlans:
    engreen: {id: 2, link: en-v, dhcp4: true}''')

        self.assert_networkd({})

        # get assigned UUID  from en-v connection
        with open(os.path.join(self.workdir.name, 'run/NetworkManager/system-connections/netplan-en-v.nmconnection')) as f:
            m = re.search('uuid=([0-9a-fA-F-]{36})\n', f.read())
            self.assertTrue(m)
            uuid = m.group(1)
            self.assertNotEquals(uuid, "00000000-0000-0000-0000-000000000000")

        self.assert_nm({'en-v': '''[connection]
id=netplan-en-v
type=ethernet
uuid=%s

[ethernet]
wake-on-lan=0
mac-address=11:22:33:44:55:66

[ipv4]
method=link-local

[ipv6]
method=ignore
''' % uuid,
                        'engreen': '''[connection]
id=netplan-engreen
type=vlan
interface-name=engreen

[vlan]
id=2
parent=%s

[ipv4]
method=auto

[ipv6]
method=ignore
''' % uuid})
        self.assert_nm_udev(None)

    def test_vlan_sriov(self):
        # we need to make sure renderer: sriov vlans are not saved as part of
        # the NM/networkd config
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    en1: {}
  vlans:
    enblue:
      id: 1
      link: en1
      addresses: [1.2.3.4/24]
      renderer: sriov
    engreen: {id: 2, link: en1, dhcp6: true}''')

        self.assert_networkd({})
        self.assert_nm({'en1': '''[connection]
id=netplan-en1
type=ethernet
interface-name=en1

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'engreen': '''[connection]
id=netplan-engreen
type=vlan
interface-name=engreen

[vlan]
id=2
parent=en1

[ipv4]
method=link-local

[ipv6]
method=auto
'''})
        self.assert_nm_udev(None)
