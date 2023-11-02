#!/usr/bin/python3
# Closed-box tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2023 Canonical, Ltd.
# Authors: Lukas Märdian <slyon@ubuntu.com>
#          Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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
import os
import shutil
import subprocess
import tempfile
import unittest
import yaml

from unittest.mock import patch, call, mock_open
from netplan_cli.cli.state import Interface, NetplanConfigState, SystemConfigState
from .test_status import (BRIDGE, DNS_ADDRESSES, DNS_IP4, DNS_SEARCH, FAKE_DEV,
                          IPROUTE2, NETWORKD, NMCLI, ROUTE4, ROUTE6)


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


class TestSystemState(unittest.TestCase):
    '''Test netplan state module'''

    def setUp(self):
        self.maxDiff = None

    @patch('subprocess.check_output')
    def test_query_iproute2(self, mock):
        mock.return_value = IPROUTE2
        res = SystemConfigState.query_iproute2()
        mock.assert_called_with(['ip', '-d', '-j', 'addr'], text=True)
        self.assertEqual(len(res), 6)
        self.assertListEqual([itf.get('ifname') for itf in res],
                             ['lo', 'enp0s31f6', 'wlan0', 'wg0', 'wwan0', 'tun0'])

    @patch('subprocess.check_output')
    def test_query_iproute2_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        with self.assertLogs() as cm:
            res = SystemConfigState.query_iproute2()
            mock.assert_called_with(['ip', '-d', '-j', 'addr'], text=True)
            self.assertIsNone(res)
            self.assertIn('CRITICAL:root:Cannot query iproute2 interface data:', cm.output[0])

    @patch('subprocess.check_output')
    def test_query_networkd(self, mock):
        mock.return_value = NETWORKD
        res = SystemConfigState.query_networkd()
        mock.assert_called_with(['networkctl', '--json=short'], text=True)
        self.assertEqual(len(res), 8)
        self.assertListEqual([itf.get('Name') for itf in res],
                             ['lo', 'enp0s31f6', 'wlan0', 'wg0', 'wwan0', 'tun0', 'mybr0', 'mybond0'])

    @patch('subprocess.check_output')
    def test_query_networkd_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        with self.assertLogs() as cm:
            res = SystemConfigState.query_networkd()
            mock.assert_called_with(['networkctl', '--json=short'], text=True)
            self.assertIsNone(res)
            self.assertIn('CRITICAL:root:Cannot query networkd interface data:', cm.output[0])

    @patch('subprocess.check_output')
    def test_query_nm(self, mock):
        mock.return_value = NMCLI
        res = SystemConfigState.query_nm()
        mock.assert_called_with(['nmcli', '-t', '-f',
                                 'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                 'con', 'show'], text=True)
        self.assertEqual(len(res), 1)
        self.assertListEqual([itf.get('device') for itf in res], ['wlan0'])

    @patch('subprocess.check_output')
    def test_query_nm_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        with self.assertLogs(level='DEBUG') as cm:
            res = SystemConfigState.query_nm()
            mock.assert_called_with(['nmcli', '-t', '-f',
                                     'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                     'con', 'show'], text=True)
            self.assertIsNone(res)
            self.assertIn('DEBUG:root:Cannot query NetworkManager interface data:', cm.output[0])

    @patch('subprocess.check_output')
    def test_query_routes(self, mock):
        mock.side_effect = [ROUTE4, ROUTE6]
        res4, res6 = SystemConfigState.query_routes()
        mock.assert_has_calls([
            call(['ip', '-d', '-j', '-4', 'route', 'show', 'table', 'all'], text=True),
            call(['ip', '-d', '-j', '-6', 'route', 'show', 'table', 'all'], text=True),
            ])
        self.assertEqual(len(res4), 7)
        self.assertListEqual([route.get('dev') for route in res4],
                             ['enp0s31f6', 'wlan0', 'wg0', 'enp0s31f6', 'wlan0', 'enp0s31f6', 'enp0s31f6'])
        self.assertEqual(len(res6), 10)
        self.assertListEqual([route.get('dev') for route in res6],
                             ['lo', 'enp0s31f6', 'wlan0', 'enp0s31f6', 'wlan0',
                              'tun0', 'enp0s31f6', 'wlan0', 'enp0s31f6', 'wlan0'])

    @patch('subprocess.check_output')
    def test_query_routes_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        with self.assertLogs(level='DEBUG') as cm:
            res4, res6 = SystemConfigState.query_routes()
            mock.assert_called_with(['ip', '-d', '-j', '-4', 'route', 'show', 'table', 'all'], text=True)
            self.assertIsNone(res4)
            self.assertIsNone(res6)
            self.assertIn('DEBUG:root:Cannot query iproute2 route data:', cm.output[0])

    @patch('dbus.Interface')
    @patch('dbus.SystemBus')
    def test_query_resolved(self, mock_ipc, mock_iface):
        mock_ipc.return_value = resolve1_ipc_mock()
        mock_iface.return_value = resolve1_iface_mock('foo', 'bar')
        addresses, search = SystemConfigState.query_resolved()
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
        with self.assertLogs(level='DEBUG') as cm:
            addresses, search = SystemConfigState.query_resolved()
            self.assertIsNone(addresses)
            self.assertIsNone(search)
            self.assertIn('DEBUG:root:Cannot query resolved DNS data:', cm.output[0])

    def test_query_resolvconf(self):
        with patch('builtins.open', mock_open(read_data='''\
nameserver 1.1.1.1
nameserver 8.8.8.8
options edns0 trust-ad
search   some.domain
search search.domain  another.one
''')):
            res = SystemConfigState.resolvconf_json()
            print(res)
            self.assertListEqual(res.get('addresses'), ['1.1.1.1', '8.8.8.8'])
            self.assertListEqual(res.get('search'), ['search.domain', 'another.one'])
            self.assertEqual(res.get('mode'), None)

    def test_query_resolvconf_stub(self):
        with patch('builtins.open', mock_open(read_data='\
# This is /run/systemd/resolve/stub-resolv.conf managed by man:systemd-resolved(8).')):
            res = SystemConfigState.resolvconf_json()
            self.assertEqual(res.get('mode'), 'stub')

    def test_query_resolvconf_compat(self):
        with patch('builtins.open', mock_open(read_data='\
# This is /run/systemd/resolve/resolv.conf managed by man:systemd-resolved(8).')):
            res = SystemConfigState.resolvconf_json()
            self.assertEqual(res.get('mode'), 'compat')

    def test_query_resolvconf_fail(self):
        with self.assertLogs() as cm:
            with patch('builtins.open', mock_open(read_data='')) as mock_file:
                mock_file.side_effect = Exception(1, '', 'ERR')
                SystemConfigState.resolvconf_json()
                self.assertIn('WARNING:root:Cannot parse /etc/resolv.conf:', cm.output[0])

    def test_query_online_state_online(self):
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
        res = SystemConfigState.query_online_state([Interface(dev, [], [], (dns, None), (routes, None))])
        self.assertTrue(res)

    def test_query_online_state_offline(self):
        res = SystemConfigState.query_online_state([Interface(FAKE_DEV, [])])
        self.assertFalse(res)

    @patch('netplan_cli.cli.utils.systemctl')
    @patch('netplan_cli.cli.state.SystemConfigState.query_members')
    @patch('netplan_cli.cli.state.SystemConfigState.query_iproute2')
    @patch('netplan_cli.cli.state.SystemConfigState.query_networkd')
    @patch('netplan_cli.cli.state.SystemConfigState.query_nm')
    @patch('netplan_cli.cli.state.SystemConfigState.query_routes')
    @patch('netplan_cli.cli.state.SystemConfigState.query_resolved')
    @patch('netplan_cli.cli.state.SystemConfigState.resolvconf_json')
    @patch('netplan_cli.cli.state.SystemConfigState.query_online_state')
    def test_system_state_config_data_interfaces(self, online_mock, resolvconf_mock, rd_mock,
                                                 routes_mock, nm_mock, networkd_mock, iproute2_mock,
                                                 members_mock, systemctl_mock):
        systemctl_mock.return_value = None
        members_mock.return_value = []
        iproute2_mock.return_value = [FAKE_DEV, BRIDGE]
        nm_mock.return_value = []
        routes_mock.return_value = (None, None)
        rd_mock.return_value = (None, None)
        resolvconf_mock.return_value = {'addresses': [], 'search': [], 'mode': None}
        online_mock.return_value = False
        networkd_mock.return_value = SystemConfigState.process_networkd(NETWORKD)
        state = SystemConfigState()
        self.assertIn('fakedev0', [iface.name for iface in state.interface_list])

    @patch('subprocess.check_output')
    def test_query_members(self, mock):
        mock.return_value = '[{"ifname":"eth0"}, {"ifname":"eth1"}]'
        members = SystemConfigState.query_members('mybr0')
        mock.assert_has_calls([
            call(['ip', '-d', '-j', 'link', 'show', 'master', 'mybr0'], text=True),     # wokeignore:rule=master
            ])
        self.assertListEqual(members, ['eth0', 'eth1'])

    @patch('subprocess.check_output')
    def test_query_members_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        with self.assertLogs(level='WARNING') as cm:
            bridge = SystemConfigState.query_members('mybr0')
            mock.assert_has_calls([
                call(['ip', '-d', '-j', 'link', 'show', 'master', 'mybr0'], text=True),     # wokeignore:rule=master
                ])
            self.assertListEqual(bridge, [])
            self.assertIn('WARNING:root:Cannot query bridge:', cm.output[0])

    @classmethod
    def mock_query_members(cls, interface):
        if interface == 'br0':
            return ['eth0', 'eth1']
        if interface == 'bond0':
            return ['eth2', 'eth3']

    @patch('netplan_cli.cli.state.SystemConfigState.query_members')
    def test_correlate_members_and_uplink_bridge(self, mock):
        mock.side_effect = self.mock_query_members
        interface1 = Interface({'ifname': 'eth0'})
        interface1.nd = {'Type': 'ether'}
        interface2 = Interface({'ifname': 'eth1'})
        interface2.nd = {'Type': 'ether'}
        interface3 = Interface({'ifname': 'br0'})
        interface3.nd = {'Type': 'bridge'}
        SystemConfigState.correlate_members_and_uplink([interface1, interface2, interface3])
        self.assertEqual(interface1.bridge, 'br0')
        self.assertEqual(interface2.bridge, 'br0')
        self.assertListEqual(interface3.members, ['eth0', 'eth1'])

    @patch('netplan_cli.cli.state.SystemConfigState.query_members')
    def test_correlate_members_and_uplink_bond(self, mock):
        mock.side_effect = self.mock_query_members
        interface1 = Interface({'ifname': 'eth2'})
        interface1.nd = {'Type': 'ether'}
        interface2 = Interface({'ifname': 'eth3'})
        interface2.nd = {'Type': 'ether'}
        interface3 = Interface({'ifname': 'bond0'})
        interface3.nd = {'Type': 'bond'}
        SystemConfigState.correlate_members_and_uplink([interface1, interface2, interface3])
        self.assertEqual(interface1.bond, 'bond0')
        self.assertEqual(interface2.bond, 'bond0')
        self.assertListEqual(interface3.members, ['eth2', 'eth3'])


class TestNetplanState(unittest.TestCase):
    '''Test netplan state NetplanConfigState class'''

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory(prefix='netplan_')
        self.file = '70-netplan-set.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: true
  bridges:
    br0:
      dhcp4: true''')

    def tearDown(self):
        shutil.rmtree(self.workdir.name)

    def test_get_data(self):
        state = NetplanConfigState(rootdir=self.workdir.name)
        state_data = state.get_data()
        self.assertIn('eth0', state_data.get('network').get('ethernets'))
        self.assertIn('br0', state_data.get('network').get('bridges'))

    def test_get_data_subtree(self):
        state = NetplanConfigState(subtree='ethernets', rootdir=self.workdir.name)
        state_data = state.get_data()
        self.assertIn('eth0', state_data)
        self.assertNotIn('br0', state_data)


class TestInterface(unittest.TestCase):
    '''Test netplan state Interface class'''

    @patch('subprocess.check_output')
    def test_query_nm_ssid(self, mock):
        mock.return_value = ' MYSSID '  # added some whitespace to strip()
        con = 'SOME_CONNECTION_ID'
        itf = Interface(FAKE_DEV, [])
        res = itf.query_nm_ssid(con)
        mock.assert_called_with(['nmcli', '--get-values', '802-11-wireless.ssid',
                                 'con', 'show', 'id', con],
                                text=True)
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
                                    text=True)
            self.assertIsNone(res)
            self.assertIn('WARNING:root:Cannot query NetworkManager SSID for {}:'.format(con), cm.output[0])

    @patch('subprocess.check_output')
    def test_query_networkctl(self, mock):
        mock.return_value = 'DOES NOT MATTER'
        dev = 'fakedev0'
        itf = Interface(FAKE_DEV, [])
        res = itf.query_networkctl(dev)
        mock.assert_called_with(['networkctl', 'status', '--', dev], text=True)
        self.assertEqual(res, mock.return_value)

    @patch('subprocess.check_output')
    def test_query_networkctl_fail(self, mock):
        mock.side_effect = subprocess.CalledProcessError(1, '', 'ERR')
        dev = 'fakedev0'
        itf = Interface(FAKE_DEV, [])
        with self.assertLogs() as cm:
            res = itf.query_networkctl(dev)
            mock.assert_called_with(['networkctl', 'status', '--', dev], text=True)
            self.assertIsNone(res)
            self.assertIn('WARNING:root:Cannot query networkctl for {}:'.format(dev), cm.output[0])

    @patch('netplan_cli.cli.state.Interface.query_nm_ssid')
    @patch('netplan_cli.cli.state.Interface.query_networkctl')
    def test_json_nm_wlan0(self, networkctl_mock, nm_ssid_mock):
        SSID = 'MYCON'
        nm_ssid_mock.return_value = SSID
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = \
            'WiFi access point: {} (b4:fb:e4:75:c6:21)'.format(SSID)

        data = next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifindex'] == 5), {})
        nd = SystemConfigState.process_networkd(NETWORKD)
        nm = SystemConfigState.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (SystemConfigState.process_generic(ROUTE4), SystemConfigState.process_generic(ROUTE6))

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

    @patch('netplan_cli.cli.state.Interface.query_networkctl')
    def test_json_nd_enp0s31f6(self, networkctl_mock):
        # networkctl mock output reduced to relevant lines
        networkctl_mock.return_value = 'Activation Policy: manual'

        data = next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifindex'] == 2), {})
        nd = SystemConfigState.process_networkd(NETWORKD)
        nm = SystemConfigState.process_nm(NMCLI)
        dns = (DNS_ADDRESSES, DNS_SEARCH)
        routes = (SystemConfigState.process_generic(ROUTE4), SystemConfigState.process_generic(ROUTE6))

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
        self.assertEqual(len(json.get('routes')), 8)

    def test_json_nd_tunnel(self):
        data = next((itf for itf in yaml.safe_load(IPROUTE2) if itf['ifindex'] == 41), {})
        nd = SystemConfigState.process_networkd(NETWORKD)

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
