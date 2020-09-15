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

import netplan.cli.utils as utils
from netplan.configmanager import ConfigManager


class NetplanGet(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='get',
                         description='Get a setting by specifying some.nested.key',
                         leaf=True)

    def run(self):
        self.parser.add_argument('key',
                                 type=str,
                                 help='The setting as some.nested.key')
        self.parser.add_argument('--root-dir',
                                 help='Overwrite configuration files in this root directory instead of /')

        self.func = self.command_get

        self.parse_args()
        self.run_command()

    def command_get(self):
        root = self.root_dir if self.root_dir else '/'
        config_manager = ConfigManager(prefix=root)
        config_manager.parse()
        tree = config_manager.network  # XXX: consider .config
        # TODO: beware of dots in key/interface-names
        for k in self.key.split('.'):
            if k in tree.keys():
                tree = tree[k]
                if not isinstance(tree, dict):
                    break
            else:
                tree = None
                break

        print(yaml.dump(tree, default_flow_style=False))
