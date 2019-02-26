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
import sys
import re
import unittest

from .base import TestBase


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
VLAN=enred
VLAN=enblue
VLAN=engreen
''',
                              'enblue.netdev': '''[NetDev]
Name=enblue
Kind=vlan

[VLAN]
Id=1
''',
                              'engreen.netdev': '''[NetDev]
Name=engreen
Kind=vlan

[VLAN]
Id=2
''',
                              'enred.netdev': '''[NetDev]
Name=enred
MACAddress=aa:bb:cc:dd:ee:11
Kind=vlan

[VLAN]
Id=3
''',
                              'enblue.network': '''[Match]
Name=enblue

[Network]
LinkLocalAddressing=ipv6
Address=1.2.3.4/24
ConfigureWithoutCarrier=yes
''',
                              'enred.network': '''[Match]
Name=enred

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:en1,interface-name:enred,interface-name:enblue,interface-name:engreen,''')
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

[802-3-ethernet]
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

