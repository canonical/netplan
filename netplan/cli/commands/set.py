#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
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

'''netplan set command line'''

import tempfile
import re
import io

from netplan.cli.utils import NetplanCommand
import netplan.libnetplan as libnetplan

FALLBACK_FILENAME = '70-netplan-set.yaml'
GLOBAL_KEYS = ['renderer', 'version']


class NetplanSet(NetplanCommand):

    def __init__(self):
        super().__init__(command_id='set',
                         description='Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true',
                         leaf=True)

    def run(self):
        self.parser.add_argument('key_value', type=str,
                                 help='The nested key=value pair in dotted format. Value can be NULL to delete a key.')
        self.parser.add_argument('--origin-hint', type=str,
                                 help='Can be used to help choose a name for the overwrite YAML file. \
                                       A .yaml suffix will be appended automatically.')
        self.parser.add_argument('--root-dir', default='/',
                                 help='Overwrite configuration files in this root directory instead of /')

        self.func = self.command_set

        self.parse_args()
        self.run_command()

    def command_set(self):
        if self.origin_hint is not None and len(self.origin_hint) == 0:
            raise Exception('Invalid/empty origin-hint')
        if self.origin_hint:
            filename = '.'.join((self.origin_hint, 'yaml'))
        else:
            filename = None
        split = self.key_value.split('=', 1)
        if len(split) != 2:
            raise Exception('Invalid value specified')

        key, value = split
        if not key.startswith('network'):
            key = '.'.join(('network', key))

        # Split the string into a list on the dot separators, and unescape the remaining dots
        yaml_path = [s.replace(r'\.', '.') for s in re.split(r'(?<!\\)\.', key)]

        parser = libnetplan.Parser()
        with tempfile.TemporaryFile() as tmp:
            libnetplan.create_yaml_patch(yaml_path, value, tmp)
            tmp.flush()
            tmp.seek(0, io.SEEK_SET)
            parser.load_nullable_fields(tmp)
            parser.load_yaml_hierarchy(self.root_dir)
            tmp.seek(0, io.SEEK_SET)
            parser.load_yaml(tmp)

        state = libnetplan.State()
        state.import_parser_results(parser)
        if self.origin_hint:
            state.write_yaml_file(filename, self.root_dir)
        else:
            state.update_yaml_hierarchy(FALLBACK_FILENAME, self.root_dir)
