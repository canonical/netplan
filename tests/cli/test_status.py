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

import copy
import io
import subprocess
import unittest
import yaml

from contextlib import redirect_stdout
from unittest.mock import patch, call, mock_open
from netplan.cli.commands.status import NetplanStatus, Interface
from tests.test_utils import call_cli


IPROUTE2 = '[{"ifindex":1,"ifname":"lo","flags":["LOOPBACK","UP","LOWER_UP"],"mtu":65536,"qdisc":"noqueue","operstate":"UNKNOWN","group":"default","txqlen":1000,"link_type":"loopback","address":"00:00:00:00:00:00","broadcast":"00:00:00:00:00:00","promiscuity":0,"min_mtu":0,"max_mtu":0,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8,"scope":"host","label":"lo","valid_life_time":4294967295,"preferred_life_time":4294967295},{"family":"inet6","local":"::1","prefixlen":128,"scope":"host","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":2,"ifname":"enp0s31f6","flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],"mtu":1500,"qdisc":"fq_codel","operstate":"UP","group":"default","txqlen":1000,"link_type":"ether","address":"54:e1:ad:5f:24:b4","broadcast":"ff:ff:ff:ff:ff:ff","promiscuity":0,"min_mtu":68,"max_mtu":9000,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"parentbus":"pci","parentdev":"0000:00:1f.6","addr_info":[{"family":"inet","local":"192.168.178.62","prefixlen":24,"metric":100,"broadcast":"192.168.178.255","scope":"global","dynamic":true,"label":"enp0s31f6","valid_life_time":850698,"preferred_life_time":850698},{"family":"inet6","local":"2001:9e8:a19f:1c00:56e1:adff:fe5f:24b4","prefixlen":64,"scope":"global","dynamic":true,"mngtmpaddr":true,"noprefixroute":true,"valid_life_time":6821,"preferred_life_time":3221},{"family":"inet6","local":"fe80::56e1:adff:fe5f:24b4","prefixlen":64,"scope":"link","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":5,"ifname":"wlan0","flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],"mtu":1500,"qdisc":"noqueue","operstate":"UP","group":"default","txqlen":1000,"link_type":"ether","address":"1c:4d:70:e4:e4:0e","broadcast":"ff:ff:ff:ff:ff:ff","promiscuity":0,"min_mtu":256,"max_mtu":2304,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"parentbus":"pci","parentdev":"0000:04:00.0","addr_info":[{"family":"inet","local":"192.168.178.142","prefixlen":24,"broadcast":"192.168.178.255","scope":"global","dynamic":true,"noprefixroute":true,"label":"wlan0","valid_life_time":850700,"preferred_life_time":850700},{"family":"inet6","local":"2001:9e8:a19f:1c00:7011:2d1:951:ad03","prefixlen":64,"scope":"global","temporary":true,"dynamic":true,"valid_life_time":6822,"preferred_life_time":3222},{"family":"inet6","local":"2001:9e8:a19f:1c00:f24f:f724:5dd1:d0ad","prefixlen":64,"scope":"global","dynamic":true,"mngtmpaddr":true,"noprefixroute":true,"valid_life_time":6822,"preferred_life_time":3222},{"family":"inet6","local":"fe80::fec1:6ced:5268:b46c","prefixlen":64,"scope":"link","noprefixroute":true,"valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":41,"ifname":"wg0","flags":["POINTOPOINT","NOARP","UP","LOWER_UP"],"mtu":1420,"qdisc":"noqueue","operstate":"UNKNOWN","group":"default","txqlen":1000,"link_type":"none","promiscuity":0,"min_mtu":0,"max_mtu":2147483552,"linkinfo":{"info_kind":"wireguard"},"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"addr_info":[{"family":"inet","local":"10.10.0.2","prefixlen":24,"scope":"global","label":"wg0","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":46,"ifname":"wwan0","flags":["BROADCAST","MULTICAST","NOARP"],"mtu":1500,"qdisc":"noop","operstate":"DOWN","group":"default","txqlen":1000,"link_type":"ether","address":"a2:23:44:c4:4e:f8","broadcast":"ff:ff:ff:ff:ff:ff","promiscuity":0,"min_mtu":0,"max_mtu":2048,"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"parentbus":"usb","parentdev":"1-6:1.12","addr_info":[]},{"ifindex":48,"link":null,"ifname":"tun0","flags":["POINTOPOINT","NOARP","UP","LOWER_UP"],"mtu":1480,"qdisc":"noqueue","operstate":"UNKNOWN","group":"default","txqlen":1000,"link_type":"sit","address":"1.1.1.1","link_pointtopoint":true,"broadcast":"2.2.2.2","promiscuity":0,"min_mtu":1280,"max_mtu":65555,"linkinfo":{"info_kind":"sit","info_data":{"proto":"ip6ip","remote":"2.2.2.2","local":"1.1.1.1","ttl":0,"pmtudisc":true,"prefix":"2002::","prefixlen":16}},"num_tx_queues":1,"num_rx_queues":1,"gso_max_size":65536,"gso_max_segs":65535,"addr_info":[{"family":"inet6","local":"2001:dead:beef::2","prefixlen":64,"scope":"global","valid_life_time":4294967295,"preferred_life_time":4294967295}]}]'  # nopep8
NETWORKD = '{"Interfaces":[{"Index":1,"Name":"lo","AlternativeNames":[],"Type":"loopback","Driver":null,"SetupState":"unmanaged","OperationalState":"carrier","CarrierState":"carrier","AddressState":"off","IPv4AddressState":"off","IPv6AddressState":"off","OnlineState":null,"LinkFile":null,"Path":null,"Vendor":null,"Model":null},{"Index":2,"Name":"enp0s31f6","AlternativeNames":[],"Type":"ether","Driver":"e1000e","SetupState":"configured","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"routable","IPv6AddressState":"routable","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-enp0s31f6.network","LinkFile":"/usr/lib/systemd/network/99-default.link","Path":"pci-0000:00:1f.6","Vendor":"Intel Corporation","Model":"Ethernet Connection I219-LM"},{"Index":5,"Name":"wlan0","AlternativeNames":[],"Type":"wlan","Driver":"iwlwifi","SetupState":"unmanaged","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"routable","IPv6AddressState":"routable","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-wlan0.network","LinkFile":"/usr/lib/systemd/network/80-iwd.link","Path":"pci-0000:04:00.0","Vendor":"Intel Corporation","Model":"Wireless 8260 (Dual Band Wireless-AC 8260)"},{"Index":41,"Name":"wg0","AlternativeNames":[],"Type":"wireguard","Driver":null,"SetupState":"configured","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"routable","IPv6AddressState":"off","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-wg0.network","LinkFile":"/usr/lib/systemd/network/99-default.link","Path":null,"Vendor":null,"Model":null},{"Index":46,"Name":"wwan0","AlternativeNames":[],"Type":"wwan","Driver":"cdc_mbim","SetupState":"unmanaged","OperationalState":"off","CarrierState":"off","AddressState":"off","IPv4AddressState":"off","IPv6AddressState":"off","OnlineState":null,"LinkFile":"/usr/lib/systemd/network/73-usb-net-by-mac.link","Path":"pci-0000:00:14.0-usb-0:6:1.12","Vendor":"Sierra Wireless, Inc.","Model":"EM7455"},{"Index":48,"Name":"tun0","AlternativeNames":[],"Type":"sit","Driver":null,"SetupState":"configured","OperationalState":"routable","CarrierState":"carrier","AddressState":"routable","IPv4AddressState":"off","IPv6AddressState":"routable","OnlineState":"online","NetworkFile":"/run/systemd/network/10-netplan-tun0.network","LinkFile":"/usr/lib/systemd/network/99-default.link","Path":null,"Vendor":null,"Model":null}]}'  # nopep8
NMCLI = 'wlan0:MYCON:b6b7a21d-186e-45e1-b3a6-636da1735563:/run/NetworkManager/system-connections/netplan-NM-b6b7a21d-186e-45e1-b3a6-636da1735563-MYCON.nmconnection:802-11-wireless:yes'  # nopep8
ROUTE4 = '[{"type":"unicast","dst":"default","gateway":"192.168.178.1","dev":"enp0s31f6","protocol":"dhcp","scope":"global","prefsrc":"192.168.178.62","metric":100,"flags":[]},{"type":"unicast","dst":"default","gateway":"192.168.178.1","dev":"wlan0","protocol":"dhcp","scope":"global","metric":600,"flags":[]},{"type":"unicast","dst":"10.10.0.0/24","dev":"wg0","protocol":"kernel","scope":"link","prefsrc":"10.10.0.2","flags":[]},{"type":"unicast","dst":"192.168.178.0/24","dev":"enp0s31f6","protocol":"kernel","scope":"link","prefsrc":"192.168.178.62","metric":100,"flags":[]},{"type":"unicast","dst":"192.168.178.0/24","dev":"wlan0","protocol":"kernel","scope":"link","prefsrc":"192.168.178.142","metric":600,"flags":[]},{"type":"unicast","dst":"192.168.178.1","dev":"enp0s31f6","protocol":"dhcp","scope":"link","prefsrc":"192.168.178.62","metric":100,"flags":[]}]'  # nopep8
ROUTE6 = '[{"type":"unicast","dst":"::1","dev":"lo","protocol":"kernel","scope":"global","metric":256,"flags":[],"pref":"medium"},{"type":"unicast","dst":"2001:9e8:a19f:1c00::/64","dev":"enp0s31f6","protocol":"ra","scope":"global","metric":100,"flags":[],"expires":7199,"pref":"medium"},{"type":"unicast","dst":"2001:9e8:a19f:1c00::/64","dev":"wlan0","protocol":"ra","scope":"global","metric":600,"flags":[],"pref":"medium"},{"type":"unicast","dst":"2001:9e8:a19f:1c00::/56","gateway":"fe80::cece:1eff:fe3d:c737","dev":"enp0s31f6","protocol":"ra","scope":"global","metric":100,"flags":[],"expires":1799,"pref":"medium"},{"type":"unicast","dst":"2001:9e8:a19f:1c00::/56","gateway":"fe80::cece:1eff:fe3d:c737","dev":"wlan0","protocol":"ra","scope":"global","metric":600,"flags":[],"pref":"medium"},{"type":"unicast","dst":"2001:dead:beef::/64","dev":"tun0","protocol":"kernel","scope":"global","metric":256,"flags":[],"pref":"medium"},{"type":"unicast","dst":"fe80::/64","dev":"enp0s31f6","protocol":"kernel","scope":"global","metric":256,"flags":[],"pref":"medium"},{"type":"unicast","dst":"fe80::/64","dev":"wlan0","protocol":"kernel","scope":"global","metric":1024,"flags":[],"pref":"medium"},{"type":"unicast","dst":"default","gateway":"fe80::cece:1eff:fe3d:c737","dev":"enp0s31f6","protocol":"ra","scope":"global","metric":100,"flags":[],"expires":1799,"metrics":[{"mtu":1492}],"pref":"medium"},{"type":"unicast","dst":"default","gateway":"fe80::cece:1eff:fe3d:c737","dev":"wlan0","protocol":"ra","scope":"global","metric":20600,"flags":[],"pref":"medium"}]'  # nopep8
DNS_IP4 = bytearray([192, 168, 178, 1])
DNS_IP6 = bytearray([0xfd, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0xce, 0xce, 0x1e, 0xff, 0xfe, 0x3d, 0xc7, 0x37])
DNS_ADDRESSES = [(5, 2, DNS_IP4), (5, 10, DNS_IP6), (2, 2, DNS_IP4), (2, 10, DNS_IP6)]  # (IFidx, IPfamily, IPbytes)
DNS_SEARCH = [(5, 'search.domain', False), (2, 'search.domain', False)]
FAKE_DEV = {'ifindex': 42, 'ifname': 'fakedev0', 'flags': [], 'operstate': 'DOWN'}


class resolve1_ipc_mock():
    def get_object(self, _foo, _bar):
        return {}  # dbus Object


class resolve1_iface_mock():
    def __init__(self, _foo, _bar):
        pass  # dbus Interface

    def GetAll(self, _):
        return {
            'DNS': DNS_ADDRESSES,
            'Domains': DNS_SEARCH,
            }


class TestStatus(unittest.TestCase):
    '''Test netplan status'''

    def setUp(self):
        self.maxDiff = None

    def _call(self, args):
        args.insert(0, 'status')
        return call_cli(args)

    def _get_itf(self, ifname):
        return next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifname'] == ifname), None)

    @patch('subprocess.check_output')
    def test_query_iproute2(self, mock):
        mock.return_value = IPROUTE2
        status = NetplanStatus()
        res = status.query_iproute2()
        mock.assert_called_with(['ip', '-d', '-j', 'addr'], universal_newlines=True)
        self.assertEqual(len(res), 6)
        self.assertListEqual([itf.get('ifname') for itf in res],
                             ['lo', 'enp0s31f6', 'wlan0', 'wg0', 'wwan0', 'tun0'])

    @patch('subprocess.check_output')
    def test_query_iproute2_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        status = NetplanStatus()
        with self.assertLogs() as cm:
            res = status.query_iproute2()
            mock.assert_called_with(['ip', '-d', '-j', 'addr'], universal_newlines=True)
            self.assertIsNone(res)
            self.assertIn('CRITICAL:root:Cannot query iproute2 interface data:', cm.output[0])

    @patch('subprocess.check_output')
    def test_query_networkd(self, mock):
        mock.return_value = NETWORKD
        status = NetplanStatus()
        res = status.query_networkd()
        mock.assert_called_with(['networkctl', '--json=short'], universal_newlines=True)
        self.assertEqual(len(res), 6)
        self.assertListEqual([itf.get('Name') for itf in res],
                             ['lo', 'enp0s31f6', 'wlan0', 'wg0', 'wwan0', 'tun0'])

    @patch('subprocess.check_output')
    def test_query_networkd_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        status = NetplanStatus()
        with self.assertLogs() as cm:
            res = status.query_networkd()
            mock.assert_called_with(['networkctl', '--json=short'], universal_newlines=True)
            self.assertIsNone(res)
            self.assertIn('CRITICAL:root:Cannot query networkd interface data:', cm.output[0])

    @patch('subprocess.check_output')
    def test_query_nm(self, mock):
        mock.return_value = NMCLI
        status = NetplanStatus()
        res = status.query_nm()
        mock.assert_called_with(['nmcli', '-t', '-f',
                                 'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                 'con', 'show'], universal_newlines=True)
        self.assertEqual(len(res), 1)
        self.assertListEqual([itf.get('device') for itf in res], ['wlan0'])

    @patch('subprocess.check_output')
    def test_query_nm_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        status = NetplanStatus()
        with self.assertLogs(level='DEBUG') as cm:
            res = status.query_nm()
            mock.assert_called_with(['nmcli', '-t', '-f',
                                     'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                     'con', 'show'], universal_newlines=True)
            self.assertIsNone(res)
            self.assertIn('DEBUG:root:Cannot query NetworkManager interface data:', cm.output[0])

    @patch('subprocess.check_output')
    def test_query_routes(self, mock):
        mock.side_effect = [ROUTE4, ROUTE6]
        status = NetplanStatus()
        res4, res6 = status.query_routes()
        mock.assert_has_calls([
            call(['ip', '-d', '-j', 'route'], universal_newlines=True),
            call(['ip', '-d', '-j', '-6', 'route'], universal_newlines=True),
            ])
        self.assertEqual(len(res4), 6)
        self.assertListEqual([route.get('dev') for route in res4],
                             ['enp0s31f6', 'wlan0', 'wg0', 'enp0s31f6', 'wlan0', 'enp0s31f6'])
        self.assertEqual(len(res6), 10)
        self.assertListEqual([route.get('dev') for route in res6],
                             ['lo', 'enp0s31f6', 'wlan0', 'enp0s31f6', 'wlan0',
                              'tun0', 'enp0s31f6', 'wlan0', 'enp0s31f6', 'wlan0'])

    @patch('subprocess.check_output')
    def test_query_routes_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        status = NetplanStatus()
        with self.assertLogs(level='DEBUG') as cm:
            res4, res6 = status.query_routes()
            mock.assert_called_with(['ip', '-d', '-j', 'route'], universal_newlines=True)
            self.assertIsNone(res4)
            self.assertIsNone(res6)
            self.assertIn('DEBUG:root:Cannot query iproute2 route data:', cm.output[0])

    @patch('dbus.Interface')
    @patch('dbus.SystemBus')
    def test_query_resolved(self, mock_ipc, mock_iface):
        mock_ipc.return_value = resolve1_ipc_mock()
        mock_iface.return_value = resolve1_iface_mock('foo', 'bar')
        status = NetplanStatus()
        addresses, search = status.query_resolved()
        self.assertEqual(len(addresses), 4)
        self.assertListEqual([addr[0] for addr in addresses],
                             [5, 5, 2, 2])  # interface index
        self.assertEqual(len(search), 2)
        self.assertListEqual([s[1] for s in search],
                             ['search.domain', 'search.domain'])

    @patch('dbus.SystemBus')
    def test_query_resolved_fail(self, mock):
        mock.return_value = resolve1_ipc_mock()
        mock.side_effect = Exception(1, '', 'ERR')
        status = NetplanStatus()
        with self.assertLogs(level='DEBUG') as cm:
            addresses, search = status.query_resolved()
            self.assertIsNone(addresses)
            self.assertIsNone(search)
            self.assertIn('DEBUG:root:Cannot query resolved DNS data:', cm.output[0])

    def test_query_resolvconf(self):
        status = NetplanStatus()
        with patch('builtins.open', mock_open(read_data='''\
nameserver 1.1.1.1
nameserver 8.8.8.8
options edns0 trust-ad
search   some.domain
search search.domain  another.one
''')):
            res = status.resolvconf_json()
            print(res)
            self.assertListEqual(res.get('addresses'), ['1.1.1.1', '8.8.8.8'])
            self.assertListEqual(res.get('search'), ['search.domain', 'another.one'])
            self.assertEqual(res.get('mode'), None)

    def test_query_resolvconf_stub(self):
        status = NetplanStatus()
        with patch('builtins.open', mock_open(read_data='\
# This is /run/systemd/resolve/stub-resolv.conf managed by man:systemd-resolved(8).')):
            res = status.resolvconf_json()
            self.assertEqual(res.get('mode'), 'stub')

    def test_query_resolvconf_compat(self):
        status = NetplanStatus()
        with patch('builtins.open', mock_open(read_data='\
# This is /run/systemd/resolve/resolv.conf managed by man:systemd-resolved(8).')):
            res = status.resolvconf_json()
            self.assertEqual(res.get('mode'), 'compat')

    def test_query_resolvconf_fail(self):
        status = NetplanStatus()
        with self.assertLogs() as cm:
            with patch('builtins.open', mock_open(read_data='')) as mock_file:
                mock_file.side_effect = Exception(1, '', 'ERR')
                status.resolvconf_json()
                self.assertIn('WARNING:root:Cannot parse /etc/resolv.conf:', cm.output[0])

    def test_query_online_state_online(self):
        status = NetplanStatus()
        dev = copy.deepcopy(FAKE_DEV)
        dev['addr_info'] = [{
            'local': '192.168.0.100',
            'prefixlen': 24,
        }]
        dev['flags'].append('UP')
        dev['operstate'] = 'UP'
        routes = [{
            'dst': 'default',
            'gateway': '192.168.0.1',
            'dev': dev['ifname'],
        }]
        dns = [(FAKE_DEV['ifindex'], 2, DNS_IP4)]
        res = status.query_online_state([Interface(dev, [], [], (dns, None), (routes, None))])
        self.assertTrue(res)

    def test_query_online_state_offline(self):
        status = NetplanStatus()
        res = status.query_online_state([Interface(FAKE_DEV, [])])
        self.assertFalse(res)

    @patch('netplan.cli.commands.status.Interface.query_nm_ssid')
    @patch('netplan.cli.commands.status.Interface.query_networkctl')
    def test_pretty_print(self, networkctl_mock, nm_ssid_mock):
        SSID = 'MYCON'
        nm_ssid_mock.return_value = SSID
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = \
            '''Activation Policy: manual
            WiFi access point: {} (b4:fb:e4:75:c6:21)'''.format(SSID)

        status = NetplanStatus()
        nd = status.process_networkd(NETWORKD)
        nm = status.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (status.process_generic(ROUTE4), status.process_generic(ROUTE6))
        fakeroute = {'type': 'local', 'dst': '10.0.0.0/16', 'gateway': '10.0.0.1', 'dev': FAKE_DEV['ifname']}

        interfaces = [
            Interface(self._get_itf('enp0s31f6'), nd, nm, dns, routes),
            Interface(self._get_itf('wlan0'), nd, nm, dns, routes),
            Interface(self._get_itf('wg0'), nd, nm, dns, routes),
            Interface(self._get_itf('tun0'), nd, nm, dns, routes),
            Interface(FAKE_DEV, [], None, (None, None), ([fakeroute], None)),
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
            status.pretty_print(data, len(interfaces)+1, _console_width=130)
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
           Routes: default via 192.168.178.1 from 192.168.178.62 metric 100 (dhcp)
                   192.168.178.0/24 from 192.168.178.62 metric 100 (link)
                   192.168.178.1 from 192.168.178.62 metric 100 (dhcp, link)
                   2001:9e8:a19f:1c00::/64 metric 100 (ra)
                   2001:9e8:a19f:1c00::/56 via fe80::cece:1eff:fe3d:c737 metric 100 (ra)
                   fe80::/64 metric 256
                   default via fe80::cece:1eff:fe3d:c737 metric 100 (ra)
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

1 inactive interfaces hidden. Use "--all" to show all.
''')

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    @patch('netplan.cli.commands.status.NetplanStatus.query_nm')
    @patch('netplan.cli.commands.status.NetplanStatus.query_routes')
    @patch('netplan.cli.commands.status.NetplanStatus.query_resolved')
    @patch('netplan.cli.commands.status.NetplanStatus.resolvconf_json')
    @patch('netplan.cli.commands.status.NetplanStatus.query_online_state')
    def test_call_cli(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock):
        status = NetplanStatus()
        iproute2_mock.return_value = [FAKE_DEV]
        networkd_mock.return_value = status.process_networkd(NETWORKD)
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        out = self._call(['-a'])
        self.assertEqual(out.strip(), '''\
Online state: offline

● 42: fakedev0 other DOWN (unmanaged)''')

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    def test_fail_cli(self, networkd_mock, iproute2_mock):
        iproute2_mock.return_value = [FAKE_DEV]
        networkd_mock.return_value = []
        with self.assertRaises(SystemExit):
            self._call([])

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    @patch('netplan.cli.commands.status.NetplanStatus.query_nm')
    @patch('netplan.cli.commands.status.NetplanStatus.query_routes')
    @patch('netplan.cli.commands.status.NetplanStatus.query_resolved')
    @patch('netplan.cli.commands.status.NetplanStatus.resolvconf_json')
    @patch('netplan.cli.commands.status.NetplanStatus.query_online_state')
    def test_call_cli_ifname(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock):
        status = NetplanStatus()
        iproute2_mock.return_value = [FAKE_DEV, self._get_itf('wlan0')]
        networkd_mock.return_value = status.process_networkd(NETWORKD)
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        out = self._call([FAKE_DEV['ifname']])
        self.assertEqual(out.strip(), '''\
Online state: offline

● 42: fakedev0 other DOWN (unmanaged)

1 inactive interfaces hidden. Use "--all" to show all.''')

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    @patch('netplan.cli.commands.status.NetplanStatus.query_nm')
    @patch('netplan.cli.commands.status.NetplanStatus.query_routes')
    @patch('netplan.cli.commands.status.NetplanStatus.query_resolved')
    @patch('netplan.cli.commands.status.NetplanStatus.resolvconf_json')
    @patch('netplan.cli.commands.status.NetplanStatus.query_online_state')
    def test_fail_cli_ifname(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock):
        status = NetplanStatus()
        iproute2_mock.return_value = [FAKE_DEV, self._get_itf('wlan0')]
        networkd_mock.return_value = status.process_networkd(NETWORKD)
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        with self.assertRaises(SystemExit):
            self._call(['notaninteface0'])

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    @patch('netplan.cli.commands.status.NetplanStatus.query_nm')
    @patch('netplan.cli.commands.status.NetplanStatus.query_routes')
    @patch('netplan.cli.commands.status.NetplanStatus.query_resolved')
    @patch('netplan.cli.commands.status.NetplanStatus.resolvconf_json')
    @patch('netplan.cli.commands.status.NetplanStatus.query_online_state')
    def test_call_cli_json(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock):
        status = NetplanStatus()
        iproute2_mock.return_value = [FAKE_DEV]
        networkd_mock.return_value = status.process_networkd(NETWORKD)
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        out = self._call(['-a', '--format=json'])
        self.assertEqual(out, '''{\
"netplan-global-state": {"online": false, "nameservers": {"addresses": [], "search": [], "mode": null}}, \
"fakedev0": {"index": 42, "adminstate": "DOWN", "operstate": "DOWN"}}\n''')

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    @patch('netplan.cli.commands.status.NetplanStatus.query_nm')
    @patch('netplan.cli.commands.status.NetplanStatus.query_routes')
    @patch('netplan.cli.commands.status.NetplanStatus.query_resolved')
    @patch('netplan.cli.commands.status.NetplanStatus.resolvconf_json')
    @patch('netplan.cli.commands.status.NetplanStatus.query_online_state')
    def test_call_cli_yaml(self, online_mock, resolvconf_mock, rd_mock, routes_mock, nm_mock, networkd_mock, iproute2_mock):
        status = NetplanStatus()
        iproute2_mock.return_value = [FAKE_DEV]
        networkd_mock.return_value = status.process_networkd(NETWORKD)
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
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

    @patch('netplan.cli.commands.status.NetplanStatus.query_iproute2')
    @patch('netplan.cli.commands.status.NetplanStatus.query_networkd')
    @patch('netplan.cli.commands.status.NetplanStatus.query_nm')
    @patch('netplan.cli.commands.status.NetplanStatus.query_routes')
    @patch('netplan.cli.commands.status.NetplanStatus.query_resolved')
    @patch('netplan.cli.commands.status.NetplanStatus.resolvconf_json')
    @patch('netplan.cli.commands.status.NetplanStatus.query_online_state')
    @patch('netplan.cli.utils.systemctl_is_active')
    @patch('netplan.cli.utils.systemctl')
    def test_call_cli_no_networkd(self, systemctl_mock, is_active_mock,
                                  online_mock, resolvconf_mock, rd_mock,
                                  routes_mock, nm_mock, networkd_mock,
                                  iproute2_mock):
        status = NetplanStatus()
        iproute2_mock.return_value = [FAKE_DEV]
        networkd_mock.return_value = status.process_networkd(NETWORKD)
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        is_active_mock.return_value = False
        with self.assertLogs(level='DEBUG') as cm:
            self._call([])
            self.assertIn('DEBUG:root:systemd-networkd.service is not active. Starting...',
                          cm.output[0])
        systemctl_mock.assert_called_once_with('start', ['systemd-networkd.service'], True)


class TestInterface(unittest.TestCase):
    '''Test netplan status' Interface class'''

    @patch('subprocess.check_output')
    def test_query_nm_ssid(self, mock):
        mock.return_value = ' MYSSID '  # added some whitespace to strip()
        con = 'SOME_CONNECTION_ID'
        itf = Interface(FAKE_DEV, [])
        res = itf.query_nm_ssid(con)
        mock.assert_called_with(['nmcli', '--get-values', '802-11-wireless.ssid',
                                 'con', 'show', 'id', con],
                                universal_newlines=True)
        self.assertEqual(res, 'MYSSID')

    @patch('subprocess.check_output')
    def test_query_nm_ssid_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        con = 'SOME_CONNECTION_ID'
        itf = Interface(FAKE_DEV, [])
        with self.assertLogs() as cm:
            res = itf.query_nm_ssid(con)
            mock.assert_called_with(['nmcli', '--get-values', '802-11-wireless.ssid',
                                     'con', 'show', 'id', con],
                                    universal_newlines=True)
            self.assertIsNone(res)
            self.assertIn('WARNING:root:Cannot query NetworkManager SSID for {}:'.format(con), cm.output[0])

    @patch('subprocess.check_output')
    def test_query_networkctl(self, mock):
        mock.return_value = 'DOES NOT MATTER'
        dev = 'fakedev0'
        itf = Interface(FAKE_DEV, [])
        res = itf.query_networkctl(dev)
        mock.assert_called_with(['networkctl', 'status', dev], universal_newlines=True)
        self.assertEqual(res, mock.return_value)

    @patch('subprocess.check_output')
    def test_query_networkctl_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        dev = 'fakedev0'
        itf = Interface(FAKE_DEV, [])
        with self.assertLogs() as cm:
            res = itf.query_networkctl(dev)
            mock.assert_called_with(['networkctl', 'status', dev], universal_newlines=True)
            self.assertIsNone(res)
            self.assertIn('WARNING:root:Cannot query networkctl for {}:'.format(dev), cm.output[0])

    @patch('netplan.cli.commands.status.Interface.query_nm_ssid')
    @patch('netplan.cli.commands.status.Interface.query_networkctl')
    def test_json_nm_wlan0(self, networkctl_mock, nm_ssid_mock):
        SSID = 'MYCON'
        nm_ssid_mock.return_value = SSID
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = \
            'WiFi access point: {} (b4:fb:e4:75:c6:21)'.format(SSID)

        status = NetplanStatus()
        data = next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifindex'] == 5), {})
        nd = status.process_networkd(NETWORKD)
        nm = status.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (status.process_generic(ROUTE4), status.process_generic(ROUTE6))

        itf = Interface(data, nd, nm, dns, routes)
        self.assertTrue(itf.up)
        self.assertFalse(itf.down)
        ifname, json = itf.json()
        self.assertEqual(ifname, 'wlan0')
        self.assertEqual(json.get('index'), 5)
        self.assertEqual(json.get('macaddress'), '1c:4d:70:e4:e4:0e')
        self.assertEqual(json.get('type'), 'wifi')
        self.assertEqual(json.get('ssid'), 'MYCON')
        self.assertEqual(json.get('backend'), 'NetworkManager')
        self.assertEqual(json.get('id'), 'NM-b6b7a21d-186e-45e1-b3a6-636da1735563')
        self.assertEqual(json.get('vendor'), 'Intel Corporation')
        self.assertEqual(json.get('adminstate'), 'UP')
        self.assertEqual(json.get('operstate'), 'UP')
        self.assertEqual(len(json.get('addresses')), 4)
        self.assertEqual(len(json.get('dns_addresses')), 2)
        self.assertEqual(len(json.get('dns_search')), 1)
        self.assertEqual(len(json.get('routes')), 6)

    @patch('netplan.cli.commands.status.Interface.query_networkctl')
    def test_json_nd_enp0s31f6(self, networkctl_mock):
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = 'Activation Policy: manual'

        status = NetplanStatus()
        data = next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifindex'] == 2), {})
        nd = status.process_networkd(NETWORKD)
        nm = status.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (status.process_generic(ROUTE4), status.process_generic(ROUTE6))

        itf = Interface(data, nd, nm, dns, routes)
        self.assertTrue(itf.up)
        self.assertFalse(itf.down)
        ifname, json = itf.json()
        self.assertEqual(ifname, 'enp0s31f6')
        self.assertEqual(json.get('index'), 2)
        self.assertEqual(json.get('macaddress'), '54:e1:ad:5f:24:b4')
        self.assertEqual(json.get('type'), 'ethernet')
        self.assertEqual(json.get('backend'), 'networkd')
        self.assertEqual(json.get('id'), 'enp0s31f6')
        self.assertEqual(json.get('vendor'), 'Intel Corporation')
        self.assertEqual(json.get('adminstate'), 'UP')
        self.assertEqual(json.get('operstate'), 'UP')
        self.assertEqual(json.get('activation_mode'), 'manual')
        self.assertEqual(len(json.get('addresses')), 3)
        _, meta = list(json.get('addresses')[0].items())[0]  # get first (any only) address
        self.assertIn('dhcp', meta.get('flags'))
        self.assertEqual(len(json.get('dns_addresses')), 2)
        self.assertEqual(len(json.get('dns_search')), 1)
        self.assertEqual(len(json.get('routes')), 7)

    def test_json_nd_tunnel(self):
        status = NetplanStatus()
        data = next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifindex'] == 41), {})
        nd = status.process_networkd(NETWORKD)

        itf = Interface(data, nd, [], (None, None), (None, None))
        ifname, json = itf.json()
        self.assertEqual(ifname, 'wg0')
        self.assertEqual(json.get('index'), 41)
        self.assertEqual(json.get('type'), 'tunnel')
        self.assertEqual(json.get('backend'), 'networkd')
        self.assertEqual(json.get('tunnel_mode'), 'wireguard')

    def test_json_no_type_id_backend(self):
        itf = Interface(FAKE_DEV, [], [], (None, None), (None, None))
        ifname, json = itf.json()
        self.assertEqual(ifname, 'fakedev0')
        self.assertEqual(json.get('index'), 42)
        self.assertNotIn('type', json)
        self.assertNotIn('id', json)
        self.assertNotIn('backend', json)
