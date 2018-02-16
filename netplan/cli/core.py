#!/usr/bin/python3
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
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

'''netplan command line'''

import logging
import os

import netplan.cli.utils as utils


class Netplan(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='',
                         description='Network configuration in YAML',
                         leaf=False)

    def parse_args(self):
        from netplan.cli.commands import NetplanApply
        from netplan.cli.commands import NetplanGenerate
        from netplan.cli.commands import NetplanIp
        from netplan.cli.commands import NetplanMigrate

        # command: generate
        self.command_generate = NetplanGenerate()
        p_generate = self.subparsers.add_parser('generate',
                                                description='Generate backend specific configuration files'
                                                            ' from /etc/netplan/*.yaml',
                                                help='Generate backend specific configuration files from /etc/netplan/*.yaml',
                                                add_help=False)
        p_generate.set_defaults(func=self.command_generate.run, commandclass=self.command_generate)

        # command: apply
        self.command_apply = NetplanApply()
        p_apply = self.subparsers.add_parser('apply',
                                             description='Apply current netplan config to running system',
                                             help='Apply current netplan config to running system (use with care!)',
                                             add_help=False)
        p_apply.set_defaults(func=self.command_apply.run, commandclass=self.command_apply)

        # command: ifupdown-migrate
        self.command_migrate = NetplanMigrate()
        p_migrate = self.subparsers.add_parser('ifupdown-migrate',
                                               description='Migration of /etc/network/interfaces to netplan',
                                               help='Try to convert /etc/network/interfaces to netplan '
                                                    'If successful, disable /etc/network/interfaces',
                                               add_help=False)
        p_migrate.set_defaults(func=self.command_migrate.run, commandclass=self.command_migrate)

        # command: ip
        self.command_ip = NetplanIp()
        p_ip = self.subparsers.add_parser('ip',
                                          description='Describe current IP configuration',
                                          help='Describe current IP configuration',
                                          add_help=False)
        p_ip.set_defaults(func=self.command_ip.run, commandclass=self.command_ip)

        super().parse_args()

    def main(self):
        self.parse_args()

        if self.debug:
            logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(message)s')
            os.environ['G_MESSAGES_DEBUG'] = 'all'
        else:
            logging.basicConfig(level=logging.INFO, format='%(message)s')

        self.run_command()
