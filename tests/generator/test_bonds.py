#
# Tests for bond devices config generated via netplan
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

from .base import TestBase


class TestNetworkd(TestBase):

    def test_bond_dhcp6_no_accept_ra(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: no
      accept-ra: no
  bonds:
    bond0:
      interfaces: [engreen]
      dhcp6: true
      accept-ra: yes''')
        self.assert_networkd({'bond0.network': '''[Match]
Name=bond0

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6
IPv6AcceptRA=yes
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'bond0.netdev': '''[NetDev]
Name=bond0
Kind=bond
''',
                              'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=no
IPv6AcceptRA=no
Bond=bond0
'''})

    def test_bond_empty(self):
        self.generate('''network:
  version: 2
  bonds:
    bn0:
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:bn0,''')
        self.assert_nm_udev(None)

    def test_bond_components(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBond=bn0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBond=bn0\n'})

    def test_bond_empty_parameters(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters: {}
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBond=bn0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBond=bn0\n'})

    def test_bond_with_parameters(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters:
        mode: 802.1ad
        lacp-rate: 10
        mii-monitor-interval: 10
        min-links: 10
        up-delay: 20
        down-delay: 30
        all-slaves-active: true
        transmit-hash-policy: none
        ad-select: none
        arp-interval: 15
        arp-validate: all
        arp-all-targets: all
        fail-over-mac-policy: none
        gratuitious-arp: 10
        packets-per-slave: 10
        primary-reselect-policy: none
        resend-igmp: 10
        learn-packet-interval: 10
        arp-ip-targets:
          - 10.10.10.10
          - 20.20.20.20
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n\n'
                                            '[Bond]\n'
                                            'Mode=802.1ad\n'
                                            'LACPTransmitRate=10\n'
                                            'MIIMonitorSec=10ms\n'
                                            'MinLinks=10\n'
                                            'TransmitHashPolicy=none\n'
                                            'AdSelect=none\n'
                                            'AllSlavesActive=1\n'
                                            'ARPIntervalSec=15ms\n'
                                            'ARPIPTargets=10.10.10.10,20.20.20.20\n'
                                            'ARPValidate=all\n'
                                            'ARPAllTargets=all\n'
                                            'UpDelaySec=20ms\n'
                                            'DownDelaySec=30ms\n'
                                            'FailOverMACPolicy=none\n'
                                            'GratuitousARP=10\n'
                                            'PacketsPerSlave=10\n'
                                            'PrimaryReselectPolicy=none\n'
                                            'ResendIGMP=10\n'
                                            'LearnPacketIntervalSec=10\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBond=bn0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBond=bn0\n'})

    def test_bond_with_parameters_all_suffix(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters:
        mode: 802.1ad
        mii-monitor-interval: 10ms
        up-delay: 20ms
        down-delay: 30s
        arp-interval: 15m
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n\n'
                                            '[Bond]\n'
                                            'Mode=802.1ad\n'
                                            'MIIMonitorSec=10ms\n'
                                            'ARPIntervalSec=15m\n'
                                            'UpDelaySec=20ms\n'
                                            'DownDelaySec=30s\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBond=bn0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBond=bn0\n'})

    def test_bond_primary_slave(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters:
        mode: active-backup
        primary: eno1
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n\n'
                                            '[Bond]\n'
                                            'Mode=active-backup\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBond=bn0\nPrimarySlave=true\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBond=bn0\n'})

    def test_bond_with_gratuitous_spelling(self):
        """Validate that the correct spelling of gratuitous also works"""
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters:
        mode: active-backup
        gratuitous-arp: 10
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n\n'
                                            '[Bond]\n'
                                            'Mode=active-backup\n'
                                            'GratuitousARP=10\n',
                              'bn0.network': '''[Match]
Name=bn0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBond=bn0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBond=bn0\n'})


class TestNetworkManager(TestBase):

    def test_bond_empty(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bonds:
    bn0:
      dhcp4: true''')

        self.assert_nm({'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

    def test_bond_components(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_bond_empty_params(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      parameters: {}
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_bond_with_params(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      parameters:
        mode: 802.1ad
        lacp-rate: 10
        mii-monitor-interval: 10
        min-links: 10
        up-delay: 10
        down-delay: 10
        all-slaves-active: true
        transmit-hash-policy: none
        ad-select: none
        arp-interval: 10
        arp-validate: all
        arp-all-targets: all
        arp-ip-targets:
          - 10.10.10.10
          - 20.20.20.20
        fail-over-mac-policy: none
        gratuitious-arp: 10
        packets-per-slave: 10
        primary-reselect-policy: none
        resend-igmp: 10
        learn-packet-interval: 10
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[bond]
mode=802.1ad
lacp_rate=10
miimon=10
min_links=10
xmit_hash_policy=none
ad_select=none
all_slaves_active=1
arp_interval=10
arp_ip_target=10.10.10.10,20.20.20.20
arp_validate=all
arp_all_targets=all
updelay=10
downdelay=10
fail_over_mac=none
num_grat_arp=10
num_unsol_na=10
packets_per_slave=10
primary_reselect=none
resend_igmp=10
lp_interval=10

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_bond_primary_slave(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      parameters:
        mode: active-backup
        primary: eno1
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[bond]
mode=active-backup
primary=eno1

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)


class TestConfigErrors(TestBase):

    def test_bond_invalid_arp_target(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bonds:
    bond0:
      interfaces: [eno1]
      parameters:
        arp-ip-targets:
          - 2001:dead:beef::1
      dhcp4: true''', expect_fail=True)

    def test_bond_invalid_primary_slave(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bonds:
    bond0:
      interfaces: [eno1]
      parameters:
        primary: wigglewiggle
      dhcp4: true''', expect_fail=True)

    def test_bond_duplicate_primary_slave(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
    eno2:
      match:
        name: eth1
  bonds:
    bond0:
      interfaces: [eno1, eno2]
      parameters:
        primary: eno1
        primary: eno2
      dhcp4: true''', expect_fail=True)

    def test_bond_multiple_assignments(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bonds:
    bond0:
      interfaces: [eno1]
    bond1:
      interfaces: [eno1]''', expect_fail=True)
        self.assertIn("bond1: interface 'eno1' is already assigned to bond bond0", err)

    def test_bond_bridge_cross_assignments1(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bonds:
    bond0:
      interfaces: [eno1]
  bridges:
    br1:
      interfaces: [eno1]''', expect_fail=True)
        self.assertIn("br1: interface 'eno1' is already assigned to bond bond0", err)

    def test_bond_bridge_cross_assignments2(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bridges:
    br0:
      interfaces: [eno1]
  bonds:
    bond1:
      interfaces: [eno1]''', expect_fail=True)
        self.assertIn("bond1: interface 'eno1' is already assigned to bridge br0", err)

    def test_bond_bridge_nested_assignments(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bonds:
    bond0:
      interfaces: [eno1]
  bridges:
    br1:
      interfaces: [bond0]''')
