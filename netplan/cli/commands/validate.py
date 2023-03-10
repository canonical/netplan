# Copyright (C) 2023 Canonical, Ltd.
# Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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

'''netplan validate command line'''

from netplan.cli.utils import NetplanCommand
import netplan.libnetplan as libnetplan


class ValidationException(Exception):
    pass


class NetplanValidate(NetplanCommand):

    def __init__(self):
        super().__init__(command_id='validate',
                         description='Load, parse and validate your configuration without applying it',
                         leaf=True)

    def run(self):
        self.parser.add_argument('--root-dir', default='/',
                                 help='Validate configuration files in this root directory instead of /')

        self.func = self.command_validate

        self.parse_args()
        self.run_command()

    def command_validate(self):
        try:
            # Parse the full, existing YAML config hierarchy
            parser = libnetplan.Parser()
            parser.load_yaml_hierarchy(self.root_dir)

            # Validate the final parser state
            state = libnetplan.State()
            state.import_parser_results(parser)
        except Exception as e:
            raise ValidationException(e)
