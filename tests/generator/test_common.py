#
# Common tests for netplan generator
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
import textwrap
import sys

from .base import TestBase, ND_DHCP4, ND_DHCP6, ND_DHCPYES


class TestNetworkd(TestBase):
    '''networkd output'''

    def test_optional(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true
      optional: true''')
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Link]
RequiredForOnline=no

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})
        self.assert_networkd_udev(None)

    def config_with_optional_addresses(self, eth_name, optional_addresses):
        return '''network:
  version: 2
  ethernets:
    {}:
      dhcp6: true
      optional-addresses: {}'''.format(eth_name, optional_addresses)

    def test_optional_addresses(self):
        eth_name = self.eth_name()
        self.generate(self.config_with_optional_addresses(eth_name, '["dhcp4"]'))
        self.assertEqual(self.get_optional_addresses(eth_name), set(["dhcp4"]))

    def test_optional_addresses_multiple(self):
        eth_name = self.eth_name()
        self.generate(self.config_with_optional_addresses(eth_name, '[dhcp4, ipv4-ll, ipv6-ra, dhcp6, dhcp4, static]'))
        self.assertEqual(
            self.get_optional_addresses(eth_name),
            set(["ipv4-ll", "ipv6-ra", "dhcp4", "dhcp6", "static"]))

    def test_optional_addresses_invalid(self):
        eth_name = self.eth_name()
        err = self.generate(self.config_with_optional_addresses(eth_name, '["invalid"]'), expect_fail=True)
        self.assertIn('invalid value for optional-addresses', err)

    def test_mtu_all(self):
        self.generate(textwrap.dedent("""
            network:
              version: 2
              ethernets:
                eth1:
                  mtu: 1280
                  dhcp4: n
              bonds:
                bond0:
                  interfaces:
                  - eth1
                  mtu: 9000
              vlans:
                bond0.108:
                  link: bond0
                  id: 108"""))
        self.assert_networkd({
            'bond0.108.netdev': '[NetDev]\nName=bond0.108\nKind=vlan\n\n[VLAN]\nId=108\n',
            'bond0.108.network': '''[Match]
Name=bond0.108

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
            'bond0.netdev': '[NetDev]\nName=bond0\nMTUBytes=9000\nKind=bond\n',
            'bond0.network': '''[Match]
Name=bond0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
VLAN=bond0.108
''',
            'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMTUBytes=1280\n',
            'eth1.network': '[Match]\nName=eth1\n\n[Network]\nLinkLocalAddressing=no\nBond=bond0\n'
        })
        self.assert_networkd_udev(None)

    def test_eth_global_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true''')

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_nm_udev(None)
        # should not allow NM to manage everything
        self.assertFalse(os.path.exists(self.nm_enable_all_conf))

    def test_eth_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    renderer: networkd
    eth0:
      dhcp4: true''')

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        self.assert_nm_udev(None)

    def test_eth_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    renderer: NetworkManager
    eth0:
      renderer: networkd
      dhcp4: true''')

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
        self.assert_networkd_udev(None)
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_nm_udev(None)

    def test_eth_dhcp6(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {dhcp6: true}''')
        self.assert_networkd({'eth0.network': ND_DHCP6 % 'eth0'})

    def test_eth_dhcp6_no_accept_ra(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true
      accept-ra: n''')
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6
IPv6AcceptRA=no

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_eth_dhcp6_accept_ra(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true
      accept-ra: yes''')
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6
IPv6AcceptRA=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_eth_dhcp6_accept_ra_unset(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true''')
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_eth_dhcp4_and_6(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {dhcp4: true, dhcp6: true}''')
        self.assert_networkd({'eth0.network': ND_DHCPYES % 'eth0'})

    def test_eth_manual_addresses(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24
Address=2001:FFfe::1/64
'''})

    def test_eth_manual_addresses_dhcp(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
Address=192.168.14.2/24
Address=2001:FFfe::1/64

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_dhcp_critical_true(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      critical: yes
''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
CriticalConnection=true
RouteMetric=100
UseMTU=true
'''})

    def test_dhcp_identifier_mac(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp-identifier: mac
''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
ClientIdentifier=mac
RouteMetric=100
UseMTU=true
'''})

    def test_dhcp_identifier_duid(self):
        # This option should be silently ignored, since it's the default
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp-identifier: duid
''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_eth_ipv6_privacy(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true
      ipv6-privacy: true''')
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6
IPv6PrivacyExtensions=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_gateway(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24", "2001:FFfe::1/64"]
      gateway4: 192.168.14.1
      gateway6: 2001:FFfe::2''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24
Address=2001:FFfe::1/64
Gateway=192.168.14.1
Gateway=2001:FFfe::2
'''})

    def test_nameserver(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      nameservers:
        addresses: [1.2.3.4, "1234::FFFF"]
    enblue:
      addresses: ["192.168.1.3/24"]
      nameservers:
        search: [lab, kitchen]
        addresses: [8.8.8.8]''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
Address=192.168.14.2/24
DNS=1.2.3.4
DNS=1234::FFFF
''',
                              'enblue.network': '''[Match]
Name=enblue

[Network]
LinkLocalAddressing=ipv6
Address=192.168.1.3/24
DNS=8.8.8.8
Domains=lab kitchen
'''})

    def test_link_local_all(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      link-local: [ ipv4, ipv6 ]
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=yes
LinkLocalAddressing=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_link_local_ipv4(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      link-local: [ ipv4 ]
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=yes
LinkLocalAddressing=ipv4

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_link_local_ipv6(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      link-local: [ ipv6 ]
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=yes
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_link_local_disabled(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      link-local: [ ]
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=yes
LinkLocalAddressing=no

[DHCP]
RouteMetric=100
UseMTU=true
'''})


class TestNetworkManager(TestBase):

    def test_mtu_all(self):
        self.generate(textwrap.dedent("""
            network:
              version: 2
              renderer: NetworkManager
              ethernets:
                eth1:
                  mtu: 1280
                  dhcp4: n
              bonds:
                bond0:
                  interfaces:
                  - eth1
                  mtu: 9000
              vlans:
                bond0.108:
                  link: bond0
                  id: 108"""))
        self.assert_nm({
            'bond0.108': '''[connection]
id=netplan-bond0.108
type=vlan
interface-name=bond0.108

[vlan]
id=108
parent=bond0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
            'bond0': '''[connection]
id=netplan-bond0
type=bond
interface-name=bond0

[802-3-ethernet]
mtu=9000

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
            'eth1': '''[connection]
id=netplan-eth1
type=ethernet
interface-name=eth1
slave-type=bond
master=bond0

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mtu=1280

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
        })

    def test_eth_global_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: true''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_eth_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: NetworkManager
    eth0:
      dhcp4: true''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_eth_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: networkd
    eth0:
      renderer: NetworkManager''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_global_renderer_only(self):
        self.generate(None, confs={'01-default-nm.yaml': 'network: {version: 2, renderer: NetworkManager}'})
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        # but not configure anything else
        self.assert_nm(None, None)
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_eth_dhcp6(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0: {dhcp6: true}''')
        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=auto
'''})

    def test_eth_dhcp4_and_6(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0: {dhcp4: true, dhcp6: true}''')
        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=auto
'''})

    def test_eth_manual_addresses(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses:
        - 192.168.14.2/24
        - 172.16.0.4/16
        - 2001:FFfe::1/64''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
address2=172.16.0.4/16

[ipv6]
method=manual
address1=2001:FFfe::1/64
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_eth_manual_addresses_dhcp(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: yes
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
address1=192.168.14.2/24

[ipv6]
method=manual
address1=2001:FFfe::1/64
'''})

    def test_eth_ipv6_privacy(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0: {dhcp6: true, ipv6-privacy: true}''')
        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=auto
ip6-privacy=2
'''})

    def test_gateway(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24", "2001:FFfe::1/64"]
      gateway4: 192.168.14.1
      gateway6: 2001:FFfe::2''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
gateway=192.168.14.1

[ipv6]
method=manual
address1=2001:FFfe::1/64
gateway=2001:FFfe::2
'''})

    def test_nameserver(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      nameservers:
        addresses: [1.2.3.4, 2.3.4.5, "1234::FFFF"]
        search: [lab, kitchen]
    enblue:
      addresses: ["192.168.1.3/24"]
      nameservers:
        addresses: [8.8.8.8]''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
dns=1.2.3.4;2.3.4.5;
dns-search=lab;kitchen;

[ipv6]
method=manual
dns=1234::FFFF;
dns-search=lab;kitchen;
''',
                        'enblue': '''[connection]
id=netplan-enblue
type=ethernet
interface-name=enblue

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.1.3/24
dns=8.8.8.8;

[ipv6]
method=ignore
'''})


class TestForwardDeclaration(TestBase):

    def test_fwdecl_bridge_on_bond(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: ['bond0']
      dhcp4: true
  bonds:
    bond0:
      interfaces: ['eth0', 'eth1']
  ethernets:
    eth0:
      match:
        macaddress: 00:01:02:03:04:05
      set-name: eth0
    eth1:
      match:
        macaddress: 02:01:02:03:04:05
      set-name: eth1
''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'bond0.netdev': '[NetDev]\nName=bond0\nKind=bond\n',
                              'bond0.network': '''[Match]
Name=bond0

[Network]
LinkLocalAddressing=no
ConfigureWithoutCarrier=yes
Bridge=br0
''',
                              'eth0.link': '''[Match]
MACAddress=00:01:02:03:04:05
Type=!vlan bond bridge

[Link]
Name=eth0
WakeOnLan=off
''',
                              'eth0.network': '''[Match]
MACAddress=00:01:02:03:04:05
Name=eth0
Type=!vlan bond bridge

[Network]
LinkLocalAddressing=no
Bond=bond0
''',
                              'eth1.link': '''[Match]
MACAddress=02:01:02:03:04:05
Type=!vlan bond bridge

[Link]
Name=eth1
WakeOnLan=off
''',
                              'eth1.network': '''[Match]
MACAddress=02:01:02:03:04:05
Name=eth1
Type=!vlan bond bridge

[Network]
LinkLocalAddressing=no
Bond=bond0
'''})

    def test_fwdecl_feature_blend(self):
        self.generate('''network:
  version: 2
  vlans:
    vlan1:
      link: 'br0'
      id: 1
      dhcp4: true
  bridges:
    br0:
      interfaces: ['bond0', 'eth2']
      parameters:
        path-cost:
          eth2: 1000
          bond0: 8888
  bonds:
    bond0:
      interfaces: ['eth0', 'br1']
  ethernets:
    eth0:
      match:
        macaddress: 00:01:02:03:04:05
      set-name: eth0
  bridges:
    br1:
      interfaces: ['eth1']
  ethernets:
    eth1:
      match:
        macaddress: 02:01:02:03:04:05
      set-name: eth1
    eth2:
      match:
        name: eth2
''')

        self.assert_networkd({'vlan1.netdev': '[NetDev]\nName=vlan1\nKind=vlan\n\n'
                                              '[VLAN]\nId=1\n',
                              'vlan1.network': '''[Match]
Name=vlan1

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n\n'
                                            '[Bridge]\nSTP=true\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
VLAN=vlan1
''',
                              'bond0.netdev': '[NetDev]\nName=bond0\nKind=bond\n',
                              'bond0.network': '''[Match]
Name=bond0

[Network]
LinkLocalAddressing=no
ConfigureWithoutCarrier=yes
Bridge=br0

[Bridge]
Cost=8888
''',
                              'eth2.network': '[Match]\nName=eth2\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBridge=br0\n\n'
                                              '[Bridge]\nCost=1000\n',
                              'br1.netdev': '[NetDev]\nName=br1\nKind=bridge\n',
                              'br1.network': '''[Match]
Name=br1

[Network]
LinkLocalAddressing=no
ConfigureWithoutCarrier=yes
Bond=bond0
''',
                              'eth0.link': '''[Match]
MACAddress=00:01:02:03:04:05
Type=!vlan bond bridge

[Link]
Name=eth0
WakeOnLan=off
''',
                              'eth0.network': '''[Match]
MACAddress=00:01:02:03:04:05
Name=eth0
Type=!vlan bond bridge

[Network]
LinkLocalAddressing=no
Bond=bond0
''',
                              'eth1.link': '''[Match]
MACAddress=02:01:02:03:04:05
Type=!vlan bond bridge

[Link]
Name=eth1
WakeOnLan=off
''',
                              'eth1.network': '''[Match]
MACAddress=02:01:02:03:04:05
Name=eth1
Type=!vlan bond bridge

[Network]
LinkLocalAddressing=no
Bridge=br1
'''})


class TestMerging(TestBase):
    '''multiple *.yaml merging'''

    def test_global_backend(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: y''',
                      confs={'backend': 'network:\n  renderer: networkd'})

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:engreen,''')
        self.assert_nm_udev(None)

    def test_add_def(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: true''',
                      confs={'blue': '''network:
  version: 2
  ethernets:
    enblue:
      dhcp4: true'''})

        self.assert_networkd({'enblue.network': ND_DHCP4 % 'enblue',
                              'engreen.network': ND_DHCP4 % 'engreen'})
        # Skip on codecov.io; GLib changed hashtable elements ordering between
        # releases, so we can't depend on the exact order.
        # TODO: (cyphermox) turn this into an "assert_in_nm()" function.
        if "CODECOV_TOKEN" not in os.environ:  # pragma: nocover
            self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:engreen,interface-name:enblue,''')
        self.assert_nm_udev(None)

    def test_change_def(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      wakeonlan: true
      dhcp4: false''',
                      confs={'green-dhcp': '''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: true'''})

        self.assert_networkd({'engreen.link': '[Match]\nOriginalName=engreen\n\n[Link]\nWakeOnLan=magic\n',
                              'engreen.network': ND_DHCP4 % 'engreen'})

    def test_cleanup_old_config(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}
    enyellow: {renderer: NetworkManager}''',
                      confs={'blue': '''network:
  version: 2
  ethernets:
    enblue:
      dhcp4: true'''})

        os.unlink(os.path.join(self.confdir, 'blue.yaml'))
        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}''')

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:engreen,''')
        self.assert_nm_udev(None)

    def test_ref(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute''',
                      confs={'bridges': '''network:
  version: 2
  bridges:
    br0:
      interfaces: [eno1, switchports]
      dhcp4: true'''})

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
''',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nLinkLocalAddressing=no\nBridge=br0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nLinkLocalAddressing=no\nBridge=br0\n'})

    def test_def_in_run(self):
        rundir = os.path.join(self.workdir.name, 'run', 'netplan')
        os.makedirs(rundir)
        # override b.yaml definition for enred
        with open(os.path.join(rundir, 'b.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enred: {dhcp4: true}}''')

        # append new definition for enblue
        with open(os.path.join(rundir, 'c.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enblue: {dhcp4: true}}''')

        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}''', confs={'b': '''network:
  version: 2
  ethernets: {enred: {wakeonlan: true}}'''})

        # b.yaml in /run/ should completely shadow b.yaml in /etc, thus no enred.link
        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen',
                              'enred.network': ND_DHCP4 % 'enred',
                              'enblue.network': ND_DHCP4 % 'enblue'})

    def test_def_in_lib(self):
        libdir = os.path.join(self.workdir.name, 'lib', 'netplan')
        rundir = os.path.join(self.workdir.name, 'run', 'netplan')
        os.makedirs(libdir)
        os.makedirs(rundir)
        # b.yaml is in /etc/netplan too which should have precedence
        with open(os.path.join(libdir, 'b.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {notme: {dhcp4: true}}''')

        # /run should trump /lib too
        with open(os.path.join(libdir, 'c.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {alsonot: {dhcp4: true}}''')
        with open(os.path.join(rundir, 'c.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enyellow: {dhcp4: true}}''')

        # this should be considered
        with open(os.path.join(libdir, 'd.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enblue: {dhcp4: true}}''')

        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}''', confs={'b': '''network:
  version: 2
  ethernets: {enred: {wakeonlan: true}}'''})

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen',
                              'enred.link': '[Match]\nOriginalName=enred\n\n[Link]\nWakeOnLan=magic\n',
                              'enred.network': '''[Match]
Name=enred

[Network]
LinkLocalAddressing=ipv6
''',
                              'enyellow.network': ND_DHCP4 % 'enyellow',
                              'enblue.network': ND_DHCP4 % 'enblue'})

