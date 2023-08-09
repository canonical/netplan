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

from . import utils
from netplan import NetplanException, NetplanValidationException, NetplanParserException


FALLBACK_PATH = '/usr/bin:/snap/bin'


class Netplan(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='',
                         description='Network configuration in YAML',
                         leaf=False)
        os.environ.update({
            'LC_ALL': 'C',
            'PATH': os.getenv('PATH', FALLBACK_PATH)})

    def parse_args(self):
        from . import commands as cli_commands

        self._import_subcommands(cli_commands)

        super().parse_args()

    def main(self):
        self.parse_args()

        if self.debug:
            logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(message)s')
            os.environ['G_MESSAGES_DEBUG'] = 'all'
        else:
            logging.basicConfig(level=logging.INFO, format='%(message)s')

        try:
            self.run_command()
        except NetplanParserException as e:
            message = f'{e.filename}:{e.line}:{e.column}: {e}'
            logging.warning(f'Command failed: {message}')
        except NetplanValidationException as e:
            logging.warning(f'Command failed: {e.filename}: {e}')
        except NetplanException as e:
            logging.warning(f'Command failed: {e}')
