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

import yaml
import re

import netplan.cli.utils as utils
from netplan.configmanager import ConfigManager


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

    def command_get(self):
        config_manager = ConfigManager(prefix=self.root_dir)
        config_manager.parse()
        tree = config_manager.tree

        if self.key != 'all':
            # The 'network.' prefix is optional for netsted keys, its always assumed to be there
            if not self.key.startswith('network.') and not self.key == 'network':
                self.key = 'network.' + self.key
            # Split at '.' but not at '\.' via negative lookbehind expression
            for k in re.split(r'(?<!\\)\.', self.key):
                k = k.replace('\\.', '.')  # Unescape interface-ids, containing dots
                if k in tree.keys():
                    tree = tree[k]
                    if not isinstance(tree, dict):
                        break
                else:
                    tree = None
                    break

        out = yaml.dump(tree, default_flow_style=False)[:-1]  # Remove trailing '\n'
        if not isinstance(tree, dict) and not isinstance(tree, list):
            out = out[:-4]  # Remove yaml.dump's '\n...' on primitive values
        print(out)
