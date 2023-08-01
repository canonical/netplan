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

import yaml
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.theme import Theme

from .. import utils
from ..state import SystemConfigState, JSON


class NetplanHighlighter(RegexHighlighter):
    base_style = 'netplan.'
    highlights = [
        r'(^|[\s\/])(?P<int>\d+)([\s:]?\s|$)',
        r'(?P<str>(\"|\').+(\"|\'))',
        ]


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
        state_data = SystemConfigState(self.ifname, self.all)

        # Output data in requested format
        output_format = self.format.lower()
        if output_format == 'json':  # structural JSON output
            print(json.dumps(state_data.get_data()))
        elif output_format == 'yaml':  # stuctural YAML output
            print(yaml.dump(state_data.get_data()))
        else:  # pretty print, human readable output
            self.pretty_print(state_data.get_data(), state_data.number_of_interfaces)
