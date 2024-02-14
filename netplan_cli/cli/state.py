#!/usr/bin/python3
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


from collections import defaultdict, namedtuple
import ipaddress
import json
import logging
import re
import socket
import subprocess
import sys
from io import StringIO
from typing import Dict, List, Type, Union

import yaml

import dbus
import netplan

from . import utils

JSON = Union[Dict[str, 'JSON'], List['JSON'], int, str, float, bool, Type[None]]

DEVICE_TYPES = {
    'bond': 'bond',
    'bridge': 'bridge',
    'dummy': 'dummy-device',
    'erspan': 'tunnel',
    'ether': 'ethernet',
    'gretap': 'tunnel',
    'ipgre': 'tunnel',
    'ip6gre': 'tunnel',
    'loopback': 'ethernet',
    'sit': 'tunnel',
    'tunnel': 'tunnel',
    'tun': 'tunnel',
    'tunnel6': 'tunnel',
    'wireguard': 'tunnel',
    'wlan': 'wifi',
    'wwan': 'modem',
    'veth': 'virtual-ethernet',
    'vlan': 'vlan',
    'vrf': 'vrf',
    'vxlan': 'tunnel',

    # Netplan netdef types
    'wifis': 'wifi',
    'ethernets': 'ethernet',
    'bridges': 'bridge',
    'bonds': 'bond',
    'nm-devices': 'nm-device',
    'dummy-devices': 'dummy-device',
    'modems': 'modem',
    'vlans': 'vlan',
    'vrfs': 'vrf',
    }


class Interface():
    def __extract_mac(self, ip: dict) -> str:
        '''
        Extract the MAC address if it's set inside the JSON data and seems to
        have the correct format. Return 'None' otherwise.
        '''
        if len(address := ip.get('address', '')) == 17:  # 6 byte MAC (+5 colons)
            return address.lower()
        return None

    def __init__(self, ip: dict, nd_data: JSON = [], nm_data: JSON = [],
                 resolved_data: tuple = (None, None), route_data: tuple = (None, None)):
        self.idx: int = ip.get('ifindex', -1)
        self.name: str = ip.get('ifname', 'unknown')
        self.adminstate: str = 'UP' if 'UP' in ip.get('flags', []) else 'DOWN'
        self.operstate: str = ip.get('operstate', 'unknown').upper()
        self.macaddress: str = self.__extract_mac(ip)
        self.bridge: str = None
        self.bond: str = None
        self.vrf: str = None
        self.members: List[str] = []

        # Filter networkd/NetworkManager data
        nm_data = nm_data or []  # avoid 'None' value on systems without NM
        self.nd: JSON = next((x for x in nd_data if x['Index'] == self.idx), None)
        self.nm: JSON = next((x for x in nm_data if x['device'] == self.name), None)

        # Filter resolved's DNS data
        self.dns_addresses: list = None
        if resolved_data[0]:
            self.dns_addresses = []
            for itr in resolved_data[0]:
                if int(itr[0]) == int(self.idx):
                    ipfamily = itr[1]
                    dns = itr[2]
                    self.dns_addresses.append(socket.inet_ntop(ipfamily, b''.join([v.to_bytes(1, 'big') for v in dns])))
        self.dns_search: list = None
        if resolved_data[1]:
            self.dns_search = []
            for v in resolved_data[1]:
                if int(v[0]) == int(self.idx):
                    self.dns_search.append(str(v[1]))

        # Filter route data
        _routes: list = []
        self.routes: list = None
        if route_data[0]:
            _routes += route_data[0]
        if route_data[1]:
            _routes += route_data[1]
        if _routes:
            self.routes = []
            for obj in _routes:
                if obj.get('dev') == self.name:
                    elem = {'to': obj.get('dst')}
                    if val := obj.get('family'):
                        elem['family'] = val
                    if val := obj.get('gateway'):
                        elem['via'] = val
                    if val := obj.get('prefsrc'):
                        elem['from'] = val
                    if val := obj.get('metric'):
                        elem['metric'] = val
                    if val := obj.get('type'):
                        elem['type'] = val
                    if val := obj.get('scope'):
                        elem['scope'] = val
                    if val := obj.get('protocol'):
                        elem['protocol'] = val
                    if val := obj.get('table'):
                        elem['table'] = val
                    self.routes.append(elem)

        self.addresses: list = None
        if addr_info := ip.get('addr_info'):
            self.addresses = []
            for addr in addr_info:
                flags: list = []
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
                if flags:
                    elem[ip_addr]['flags'] = flags
                self.addresses.append(elem)

        self.iproute_type: str = None
        if info_kind := ip.get('linkinfo', {}).get('info_kind'):
            self.iproute_type = info_kind.strip()

        # workaround: query some data which is not available via networkctl's JSON output
        self._networkctl: str = self.query_networkctl(self.name) or ''

    def query_nm_ssid(self, con_name: str) -> str:
        ssid: str = None
        try:
            ssid = utils.nmcli_out(['--get-values', '802-11-wireless.ssid',
                                    'con', 'show', 'id', con_name])
            return ssid.strip()
        except Exception as e:
            logging.warning('Cannot query NetworkManager SSID for {}: {}'.format(
                            con_name, str(e)))
        return ssid

    def query_networkctl(self, ifname: str) -> str:
        output: str = None
        try:
            output = subprocess.check_output(['networkctl', 'status', '--', ifname], text=True)
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
        if self.bridge:
            json['bridge'] = self.bridge
        if self.bond:
            json['bond'] = self.bond
        if self.vrf:
            json['vrf'] = self.vrf
        if self.members:
            json['interfaces'] = self.members
        return (self.name, json)

    @property
    def up(self) -> bool:
        return self.adminstate == 'UP' and self.operstate == 'UP'

    @property
    def down(self) -> bool:
        return self.adminstate == 'DOWN' and self.operstate == 'DOWN'

    @property
    def type(self) -> str:
        nd_type = self.nd.get('Type') if self.nd else None
        if nd_type == 'none':
            # If the Type is reported as 'none' by networkd, the interface still might have a Kind.
            nd_type = self.nd.get('Kind')
        if nd_type == 'ether':
            # There are different kinds of 'ether' devices, such as VRFs, veth and dummies
            if kind := self.nd.get('Kind'):
                nd_type = kind
        if device_type := DEVICE_TYPES.get(nd_type):
            return device_type
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
            # XXX: available from networkctl's JSON output as of v250:
            #      https://github.com/systemd/systemd/commit/da7c995
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
            # XXX: available from networkctl's JSON output as of v250:
            #      https://github.com/systemd/systemd/commit/3b60ede
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


class SystemConfigState():
    ''' Collects the system's network configuration '''

    def __init__(self, ifname=None, all=False):
        # Make sure sd-networkd is running, as we need the data it provides.
        if not utils.systemctl_is_active('systemd-networkd.service'):
            if utils.systemctl_is_masked('systemd-networkd.service'):
                logging.error('\'netplan status\' depends on networkd, '
                              'but systemd-networkd.service is masked. '
                              'Please start it.')
                sys.exit(1)
            logging.debug('systemd-networkd.service is not active. Starting...')
            utils.systemctl('start', ['systemd-networkd.service'], True)

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

        self.interface_list = [Interface(itf, networkd, nmcli, (dns_addresses, dns_search),
                                         (route4, route6)) for itf in iproute2]

        # get bridge/bond/vrf data
        self.correlate_members_and_uplink(self.interface_list)

        # show only active interfaces by default
        filtered = [itf for itf in self.interface_list if itf.operstate != 'DOWN']
        # down interfaces do not contribute anything to the online state
        online_state = self.query_online_state(filtered)
        # show only a single interface, if requested
        # XXX: bash completion (for interfaces names)
        if ifname:
            filtered = [next((itf for itf in self.interface_list if itf.name == ifname), None)]
        filtered = [elem for elem in filtered if elem is not None]
        if ifname and filtered == []:
            logging.error('Could not find interface {}'.format(ifname))
            sys.exit(1)

        # Global state
        self.state = {
            'netplan-global-state': {
                'online': online_state,
                'nameservers': self.resolvconf_json()
            }
        }
        # Per interface
        itf_iter = self.interface_list if all else filtered
        for itf in itf_iter:
            ifname, obj = itf.json()
            self.state[ifname] = obj

    @classmethod
    def resolvconf_json(cls) -> dict:
        res = {
            'addresses': [],
            'search': [],
            'mode': None,
            }
        try:
            with open('/etc/resolv.conf') as f:
                # check first line for systemd-resolved stub or compat modes
                firstline = f.readline()
                if '# This is /run/systemd/resolve/stub-resolv.conf' in firstline:
                    res['mode'] = 'stub'
                elif '# This is /run/systemd/resolve/resolv.conf' in firstline:
                    res['mode'] = 'compat'
                for line in [firstline] + f.readlines():
                    if line.startswith('nameserver'):
                        res['addresses'] += line.split()[1:]  # append
                    if line.startswith('search'):
                        res['search'] = line.split()[1:]  # override
        except Exception as e:
            logging.warning('Cannot parse /etc/resolv.conf: {}'.format(str(e)))
        return res

    @classmethod
    def query_online_state(cls, interfaces: list) -> bool:
        # TODO: fully implement network-online.target specification (FO020):
        # https://discourse.ubuntu.com/t/spec-definition-of-an-online-system/27838
        for itf in interfaces:
            if itf.up and itf.addresses and itf.routes and itf.dns_addresses:
                non_local_ips = []
                for addr in itf.addresses:
                    ip, extra = list(addr.items())[0]
                    if 'flags' not in extra or 'link' not in extra['flags']:
                        non_local_ips.append(ip)
                default_routes = [x for x in itf.routes if x.get('to', None) == 'default']
                if non_local_ips and default_routes and itf.dns_addresses:
                    return True
        return False

    @classmethod
    def process_generic(cls, cmd_output: str) -> JSON:
        return json.loads(cmd_output)

    @classmethod
    def query_iproute2(cls) -> JSON:
        data: JSON = None
        try:
            output: str = subprocess.check_output(['ip', '-d', '-j', 'addr'],
                                                  text=True)
            data = cls.process_generic(output)
        except Exception as e:
            logging.critical('Cannot query iproute2 interface data: {}'.format(str(e)))
        return data

    @classmethod
    def process_networkd(cls, cmd_output) -> JSON:
        return json.loads(cmd_output)['Interfaces']

    @classmethod
    def query_networkd(cls) -> JSON:
        data: JSON = None
        try:
            output: str = subprocess.check_output(['networkctl', '--json=short'],
                                                  text=True)
            data = cls.process_networkd(output)
        except Exception as e:
            logging.critical('Cannot query networkd interface data: {}'.format(str(e)))
        return data

    @classmethod
    def process_nm(cls, cmd_output) -> JSON:
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

    @classmethod
    def query_nm(cls) -> JSON:
        data: JSON = None
        try:
            output: str = utils.nmcli_out(['-t', '-f',
                                           'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                           'con', 'show'])
            data = cls.process_nm(output)
        except Exception as e:
            logging.debug('Cannot query NetworkManager interface data: {}'.format(str(e)))
        return data

    @classmethod
    def query_routes(cls) -> tuple:
        data4 = None
        data6 = None
        try:
            output4: str = subprocess.check_output(['ip', '-d', '-j', '-4', 'route', 'show', 'table', 'all'],
                                                   text=True)
            data4: JSON = cls.process_generic(output4)
            output6: str = subprocess.check_output(['ip', '-d', '-j', '-6', 'route', 'show', 'table', 'all'],
                                                   text=True)
            data6: JSON = cls.process_generic(output6)
        except Exception as e:
            logging.debug('Cannot query iproute2 route data: {}'.format(str(e)))

        # Add the address family to the data
        # IPv4: 2, IPv6: 10
        if data4:
            for route in data4:
                route.update({'family': socket.AF_INET.value})
        if data6:
            for route in data6:
                route.update({'family': socket.AF_INET6.value})
        return (data4, data6)

    @classmethod
    def query_resolved(cls) -> tuple:
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

    @classmethod
    def query_members(cls, ifname: str) -> List[str]:
        ''' Return a list containing the interfaces that are members of a bond/bridge/vrf '''
        members = []
        output: str = None
        try:
            output = subprocess.check_output(
                ['ip', '-d', '-j', 'link', 'show', 'master', ifname], text=True)   # wokeignore:rule=master
        except Exception as e:
            logging.warning('Cannot query bridge: {}'.format(str(e)))
            return []

        output_json = json.loads(output)
        for member in output_json:
            members.append(member.get('ifname'))

        return members

    @classmethod
    def correlate_members_and_uplink(cls, interfaces: List[Interface]) -> None:
        '''
        Associate interfaces with their members and parent interfaces.
        If an interface is a member of a bond/bridge/vrf, identify which interface
        if a member of. If an interface has members, identify what are the members.
        '''
        uplink_types = ['bond', 'bridge', 'vrf']
        members_to_uplink = {}
        uplink_to_members = defaultdict(list)
        for interface in filter(lambda i: i.type in uplink_types, interfaces):
            members = cls.query_members(interface.name)
            for member in members:
                member_tuple = namedtuple('Member', ['name', 'type'])
                members_to_uplink[member] = member_tuple(interface.name, interface.type)
            uplink_to_members[interface.name] = members

        for interface in interfaces:
            if uplink := members_to_uplink.get(interface.name):
                if uplink.type == 'bridge':
                    interface.bridge = uplink.name
                if uplink.type == 'bond':
                    interface.bond = uplink.name
                if uplink.type == 'vrf':
                    interface.vrf = uplink.name

            if interface.type in uplink_types:
                if members := uplink_to_members.get(interface.name):
                    interface.members = members

    @property
    def number_of_interfaces(self) -> int:
        return len(self.interface_list)

    def get_data(self) -> dict:
        return self.state


class NetplanConfigState():
    ''' Collects the Netplan's network configuration '''

    def __init__(self, subtree='all', rootdir='/'):

        parser = netplan.Parser()
        parser.load_yaml_hierarchy(rootdir)

        np_state = netplan.State()
        np_state.import_parser_results(parser)
        self.netdefs = np_state.netdefs

        self.state = StringIO()

        if subtree == 'all':
            np_state._dump_yaml(output_file=self.state)
        else:
            if not subtree.startswith('network'):
                subtree = '.'.join(('network', subtree))
            # Split at '.' but not at '\.' via negative lookbehind expression
            subtree = re.split(r'(?<!\\)\.', subtree)
            # Replace remaining '\.' by plain '.'
            subtree = [elem.replace(r'\.', '.') for elem in subtree]

            tmp_in = StringIO()
            np_state._dump_yaml(output_file=tmp_in)
            netplan._dump_yaml_subtree(subtree, tmp_in, self.state)

    def __str__(self) -> str:
        return self.state.getvalue()

    def get_data(self) -> dict:
        return yaml.safe_load(self.state.getvalue())
