#!/usr/bin/python3
# Blackbox tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
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

import os
import sys
import unittest
import tempfile
import io
import shutil

from contextlib import redirect_stdout
from netplan.cli.core import Netplan


def _call_cli(args):
    old_sys_argv = sys.argv
    sys.argv = [old_sys_argv[0]] + args
    f = io.StringIO()
    try:
        with redirect_stdout(f):
            Netplan().main()
            return f.getvalue()
    finally:
        sys.argv = old_sys_argv


class TestSet(unittest.TestCase):
    '''Test netplan set'''
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory(prefix='netplan_')
        self.file = '70-netplan-set.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

    def tearDown(self):
        shutil.rmtree(self.workdir.name)

    def _set(self, args):
        args.insert(0, 'set')
        out = _call_cli(args + ['--root-dir', self.workdir.name])
        self.assertEqual(out, '', msg='netplan set returned unexpected output')

    def test_set_scalar(self):
        self._set(['ethernets.eth0.dhcp4=true'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0:\n      dhcp4: true', f.read())

    def test_set_scalar2(self):
        self._set(['ethernets.eth0.dhcp4="yes"'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0:\n      dhcp4: \'yes\'', f.read())

    def test_set_global(self):
        self._set([r'network={renderer: NetworkManager}'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('network:\n  renderer: NetworkManager', f.read())

    def test_set_sequence(self):
        self._set(['ethernets.eth0.addresses=[1.2.3.4/24, \'5.6.7.8/24\']'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('''network:\n  ethernets:\n    eth0:
      addresses:
      - 1.2.3.4/24
      - 5.6.7.8/24''', f.read())

    def test_set_sequence2(self):
        self._set(['ethernets.eth0.addresses=["1.2.3.4/24", 5.6.7.8/24]'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('''network:\n  ethernets:\n    eth0:
      addresses:
      - 1.2.3.4/24
      - 5.6.7.8/24''', f.read())

    def test_set_mapping(self):
        self._set(['ethernets.eth0={addresses: [1.2.3.4/24], dhcp4: true}'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('''network:\n  ethernets:\n    eth0:
      addresses:
      - 1.2.3.4/24
      dhcp4: true''', f.read())

    def test_set_origin_hint(self):
        self._set(['ethernets.eth0.dhcp4=true', '--origin-hint=99_snapd'])
        p = os.path.join(self.workdir.name, 'etc', 'netplan', '99_snapd.yaml')
        self.assertTrue(os.path.isfile(p))
        with open(p, 'r') as f:
            self.assertEquals('network:\n  ethernets:\n    eth0:\n      dhcp4: true\n', f.read())

    def test_set_empty_origin_hint(self):
        with self.assertRaises(Exception) as context:
            self._set(['ethernets.eth0.dhcp4=true', '--origin-hint='])
        self.assertTrue('Invalid/empty origin-hint' in str(context.exception))

    def test_set_empty_hint_file(self):
        empty_file = os.path.join(self.workdir.name, 'etc', 'netplan', '00-empty.yaml')
        open(empty_file, 'w').close()  # touch empty file
        self._set(['ethernets.eth0.dhcp4=true', '--origin-hint=00-empty'])
        self.assertTrue(os.path.isfile(empty_file))
        with open(empty_file, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0:\n      dhcp4: true', f.read())

    def test_set_invalid(self):
        with self.assertRaises(Exception) as context:
            self._set(['xxx.yyy=abc'])
        self.assertIn('unknown key \'xxx\'\n  xxx:\n', str(context.exception))
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid_validation(self):
        with self.assertRaises(Exception) as context:
            self._set(['ethernets.eth0.set-name=myif0'])
        self.assertIn('eth0: \'set-name:\' requires \'match:\' properties', str(context.exception))
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid_validation2(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  tunnels:
    tun0:
      mode: sit
      local: 1.2.3.4
      remote: 5.6.7.8''')
        with self.assertRaises(Exception) as context:
            self._set(['tunnels.tun0.keys.input=12345'])
        self.assertIn('tun0: \'input-key\' is not required for this tunnel type', str(context.exception))

    def test_set_append(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['ethernets.eth0.dhcp4=true'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  ethernets:\n', out)
            self.assertIn('    ens3:\n      dhcp4: true', out)
            self.assertIn('    eth0:\n      dhcp4: true', out)
            self.assertIn('  version: 2', out)

    def test_set_overwrite_eq(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    ens3: {dhcp4: "yes"}''')
        self._set(['ethernets.ens3.dhcp4=yes'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  ethernets:\n', out)
            self.assertIn('    ens3:\n      dhcp4: true', out)

    def test_set_overwrite(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    ens3: {dhcp4: "yes"}''')
        self._set(['ethernets.ens3.dhcp4=true'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  ethernets:\n', out)
            self.assertIn('    ens3:\n      dhcp4: true', out)

    def test_set_delete(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    ens3: {dhcp4: yes, dhcp6: yes}
    eth0: {addresses: [1.2.3.4/24]}''')
        self._set(['ethernets.eth0.addresses=NULL'])
        self._set(['ethernets.ens3.dhcp6=null'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  ethernets:\n', out)
            self.assertIn('  version: 2', out)
            self.assertIn('    ens3:\n      dhcp4: true', out)
            self.assertNotIn('dhcp6: true', out)
            self.assertNotIn('addresses:', out)
            self.assertNotIn('eth0:', out)

    def test_set_delete_subtree(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    eth0: {addresses: [1.2.3.4/24]}''')
        self._set(['network.ethernets=null'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
        self.assertIn('network:\n', out)
        self.assertIn(' version: 2\n', out)
        self.assertIn(' renderer: NetworkManager\n', out)
        self.assertNotIn('ethernets:', out)

    def test_set_delete_file(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['network.ethernets.ens3.dhcp4=NULL'])
        # The file should be deleted if this was the last/only key left
        self.assertFalse(os.path.isfile(self.path))

    def test_set_delete_file_with_version(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['network.ethernets.ens3=NULL'])
        # The file should be deleted if only "network: {version: 2}" is left
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid_delete(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    eth0: {addresses: [1.2.3.4]}''')
        with self.assertRaises(Exception) as context:
            self._set(['ethernets.eth0.addresses'])
        self.assertEquals('Invalid value specified', str(context.exception))

    def test_set_escaped_dot(self):
        self._set([r'ethernets.eth0\.123.dhcp4=false'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0.123:\n      dhcp4: false', f.read())

    def test_set_invalid_input(self):
        with self.assertRaises(Exception) as context:
            self._set([r'ethernets.eth0={dhcp4:false}'])
        self.assertEquals(
                'Invalid input: {\'network\': {\'ethernets\': {\'eth0\': {\'dhcp4:false\': None}}}}',
                str(context.exception))

    def test_set_override_existing_file(self):
        override = os.path.join(self.workdir.name, 'etc', 'netplan', 'some-file.yaml')
        with open(override, 'w') as f:
            f.write(r'network: {ethernets: {eth0: {dhcp4: true}, eth1: {dhcp6: false}}}')
        self._set([r'ethernets.eth0.dhcp4=false'])
        self.assertFalse(os.path.isfile(self.path))
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  ethernets:\n    eth0:\n      dhcp4: false', out)  # new
            self.assertIn('eth1:\n      dhcp6: false', out)  # old

    def test_set_override_existing_file_escaped_dot(self):
        override = os.path.join(self.workdir.name, 'etc', 'netplan', 'some-file.yaml')
        with open(override, 'w') as f:
            f.write(r'network: {ethernets: {eth0.123: {dhcp4: true}}}')
        self._set([r'ethernets.eth0\.123.dhcp4=false'])
        self.assertFalse(os.path.isfile(self.path))
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0.123:\n      dhcp4: false', f.read())

    def test_set_override_multiple_existing_files(self):
        file1 = os.path.join(self.workdir.name, 'etc', 'netplan', 'eth0.yaml')
        with open(file1, 'w') as f:
            f.write(r'network: {ethernets: {eth0.1: {dhcp4: true}, eth0.2: {dhcp4: true}}}')
        file2 = os.path.join(self.workdir.name, 'etc', 'netplan', 'eth1.yaml')
        with open(file2, 'w') as f:
            f.write(r'network: {ethernets: {eth1: {dhcp4: true}}}')
        self._set([(r'network={renderer: NetworkManager, version: 2,'
                    r'ethernets:{'
                    r'eth1:{dhcp4: false},'
                    r'eth0.1:{dhcp4: false},'
                    r'eth0.2:{dhcp4: false}},'
                    r'bridges:{'
                    r'br99:{dhcp4: false}}}')])
        self.assertTrue(os.path.isfile(file1))
        with open(file1, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0.1:\n      dhcp4: false', f.read())
        self.assertTrue(os.path.isfile(file2))
        with open(file2, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth1:\n      dhcp4: false', f.read())
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  bridges:\n    br99:\n      dhcp4: false', out)
            self.assertIn('  version: 2', out)
            self.assertIn('  renderer: NetworkManager', out)


class TestGet(unittest.TestCase):
    '''Test netplan get'''
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.file = '00-config.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

    def _get(self, args):
        args.insert(0, 'get')
        return _call_cli(args + ['--root-dir', self.workdir.name])

    def test_get_scalar(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        out = self._get(['ethernets.ens3.dhcp4'])
        self.assertIn('true', out)

    def test_get_mapping(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3:
      dhcp4: yes
      addresses: [1.2.3.4/24, 5.6.7.8/24]''')
        out = self._get(['ethernets'])
        self.assertIn('''ens3:
  addresses:
  - 1.2.3.4/24
  - 5.6.7.8/24
  dhcp4: true''', out)

    def test_get_modems(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  modems:
    wwan0:
      apn: internet
      pin: 1234
      dhcp4: yes
      addresses: [1.2.3.4/24, 5.6.7.8/24]''')
        out = self._get(['modems.wwan0'])
        self.assertIn('''addresses:
- 1.2.3.4/24
- 5.6.7.8/24
apn: internet
dhcp4: true
pin: 1234''', out)

    def test_get_sequence(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {addresses: [1.2.3.4/24, 5.6.7.8/24]}''')
        out = self._get(['network.ethernets.ens3.addresses'])
        self.assertIn('- 1.2.3.4/24\n- 5.6.7.8/24', out)

    def test_get_null(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        out = self._get(['ethernets.eth0.dhcp4'])
        self.assertEqual('null\n', out)

    def test_get_escaped_dot(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0.123: {dhcp4: yes}''')
        out = self._get([r'ethernets.eth0\.123.dhcp4'])
        self.assertEquals('true\n', out)

    def test_get_all(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0: {dhcp4: yes}''')
        out = self._get([])
        self.assertEquals('''network:
  ethernets:
    eth0:
      dhcp4: true
  version: 2\n''', out)

    def test_get_network(self):
        with open(self.path, 'w') as f:
            f.write('network:\n  version: 2\n  renderer: NetworkManager')
        out = self._get(['network'])
        self.assertEquals('renderer: NetworkManager\nversion: 2\n', out)
