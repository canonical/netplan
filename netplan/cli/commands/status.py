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

import subprocess
import yaml
import netplan.cli.utils as utils


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

    def command(self):
        networkd: str = subprocess.check_output(['networkctl', '--json=short'],
                                                universal_newlines=True)
        networkd_data = yaml.safe_load(networkd)
        for itf in networkd_data['Interfaces']:
            idx = itf['Index']
            dev = itf['Name']
            print('● {idx}: {name}'.format(idx=idx, name=dev))
