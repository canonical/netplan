#!/usr/bin/env python3

# Copyright (C) 2023 Canonical, Ltd.
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

import io
import tempfile
from netplan import Parser, State, _create_yaml_patch
from netplan import NetplanException, NetplanParserException
FALLBACK_FILENAME = '70-netplan-set.yaml'

# This script is a demo/example, making use of Netplan's CFFI Python bindings.
# It does process your local /etc/netplan/ hierarchy, so be careful using it.
# At first, it creates a Parser() object and a YAML patch, setting a
# "network.ethernets.eth99.dhcp4=true" value. It loads any existing Netplan
# YAML hierarcy from /etc/netplan/ and loads/applies the above mentioned patch
# on top of it. Afterwards, it creates a State() object, importing parsed data
# for validation and checks for any errors.
# On succesful validation, it walks through all NetDefs in the validated
# Netplan state and prints the Netplan ID and backend renderer of given NetDef.
# Finally, it writes the validated state (including the eth99.dhcp4 setting)
# back to disk in /etc/netplan/.
if __name__ == '__main__':
    yaml_path = ['network', 'ethernets', 'eth99', 'dhcp4']
    value = 'true'

    parser = Parser()
    with tempfile.TemporaryFile() as tmp:
        _create_yaml_patch(yaml_path, value, tmp)
        tmp.flush()

        # Parse the full, existing YAML config hierarchy
        parser.load_yaml_hierarchy(rootdir='/')

        # Load YAML patch, containing our new settings
        tmp.seek(0, io.SEEK_SET)
        parser.load_yaml(tmp)

        # Validate the final parser state
        state = State()
        try:
            # validation of current state + new settings
            state.import_parser_results(parser)
        except NetplanParserException as e:
            print('Error in', e.filename, 'Row/Col', e.line, e.column, '->', e.message)
        except NetplanException as e:
            print('Error:', e.message)

        # Walk through all NetdefIDs in the state and print their backend
        # renderer, to demonstrate working with NetDefinitionIterator &
        # NetDefinition
        for netdef_id, netdef in state.netdefs.items():
            print('Netdef', netdef_id, 'is managed by:', netdef.backend)

        # Write the new data from the YAML patch to disk, updating an
        # existing Netdef, if file already exists, or FALLBACK_FILENAME
        state._update_yaml_hierarchy(FALLBACK_FILENAME, rootdir='/')
