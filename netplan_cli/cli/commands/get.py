#!/usr/bin/python3
#
# Copyright (C) 2020-2023 Canonical, Ltd.
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

'''netplan get command line'''

from ..state import NetplanConfigState
from .. import utils


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
        state_data = NetplanConfigState(self.key, self.root_dir)
        print(state_data, end='')
