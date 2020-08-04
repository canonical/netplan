#!/usr/bin/python3
#
# Copyright (C) 2018 Canonical, Ltd.
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

'''netplan generate command line'''

import logging
import sys
import subprocess

import netplan.cli.utils as utils


class NetplanGenerate(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='generate',
                         description='Generate backend specific configuration files'
                                     ' from /etc/netplan/*.yaml',
                         leaf=True)

    def run(self):
        self.parser.add_argument('--root-dir',
                                 help='Search for and generate configuration files in this root directory instead of /')
        self.parser.add_argument('--mapping',
                                 help='Display the netplan device ID/backend/interface name mapping and exit.')

        self.func = self.command_generate

        self.parse_args()
        self.run_command()

    def command_generate(self):
        argv = [utils.get_generator_path()]
        if self.root_dir:
            argv += ['--root-dir', self.root_dir]
        if self.mapping:
            argv += ['--mapping', self.mapping]
        logging.debug('command generate: running %s', argv)
        # FIXME: os.execv(argv[0], argv) would be better but fails coverage
        sys.exit(subprocess.call(argv))
