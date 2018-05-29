#
# Tests for ethernet devices config generated via netplan
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

from .base import TestBase, ND_DHCP4, ND_DHCP6, ND_DHCPYES, UDEV_MAC_RULE, UDEV_NO_MAC_RULE


class TestNetworkd(TestBase):

    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      wakeonlan: true
      dhcp4: n''')

        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=magic\n',
                              'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_networkd_udev(None)
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_nm_udev(None)
        # should not allow NM to manage everything
        self.assertFalse(os.path.exists(self.nm_enable_all_conf))

    def test_eth_mtu(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1:
      mtu: 1280
      dhcp4: n''')

        self.assert_networkd({'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMTUBytes=1280\n',
                              'eth1.network': '''[Match]
Name=eth1

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_networkd_udev(None)

    def test_eth_match_by_driver_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ixgbe
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nDriver=ixgbe\n\n[Link]\nName=lom1\nWakeOnLan=off\n',
                              'def1.network': '''[Match]
Driver=ixgbe
Name=lom1

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_networkd_udev({'def1.rules': (UDEV_NO_MAC_RULE % ('ixgbe', 'lom1'))})
        # NM cannot match by driver, so blacklisting needs to happen via udev
        self.assert_nm(None, None)
        self.assert_nm_udev('ACTION=="add|change", SUBSYSTEM=="net", ENV{ID_NET_DRIVER}=="ixgbe", ENV{NM_UNMANAGED}="1"\n')

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n',
                              'def1.network': '''[Match]
MACAddress=11:22:33:44:55:66
Name=lom1

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_networkd_udev({'def1.rules': (UDEV_MAC_RULE % ('?*', '11:22:33:44:55:66', 'lom1'))})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=mac:11:22:33:44:55:66,''')
        self.assert_nm_udev(None)

    def test_eth_implicit_name_match_dhcp4(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: y''')

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})
        self.assert_networkd_udev(None)

    def test_eth_match_dhcp4(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ixgbe
      dhcp4: true''')

        self.assert_networkd({'def1.network': '''[Match]
Driver=ixgbe

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_networkd_udev(None)
        self.assert_nm_udev('ACTION=="add|change", SUBSYSTEM=="net", ENV{ID_NET_DRIVER}=="ixgbe", ENV{NM_UNMANAGED}="1"\n')

    def test_eth_match_name(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      dhcp4: true''')

        self.assert_networkd({'def1.network': ND_DHCP4 % 'green'})
        self.assert_networkd_udev(None)
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:green,''')
        self.assert_nm_udev(None)

    def test_eth_set_mac(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'def1.network': ND_DHCP4 % 'green',
                              'def1.link': '[Match]\nOriginalName=green\n\n[Link]\nWakeOnLan=off\nMACAddress=00:01:02:03:04:05\n'
                              })
        self.assert_networkd_udev(None)

    def test_eth_match_name_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      set-name: blue
      dhcp4: true''')

        # the .network needs to match on the renamed name
        self.assert_networkd({'def1.link': '[Match]\nOriginalName=green\n\n[Link]\nName=blue\nWakeOnLan=off\n',
                              'def1.network': ND_DHCP4 % 'blue'})

        # The udev rules engine does support renaming by name
        self.assert_networkd_udev(None)

        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:blue,''')

    def test_eth_match_all_names(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {name: "*"}
      dhcp4: true''')

        self.assert_networkd({'def1.network': ND_DHCP4 % '*'})
        self.assert_networkd_udev(None)
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:*,''')
        self.assert_nm_udev(None)

    def test_eth_match_all(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {}
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\n\n[Network]\nDHCP=ipv4\nLinkLocalAddressing=ipv6\n\n'
                                              '[DHCP]\nRouteMetric=100\nUseMTU=true\n'})
        self.assert_networkd_udev(None)
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=type:ethernet,''')
        self.assert_nm_udev(None)

    def test_match_multiple(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: en1s*
        macaddress: 00:11:22:33:44:55
      dhcp4: on''')
        self.assert_networkd({'def1.network': '''[Match]
MACAddress=00:11:22:33:44:55
Name=en1s*

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=mac:00:11:22:33:44:55,''')


class TestNetworkManager(TestBase):

    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      wakeonlan: true''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=1

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=magic\n'})
        self.assert_nm_udev(None)

    def test_eth_mtu(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth1:
      mtu: 1280
      dhcp4: n''')

        self.assert_networkd({'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMTUBytes=1280\n'})
        self.assert_nm({'eth1': '''[connection]
id=netplan-eth1
type=ethernet
interface-name=eth1

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mtu=1280

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})

    def test_eth_set_mac(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'eth0.link': '''[Match]
OriginalName=eth0

[Link]
WakeOnLan=off
MACAddress=00:01:02:03:04:05
'''})

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[802-3-ethernet]
cloned-mac-address=00:01:02:03:04:05

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

    def test_eth_match_by_driver(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        driver: ixgbe''', expect_fail=True)
        self.assertIn('NetworkManager definitions do not support matching by driver', err)

    def test_eth_match_by_driver_rename(self):
        # in this case udev will rename the device so that NM can use the name
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        driver: ixgbe
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nDriver=ixgbe\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})
        self.assert_networkd_udev({'def1.rules': (UDEV_NO_MAC_RULE % ('ixgbe', 'lom1'))})
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=lom1

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_nm_udev(None)

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})
        self.assert_networkd_udev({'def1.rules': (UDEV_MAC_RULE % ('?*', '11:22:33:44:55:66', 'lom1'))})
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=lom1

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_nm_udev(None)

    def test_eth_implicit_name_match_dhcp4(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: true''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})

    def test_eth_match_mac_dhcp4(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mac-address=11:22:33:44:55:66

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})

    def test_eth_match_name(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        name: green
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=green

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_eth_match_name_rename(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        name: green
      set-name: blue
      dhcp4: true''')

        # The udev rules engine does support renaming by name
        self.assert_networkd_udev(None)

        # NM needs to match on the renamed name
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=blue

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        # ... while udev renames it
        self.assert_networkd({'def1.link': '[Match]\nOriginalName=green\n\n[Link]\nName=blue\nWakeOnLan=off\n'})
        self.assert_nm_udev(None)

    def test_eth_match_name_glob(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match: {name: "en*"}
      dhcp4: true''', expect_fail=True)
        self.assertIn('def1: NetworkManager definitions do not support name globbing', err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_eth_match_all(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match: {}
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})

    def test_match_multiple(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        name: engreen
        macaddress: 00:11:22:33:44:55
      dhcp4: yes''')
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mac-address=00:11:22:33:44:55

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

