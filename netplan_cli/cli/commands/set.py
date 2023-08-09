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

'''netplan set command line'''

import tempfile
import re
import io

from ..utils import NetplanCommand
import netplan

FALLBACK_FILENAME = '70-netplan-set.yaml'
GLOBAL_KEYS = ['renderer', 'version']


class NetplanSet(NetplanCommand):

    def __init__(self):
        super().__init__(command_id='set',
                         description='Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true',
                         leaf=True)

    def run(self):
        self.parser.add_argument('key_value', type=str,
                                 help='The nested key=value pair in dotted format. Value can be NULL to delete a key.')
        self.parser.add_argument('--origin-hint', type=str,
                                 help='Can be used to help choose a name for the overwrite YAML file. \
                                       A .yaml suffix will be appended automatically.')
        self.parser.add_argument('--root-dir', default='/',
                                 help='Overwrite configuration files in this root directory instead of /')

        self.func = self.command_set

        self.parse_args()
        self.run_command()

    def command_set(self):
        if self.origin_hint is not None and len(self.origin_hint) == 0:
            raise Exception('Invalid/empty origin-hint')
        if self.origin_hint:
            filename = '.'.join((self.origin_hint, 'yaml'))
        else:
            filename = None
        split = self.key_value.split('=', 1)
        if len(split) != 2:
            raise Exception('Invalid value specified')

        key, value = split
        if not key.startswith('network'):
            key = '.'.join(('network', key))

        # Split the string into a list on the dot separators, and unescape the remaining dots
        yaml_path = [s.replace(r'\.', '.') for s in re.split(r'(?<!\\)\.', key)]

        parser = netplan.Parser()
        with tempfile.TemporaryFile() as tmp:
            netplan._create_yaml_patch(yaml_path, value, tmp)
            tmp.flush()

            # Load fields that are about to be deleted (e.g. some.setting=NULL)
            # Ignore those fields when parsing subsequent YAML files
            tmp.seek(0, io.SEEK_SET)
            parser.load_nullable_fields(tmp)

            # Parse the full, existing YAML config hierarchy
            parser.load_yaml_hierarchy(self.root_dir)

            # Load YAML patch, containing our update (new or deleted settings)
            tmp.seek(0, io.SEEK_SET)
            parser.load_yaml(tmp)

            # Validate the final parser state
            state = netplan.State()
            state.import_parser_results(parser)

            if filename:  # only act on the output file (a.k.a. "origin-hint")
                parser_output_file = netplan.Parser()

                # Load fields that are about to be deleted ("some.setting=NULL")
                # Ignore those fields when parsing subsequent YAML files
                tmp.seek(0, io.SEEK_SET)
                parser_output_file.load_nullable_fields(tmp)

                # Load globals/netdefs that are to be ignored from the existing
                # YAML hierarchy, as our patch is supposed to override settings
                # in those netdefs via the output file.
                # Those netdefs and globals must end up in the output file
                # (a.k.a. "origin-hint", <filename>), have they been defined in
                # pre-existing YAML files or not.
                tmp.seek(0, io.SEEK_SET)
                parser_output_file._load_nullable_overrides(tmp, constraint=filename)

                # Parse the full YAML hierarchy and new patch, ignoring any
                # nullable overrides (netdefs/globals) from pre-existing files
                # and ignoring any nullable fields (settings to be deleted).
                # This way we can avoid updates to certain netdefs/globals to be
                # redirected into existing YAML files (defining those same
                # stanzas) or ignored, but have them written out to the single
                # output file.
                # XXX: The origin file of each individual YAML setting/stanza
                #      should be tracked individually, to avoid this
                #      double-parsing workaround (LP: #2003727)
                parser_output_file.load_yaml_hierarchy(self.root_dir)
                tmp.seek(0, io.SEEK_SET)
                parser_output_file.load_yaml(tmp)

                # Import the partial parser state, ignoring duplicated netdefs
                # from pre-existing YAML files, so we can force write the patch
                # contents to the output file or update this file if exists.
                state_output_file = netplan.State()
                state_output_file.import_parser_results(parser_output_file)
                state_output_file._write_yaml_file(filename, self.root_dir)
            else:
                state._update_yaml_hierarchy(FALLBACK_FILENAME, self.root_dir)
