#!/usr/bin/python3
# Closed-box tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2022 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
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

import io
import unittest
import yaml

from contextlib import redirect_stdout
from unittest.mock import patch
from netplan_cli.cli.commands.status import NetplanStatus
from netplan_cli.cli.state import Interface, SystemConfigState
from tests.test_utils import call_cli


IPROUTE2 = '[{"ifindex":1,"ifname":"lo","flags":["LOOPBACK","UP","LOWER_UP"],"mtu":65536,"qdisc":"noqueue","operstate":"UNKNOWN","group":"default","txqlen":1000,"link_type":"loopback","address":"00:00:00:00:00:00","broadcast":"00:00:00:00:00:00","promiscuity":0,"min_mtu":0,"max_mtu":0,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8,"scope":"host","label":"lo","valid_life_time":4294967295,"preferred_life_time":4294967295},{"family":"inet6","local":"::1","prefixlen":128,"scope":"host","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":2,"ifname":"enp0s31f6","flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],"mtu":1500,"qdisc":"fq_codel","operstate":"UP","group":"default","txqlen":1000,"link_type":"ether","address":"54:e1:ad:5f:24:b4","broadcast":"ff:ff:ff:ff:ff:ff","promiscuity":0,"min_mtu":68,"max_mtu":9000,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"parentbus":"pci","parentdev":"0000:00:1f.6","addr_info":[{"family":"inet","local":"192.168.178.62","prefixlen":24,"metric":100,"broadcast":"192.168.178.255","scope":"global","dynamic":true,"label":"enp0s31f6","valid_life_time":850698,"preferred_life_time":850698},{"family":"inet6","local":"2001:9e8:a19f:1c00:56e1:adff:fe5f:24b4","prefixlen":64,"scope":"global","dynamic":true,"mngtmpaddr":true,"noprefixroute":true,"valid_life_time":6821,"preferred_life_time":3221},{"family":"inet6","local":"fe80::56e1:adff:fe5f:24b4","prefixlen":64,"scope":"link","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":5,"ifname":"wlan0","flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],"mtu":1500,"qdisc":"noqueue","operstate":"UP","group":"default","txqlen":1000,"link_type":"ether","address":"1c:4d:70:e4:e4:0e","broadcast":"ff:ff:ff:ff:ff:ff","promiscuity":0,"min_mtu":256,"max_mtu":2304,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"parentbus":"pci","parentdev":"0000:04:00.0","addr_info":[{"family":"inet","local":"192.168.178.142","prefixlen":24,"broadcast":"192.168.178.255","scope":"global","dynamic":true,"noprefixroute":true,"label":"wlan0","valid_life_time":850700,"preferred_life_time":850700},{"family":"inet6","local":"2001:9e8:a19f:1c00:7011:2d1:951:ad03","prefixlen":64,"scope":"global","temporary":true,"dynamic":true,"valid_life_time":6822,"preferred_life_time":3222},{"family":"inet6","local":"2001:9e8:a19f:1c00:f24f:f724:5dd1:d0ad","prefixlen":64,"scope":"global","dynamic":true,"mngtmpaddr":true,"noprefixroute":true,"valid_life_time":6822,"preferred_life_time":3222},{"family":"inet6","local":"fe80::fec1:6ced:5268:b46c","prefixlen":64,"scope":"link","noprefixroute":true,"valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":41,"ifname":"wg0","flags":["POINTOPOINT","NOARP","UP","LOWER_UP"],"mtu":1420,"qdisc":"noqueue","operstate":"UNKNOWN","group":"default","txqlen":1000,"link_type":"none","promiscuity":0,"min_mtu":0,"max_mtu":2147483552,"linkinfo":{"info_kind":"wireguard"},"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"addr_info":[{"family":"inet","local":"10.10.0.2","prefixlen":24,"scope":"global","label":"wg0","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":46,"ifname":"wwan0","flags":["BROADCAST","MULTICAST","NOARP"],"mtu":1500,"qdisc":"noop","operstate":"DOWN","group":"default","txqlen":1000,"link_type":"ether","address":"a2:23:44:c4:4e:f8","broadcast":"ff:ff:ff:ff:ff:ff","promiscuity":0,"min_mtu":0,"max_mtu":2048,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"parentbus":"usb","parentdev":"1-6:1.12","addr_info":[]},{"ifindex":48,"link":null,"ifname":"tun0","flags":["POINTOPOINT","NOARP","UP","LOWER_UP"],"mtu":1480,"qdisc":"noqueue","operstate":"UNKNOWN","group":"default","txqlen":1000,"link_type":"sit","address":"1.1.1.1","link_pointtopoint":true,"broadcast":"2.2.2.2","promiscuity":0,"min_mtu":1280,"max_mtu":65555,"linkinfo":{"info_kind":"sit","info_data":{"proto":"ip6ip","remote":"2.2.2.2","local":"1.1.1.1","ttl":0,"pmtudisc":true,"prefix":"2002::","prefixlen":16}},"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"addr_info":[{"family":"inet6","local":"2001:dead:beef::2","prefixlen":64,"scope":"global","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":49,"ifname":"tun1","flags":["POINTOPOINT","MULTICAST","NOARP","UP","LOWER_UP"],"mtu":1500,"qdisc":"pfifo_fast","operstate":"UNKNOWN","link_type":"none","linkinfo":{"info_kind":"tun","info_data":{"type":"tun"}}}]'  # nopep8
NETWORKD = '{"Interfaces":[{"Index":1,"Name":"lo","AlternativeNames":[],"Type":"loopback","Driver":null,"SetupState":"unmanaged","OperationalState":"carrier","CarrierState":"carrier","AddressState":"off","IPv4AddressState":"off","IPv6AddressState":"off","OnlineState":null,"LinkFile":null,"Path":null,"Vendor":null,"Model":null},{"Index":2,"Name":"enp0s31f6","AlternativeNames":[],"Type":"ether","Driver":"e1000e","SetupState":"configured","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"routable","IPv6AddressState":"routable","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-enp0s31f6.network","LinkFile":"/usr/lib/systemd/network/99-default.link","Path":"pci-0000:00:1f.6","Vendor":"Intel Corporation","Model":"Ethernet Connection I219-LM"},{"Index":5,"Name":"wlan0","AlternativeNames":[],"Type":"wlan","Driver":"iwlwifi","SetupState":"unmanaged","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"routable","IPv6AddressState":"routable","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-wlan0.network","LinkFile":"/usr/lib/systemd/network/80-iwd.link","Path":"pci-0000:04:00.0","Vendor":"Intel Corporation","Model":"Wireless 8260 (Dual Band Wireless-AC 8260)"},{"Index":41,"Name":"wg0","AlternativeNames":[],"Type":"wireguard","Driver":null,"SetupState":"configured","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"routable","IPv6AddressState":"off","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-wg0.network","LinkFile":"/usr/lib/systemd/network/99-default.link","Path":null,"Vendor":null,"Model":null},{"Index":46,"Name":"wwan0","AlternativeNames":[],"Type":"wwan","Driver":"cdc_mbim","SetupState":"unmanaged","OperationalState":"off","CarrierState":"off","AddressState":"off","IPv4AddressState":"off","IPv6AddressState":"off","OnlineState":null,"LinkFile":"/usr/lib/systemd/network/73-usb-net-by-mac.link","Path":"pci-0000:00:14.0-usb-0:6:1.12","Vendor":"Sierra Wireless, Inc.","Model":"EM7455"},{"Index":48,"Name":"tun0","AlternativeNames":[],"Type":"sit","Driver":null,"SetupState":"configured","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"off","IPv6AddressState":"routable","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-tun0.network","LinkFile":"/usr/lib/systemd/network/99-default.link","Path":null,"Vendor":null,"Model":null}, {"Index":43,"Name":"mybr0","Type":"bridge","Driver":"bridge","OperationalState":"degraded","CarrierState":"carrier","AddressState":"degraded","IPv4AddressState":"degraded","IPv6AddressState":"degraded","OnlineState":null}, {"Index":45,"Name":"mybond0","Type":"bond","Driver":"bonding","OperationalState":"degraded","CarrierState":"carrier","AddressState":"degraded","IPv4AddressState":"degraded","IPv6AddressState":"degraded","OnlineState":null}, {"Index":47,"Name":"myvrf0","Type":"ether","Kind":"vrf","Driver":"vrf","OperationalState":"degraded","CarrierState":"carrier","AddressState":"degraded","IPv4AddressState":"degraded","IPv6AddressState":"degraded","OnlineState":null},{"Index":49,"Name":"tun1","Kind":"tun","Type":"none","Driver":"tun"}]}'  # nopep8
NMCLI = 'wlan0:MYCON:b6b7a21d-186e-45e1-b3a6-636da1735563:/run/NetworkManager/system-connections/netplan-NM-b6b7a21d-186e-45e1-b3a6-636da1735563-MYCON.nmconnection:802-11-wireless:yes'  # nopep8
ROUTE4 = '[{"family":2,"type":"unicast","dst":"default","gateway":"192.168.178.1","dev":"enp0s31f6","table":"main","protocol":"dhcp","scope":"global","prefsrc":"192.168.178.62","metric":100,"flags":[]},{"family":2,"type":"unicast","dst":"default","gateway":"192.168.178.1","dev":"wlan0","table":"main","protocol":"dhcp","scope":"global","metric":600,"flags":[]},{"family":2,"type":"unicast","dst":"10.10.0.0/24","dev":"wg0","table":"main","protocol":"kernel","scope":"link","prefsrc":"10.10.0.2","flags":[]},{"family":2,"type":"unicast","dst":"192.168.178.0/24","dev":"enp0s31f6","table":"main","protocol":"kernel","scope":"link","prefsrc":"192.168.178.62","metric":100,"flags":[]},{"family":2,"type":"unicast","dst":"192.168.178.0/24","dev":"wlan0","table":"main","protocol":"kernel","scope":"link","prefsrc":"192.168.178.142","metric":600,"flags":[]},{"family":2,"type":"unicast","dst":"192.168.178.1","dev":"enp0s31f6","table":"1234","protocol":"dhcp","scope":"link","prefsrc":"192.168.178.62","metric":100,"flags":[]},{"family":2,"type":"broadcast","dst":"192.168.178.255","dev":"enp0s31f6","table":"local","protocol":"kernel","scope":"link","prefsrc":"192.168.178.62","flags":[]}]'  # nopep8
ROUTE6 = '[{"family":10,"type":"unicast","dst":"::1","dev":"lo","table":"main","protocol":"kernel","scope":"global","metric":256,"flags":[],"pref":"medium"},{"family":10,"type":"unicast","dst":"2001:9e8:a19f:1c00::/64","dev":"enp0s31f6","table":"main","protocol":"ra","scope":"global","metric":100,"flags":[],"expires":7199,"pref":"medium"},{"family":10,"type":"unicast","dst":"2001:9e8:a19f:1c00::/64","dev":"wlan0","table":"main","protocol":"ra","scope":"global","metric":600,"flags":[],"pref":"medium"},{"family":10,"type":"unicast","dst":"2001:9e8:a19f:1c00::/56","gateway":"fe80::cece:1eff:fe3d:c737","dev":"enp0s31f6","table":"main","protocol":"ra","scope":"global","metric":100,"flags":[],"expires":1799,"pref":"medium"},{"family":10,"type":"unicast","dst":"2001:9e8:a19f:1c00::/56","gateway":"fe80::cece:1eff:fe3d:c737","dev":"wlan0","table":"main","protocol":"ra","scope":"global","metric":600,"flags":[],"pref":"medium"},{"family":10,"type":"unicast","dst":"2001:dead:beef::/64","dev":"tun0","table":"main","protocol":"kernel","scope":"global","metric":256,"flags":[],"pref":"medium"},{"family":10,"type":"unicast","dst":"fe80::/64","dev":"enp0s31f6","table":"main","protocol":"kernel","scope":"global","metric":256,"flags":[],"pref":"medium"},{"family":10,"type":"unicast","dst":"fe80::/64","dev":"wlan0","table":"main","protocol":"kernel","scope":"global","metric":1024,"flags":[],"pref":"medium"},{"family":10,"type":"unicast","dst":"default","gateway":"fe80::cece:1eff:fe3d:c737","dev":"enp0s31f6","table":"1234","protocol":"ra","scope":"global","metric":100,"flags":[],"expires":1799,"metrics":[{"mtu":1492}],"pref":"medium"},{"family":10,"type":"unicast","dst":"default","gateway":"fe80::cece:1eff:fe3d:c737","dev":"wlan0","table":"main","protocol":"ra","scope":"global","metric":20600,"flags":[],"pref":"medium"}]'  # nopep8
DNS_IP4 = bytearray([192, 168, 178, 1])
DNS_IP6 = bytearray([0xfd, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0xce, 0xce, 0x1e, 0xff, 0xfe, 0x3d, 0xc7, 0x37])
DNS_ADDRESSES = [(5, 2, DNS_IP4), (5, 10, DNS_IP6), (2, 2, DNS_IP4), (2, 10, DNS_IP6)]  # (IFidx, IPfamily, IPbytes)
DNS_SEARCH = [(5, 'search.domain', False), (2, 'search.domain', False)]
FAKE_DEV = {'ifindex': 42, 'ifname': 'fakedev0', 'flags': [], 'operstate': 'DOWN'}
BRIDGE = {'ifindex': 43, 'ifname': 'mybr0', 'flags': [], 'operstate': 'UP'}
BOND = {'ifindex': 45, 'ifname': 'mybond0', 'flags': [], 'operstate': 'UP'}
VRF = {'ifindex': 47, 'ifname': 'myvrf0', 'flags': [], 'operstate': 'UP'}
STATUS_OUTPUT = '''\
     Online state: online
    DNS Addresses: 127.0.0.53 (stub)
       DNS Search: search.domain

●  2: enp0s31f6 ethernet UP (networkd: enp0s31f6)
      MAC Address: 54:e1:ad:5f:24:b4 (Intel Corporation)
        Addresses: 192.168.178.62/24 (dhcp)
                   2001:9e8:a19f:1c00:56e1:adff:fe5f:24b4/64
                   fe80::56e1:adff:fe5f:24b4/64 (link)
    DNS Addresses: 192.168.178.1
                   fd00::cece:1eff:fe3d:c737
       DNS Search: search.domain
           Routes: default via 192.168.178.1 from 192.168.178.62 metric 100 (dhcp)
                   192.168.178.0/24 from 192.168.178.62 metric 100 (link)
                   2001:9e8:a19f:1c00::/64 metric 100 (ra)
                   2001:9e8:a19f:1c00::/56 via fe80::cece:1eff:fe3d:c737 metric 100 (ra)
                   fe80::/64 metric 256
  Activation Mode: manual

●  5: wlan0 wifi/"MYCON" UP (NetworkManager: NM-b6b7a21d-186e-45e1-b3a6-636da1735563)
      MAC Address: 1c:4d:70:e4:e4:0e (Intel Corporation)
        Addresses: 192.168.178.142/24
                   2001:9e8:a19f:1c00:7011:2d1:951:ad03/64
                   2001:9e8:a19f:1c00:f24f:f724:5dd1:d0ad/64
                   fe80::fec1:6ced:5268:b46c/64 (link)
    DNS Addresses: 192.168.178.1
                   fd00::cece:1eff:fe3d:c737
       DNS Search: search.domain
           Routes: default via 192.168.178.1 metric 600 (dhcp)
                   192.168.178.0/24 from 192.168.178.142 metric 600 (link)
                   2001:9e8:a19f:1c00::/64 metric 600 (ra)
                   2001:9e8:a19f:1c00::/56 via fe80::cece:1eff:fe3d:c737 metric 600 (ra)
                   fe80::/64 metric 1024
                   default via fe80::cece:1eff:fe3d:c737 metric 20600 (ra)

● 41: wg0 tunnel/wireguard UNKNOWN/UP (networkd: wg0)
        Addresses: 10.10.0.2/24
           Routes: 10.10.0.0/24 from 10.10.0.2 (link)
  Activation Mode: manual

● 48: tun0 tunnel/sit UNKNOWN/UP (networkd: tun0)
        Addresses: 2001:dead:beef::2/64
           Routes: 2001:dead:beef::/64 metric 256
  Activation Mode: manual

● 42: fakedev0 other DOWN (unmanaged)
           Routes: 10.0.0.0/16 via 10.0.0.1 (local)

● 43: mybr0 bridge UP/DOWN (unmanaged)
       Interfaces: fakedev1

● 44: fakedev1 other DOWN (unmanaged)
           Routes: 10.0.0.0/16 via 10.0.0.1 (local)
           Bridge: mybr0

● 45: mybond0 bond UP/DOWN (unmanaged)
       Interfaces: fakedev2

● 46: fakedev2 other DOWN (unmanaged)
           Routes: 10.0.0.0/16 via 10.0.0.1 (local)
             Bond: mybond0

● 47: myvrf0 vrf UP/DOWN (unmanaged)
       Interfaces: fakedev3

● 48: fakedev3 other DOWN (unmanaged)
           Routes: 10.0.0.0/16 via 10.0.0.1 (local)
              VRF: myvrf0

● 49: tun1 tunnel/tun UNKNOWN/UP (unmanaged)

1 inactive interfaces hidden. Use "--all" to show all.
'''


class TestStatus(unittest.TestCase):
    '''Test netplan status'''

    def setUp(self):
        self.maxDiff = None

    def _call(self, args):
        args.insert(0, 'status')
        return call_cli(args)

    def _get_itf(self, ifname):
        return next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifname'] == ifname), None)

    @patch('netplan_cli.cli.commands.status.RICH_OUTPUT', False)
    @patch('netplan_cli.cli.state.Interface.query_nm_ssid')
    @patch('netplan_cli.cli.state.Interface.query_networkctl')
    def test_plain_print(self, networkctl_mock, nm_ssid_mock):
        SSID = 'MYCON'
        nm_ssid_mock.return_value = SSID
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = \
            '''Activation Policy: manual
            WiFi access point: {} (b4:fb:e4:75:c6:21)'''.format(SSID)

        nd = SystemConfigState.process_networkd(NETWORKD)
        nm = SystemConfigState.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (SystemConfigState.process_generic(ROUTE4), SystemConfigState.process_generic(ROUTE6))
        fakeroute = {'type': 'local', 'dst': '10.0.0.0/16', 'gateway': '10.0.0.1', 'dev': FAKE_DEV['ifname'], 'table': 'main'}

        bridge = Interface(BRIDGE, nd, None, (None, None), (None, None))
        bridge.members = ['fakedev1']
        bridge_member = Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None))
        bridge_member.idx = 44
        bridge_member.name = 'fakedev1'
        bridge_member.bridge = 'mybr0'

        bond = Interface(BOND, nd, None, (None, None), (None, None))
        bond.members = ['fakedev2']
        bond_member = Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None))
        bond_member.idx = 46
        bond_member.name = 'fakedev2'
        bond_member.bond = 'mybond0'

        vrf = Interface(VRF, nd, None, (None, None), (None, None))
        vrf.members = ['fakedev3']
        vrf_member = Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None))
        vrf_member.idx = 48
        vrf_member.name = 'fakedev3'
        vrf_member.vrf = 'myvrf0'

        interfaces = [
            Interface(self._get_itf('enp0s31f6'), nd, nm, dns, routes),
            Interface(self._get_itf('wlan0'), nd, nm, dns, routes),
            Interface(self._get_itf('wg0'), nd, nm, dns, routes),
            Interface(self._get_itf('tun0'), nd, nm, dns, routes),
            Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None)),
            bridge,
            bridge_member,
            bond,
            bond_member,
            vrf,
            vrf_member,
            Interface(self._get_itf('tun1'), nd, nm, dns, routes),
            ]
        data = {'netplan-global-state': {
            'online': True,
            'nameservers': {
                'addresses': ['127.0.0.53'],
                'search': ['search.domain'],
                'mode': 'stub',
            }}}
        for itf in interfaces:
            ifname, obj = itf.json()
            data[ifname] = obj
        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.verbose = False
            status.pretty_print(data, len(interfaces)+1, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, STATUS_OUTPUT)

    @patch('netplan_cli.cli.state.Interface.query_nm_ssid')
    @patch('netplan_cli.cli.state.Interface.query_networkctl')
    def test_pretty_print(self, networkctl_mock, nm_ssid_mock):
        SSID = 'MYCON'
        nm_ssid_mock.return_value = SSID
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = \
            '''Activation Policy: manual
            WiFi access point: {} (b4:fb:e4:75:c6:21)'''.format(SSID)

        nd = SystemConfigState.process_networkd(NETWORKD)
        nm = SystemConfigState.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (SystemConfigState.process_generic(ROUTE4), SystemConfigState.process_generic(ROUTE6))
        fakeroute = {'type': 'local', 'dst': '10.0.0.0/16', 'gateway': '10.0.0.1', 'dev': FAKE_DEV['ifname'], 'table': 'main'}

        bridge = Interface(BRIDGE, nd, None, (None, None), (None, None))
        bridge.members = ['fakedev1']
        bridge_member = Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None))
        bridge_member.idx = 44
        bridge_member.name = 'fakedev1'
        bridge_member.bridge = 'mybr0'

        bond = Interface(BOND, nd, None, (None, None), (None, None))
        bond.members = ['fakedev2']
        bond_member = Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None))
        bond_member.idx = 46
        bond_member.name = 'fakedev2'
        bond_member.bond = 'mybond0'

        vrf = Interface(VRF, nd, None, (None, None), (None, None))
        vrf.members = ['fakedev3']
        vrf_member = Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None))
        vrf_member.idx = 48
        vrf_member.name = 'fakedev3'
        vrf_member.vrf = 'myvrf0'

        interfaces = [
            Interface(self._get_itf('enp0s31f6'), nd, nm, dns, routes),
            Interface(self._get_itf('wlan0'), nd, nm, dns, routes),
            Interface(self._get_itf('wg0'), nd, nm, dns, routes),
            Interface(self._get_itf('tun0'), nd, nm, dns, routes),
            Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None)),
            bridge,
            bridge_member,
            bond,
            bond_member,
            vrf,
            vrf_member,
            Interface(self._get_itf('tun1'), nd, nm, dns, routes),
            ]
        data = {'netplan-global-state': {
            'online': True,
            'nameservers': {
                'addresses': ['127.0.0.53'],
                'search': ['search.domain'],
                'mode': 'stub',
            }}}
        for itf in interfaces:
            ifname, obj = itf.json()
            data[ifname] = obj
        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.verbose = False
            status.pretty_print(data, len(interfaces)+1, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, STATUS_OUTPUT)

    @patch('netplan_cli.cli.state.Interface.query_nm_ssid')
    @patch('netplan_cli.cli.state.Interface.query_networkctl')
    def test_pretty_print_verbose(self, networkctl_mock, nm_ssid_mock):
        SSID = 'MYCON'
        nm_ssid_mock.return_value = SSID
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = \
            '''Activation Policy: manual
            WiFi access point: {} (b4:fb:e4:75:c6:21)'''.format(SSID)

        nd = SystemConfigState.process_networkd(NETWORKD)
        nm = SystemConfigState.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (SystemConfigState.process_generic(ROUTE4), SystemConfigState.process_generic(ROUTE6))

        interfaces = [
            Interface(self._get_itf('enp0s31f6'), nd, nm, dns, routes),
            ]
        data = {'netplan-global-state': {
            'online': True,
            'nameservers': {
                'addresses': ['127.0.0.53'],
                'search': ['search.domain'],
                'mode': 'stub',
            }}}
        for itf in interfaces:
            ifname, obj = itf.json()
            data[ifname] = obj
        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.verbose = True
            status.pretty_print(data, len(interfaces), _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, '''\
     Online state: online
    DNS Addresses: 127.0.0.53 (stub)
       DNS Search: search.domain

●  2: enp0s31f6 ethernet UP (networkd: enp0s31f6)
      MAC Address: 54:e1:ad:5f:24:b4 (Intel Corporation)
        Addresses: 192.168.178.62/24 (dhcp)
                   2001:9e8:a19f:1c00:56e1:adff:fe5f:24b4/64
                   fe80::56e1:adff:fe5f:24b4/64 (link)
    DNS Addresses: 192.168.178.1
                   fd00::cece:1eff:fe3d:c737
       DNS Search: search.domain
           Routes: default via 192.168.178.1 from 192.168.178.62 metric 100 table main (dhcp)
                   192.168.178.0/24 from 192.168.178.62 metric 100 table main (link)
                   192.168.178.1 from 192.168.178.62 metric 100 table 1234 (dhcp, link)
                   192.168.178.255 from 192.168.178.62 table local (link, broadcast)
                   2001:9e8:a19f:1c00::/64 metric 100 table main (ra)
                   2001:9e8:a19f:1c00::/56 via fe80::cece:1eff:fe3d:c737 metric 100 table main (ra)
                   fe80::/64 metric 256 table main
                   default via fe80::cece:1eff:fe3d:c737 metric 100 table 1234 (ra)
  Activation Mode: manual\n\n''')

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    def test_call_cli(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock,
                      systemctl_mock):
        systemctl_mock.return_value = None
        iproute2_mock.return_value = [FAKE_DEV]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        state = SystemConfigState()
        networkd_mock.return_value = state.process_networkd(NETWORKD)
        out = self._call(['-a'])
        self.assertEqual(out.strip(), '''\
Online state: offline

● 42: fakedev0 other DOWN (unmanaged)''')

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    def test_fail_cli(self, networkd_mock, iproute2_mock, systemctl_mock):
        systemctl_mock.return_value = None
        iproute2_mock.return_value = [FAKE_DEV]
        networkd_mock.return_value = []
        with self.assertRaises(SystemExit):
            self._call([])

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    def test_call_cli_ifname(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock,
                             systemctl_mock):
        systemctl_mock.return_value = None
        iproute2_mock.return_value = [FAKE_DEV, self._get_itf('wlan0')]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        state = SystemConfigState()
        networkd_mock.return_value = state.process_networkd(NETWORKD)
        out = self._call([FAKE_DEV['ifname']])
        self.assertEqual(out.strip(), '''\
Online state: offline

● 42: fakedev0 other DOWN (unmanaged)

1 inactive interfaces hidden. Use "--all" to show all.''')

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    def test_fail_cli_ifname(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock,
                             systemctl_mock):
        systemctl_mock.return_value = None
        iproute2_mock.return_value = [FAKE_DEV, self._get_itf('wlan0')]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        state = SystemConfigState()
        networkd_mock.return_value = state.process_networkd(NETWORKD)
        with self.assertRaises(SystemExit):
            self._call(['notaninteface0'])

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    def test_call_cli_json(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock,
                           systemctl_mock):
        systemctl_mock.return_value = None
        iproute2_mock.return_value = [FAKE_DEV]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        state = SystemConfigState()
        networkd_mock.return_value = state.process_networkd(NETWORKD)
        out = self._call(['-a', '--format=json'])
        self.assertEqual(out, '''{\
"netplan-global-state": {"online": false, "nameservers": {"addresses": [], "search": [], "mode": null}}, \
"fakedev0": {"index": 42, "adminstate": "DOWN", "operstate": "DOWN"}}\n''')

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    def test_call_cli_yaml(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock,
                           systemctl_mock):
        systemctl_mock.return_value = None
        iproute2_mock.return_value = [FAKE_DEV]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        state = SystemConfigState()
        networkd_mock.return_value = state.process_networkd(NETWORKD)
        out = self._call(['-a', '--format=yaml'])
        self.assertEqual(out.strip(), '''\
fakedev0:
  adminstate: DOWN
  index: 42
  operstate: DOWN
netplan-global-state:
  nameservers:
    addresses: []
    mode: null
    search: []
  online: false'''.strip())

    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    @patch('netplan_cli.cli.utils.systemctl_is_active')
    @patch('netplan_cli.cli.utils.systemctl')
    def test_call_cli_no_networkd(self, systemctl_mock, is_active_mock,
                                  online_mock, resolvconf_mock, rd_mock,
                                  routes_mock, nm_mock, networkd_mock,
                                  iproute2_mock):
        iproute2_mock.return_value = [FAKE_DEV]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        is_active_mock.return_value = False
        state = SystemConfigState()
        networkd_mock.return_value = state.process_networkd(NETWORKD)
        with self.assertLogs(level='DEBUG') as cm:
            self._call([])
            self.assertIn('DEBUG:root:systemd-networkd.service is not active. Starting...',
                          cm.output[0])
        systemctl_mock.assert_called_with('start', ['systemd-networkd.service'], True)

    @patch('netplan_cli.cli.utils.systemctl_is_active')
    @patch('netplan_cli.cli.utils.systemctl_is_masked')
    def test_call_cli_networkd_masked(self, is_masked_mock, is_active_mock):
        is_active_mock.return_value = False
        is_masked_mock.return_value = True
        with self.assertLogs() as cm, self.assertRaises(SystemExit) as e:
            self._call([])
        self.assertEqual(1, e.exception.code)
        self.assertIn('systemd-networkd.service is masked', cm.output[0])
