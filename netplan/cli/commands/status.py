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
import logging
import subprocess
import sys
import yaml
import netplan.cli.utils as utils

from typing import Union, Dict, List, Type

JSON = Union[Dict[str, 'JSON'], List['JSON'], int, str, float, bool, Type[None]]


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

        for itf in networkd:
            idx = itf['Index']
            dev = itf['Name']
            print('● {idx}: {name}'.format(idx=idx, name=dev))
