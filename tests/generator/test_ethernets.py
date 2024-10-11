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

from .base import TestBase, ND_DHCP4, UDEV_MAC_RULE, UDEV_NO_MAC_RULE, \
    NM_MANAGED, NM_UNMANAGED, NM_MANAGED_MAC, NM_UNMANAGED_MAC, \
    NM_MANAGED_DRIVER, NM_UNMANAGED_DRIVER


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
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'eth0')
        # should not allow NM to manage everything
        self.assertFalse(os.path.exists(self.nm_enable_all_conf))

    def test_eth_lldp(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: n
      emit-lldp: true''')

        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
EmitLLDP=true
LinkLocalAddressing=ipv6
'''})

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

[Link]
MTUBytes=1280

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
        # NM cannot match by driver, so denylisting needs to happen via udev
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'lom1' + NM_UNMANAGED_DRIVER % 'ixgbe')

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nPermanentMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n',
                              'def1.network': '''[Match]
PermanentMACAddress=11:22:33:44:55:66
Name=lom1

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_networkd_udev({'def1.rules': (UDEV_MAC_RULE % ('?*', '11:22:33:44:55:66', 'lom1'))})
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'lom1' + NM_UNMANAGED_MAC % '11:22:33:44:55:66')

    # https://bugs.launchpad.net/netplan/+bug/1848474
    def test_eth_match_by_mac_infiniband(self):
        self.generate('''network:
  version: 2
  ethernets:
    ib0:
      match:
        macaddress: 11:22:33:44:55:66:77:88:99:00:11:22:33:44:55:66:77:88:99:00
      dhcp4: true
      infiniband-mode: connected''')

        self.assert_networkd({'ib0.network': '''[Match]
PermanentMACAddress=11:22:33:44:55:66:77:88:99:00:11:22:33:44:55:66:77:88:99:00

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true

[IPoIB]
Mode=connected
'''})
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED_MAC % '11:22:33:44:55:66:77:88:99:00:11:22:33:44:55:66:77:88:99:00')

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
        self.assert_nm_udev(NM_UNMANAGED_DRIVER % 'ixgbe')

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
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'green')

    def test_eth_set_mac(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'def1.network': (ND_DHCP4 % 'green')
                              .replace('[Network]', '[Link]\nMACAddress=00:01:02:03:04:05\n\n[Network]')
                              })
        self.assert_networkd_udev(None)

    def test_eth_set_mac_value_not_valid(self):
        res = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      macaddress: typorandom
      dhcp4: true''', expect_fail=True)

        self.assertIn('Invalid MAC address \'typorandom\'', res)

    def test_eth_set_mac_value_only_valid_for_network_manager(self):
        res = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      macaddress: stable
      dhcp4: true''', expect_fail=True)

        self.assertIn('networkd backend does not support the MAC address option \'stable\'', res)

    def test_eth_set_mac_special_values(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      macaddress: permanent
      dhcp4: true
    eth1:
      macaddress: random
      dhcp4: true''')

        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=off\nMACAddressPolicy=persistent\n',
                              'eth0.network': ND_DHCP4 % 'eth0',
                              'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMACAddressPolicy=random\n',
                              'eth1.network': ND_DHCP4 % 'eth1'})

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

        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'blue' + NM_UNMANAGED % 'green')

    def test_eth_match_all_names(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {name: "*"}
      dhcp4: true''')

        self.assert_networkd({'def1.network': ND_DHCP4 % '*'})
        self.assert_networkd_udev(None)
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % '*')

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
        self.assert_nm(None, '''[device-netplan.ethernets.def1]
match-device=type:ethernet
managed=0\n\n''')
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
PermanentMACAddress=00:11:22:33:44:55
Name=en1s*

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None)
        self.assert_nm_udev('SUBSYSTEM=="net", ACTION=="add|change|move", ENV{ID_NET_NAME}=="en1s*", '
                            'ATTR{address}=="00:11:22:33:44:55", ENV{NM_UNMANAGED}="1"\n')


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
        self.assert_nm_udev(NM_MANAGED % 'eth0')

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

        self.assert_networkd(None)

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0
cloned-mac-address=00:01:02:03:04:05

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

    def test_eth_set_mac_special_values(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      macaddress: preserve
      dhcp4: true
    eth1:
      macaddress: permanent
      dhcp4: true
    eth2:
      macaddress: random
      dhcp4: true
    eth3:
      macaddress: stable
      dhcp4: true''')

        self.assert_networkd(None)

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0
cloned-mac-address=preserve

[ipv4]
method=auto

[ipv6]
method=ignore
''',
                       'eth1': '''[connection]
id=netplan-eth1
type=ethernet
interface-name=eth1

[ethernet]
wake-on-lan=0
cloned-mac-address=permanent

[ipv4]
method=auto

[ipv6]
method=ignore
''',
                        'eth2': '''[connection]
id=netplan-eth2
type=ethernet
interface-name=eth2

[ethernet]
wake-on-lan=0
cloned-mac-address=random

[ipv4]
method=auto

[ipv6]
method=ignore
''',
                        'eth3': '''[connection]
id=netplan-eth3
type=ethernet
interface-name=eth3

[ethernet]
wake-on-lan=0
cloned-mac-address=stable

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

    def test_eth_set_mac_special_values_error(self):
        res = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      macaddress: preservetypo
      dhcp4: true''', expect_fail=True)

        error = ("Invalid MAC address 'preservetypo', must be XX:XX:XX:XX:XX:XX, "
                 "XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX or "
                 "one of 'permanent', 'random', 'stable', 'preserve', 'stable-ssid' (Wi-Fi only)")
        self.assertIn(error, res)

    def test_eth_set_mac_special_values_ethernet_stable_ssid(self):
        res = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      macaddress: stable-ssid
      dhcp4: true''', expect_fail=True)

        error = ("Invalid MAC address 'stable-ssid', must be XX:XX:XX:XX:XX:XX, "
                 "XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX or "
                 "one of 'permanent', 'random', 'stable', 'preserve', 'stable-ssid' (Wi-Fi only)")
        self.assertIn(error, res)

    def test_eth_match_by_driver(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        driver: ixgbe''', expect_fail=True)
        self.assertIn('NetworkManager definitions do not support matching by driver', err)

    def test_eth_match_by_drivers(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    def1:
      match:
        driver: ["bcmgenet", "smsc*"]''')
        self.assert_networkd({'def1.network': '''[Match]
Driver=bcmgenet smsc*

[Network]
LinkLocalAddressing=ipv6
'''})

    def test_eth_match_by_drivers_whitespace(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: "bcmgenet smsc*"''', expect_fail=True)
        self.assertIn('A \'driver\' glob cannot contain whitespace', err)

    def test_eth_match_by_drivers_whitespace_sequence(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ["ixgbe", "bcmgenet smsc*"]''', expect_fail=True)
        self.assertIn('A \'driver\' glob cannot contain whitespace', err)

    def test_eth_match_by_drivers_invalid_sequence(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: []''', expect_fail=True)
        self.assertIn('invalid sequence for \'driver\'', err)

    def test_eth_match_by_drivers_invalid_type(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver:
            some_mapping: true''', expect_fail=True)
        self.assertIn('invalid type for \'driver\': must be a scalar or a sequence of scalars', err)

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
        self.assert_nm_udev(NM_MANAGED % 'lom1' + NM_MANAGED_DRIVER % 'ixgbe')

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '''[Match]
PermanentMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n'''})
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
        self.assert_nm_udev(NM_MANAGED % 'lom1' + NM_MANAGED_MAC % '11:22:33:44:55:66')

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
        self.assert_nm_udev(NM_MANAGED % 'green')

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
        self.assert_nm_udev(NM_MANAGED % 'blue' + NM_MANAGED % 'green')

    def test_eth_match_name_glob(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match: {name: "en*"}
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet

[ethernet]
wake-on-lan=0

[match]
interface-name=en*;

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
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
'''}, '''[device-netplan.ethernets.def1]
match-device=type:ethernet
managed=1\n\n''')
        self.assert_nm_udev(None)
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
mac-address=00:11:22:33:44:55

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev('SUBSYSTEM=="net", ACTION=="add|change|move", ENV{ID_NET_NAME}=="engreen", '
                            'ATTR{address}=="00:11:22:33:44:55", ENV{NM_UNMANAGED}="0"\n')

    def test_offload(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1:
      receive-checksum-offload: true
      transmit-checksum-offload: off
      tcp-segmentation-offload: true
      tcp6-segmentation-offload: false
      generic-segmentation-offload: true
      generic-receive-offload: no
      large-receive-offload: true''')

        self.assert_networkd({'eth1.link': '''[Match]
OriginalName=eth1

[Link]
WakeOnLan=off
ReceiveChecksumOffload=true
TransmitChecksumOffload=false
TCPSegmentationOffload=true
TCP6SegmentationOffload=false
GenericSegmentationOffload=true
GenericReceiveOffload=false
LargeReceiveOffload=true
''',
                              'eth1.network': '''[Match]
Name=eth1

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_networkd_udev(None)

    def test_offload_invalid(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth1:
      generic-receive-offload: n
      receive-checksum-offload: true
      tcp-segmentation-offload: true
      tcp6-segmentation-offload: false
      generic-segmentation-offload: true
      transmit-checksum-offload: xx
      large-receive-offload: true''', expect_fail=True)
        self.assertIn('invalid boolean value \'xx\'', err)

    # https://bugs.launchpad.net/netplan/+bug/1848474
    def test_eth_match_by_mac_infiniband(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    ib0:
      match:
        macaddress: 11:22:33:44:55:66:77:88:99:00:11:22:33:44:55:66:77:88:99:00
      dhcp4: true
      infiniband-mode: datagram''')

        self.assert_networkd(None)
        self.assert_nm({'ib0': '''[connection]
id=netplan-ib0
type=infiniband

[infiniband]
mac-address=11:22:33:44:55:66:77:88:99:00:11:22:33:44:55:66:77:88:99:00
transport-mode=datagram

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_nm_udev(NM_MANAGED_MAC % '11:22:33:44:55:66:77:88:99:00:11:22:33:44:55:66:77:88:99:00')
