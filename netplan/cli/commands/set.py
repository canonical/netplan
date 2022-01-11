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

'''netplan set command line'''

import os
import yaml
import tempfile
import re
import logging
import shutil
import glob

from netplan.cli.utils import NetplanCommand
import netplan.libnetplan as libnetplan
from netplan.configmanager import ConfigManager

FALLBACK_HINT = '70-netplan-set'
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

    def is_emtpy_yaml(self, tree):
        if isinstance(tree, dict) and list(tree.keys()) == ['network'] and tree['network'] is None:
            return True
        return False

    def split_tree_by_hint(self, set_tree) -> (str, dict):
        network = set_tree.get('network', {})
        # A mapping of 'origin-hint' -> YAML tree (one subtree per netdef)
        subtrees = dict()
        for devtype in network:
            if devtype in GLOBAL_KEYS:
                continue  # special handling of global keys down below
            devtype_content = network.get(devtype, [])
            # Special case: removal of a whole devtype.
            # We replace the devtype null node with a dict of all defined netdefs
            # set to None.
            if devtype_content is None:
                devtype_content = {dev: None for dev in libnetplan.netplan_get_ids_for_devtype(devtype, self.root_dir)}
                network[devtype] = devtype_content
            for netdef in devtype_content:
                hint = FALLBACK_HINT
                filename = libnetplan.netplan_get_filename_by_id(netdef, self.root_dir)
                if filename:
                    hint = os.path.basename(filename)[:-5]  # strip prefix and .yaml
                netdef_tree = {'network': {devtype: {netdef: network.get(devtype).get(netdef)}}}
                # Merge all netdef trees which are going to be written to the same file/hint
                subtrees[hint] = self.merge(subtrees.get(hint, {}), netdef_tree)

        # Merge GLOBAL_KEYS into one of the available subtrees
        # Write to same file (if only one hint/subtree is available)
        # Write to FALLBACK_HINT if multiple hints/subtrees are available, as we do not know where it is supposed to go
        if any(network.get(key) for key in GLOBAL_KEYS):
            # Write to the same file, if we have only one file-hint or to FALLBACK_HINT otherwise
            hint = list(subtrees)[0] if len(subtrees) == 1 else FALLBACK_HINT
            for key in GLOBAL_KEYS:
                tree = {'network': {key: network.get(key)}}
                subtrees[hint] = self.merge(subtrees.get(hint, {}), tree)

        # return a list of (str:hint, dict:subtree) tuples
        return subtrees.items()

    def command_set(self):
        if self.origin_hint is not None and len(self.origin_hint) == 0:
            raise Exception('Invalid/empty origin-hint')
        split = self.key_value.split('=', 1)
        if len(split) != 2:
            raise Exception('Invalid value specified')
        key, value = split
        set_tree = self.parse_key(key, yaml.safe_load(value))

        # special case: clear all YAML (or a specific hint file) if "network=null" is set
        if self.is_emtpy_yaml(set_tree):
            path = os.path.join('etc', 'netplan')
            if self.origin_hint:  # clear specific hint file, it it does exist
                hint_path = os.path.join(self.root_dir, path, self.origin_hint + '.yaml')
                if os.path.isfile(hint_path):
                    os.remove(hint_path)
            else:  # clear all YAML files in <ROOT_DIR>/etc/netplan/*.yaml
                yaml_files = glob.glob(os.path.join(self.root_dir, path, '*.yaml'))
                for f in yaml_files:
                    os.remove(f)
            return

        hints = [(self.origin_hint, set_tree)]
        # Override YAML config in each individual netdef file if origin-hint is not set
        if self.origin_hint is None:
            hints = self.split_tree_by_hint(set_tree)

        for hint, subtree in hints:
            self.write_file(subtree, hint + '.yaml', self.root_dir)

    def parse_key(self, key, value):
        # The 'network.' prefix is optional for netsted keys, its always assumed to be there
        if not key.startswith('network.') and not key == 'network':
            key = 'network.' + key
        # Split at '.' but not at '\.' via negative lookbehind expression
        split = re.split(r'(?<!\\)\.', key)
        tree = {}
        i = 1
        t = tree
        for part in split:
            part = part.replace('\\.', '.')  # Unescape interface-ids, containing dots
            val = {}
            if i == len(split):
                val = value
            t = t.setdefault(part, val)
            i += 1
        return tree

    def merge(self, a, b, path=None):
        """
        Merges tree/dict 'b' into tree/dict 'a'
        """
        if path is None:
            path = []
        for key in b:
            if key in a:
                if isinstance(a[key], dict) and isinstance(b[key], dict):
                    self.merge(a[key], b[key], path + [str(key)])
                elif b[key] is None:
                    del a[key]
                else:
                    # Overwrite existing key with new key/value from 'set' command
                    a[key] = b[key]
            else:
                a[key] = b[key]
        return a

    def write_file(self, set_tree, name, rootdir='/'):
        tmproot = tempfile.TemporaryDirectory(prefix='netplan-set_')
        path = os.path.join('etc', 'netplan')
        os.makedirs(os.path.join(tmproot.name, path))

        config = {'network': {}}
        absp = os.path.join(rootdir, path, name)
        # check stat(absp), as we don't care about empty hint files
        if os.path.isfile(absp) and os.stat(absp).st_size > 0:
            with open(absp, 'r') as f:
                c = yaml.safe_load(f)
                if c is not None:  # ignore empty file, even if it contains whitespace
                    config = c

        new_tree = self.merge(config, set_tree)
        stripped = ConfigManager.strip_tree(new_tree)
        logging.debug('Writing file {}: {}'.format(name, stripped))
        if 'network' in stripped and list(stripped['network'].keys()) == ['version']:
            # Clear file if only 'network: {version: 2}' is left
            logging.debug('Empty YAML, deleting file {}'.format(absp))
            if os.path.isfile(absp):
                os.remove(absp)
        elif 'network' in stripped:
            tmpp = os.path.join(tmproot.name, path, name)
            with open(tmpp, 'w+') as f:
                new_yaml = yaml.dump(stripped, indent=2, default_flow_style=False)
                f.write(new_yaml)
            # Validate the newly created file, by parsing it via libnetplan
            libnetplan.netplan_parse(tmpp)
            # Valid, move it to final destination
            shutil.copy2(tmpp, absp)
            os.remove(tmpp)
        elif stripped == {}:
            # Clear file (if it exists) if the last/only key got removed
            # do nothing otherwise
            logging.debug('Removed last key from YAML, deleting file {}'.format(absp))
            if os.path.isfile(absp):
                os.remove(absp)
        else:  # pragma nocover
            raise Exception('Invalid input: {}'.format(set_tree))
