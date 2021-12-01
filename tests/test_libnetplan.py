#!/usr/bin/python3
# Blackbox tests of certain libnetplan functions. These are run during
# "make check" and don't touch the system configuration at all.
#
# Copyright (C) 2020-2021 Canonical, Ltd.
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
import ctypes
import ctypes.util

from generator.base import TestBase
from parser.base import capture_stderr
from tests.test_utils import MockCmd

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = os.path.join(rootdir, 'src', 'netplan.script')
# Make sure we can import our development netplan.
os.environ.update({'PYTHONPATH': '.'})

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p


class TestLibnetplan(TestBase):
    '''Test libnetplan functionality as used by the NetworkManager backend'''

    def setUp(self):
        super().setUp()
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        lib.netplan_clear_netdefs()
        super().tearDown()

    def test_get_id_from_filename(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_rootdir(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/some/rootdir/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_wifi(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection'.encode(), 'SOME-SSID'.encode())
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_wifi_invalid_suffix(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID'.encode(), 'SOME-SSID'.encode())
        self.assertEqual(out, None)

    def test_get_id_from_filename_invalid_prefix(self):
        out = lib.netplan_get_id_from_nm_filename('INVALID/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, None)

    def test_parse_keyfile_missing(self):
        f = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(f))
        with capture_stderr() as outf:
            self.assertFalse(lib.netplan_parse_keyfile(f.encode(), None))
            with open(outf.name, 'r') as f:
                self.assertIn('netplan: cannot load keyfile', f.read().strip())

    def test_generate(self):
        self.mock_netplan_cmd = MockCmd("netplan")
        os.environ["TEST_NETPLAN_CMD"] = self.mock_netplan_cmd.path
        self.assertTrue(lib.netplan_generate(self.workdir.name.encode()))
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "generate", "--root-dir", self.workdir.name],
        ])

    def test_delete_connection(self):
        os.environ["TEST_NETPLAN_CMD"] = exe_cli
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true''')
        self.assertTrue(os.path.isfile(orig))
        # Parse all YAML and delete 'some-netplan-id' connection file
        self.assertTrue(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
        self.assertFalse(os.path.isfile(orig))

    def test_delete_connection_id_not_found(self):
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true''')
        self.assertTrue(os.path.isfile(orig))
        with capture_stderr() as outf:
            self.assertFalse(lib.netplan_delete_connection('unknown-id'.encode(), self.workdir.name.encode()))
            self.assertTrue(os.path.isfile(orig))
            with open(outf.name, 'r') as f:
                self.assertIn('netplan_delete_connection: Cannot delete unknown-id, does not exist.', f.read().strip())

    def test_delete_connection_two_in_file(self):
        os.environ["TEST_NETPLAN_CMD"] = exe_cli
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true
    other-id:
      dhcp6: true''')
        self.assertTrue(os.path.isfile(orig))
        self.assertTrue(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
        self.assertTrue(os.path.isfile(orig))
        # Verify the file still exists and still contains the other connection
        with open(orig, 'r') as f:
            self.assertEquals(f.read(), 'network:\n  ethernets:\n    other-id:\n      dhcp6: true\n')

    def test_write_netplan_conf(self):
        netdef_id = 'some-netplan-id'
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        generated = os.path.join(self.confdir, '10-netplan-{}.yaml'.format(netdef_id))
        with open(orig, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    some-netplan-id:
      renderer: networkd
      match:
        name: "eth42"
''')
        # Parse YAML and and re-write the specified netdef ID into a new file
        self.assertTrue(lib.netplan_parse_yaml(orig.encode(), None))
        lib._write_netplan_conf(netdef_id.encode(), self.workdir.name.encode())
        self.assertEqual(lib.netplan_clear_netdefs(), 1)
        self.assertTrue(os.path.isfile(generated))
        with open(orig, 'r') as f:
            with open(generated, 'r') as new:
                self.assertEquals(f.read(), new.read())
