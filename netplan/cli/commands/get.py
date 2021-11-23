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

'''netplan get command line'''

import sys
import io
import tempfile
import re

import netplan.cli.utils as utils
import netplan.libnetplan as libnetplan


class NetplanGet(utils.NetplanCommand):
    def __init__(self):
        super().__init__(command_id='get',
                         description='Get a setting by specifying a nested key like "ethernets.eth0.addresses", or "all"',
                         leaf=True)

    def run(self):
        self.parser.add_argument('key', type=str, nargs='?', default='all', help='The nested key in dotted format')
        self.parser.add_argument('--root-dir', default='/',
                                 help='Read configuration files from this root directory instead of /')

        self.func = self.command_get

        self.parse_args()
        self.run_command()

    def dump_state(self, key, np_state, output_file):
        if key == 'all':
            np_state.dump_yaml(output_file=output_file)
            return

        if not key.startswith('network'):
            key = '.'.join(('network', key))
        # Replace the '.' with '\t' but not at '\.' via negative lookbehind expression
        key = re.sub(r'(?<!\\)\.', '\t', key).replace(r'\.', '.')

        with tempfile.NamedTemporaryFile() as tmp_in:
            np_state.dump_yaml(output_file=tmp_in)
            libnetplan.dump_yaml_subtree(key, tmp_in, output_file=output_file)

    def command_get(self):
        parser = libnetplan.Parser()
        parser.load_yaml_hierarchy(rootdir=self.root_dir)

        np_state = libnetplan.State()
        np_state.import_parser_results(parser)

        try:
            sys.stdout.fileno()
            output_file = sys.stdout  # pragma: nocover
        except io.UnsupportedOperation:  # Test environment detected, using a buffer file
            output_file = tempfile.TemporaryFile()

        self.dump_state(self.key, np_state, output_file)

        if output_file != sys.stdout:
            output_file.flush()
            output_file.seek(0)
            sys.stdout.write(output_file.read().decode('utf-8'))
            output_file.close()
