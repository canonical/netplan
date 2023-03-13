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

import glob
import os

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

        if self.debug:
            # Replicates the behavior of src/util.c:netplan_parser_load_yaml_hierarchy()

            lib_glob = 'lib/netplan/*.yaml'
            etc_glob = 'etc/netplan/*.yaml'
            run_glob = 'run/netplan/*.yaml'

            lib_files = glob.glob(lib_glob, root_dir=self.root_dir)
            etc_files = glob.glob(etc_glob, root_dir=self.root_dir)
            run_files = glob.glob(run_glob, root_dir=self.root_dir)

            # Order of priority: lib -> etc -> run
            files = lib_files + etc_files + run_files
            files_dict = {}
            shadows = []

            # Shadowing files with the same name and lower priority
            for file in files:
                basename = os.path.basename(file)
                filepath = os.path.join(self.root_dir, file)

                if key := files_dict.get(basename):
                    shadows.append((key, filepath))

                files_dict[basename] = filepath

            files = sorted(files_dict.keys())
            if files:
                print('Order in which your files are parsed:')
                for file in files:
                    print(files_dict.get(file))

            if shadows:
                print('\nThe following files were shadowed:')
                for shadow in shadows:
                    print(f'{shadow[0]} shadowed by {shadow[1]}')

        try:
            # Parse the full, existing YAML config hierarchy
            parser = libnetplan.Parser()
            parser.load_yaml_hierarchy(self.root_dir)

            # Validate the final parser state
            state = libnetplan.State()
            state.import_parser_results(parser)
        except Exception as e:
            raise ValidationException(e)
