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

import ipaddress
import json
import logging
import socket
import subprocess
import sys
from typing import Union, Dict, List, Type

import dbus
import yaml
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.theme import Theme

import netplan.cli.utils as utils

JSON = Union[Dict[str, 'JSON'], List['JSON'], int, str, float, bool, Type[None]]


class NetplanHighlighter(RegexHighlighter):
    base_style = 'netplan.'
    highlights = [
        r'(^|[\s\/])(?P<int>\d+)([\s:]?\s|$)',
        r'(?P<str>(\"|\').+(\"|\'))',
        ]


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


class NetplanStatus(utils.NetplanCommand):
    def __init__(self):
        super().__init__(command_id='status',
                         description='Query networking state of the running system',
                         leaf=True)
        self.all = False

    def run(self):
        self.parser.add_argument('ifname', nargs='?', type=str, default=None,
                                 help='Show only this interface')
        self.parser.add_argument('-a', '--all', action='store_true',
                                 help='Show all interface data (incl. inactive)')
        self.parser.add_argument('-f', '--format', default='tabular',
                                 help='Output in machine readable `json` or `yaml` format')

        self.func = self.command
        self.parse_args()
        self.run_command()

    def resolvconf_json(self) -> dict:
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

    def query_online_state(self, interfaces: list) -> bool:
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

    def process_generic(self, cmd_output: str) -> JSON:
        return json.loads(cmd_output)

    def query_iproute2(self) -> JSON:
        data: JSON = None
        try:
            output: str = subprocess.check_output(['ip', '-d', '-j', 'addr'],
                                                  universal_newlines=True)
            data = self.process_generic(output)
        except Exception as e:
            logging.critical('Cannot query iproute2 interface data: {}'.format(str(e)))
        return data

    def process_networkd(self, cmd_output) -> JSON:
        return json.loads(cmd_output)['Interfaces']

    def query_networkd(self) -> JSON:
        data: JSON = None
        try:
            output: str = subprocess.check_output(['networkctl', '--json=short'],
                                                  universal_newlines=True)
            data = self.process_networkd(output)
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
        data: JSON = None
        try:
            output: str = utils.nmcli_out(['-t', '-f',
                                           'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT',
                                           'con', 'show'])
            data = self.process_nm(output)
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

    def pretty_print(self, data: JSON, total: int, _console_width=None) -> None:
        # TODO: Use a proper (subiquity?) color palette
        theme = Theme({
            'netplan.int': 'bold cyan',
            'netplan.str': 'yellow',
            'muted': 'grey62',
            'online': 'green bold',
            'offline': 'red bold',
            'unknown': 'yellow bold',
            'highlight': 'bold'
            })
        console = Console(highlighter=NetplanHighlighter(), theme=theme,
                          width=_console_width, emoji=False)
        pprint = console.print

        pad = '18'
        global_state = data.get('netplan-global-state', {})
        interfaces = [(key, data[key]) for key in data if key != 'netplan-global-state']

        # Global state
        pprint(('{title:>'+pad+'} {value}').format(
            title='Online state:',
            value='[online]online[/online]' if global_state.get('online', False) else '[offline]offline[/offline]',
            ))
        ns = global_state.get('nameservers', {})
        dns_addr: list = ns.get('addresses', [])
        dns_mode: str = ns.get('mode')
        dns_search: list = ns.get('search', [])
        if dns_addr:
            for i, val in enumerate(dns_addr):
                pprint(('{title:>'+pad+'} {value}[muted]{mode}[/muted]').format(
                    title='DNS Addresses:' if i == 0 else '',
                    value=val,
                    mode=' ({})'.format(dns_mode) if dns_mode else '',
                    ))
        if dns_search:
            for i, val in enumerate(dns_search):
                pprint(('{title:>'+pad+'} {value}').format(
                    title='DNS Search:' if i == 0 else '',
                    value=val,
                    ))
        pprint()

        # Per interface
        for (ifname, data) in interfaces:
            state = data.get('operstate', 'UNKNOWN') + '/' + data.get('adminstate', 'UNKNOWN')
            scolor = 'unknown'
            if state == 'UP/UP':
                state = 'UP'
                scolor = 'online'
            elif state == 'DOWN/DOWN':
                state = 'DOWN'
                scolor = 'offline'
            full_type = data.get('type', 'other')
            ssid = data.get('ssid')
            tunnel_mode = data.get('tunnel_mode')
            if full_type == 'wifi' and ssid:
                full_type += ('/"' + ssid + '"')
            elif full_type == 'tunnel' and tunnel_mode:
                full_type += ('/' + tunnel_mode)
            pprint('[{col}]●[/{col}] {idx:>2}: {name} {type} [{col}]{state}[/{col}] ({backend}{netdef})'.format(
                col=scolor,
                idx=data.get('index', '?'),
                name=ifname,
                type=full_type,
                state=state,
                backend=data.get('backend', 'unmanaged'),
                netdef=': [highlight]{}[/highlight]'.format(data.get('id')) if data.get('id') else ''
                ))

            if data.get('macaddress'):
                pprint(('{title:>'+pad+'} {mac}[muted]{vendor}[/muted]').format(
                    title='MAC Address:',
                    mac=data.get('macaddress', ''),
                    vendor=' ({})'.format(data.get('vendor', '')) if data.get('vendor') else '',
                    ))

            lst: list = data.get('addresses', [])
            if lst:
                for i, obj in enumerate(lst):
                    ip, extra = list(obj.items())[0]  # get first (any only) address
                    flags = []
                    if extra.get('flags'):  # flags
                        flags = extra.get('flags', [])
                    highlight_start = ''
                    highlight_end = ''
                    if not flags or 'dhcp' in flags:
                        highlight_start = '[highlight]'
                        highlight_end = '[/highlight]'
                    pprint(('{title:>'+pad+'} {start}{ip}/{prefix}{end}[muted]{extra}[/muted]').format(
                        title='Addresses:' if i == 0 else '',
                        ip=ip,
                        prefix=extra.get('prefix', ''),
                        extra=' ('+', '.join(flags)+')' if flags else '',
                        start=highlight_start,
                        end=highlight_end,
                        ))

            lst = data.get('dns_addresses', [])
            if lst:
                for i, val in enumerate(lst):
                    pprint(('{title:>'+pad+'} {value}').format(
                        title='DNS Addresses:' if i == 0 else '',
                        value=val,
                        ))

            lst = data.get('dns_search', [])
            if lst:
                for i, val in enumerate(lst):
                    pprint(('{title:>'+pad+'} {value}').format(
                        title='DNS Search:' if i == 0 else '',
                        value=val,
                        ))

            lst = data.get('routes', [])
            if lst:
                for i, obj in enumerate(lst):
                    default_start = ''
                    default_end = ''
                    if obj['to'] == 'default':
                        default_start = '[highlight]'
                        default_end = '[/highlight]'
                    via = ''
                    if 'via' in obj:
                        via = ' via ' + obj['via']
                    src = ''
                    if 'from' in obj:
                        src = ' from ' + obj['from']
                    metric = ''
                    if 'metric' in obj:
                        metric = ' metric ' + str(obj['metric'])

                    extra = []
                    if 'protocol' in obj and obj['protocol'] != 'kernel':
                        proto = obj['protocol']
                        extra.append(proto)
                    if 'scope' in obj and obj['scope'] != 'global':
                        scope = obj['scope']
                        extra.append(scope)
                    if 'type' in obj and obj['type'] != 'unicast':
                        type = obj['type']
                        extra.append(type)

                    pprint(('{title:>'+pad+'} {start}{to}{via}{src}{metric}{end}[muted]{extra}[/muted]').format(
                        title='Routes:' if i == 0 else '',
                        to=obj['to'],
                        via=via,
                        src=src,
                        metric=metric,
                        extra=' ('+', '.join(extra)+')' if extra else '',
                        start=default_start,
                        end=default_end))

            val = data.get('activation_mode')
            if val:
                pprint(('{title:>'+pad+'} {value}').format(
                    title='Activation Mode:',
                    value=val,
                    ))
            pprint()

        hidden = total - len(interfaces)
        if (hidden > 0):
            pprint('{} inactive interfaces hidden. Use "--all" to show all.'.format(hidden))

    def command(self):
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

        interfaces = [Interface(itf, networkd, nmcli, (dns_addresses, dns_search), (route4, route6)) for itf in iproute2]
        total = len(interfaces)
        # show only active interfaces by default
        filtered = [itf for itf in interfaces if itf.operstate != 'DOWN']
        # down interfaces do not contribute anything to the online state
        online_state = self.query_online_state(filtered)
        # show only a single interface, if requested
        # XXX: bash completion (for interfaces names)
        if self.ifname:
            filtered = [next((itf for itf in interfaces if itf.name == self.ifname), None)]
        filtered = [elem for elem in filtered if elem is not None]
        if self.ifname and filtered == []:
            logging.error('Could not find interface {}'.format(self.ifname))
            sys.exit(1)

        # Global state
        data = {
            'netplan-global-state': {
                'online': online_state,
                'nameservers': self.resolvconf_json()
            }
        }
        # Per interface
        itf_iter = interfaces if self.all else filtered
        for itf in itf_iter:
            ifname, obj = itf.json()
            data[ifname] = obj

        # Output data in requested format
        output_format = self.format.lower()
        if output_format == 'json':  # structural JSON output
            print(json.dumps(data, indent=None))
        elif output_format == 'yaml':  # stuctural YAML output
            print(yaml.dump(data, default_flow_style=False))
        else:  # pretty print, human readable output
            self.pretty_print(data, total)
