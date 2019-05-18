#!/usr/bin/python3
#
# Copyright (C) 2019 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

'''netplan info command line'''

from collections import OrderedDict
import netplan.cli.utils as utils
import netplan.version_info

class NetplanInfo(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='info',
                         description='Show current netplan version and available features',
                         leaf=True)

    def run(self):  # pragma: nocover (covered in autopkgtest)
        format_group = self.parser.add_mutually_exclusive_group(required=False)
        format_group.add_argument('--json', dest='version_format', action='store_const',
                                  const='json',
                                  help='Output version and features in JSON format')
        format_group.add_argument('--yaml', dest='version_format', action='store_const',
                                  const='yaml',
                                  help='Output version and features in YAML format')

        self.func = self.command_info
        self.parse_args()
        self.run_command()

    def command_info(self):

        netplan_version = {
            'netplan.io': {
                'version': netplan.version_info.version(),
                'website': 'http://netplan.io/',
            }
        }

        # The C code for version_info gets you Bytes, not strings; decode it to UTF-8.
        flags = [ x.decode('utf-8') for x in netplan.version_info.features() ]
        netplan_version['netplan.io'].update({'features': flags})

        # Default to output in YAML format.
        if self.version_format is None:
            self.version_format = 'yaml'

        if self.version_format == 'json':
            import json
            print(json.dumps(netplan_version))

        elif self.version_format == 'yaml':
            import yaml
            print(yaml.dump(netplan_version, default_flow_style=False))
