#!/usr/bin/python3
# Functional tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2021 Canonical, Ltd.
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

import os
import shutil
import tempfile
import unittest

from tests.test_utils import call_cli


@unittest.skip('tests Python NetplanApply/NetplanTry internals, not the CLI binary')
class TestCLIPythonInternals(unittest.TestCase):
    '''Python-internal tests for NetplanApply and NetplanTry.

    These test static methods and object state that have no equivalent
    in the Rust CLI binary. They remain here for reference but are skipped
    when running the Rust-targeted test suite.
    '''
    pass


class TestCLIGet(unittest.TestCase):
    '''Netplan CLI get error-handling tests against the Rust binary'''

    def setUp(self):
        self.tmproot = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmproot, 'etc/netplan'))

    def tearDown(self):
        shutil.rmtree(self.tmproot)

    def test_raises_exception_invalid_bool(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('network:\n  ethernets:\n    eth0:\n      dhcp4: nothanks')
        with self.assertRaises(Exception) as ctx:
            call_cli(['get', '--root-dir', self.tmproot])
        self.assertIn('invalid boolean value', str(ctx.exception))

    @unittest.skipIf(os.getuid() == 0, 'Root can always read the file')
    def test_raises_exception_permission_denied(self):
        path = os.path.join(self.tmproot, 'etc/netplan/test.yaml')
        with open(path, 'w') as f:
            f.write('network:\n  ethernets:\n    eth0:\n      dhcp4: nothanks')
        os.chmod(path, 0)
        with self.assertRaises(Exception) as ctx:
            call_cli(['get', '--root-dir', self.tmproot])
        self.assertIn('Permission denied', str(ctx.exception))

    def test_raises_exception_validation_error(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('network:\n  ethernets:\n    eth0:\n      set-name: abc')
        with self.assertRaises(Exception) as ctx:
            call_cli(['get', '--root-dir', self.tmproot])
        self.assertIn('Error in network definition', str(ctx.exception))

    def test_raises_exception_vrf_mismatch(self):
        with open(os.path.join(self.tmproot, 'etc/netplan/test.yaml'), 'w') as f:
            f.write('''network:
  vrfs:
    vrf0:
      table: 100
      routes:
        - table: 200
          to: 1.2.3.4''')
        with self.assertRaises(Exception) as ctx:
            call_cli(['get', '--root-dir', self.tmproot])
        self.assertIn('VRF routes table mismatch', str(ctx.exception))
