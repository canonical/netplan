#!/usr/bin/python3
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

'''netplan status command line'''

import dbus
import ipaddress
import logging
import socket
import subprocess
import sys
import yaml
import netplan.cli.utils as utils

from typing import Union, Dict, List, Type

JSON = Union[Dict[str, 'JSON'], List['JSON'], int, str, float, bool, Type[None]]


class Interface():
    def __init__(self, ip: JSON, nd_data: JSON = [], nm_data: JSON = [],
                 resolved_data: tuple = (None, None), route_data: tuple = (None, None)):
        self.idx: int = ip['ifindex']
        self.name: str = ip['ifname']
        self.adminstate: str = 'UP' if 'UP' in ip['flags'] else 'DOWN'
        self.operstate: str = ip['operstate'].upper()
        self.macaddress: str = None
        if 'address' in ip and len(ip['address']) == 17:  # 6 byte MAC
            self.macaddress = ip['address'].lower()

        # Filter networkd/NetworkManager data
        self.nd: JSON = next((x for x in nd_data if x['Index'] == self.idx), None)
        self.nm: JSON = next((x for x in nm_data if x['device'] == self.name), None)

        # Filter resolved's DNS data
        self.dns_addresses: list = None
        if resolved_data[0] and len(resolved_data[0]) > 0:
            self.dns_addresses = []
            for itr in resolved_data[0]:
                if int(itr[0]) == int(self.idx):
                    ipfamily = itr[1]
                    dns = itr[2]
                    self.dns_addresses.append(socket.inet_ntop(ipfamily, b''.join([v.to_bytes(1, 'big') for v in dns])))
        self.dns_search: list = None
        if resolved_data[1] and len(resolved_data[1]) > 0:
            self.dns_search = []
            for v in resolved_data[1]:
                if int(v[0]) == int(self.idx):
                    self.dns_search.append(str(v[1]))

        # Filter route data
        _routes: list = []
        self.routes: list = None
        if route_data[0] and len(route_data[0]) > 0:
            _routes += route_data[0]
        if route_data[1] and len(route_data[1]) > 0:
            _routes += route_data[1]
        if len(_routes) > 0:
            self.routes = []
            for obj in _routes:
                if obj.get('dev') == self.name:
                    elem = {'to': obj.get('dst')}
                    val = obj.get('gateway')
                    if val:
                        elem['via'] = val
                    val = obj.get('prefsrc')
                    if val:
                        elem['from'] = val
                    val = obj.get('metric')
                    if val:
                        elem['metric'] = val
                    val = obj.get('type')
                    if val:
                        elem['type'] = val
                    val = obj.get('scope')
                    if val:
                        elem['scope'] = val
                    val = obj.get('protocol')
                    if val:
                        elem['protocol'] = val
                    self.routes.append(elem)

        self.addresses: list = None
        if 'addr_info' in ip and len(ip['addr_info']) > 0:
            self.addresses = []
            for addr in ip['addr_info']:
                flags = []
                if ipaddress.ip_address(addr['local']).is_link_local:
                    flags.append('link')
                if self.routes:
                    for route in self.routes:
                        if ('from' in route and
                                ipaddress.ip_address(route['from']) == ipaddress.ip_address(addr['local'])):
                            if route['protocol'] == 'dhcp':
                                flags.append('dhcp')
                                break
                ip_addr = addr['local'].lower()
                elem = {ip_addr: {'prefix': addr['prefixlen']}}
                if len(flags) > 0:
                    elem[ip_addr]['flags'] = flags
                self.addresses.append(elem)

        self.iproute_type: str = None
        if 'linkinfo' in ip and 'info_kind' in ip['linkinfo']:
            self.iproute_type = ip['linkinfo']['info_kind'].strip()

        # workaround: query some data which is not available via networkctl's JSON output
        self._networkctl: str = self.query_networkctl(self.name) or ''

    def query_nm_ssid(self, con_name: str) -> str:
        ssid: str = None
        try:
            ssid = subprocess.check_output(['nmcli', '--get-values',
                                            '802-11-wireless.ssid', 'con',
                                            'show', 'id', con_name],
                                           universal_newlines=True)
            return ssid.strip()
        except Exception as e:
            logging.warning('Cannot query NetworkManager SSID for {}: {}'.format(
                            con_name, str(e)))
        return ssid

    def query_networkctl(self, ifname: str) -> str:
        output: str = None
        try:
            output = subprocess.check_output(['networkctl', 'status', ifname],
                                             universal_newlines=True)
        except Exception as e:
            logging.warning('Cannot query networkctl for {}: {}'.format(
                ifname, str(e)))
        return output

    def json(self) -> JSON:
        json = {
            'index': self.idx,
            'adminstate': self.adminstate,
            'operstate': self.operstate,
            }
        if self.type:
            json['type'] = self.type
        if self.ssid:
            json['ssid'] = self.ssid
        if self.tunnel_mode:
            json['tunnel_mode'] = self.tunnel_mode
        if self.backend:
            json['backend'] = self.backend
        if self.netdef_id:
            json['id'] = self.netdef_id
        if self.macaddress:
            json['macaddress'] = self.macaddress
        if self.vendor:
            json['vendor'] = self.vendor
        if self.addresses:
            json['addresses'] = self.addresses
        if self.dns_addresses:
            json['dns_addresses'] = self.dns_addresses
        if self.dns_search:
            json['dns_search'] = self.dns_search
        if self.routes:
            json['routes'] = self.routes
        if self.activation_mode:
            json['activation_mode'] = self.activation_mode
        return (self.name, json)

    @property
    def up(self) -> bool:
        return self.adminstate == 'UP' and self.operstate == 'UP'

    @property
    def down(self) -> bool:
        return self.adminstate == 'DOWN' and self.operstate == 'DOWN'

    @property
    def type(self) -> str:
        match = dict({
            'bond': 'bond',
            'bridge': 'bridge',
            'ether': 'ethernet',
            'ipgre': 'tunnel',
            'ip6gre': 'tunnel',
            'loopback': 'ethernet',
            'sit': 'tunnel',
            'tunnel': 'tunnel',
            'tunnel6': 'tunnel',
            'wireguard': 'tunnel',
            'wlan': 'wifi',
            'wwan': 'modem',
            'vrf': 'vrf',
            'vxlan': 'tunnel',
            })
        nd_type = self.nd.get('Type') if self.nd else None
        if nd_type in match:
            return match[nd_type]
        logging.warning('Unknown device type: {}'.format(nd_type))
        return None

    @property
    def tunnel_mode(self) -> str:
        if self.type == 'tunnel' and self.iproute_type:
            return self.iproute_type
        return None

    @property
    def backend(self) -> str:
        if (self.nd and
                'unmanaged' not in self.nd.get('SetupState', '') and
                'run/systemd/network/10-netplan-' in self.nd.get('NetworkFile', '')):
            return 'networkd'
        elif self.nm and 'run/NetworkManager/system-connections/netplan-' in self.nm.get('filename', ''):
            return 'NetworkManager'
        return None

    @property
    def netdef_id(self) -> str:
        if self.backend == 'networkd':
            return self.nd.get('NetworkFile', '').split(
                'run/systemd/network/10-netplan-')[1].split('.network')[0]
        elif self.backend == 'NetworkManager':
            netdef = self.nm.get('filename', '').split(
                'run/NetworkManager/system-connections/netplan-')[1].split('.nmconnection')[0]
            if self.nm.get('type', '') == '802-11-wireless':
                ssid = self.query_nm_ssid(self.nm.get('name'))
                if ssid:  # XXX: escaping needed?
                    netdef = netdef.split('-' + ssid)[0]
            return netdef
        return None

    @property
    def vendor(self) -> str:
        if self.nd and 'Vendor' in self.nd and self.nd['Vendor']:
            return self.nd['Vendor'].strip()
        return None

    @property
    def ssid(self) -> str:
        if self.type == 'wifi':
            # XXX: this data is missing from networkctl's JSON output
            for line in self._networkctl.splitlines():
                line = line.strip()
                key = 'WiFi access point: '
                if line.startswith(key):
                    ssid = line[len(key):-len(' (xB:SS:ID:xx:xx:xx)')].strip()
                    return ssid if ssid else None
        return None

    @property
    def activation_mode(self) -> str:
        if self.backend == 'networkd':
            # XXX: this data is missing from networkctl's JSON output
            for line in self._networkctl.splitlines():
                line = line.strip()
                key = 'Activation Policy: '
                if line.startswith(key):
                    mode = line[len(key):].strip()
                    return mode if mode != 'up' else None
        # XXX: this is not fully supported on NetworkManager, only 'manual'/'up'
        elif self.backend == 'NetworkManager':
            return 'manual' if self.nm['autoconnect'] == 'no' else None
        return None


class NetplanStatus(utils.NetplanCommand):
    def __init__(self):
        super().__init__(command_id='status',
                         description='Query networking state of the running system',
                         leaf=True)
        self.all = False

    def run(self):
        self.parser.add_argument('-a', '--all', action='store_true', help='Show all interface data (incl. inactive)')
        self.parser.add_argument('-f', '--format', default='json', help='Output in machine readable JSON/YAML format')

        self.func = self.command
        self.parse_args()
        self.run_command()

    def process_generic(self, cmd_output: str) -> JSON:
        return yaml.safe_load(cmd_output)

    def query_iproute2(self) -> JSON:
        data = None
        try:
            output: str = subprocess.check_output(['ip', '-d', '-j', 'addr'],
                                                  universal_newlines=True)
            data: JSON = self.process_generic(output)
        except Exception as e:
            logging.critical('Cannot query iproute2 interface data: {}'.format(str(e)))
        return data

    def process_networkd(self, cmd_output) -> JSON:
        return yaml.safe_load(cmd_output)['Interfaces']

    def query_networkd(self) -> JSON:
        data = None
        try:
            output: str = subprocess.check_output(['networkctl', '--json=short'],
                                                  universal_newlines=True)
            data: JSON = self.process_networkd(output)
        except Exception as e:
            logging.critical('Cannot query networkd interface data: {}'.format(str(e)))
        return data

    def process_nm(self, cmd_output) -> JSON:
        data: JSON = []
        for line in cmd_output.splitlines():
            split = line.split(':')
            dev = split[0] if split[0] else None
            if dev:  # ignore inactive connection profiles
                data.append({
                    'device': dev,
                    'name': split[1],
                    'uuid': split[2],
                    'filename': split[3],
                    'type': split[4],
                    'autoconnect': split[5],
                    })
        return data

    def query_nm(self) -> JSON:
        data = None
        try:
            output: str = subprocess.check_output(['nmcli', '-t', '-f',
                                                   'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                                   'con', 'show'],
                                                  universal_newlines=True)
            data: JSON = self.process_nm(output)
        except Exception as e:
            logging.debug('Cannot query NetworkManager interface data: {}'.format(str(e)))
        return data

    def query_routes(self) -> tuple:
        data4 = None
        data6 = None
        try:
            output4: str = subprocess.check_output(['ip', '-d', '-j', 'route'],
                                                   universal_newlines=True)
            data4: JSON = self.process_generic(output4)
            output6: str = subprocess.check_output(['ip', '-d', '-j', '-6', 'route'],
                                                   universal_newlines=True)
            data6: JSON = self.process_generic(output6)
        except Exception as e:
            logging.debug('Cannot query iproute2 route data: {}'.format(str(e)))
        return (data4, data6)

    def query_resolved(self) -> tuple:
        addresses = None
        search = None
        try:
            ipc = dbus.SystemBus()
            resolve1 = ipc.get_object('org.freedesktop.resolve1', '/org/freedesktop/resolve1')
            resolve1_if = dbus.Interface(resolve1, 'org.freedesktop.DBus.Properties')
            res = resolve1_if.GetAll('org.freedesktop.resolve1.Manager')
            addresses = res['DNS']
            search = res['Domains']
        except Exception as e:
            logging.debug('Cannot query resolved DNS data: {}'.format(str(e)))
        return (addresses, search)

    def command(self):
        # required data: iproute2 and sd-networkd can be expected to exist,
        # due to hard package dependencies
        iproute2 = self.query_iproute2()
        networkd = self.query_networkd()
        if not iproute2 or not networkd:
            logging.error('Could not query iproute2 or systemd-networkd')
            sys.exit(1)

        # optional data
        nmcli = self.query_nm()
        route4, route6 = self.query_routes()
        dns_addresses, dns_search = self.query_resolved()

        interfaces = [Interface(itf, networkd, nmcli, (dns_addresses, dns_search), (route4, route6)) for itf in iproute2]
        # show only active interfaces by default
        filtered = [itf for itf in interfaces if itf.operstate != 'DOWN']

        # Per interface
        itf_iter = interfaces if self.all else filtered
        for itf in itf_iter:
            idx = itf.idx
            dev = itf.name
            print('● {idx}: {name}'.format(idx=idx, name=dev))
