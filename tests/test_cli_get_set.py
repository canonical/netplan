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

from contextlib import redirect_stdout
from netplan.cli.core import Netplan

# Make sure we can import our development netplan.
# os.environ.update({'PYTHONPATH': '.'})
# os.environ.update({'LD_LIBRARY_PATH': '.:{}'.format(os.environ.get('LD_LIBRARY_PATH'))})


def _call_cli(args):
    old_sys_argv = sys.argv
    sys.argv = [old_sys_argv[0]] + args
    try:
        f = io.StringIO()
        with redirect_stdout(f):
            Netplan().main()
            return f.getvalue()
    except Exception as e:
        return e
    finally:
        sys.argv = old_sys_argv


class TestSet(unittest.TestCase):
    '''Test netplan set'''
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.file = '00-netplan-set.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

    def _set(self, args):
        args.insert(0, 'set')
        return _call_cli(args + ['--root-dir', self.workdir.name])

    def test_set_scalar(self):
        self._set(['ethernets.eth0.dhcp4=true'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0:\n      dhcp4: \'true\'', f.read())

    def test_set_scalar2(self):
        self._set(['ethernets.eth0.dhcp4="yes"'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('network:\n  ethernets:\n    eth0:\n      dhcp4: \'yes\'', f.read())

    def test_set_sequence(self):
        self._set(['ethernets.eth0.addresses=[1.2.3.4/24, \'5.6.7.8/24\']'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('''network:\n  ethernets:\n    eth0:
      addresses:
      - 1.2.3.4/24
      - 5.6.7.8/24''', f.read())

    def test_set_sequence2(self):
        self._set(['ethernets.eth0.addresses="1.2.3.4/24",5.6.7.8/24'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIn('''network:\n  ethernets:\n    eth0:
      addresses:
      - 1.2.3.4/24
      - 5.6.7.8/24''', f.read())

    def test_set_invalid_hint(self):
        err = self._set(['ethernets.eth0.dhcp4=true', '--origin-hint=some-file.yml'])
        self.assertIsInstance(err, Exception)
        self.assertIn('needs to be a .yaml file!', str(err))
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid(self):
        err = self._set(['xxx.yyy=abc'])
        self.assertIsInstance(err, Exception)
        self.assertIn('unknown key \'xxx\'\n  xxx:\n', str(err))
        self.assertFalse(os.path.isfile(self.path))

    def test_invalid_yaml_read(self):
        with open(self.path, 'w') as f:
            f.write('''network: {}}''')
        err = self._set(['ethernets.eth0.dhcp4=true'])
        self.assertIsInstance(err, Exception)
        self.assertTrue(os.path.isfile(self.path))
        self.assertIn('expected <block end>, but found \'}\'', str(err))

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
            self.assertIn('    eth0:\n      dhcp4: \'true\'', out)
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
            self.assertIn('    ens3:\n      dhcp4: \'yes\'', out)

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
            self.assertIn('    ens3:\n      dhcp4: \'true\'', out)

    def test_set_delete(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    ens3: {dhcp4: yes, dhcp6: yes}
    eth0: {addresses: [1.2.3.4]}''')
        self._set(['ethernets.eth0.addresses=NULL'])
        self._set(['ethernets.ens3.dhcp6=NULL'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = f.read()
            self.assertIn('network:\n  ethernets:\n', out)
            self.assertIn('  version: 2', out)
            self.assertIn('    ens3:\n      dhcp4: true', out)
            self.assertNotIn('dhcp6: true', out)
            self.assertNotIn('addresses:', out)
            self.assertNotIn('eth0:', out)

    def test_set_delete_file(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['ethernets.ens3.dhcp4=NULL'])
        # The file should be deleted if this was the last/only key left
        self.assertFalse(os.path.isfile(self.path))


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

    def test_get_sequence(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {addresses: [1.2.3.4/24, 5.6.7.8/24]}''')
        out = self._get(['ethernets.ens3.addresses'])
        self.assertIn('- 1.2.3.4/24\n- 5.6.7.8/24', out)

    def test_get_null(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        out = self._get(['ethernets.eth0.dhcp4'])
        self.assertIn('null', out)
