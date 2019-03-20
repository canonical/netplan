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
        import netplan.cli.commands

        self._import_subcommands(netplan.cli.commands)

        super().parse_args()

    def main(self):
        logger = logging.getLogger('')
        logstream = logging.StreamHandler()
        logger.setLevel('INFO')

        logstream.setFormatter(
            logging.Formatter("%(name)s:%(lineno)d: %(levelname)s: %(message)s"))

        logger.addHandler(logstream)

        self.parse_args()

        self.run_command()
