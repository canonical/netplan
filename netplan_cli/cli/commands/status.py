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

import json
import logging
import re
from netplan.netdef import NetplanRoute

import yaml

from .. import utils
from ..state import NetplanConfigState, SystemConfigState, JSON
from ..state_diff import DiffJSONEncoder, NetplanDiffState


MATCH_TAGS = re.compile(r'\[([a-z0-9]+)\].*\[\/\1\]')
RICH_OUTPUT = False
try:
    from rich.console import Console
    from rich.highlighter import RegexHighlighter
    from rich.theme import Theme

    class NetplanHighlighter(RegexHighlighter):
        base_style = 'netplan.'
        highlights = [
            r'(^|[\s\/])(?P<int>\d+)([\s:]?\s|$)',
            r'(?P<str>(\"|\').+(\"|\'))',
            ]
    RICH_OUTPUT = True
except ImportError:  # pragma: nocover (we mock RICH_OUTPUT, ignore the logging)
    logging.debug("python3-rich not found, falling back to plain output")


class NetplanStatus(utils.NetplanCommand):
    def __init__(self):
        super().__init__(command_id='status',
                         description='Query networking state of the running system',
                         leaf=True)
        self.all = False
        self.state_diff = None
        self.route_lookup_table_names = {}

    def run(self):
        self.parser.add_argument('ifname', nargs='?', type=str, default=None,
                                 help='Show only this interface')
        self.parser.add_argument('-a', '--all', action='store_true',
                                 help='Show all interface data (incl. inactive)')
        self.parser.add_argument('-v', '--verbose', action='store_true',
                                 help='Show extra information')
        self.parser.add_argument('-f', '--format', default='tabular',
                                 help='Output in machine readable `json` or `yaml` format')
        self.parser.add_argument('--diff', action='store_true',
                                 help='Show the differences between the system\'s and netplan\'s states')
        self.parser.add_argument('--diff-only', action='store_true',
                                 help='Only show the differences between the system\'s and netplan\'s states')
        self.parser.add_argument('--root-dir',
                                 help='Search for configuration files in this root directory instead of /')

        self.func = self.command
        self.parse_args()
        self.run_command()

    def _create_pretty_print(self, _console_width):
        if RICH_OUTPUT:
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
            if self.diff:
                theme = Theme({
                    'netplan.int': 'grey62',
                    'netplan.str': 'grey62',
                    'muted': 'grey62',
                    'online': 'green bold',
                    'offline': 'red bold',
                    'unknown': 'yellow bold',
                    'highlight': 'bold'
                    })

            console = Console(highlighter=NetplanHighlighter(), theme=theme,
                              width=_console_width, emoji=False)
            pprint = console.print
        else:
            pprint = self.plain_print

        return pprint

    def _get_interface_diff(self, ifname) -> dict:
        if self.state_diff:
            if diff := self.state_diff['interfaces'].get(ifname):
                if diff.get('system_state') or diff.get('netplan_state'):
                    return diff
        return {}

    def _is_interface_missing_in_netplan(self, ifname) -> bool:
        if self.state_diff:
            if missing := self.state_diff.get('missing_interfaces_netplan'):
                if ifname in missing:
                    return True
        return False

    def _get_missing_property_list(self, ifname: str, state: str, property: str) -> list[str]:
        if self.state_diff:
            if diff := self.state_diff['interfaces'].get(ifname):
                return diff.get(state, {}).get(property, [])
        return []

    def _get_missing_property_str(self, ifname: str, state: str, property: str) -> str:
        if self.state_diff:
            if diff := self.state_diff['interfaces'].get(ifname):
                return diff.get(state, {}).get(property, '')
        return ''

    def _get_missing_property_set(self, ifname: str, state: str, property: str) -> set:
        if self.state_diff:
            if diff := self.state_diff['interfaces'].get(ifname):
                return diff.get(state, {}).get(property, set())
        return set()

    def _get_missing_property_bool(self, ifname: str, state: str, property: str) -> bool:
        if self.state_diff:
            if diff := self.state_diff['interfaces'].get(ifname):
                return diff.get(state, {}).get(property, False)
        return False

    def _get_missing_netplan_addresses(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'netplan_state', 'missing_addresses')

    def _get_missing_system_nameservers(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'system_state', 'missing_nameservers_addresses')

    def _get_missing_netplan_nameservers(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'netplan_state', 'missing_nameservers_addresses')

    def _get_missing_netplan_search(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'netplan_state', 'missing_nameservers_search')

    def _get_missing_system_search(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'system_state', 'missing_nameservers_search')

    def _get_missing_system_macaddress(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'system_state', 'missing_macaddress')

    def _get_missing_netplan_routes(self, ifname) -> set[NetplanRoute]:
        return self._get_missing_property_set(ifname, 'netplan_state', 'missing_routes')

    def _get_missing_system_routes(self, ifname) -> set[NetplanRoute]:
        return self._get_missing_property_set(ifname, 'system_state', 'missing_routes')

    def _is_missing_dhcp4_address(self, ifname) -> bool:
        return self._get_missing_property_bool(ifname, 'system_state', 'missing_dhcp4_address')

    def _is_missing_dhcp6_address(self, ifname) -> bool:
        return self._get_missing_property_bool(ifname, 'system_state', 'missing_dhcp6_address')

    def _get_missing_system_bond_link(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'system_state', 'missing_bond_link')

    def _get_missing_netplan_bond_link(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'netplan_state', 'missing_bond_link')

    def _get_missing_system_bridge_link(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'system_state', 'missing_bridge_link')

    def _get_missing_netplan_bridge_link(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'netplan_state', 'missing_bridge_link')

    def _get_missing_system_vrf_link(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'system_state', 'missing_vrf_link')

    def _get_missing_netplan_vrf_link(self, ifname) -> str:
        return self._get_missing_property_str(ifname, 'netplan_state', 'missing_vrf_link')

    def _get_missing_netplan_members(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'netplan_state', 'missing_interfaces')

    def _get_missing_system_members(self, ifname) -> list[str]:
        return self._get_missing_property_list(ifname, 'system_state', 'missing_interfaces')

    def _get_missing_system_interfaces(self) -> dict:
        if self.state_diff:
            return self.state_diff.get('missing_interfaces_system', {})
        return {}

    def _has_diff(self, ifname) -> bool:
        if self._is_interface_missing_in_netplan(ifname):
            return True
        if self.state_diff:
            if diff := self.state_diff['interfaces'].get(ifname):
                if diff.get('system_state') or diff.get('netplan_state'):
                    return True
        return False

    def _display_global_state(self, data):
        global_state = data.get('netplan-global-state', {})
        self.pprint(('{title:>'+self.PAD+'} {value}').format(
            title='Online state:',
            value='[online]online[/online]' if global_state.get('online', False) else '[offline]offline[/offline]',
            ))
        ns = global_state.get('nameservers', {})
        dns_addr: list = ns.get('addresses', [])
        dns_mode: str = ns.get('mode')
        dns_search: list = ns.get('search', [])
        if dns_addr:
            for i, val in enumerate(dns_addr):
                self.pprint(('{title:>'+self.PAD+'} {value}[muted]{mode}[/muted]').format(
                    title='DNS Addresses:' if i == 0 else '',
                    value=val,
                    mode=' ({})'.format(dns_mode) if dns_mode else '',
                    ))
        if dns_search:
            for i, val in enumerate(dns_search):
                self.pprint(('{title:>'+self.PAD+'} {value}').format(
                    title='DNS Search:' if i == 0 else '',
                    value=val,
                    ))
        self.pprint()

    def _display_interface_header(self, ifname: str, data):
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

        format = '[{col}]●[/{col}] {idx:>2}: {name} {type} [{col}]{state}[/{col}] ({backend}{netdef})'
        netdef = ': [highlight]{}[/highlight]'.format(data.get('id')) if data.get('id') else ''
        extra = ''
        sign = ''
        if self.diff:
            if self._is_interface_missing_in_netplan(ifname):
                sign = self.PLUS
                format = '{sign} [{col}]●[/{col}] {idx:>2}: [green][highlight]{name} {type}'
                format += ' [{col}]{state}[/{col}] ({backend}{netdef})[/highlight][/green]'
            else:
                format = '  [muted]● {idx:>2}: {name} {type} {state} ({backend}{netdef})[/muted]'
                netdef = ': {}'.format(data.get('id')) if data.get('id') else ''

        if not self.diff_only or self._has_diff(ifname):
            self.pprint(format.format(
                sign=sign,
                col=scolor,
                idx=data.get('index', '?'),
                name=ifname,
                type=full_type,
                state=state,
                backend=data.get('backend', 'unmanaged'),
                netdef=netdef,
                extra=extra,
                ))

    def _display_mac_address(self, ifname: str, data):
        if macaddress := data.get('macaddress'):
            hide_macaddress = False
            missing_system_macaddress = self._get_missing_system_macaddress(ifname)
            format = '{title:>'+self.PAD+'} {mac}[muted]{vendor}[/muted]'
            sign = ''
            if self.diff and not missing_system_macaddress:
                format = '  [muted]{title:>'+self.PAD+'} {mac}{vendor}[/muted]'
                if self.diff_only:
                    hide_macaddress = True
            elif self.diff and missing_system_macaddress:
                sign = self.PLUS
                format = '{sign} {title:>'+self.PAD+'} [green][highlight]{mac}{vendor}[/highlight][/green]'

            if not hide_macaddress:
                self.pprint((format).format(
                    sign=sign,
                    title='MAC Address:',
                    mac=macaddress,
                    vendor=' ({})'.format(data.get('vendor', '')) if data.get('vendor') else '',
                    ))

                if self.diff and missing_system_macaddress:
                    sign = self.MINUS
                    format = '{sign} {title:>'+self.PAD+'} [red][highlight]{mac}{vendor}[/highlight][/red]'
                    self.pprint((format).format(
                        sign=sign,
                        title='',
                        mac=missing_system_macaddress,
                        vendor=' ({})'.format(data.get('vendor', '')) if data.get('vendor') else '',
                        ))

    def _display_ip_addresses(self, ifname: str, data):
        lst: list = data.get('addresses', [])
        addresses_displayed = 0
        if lst:
            missing_netplan_addresses = self._get_missing_netplan_addresses(ifname)
            for obj in lst:
                sign = ''
                hide_address = False
                ip, extra = list(obj.items())[0]  # get first (and only) address
                prefix = extra.get('prefix', '')
                flags = []
                if extra.get('flags'):  # flags
                    flags = extra.get('flags', [])
                highlight_start = ''
                highlight_end = ''
                if not flags or 'dhcp' in flags:
                    highlight_start = '[highlight]'
                    highlight_end = '[/highlight]'

                address = f'{ip}/{prefix}'
                if self.diff and address not in missing_netplan_addresses:
                    format = '  [muted]{title:>'+self.PAD+'} {start}{ip}/{prefix}{end}{extra}[/muted]'
                    highlight_start = ''
                    highlight_end = ''
                    if self.diff_only:
                        hide_address = True
                elif self.diff and address in missing_netplan_addresses:
                    sign = self.PLUS
                    format = '{sign} {title:>'+self.PAD+'} [green]{start}{ip}/{prefix}{extra}{end}[/green]'
                    highlight_start = '[highlight]'
                    highlight_end = '[/highlight]'
                else:
                    format = '{title:>'+self.PAD+'} {start}{ip}/{prefix}{end}[muted]{extra}[/muted]'

                if not hide_address:
                    self.pprint((format).format(
                        sign=sign,
                        title='Addresses:' if addresses_displayed == 0 else '',
                        ip=ip,
                        prefix=prefix,
                        extra=' ('+', '.join(flags)+')' if flags else '',
                        start=highlight_start,
                        end=highlight_end,
                        ))
                    addresses_displayed += 1

        if diff := self._get_interface_diff(ifname):
            sign = self.MINUS
            if missing_addresses := diff.get('system_state', {}).get('missing_addresses'):
                for ip in missing_addresses:
                    self.pprint(('{sign} {title:>'+self.PAD+'} [highlight][red]{ip}[/red][/highlight]').format(
                        sign=sign,
                        title='Addresses:' if addresses_displayed == 0 else '',
                        ip=ip,
                        ))
                    addresses_displayed += 1
            if self._is_missing_dhcp4_address(ifname):
                self.pprint(('{sign} {title:>'+self.PAD+'} [highlight][red]0.0.0.0/0 (dhcp)[/red][/highlight]').format(
                    sign=sign,
                    title='Addresses:' if addresses_displayed == 0 else '',
                    ))
                addresses_displayed += 1
            if self._is_missing_dhcp6_address(ifname):
                self.pprint(('{sign} {title:>'+self.PAD+'} [highlight][red]::/0 (dhcp)[/red][/highlight]').format(
                    sign=sign,
                    title='Addresses:' if addresses_displayed == 0 else '',
                    ))

    def _display_dns_addresses(self, ifname: str, data):
        lst = data.get('dns_addresses', [])
        nameservers_displayed = 0
        if lst:
            missing_netplan_nameservers = self._get_missing_netplan_nameservers(ifname)
            for val in lst:
                sign = ''
                hide_nameserver = False
                if self.diff and val not in missing_netplan_nameservers:
                    format = '  [muted]{title:>'+self.PAD+'} {value}[/muted]'
                    highlight_start = ''
                    highlight_end = ''
                    if self.diff_only:
                        hide_nameserver = True
                elif self.diff and val in missing_netplan_nameservers:
                    sign = self.PLUS
                    format = '{sign} {title:>'+self.PAD+'} [green]{start}{value}{end}[/green]'
                    highlight_start = '[highlight]'
                    highlight_end = '[/highlight]'
                else:
                    format = '{title:>'+self.PAD+'} {value}'
                    highlight_start = ''
                    highlight_end = ''

                if not hide_nameserver:
                    self.pprint((format).format(
                        sign=sign,
                        title='DNS Addresses:' if nameservers_displayed == 0 else '',
                        value=val,
                        start=highlight_start,
                        end=highlight_end
                        ))
                    nameservers_displayed += 1

        if self._has_diff(ifname):
            if missing_nameservers_addresses := self._get_missing_system_nameservers(ifname):
                sign = self.MINUS
                for ip in missing_nameservers_addresses:
                    self.pprint(('{sign} {title:>'+self.PAD+'} [red][highlight]{ip}[/highlight][/red]').format(
                        sign=sign,
                        title='DNS Addresses:' if nameservers_displayed == 0 else '',
                        ip=ip,
                        ))
                    nameservers_displayed += 1

    def _display_dns_search(self, ifname, data):
        lst = data.get('dns_search', [])
        searches_displayed = 0
        if lst:
            missing_netplan_search = self._get_missing_netplan_search(ifname)
            for i, val in enumerate(lst):
                sign = ''
                hide_search = False
                if self.diff and val not in missing_netplan_search:
                    format = '  [muted]{title:>'+self.PAD+'} {value}[/muted]'
                    highlight_start = ''
                    highlight_end = ''
                    if self.diff_only:
                        hide_search = True
                elif self.diff and val in missing_netplan_search:
                    sign = self.PLUS
                    format = '{sign} {title:>'+self.PAD+'} [green]{start}{value}{end}[/green]'
                    highlight_start = '[highlight]'
                    highlight_end = '[/highlight]'
                else:
                    format = '{title:>'+self.PAD+'} {value}'
                    highlight_start = ''
                    highlight_end = ''

                if not hide_search:
                    self.pprint((format).format(
                        sign=sign,
                        title='DNS Search:' if searches_displayed == 0 else '',
                        value=val,
                        start=highlight_start,
                        end=highlight_end
                        ))
                    searches_displayed += 1

        if self._has_diff(ifname):
            if missing_nameservers_search := self._get_missing_system_search(ifname):
                sign = self.MINUS
                for domain in missing_nameservers_search:
                    self.pprint(('{sign} {title:>'+self.PAD+'} [red][highlight]{domain}[/highlight][/red]').format(
                        sign=sign,
                        title='DNS Search:' if searches_displayed == 0 else '',
                        domain=domain,
                        ))
                    searches_displayed += 1

    def _display_routes(self, ifname, data):
        lst = data.get('routes', [])
        missing_netplan_routes = self._get_missing_netplan_routes(ifname)
        missing_system_routes = self._get_missing_system_routes(ifname)
        routes_displayed = 0
        if lst:
            if not self.route_lookup_table_names:
                self.route_lookup_table_names = utils.route_table_lookup()

            diff_state = NetplanDiffState(None, None)
            routes = [diff_state._system_route_to_netplan(route) for route in lst]
            if not self.verbose:
                # filter out routes that are not in the main route table
                routes = filter(lambda r: r.table == 254, routes)
            for route in routes:
                hide_route = False
                default_start = ''
                default_end = ''
                if route.to == 'default':
                    default_start = '[highlight]'
                    default_end = '[/highlight]'
                via = ''
                if route.via:
                    via = ' via ' + route.via
                src = ''
                if route.from_addr:
                    src = ' from ' + route.from_addr
                metric = ''
                if route.metric < NetplanRoute._METRIC_UNSPEC_:
                    metric = ' metric ' + str(route.metric)
                table = ''
                if self.verbose and route.table > 0:
                    table = ' table {}'.format(self.route_lookup_table_names.get(route.table, route.table))

                extra = []
                if route.protocol and route.protocol != 'kernel':
                    proto = route.protocol
                    extra.append(proto)
                if route.scope and route.scope != 'global':
                    scope = route.scope
                    extra.append(scope)
                if route.type and route.type != 'unicast':
                    type = route.type
                    extra.append(type)

                sign = ''
                if self.diff and route not in missing_netplan_routes:
                    format = '  [muted]{title:>'+self.PAD+'} {start}{to}{via}{src}{metric}{table}{end}{extra}[/muted]'
                    default_start = ''
                    default_end = ''
                    if self.diff_only:
                        hide_route = True
                elif self.diff and route in missing_netplan_routes:
                    sign = self.PLUS
                    format = '{sign} {title:>'+self.PAD+'} [green][highlight]{start}{to}{via}{src}{metric}'
                    format += '{table}{end}{extra}[/highlight][/green]'
                else:
                    format = '{title:>'+self.PAD+'} {start}{to}{via}{src}{metric}{table}{end}[muted]{extra}[/muted]'

                if not hide_route:
                    self.pprint(format.format(
                        sign=sign,
                        title='Routes:' if routes_displayed == 0 else '',
                        to=route.to,
                        via=via,
                        src=src,
                        metric=metric,
                        table=table,
                        extra=' ('+', '.join(extra)+')' if extra else '',
                        start=default_start,
                        end=default_end))
                    routes_displayed += 1

        if self.diff:
            for route in missing_system_routes:
                via = ''
                if route.via:
                    via = ' via ' + route.via
                src = ''
                if route.from_addr:
                    src = ' from ' + route.from_addr
                metric = ''
                if route.metric < NetplanRoute._METRIC_UNSPEC_:
                    metric = ' metric ' + str(route.metric)
                table = ''
                if self.verbose and route.table > 0:
                    table = ' table {}'.format(self.route_lookup_table_names.get(route.table, route.table))

                extra = []
                if route.scope and route.scope != 'global':
                    scope = route.scope
                    extra.append(scope)
                if route.type and route.type != 'unicast':
                    type = route.type
                    extra.append(type)

                sign = self.MINUS
                format = '{sign} {title:>'+self.PAD+'} {start}[red]{to}{via}{src}{metric}{table}{extra}[/red]{end}'
                self.pprint(format.format(
                    sign=sign,
                    title='Routes:' if routes_displayed == 0 else '',
                    to=route.to,
                    via=via,
                    src=src,
                    metric=metric,
                    table=table,
                    extra=' ('+', '.join(extra)+')' if extra else '',
                    start='[highlight]',
                    end='[/highlight]'))
                routes_displayed += 1

    def _display_bridge(self, ifname, data):
        val = data.get('bridge')
        if val:
            missing_netplan_bridge_link = self._get_missing_netplan_bridge_link(ifname)
            format = '{title:>'+self.PAD+'} {value}'
            sign = ''
            hide_bridge = False
            if self.diff and not missing_netplan_bridge_link:
                format = '  [muted]{title:>'+self.PAD+'} {value}[/muted]'
                if self.diff_only:
                    hide_bridge = True
            elif self.diff and missing_netplan_bridge_link:
                sign = self.PLUS
                format = '{sign} {title:>'+self.PAD+'} [highlight][green]{value}[/green][/highlight]'
                val = missing_netplan_bridge_link

            if not hide_bridge:
                self.pprint((format).format(
                    sign=sign,
                    title='Bridge:',
                    value=val,
                    ))
        if missing_system_bridge_link := self._get_missing_system_bridge_link(ifname):
            sign = self.MINUS
            format = '{sign} {title:>'+self.PAD+'} [highlight][red]{value}[/red][/highlight]'
            self.pprint((format).format(
                sign=sign,
                title='Bridge:',
                value=missing_system_bridge_link,
            ))

    def _display_bond(self, ifname, data):
        val = data.get('bond')
        if val:
            missing_netplan_bond_link = self._get_missing_netplan_bond_link(ifname)
            format = '{title:>'+self.PAD+'} {value}'
            sign = ''
            hide_bond = False
            if self.diff and not missing_netplan_bond_link:
                format = '  [muted]{title:>'+self.PAD+'} {value}[/muted]'
                if self.diff_only:
                    hide_bond = True
            elif self.diff and missing_netplan_bond_link:
                sign = self.PLUS
                format = '{sign} {title:>'+self.PAD+'} [highlight][green]{value}[/green][/highlight]'
                val = missing_netplan_bond_link

            if not hide_bond:
                self.pprint((format).format(
                    sign=sign,
                    title='Bond:',
                    value=val,
                    ))
        if missing_system_bond_link := self._get_missing_system_bond_link(ifname):
            sign = self.MINUS
            format = '{sign} {title:>'+self.PAD+'} [highlight][red]{value}[/red][/highlight]'
            self.pprint((format).format(
                sign=sign,
                title='Bond:',
                value=missing_system_bond_link,
            ))

    def _display_vrf(self, ifname, data):
        val = data.get('vrf')
        if val:
            missing_netplan_vrf_link = self._get_missing_netplan_vrf_link(ifname)
            format = '{title:>'+self.PAD+'} {value}'
            sign = ''
            hide_vrf = False
            if self.diff and not missing_netplan_vrf_link:
                format = '  [muted]{title:>'+self.PAD+'} {value}[/muted]'
                if self.diff_only:
                    hide_vrf = True
            elif self.diff and missing_netplan_vrf_link:
                sign = self.PLUS
                format = '{sign} {title:>'+self.PAD+'} [highlight][green]{value}[/green][/highlight]'
                val = missing_netplan_vrf_link

            if not hide_vrf:
                self.pprint((format).format(
                    sign=sign,
                    title='VRF:',
                    value=val,
                    ))
        if missing_system_vrf_link := self._get_missing_system_vrf_link(ifname):
            sign = self.MINUS
            format = '{sign} {title:>'+self.PAD+'} [highlight][red]{value}[/red][/highlight]'
            self.pprint((format).format(
                sign=sign,
                title='VRF:',
                value=missing_system_vrf_link,
            ))

    def _display_members(self, ifname: str, data):
        lst = data.get('interfaces', [])
        members_displayed = 0
        if lst:
            missing_netplan_interfaces = self._get_missing_netplan_members(ifname)
            for val in lst:
                sign = ''
                hide_member = False
                if self.diff and val not in missing_netplan_interfaces:
                    format = '  [muted]{title:>'+self.PAD+'} {value}[/muted]'
                    highlight_start = ''
                    highlight_end = ''
                    if self.diff_only:
                        hide_member = True
                elif self.diff and val in missing_netplan_interfaces:
                    sign = self.PLUS
                    format = '{sign} {title:>'+self.PAD+'} [green]{start}{value}{end}[/green]'
                    highlight_start = '[highlight]'
                    highlight_end = '[/highlight]'
                else:
                    format = '{title:>'+self.PAD+'} {value}'
                    highlight_start = ''
                    highlight_end = ''

                if not hide_member:
                    self.pprint((format).format(
                        sign=sign,
                        title='Interfaces:' if members_displayed == 0 else '',
                        value=val,
                        start=highlight_start,
                        end=highlight_end,
                        ))
                    members_displayed += 1

        if self._has_diff(ifname):
            if missing_members := self._get_missing_system_members(ifname):
                sign = self.MINUS
                for member in missing_members:
                    self.pprint(('{sign} {title:>'+self.PAD+'} [red][highlight]{member}[/highlight][/red]').format(
                        sign=sign,
                        title='Interfaces:' if members_displayed == 0 else '',
                        member=member,
                        ))
                    members_displayed += 1

    def _display_activation_mode(self, data):
        val = data.get('activation_mode')
        if val:
            self.pprint(('{title:>'+self.PAD+'} {value}').format(
                title='Activation Mode:',
                value=val,
                ))

    def _display_missing_interfaces(self):
        missing_interfaces = self._get_missing_system_interfaces()
        sign = self.MINUS
        for index, (interface, properties) in enumerate(missing_interfaces.items(), 1):
            # If we called netplan status for a single interface, ignore the rest
            if self.ifname and self.ifname != interface:
                continue

            self.pprint('{sign} [{col}]● {idx:>2}  {name} {type}[/{col}]'.format(
                sign=sign,
                col='red',
                idx='',
                name=interface,
                type=properties.get('type'),
                ))

            if index != len(missing_interfaces) and not self.ifname:
                # linebreak only if it's not the last interfaces or the only one
                self.pprint()

    def plain_print(self, *args, **kwargs):
        if len(args):
            lst = list(args)
            for tag in MATCH_TAGS.findall(lst[0]):
                # remove matching opening and closing tag
                lst[0] = lst[0].replace('[{}]'.format(tag), '')\
                               .replace('[/{}]'.format(tag), '')
            return print(*lst, **kwargs)
        return print(*args, **kwargs)

    def pretty_print(self, data: JSON, total: int, _console_width=None) -> None:
        self.pprint = self._create_pretty_print(_console_width)
        self.PLUS = '[green]+[/green]'
        self.MINUS = '[red]-[/red]'
        self.PAD = '18'
        if self.diff:
            # In diff mode we shift the text 2 columns to the right so we can display
            # + and - and maintain the alignment consistency
            self.PAD = '20'

        # Global state
        if not self.diff:
            self._display_global_state(data)

        # Per interface
        interfaces = [(key, data[key]) for key in data if key != 'netplan-global-state']
        if self.diff_only:
            # in diff-only mode we filter out interfaces that don't have any diff
            interfaces = list(filter(lambda i: self._has_diff(i[0]), interfaces))

        missing_interfaces = self._get_missing_system_interfaces()
        for index, (ifname, ifconfig) in enumerate(interfaces, 1):
            # If we called netplan status for a single interface, ignore the rest
            if self.ifname and self.ifname != ifname:
                continue

            self._display_interface_header(ifname, ifconfig)
            self._display_mac_address(ifname, ifconfig)
            self._display_ip_addresses(ifname, ifconfig)
            self._display_dns_addresses(ifname, ifconfig)
            self._display_dns_search(ifname, ifconfig)
            self._display_routes(ifname, ifconfig)
            self._display_bridge(ifname, ifconfig)
            self._display_bond(ifname, ifconfig)
            self._display_vrf(ifname, ifconfig)
            self._display_members(ifname, ifconfig)
            self._display_activation_mode(ifconfig)

            if not self.diff_only or self._has_diff(ifname):
                # we only break to a new line if we still have data to display
                if (index != len(interfaces) or len(missing_interfaces) > 0) and not self.ifname:
                    self.pprint()

        if self.diff:
            self._display_missing_interfaces()

        hidden = total - len(interfaces)
        if hidden > 0 and not self.diff:
            self.pprint('\n{} inactive interfaces hidden. Use "--all" to show all.'.format(hidden))

        if self.diff and not self.diff_only:
            self.pprint(
                '\nUse [yellow]"--diff-only"[/yellow] to omit the information that is consistent between the system and Netplan.'
            )

    def command(self):
        # --diff-only implies --diff
        if self.diff_only:
            self.diff = True

        # --diff needs data from all interfaces to work
        if self.diff:
            self.all = True

        system_state = SystemConfigState(self.ifname, self.all)

        output_format = self.format.lower()

        if self.diff:
            netplan_state = NetplanConfigState(rootdir=self.root_dir)
            diff_state = NetplanDiffState(system_state, netplan_state)

            self.state_diff = diff_state.get_diff(self.ifname)

            if output_format == 'json':
                print(json.dumps(self.state_diff, cls=DiffJSONEncoder))
                return
            elif output_format == 'yaml':
                serialized = json.dumps(self.state_diff, cls=DiffJSONEncoder)
                print(yaml.dump(json.loads(serialized)))
                return

        if output_format == 'json':  # structural JSON output
            print(json.dumps(system_state.get_data()))
        elif output_format == 'yaml':  # stuctural YAML output
            print(yaml.dump(system_state.get_data()))
        else:  # pretty print, human readable output
            self.pretty_print(system_state.get_data(), system_state.number_of_interfaces)
