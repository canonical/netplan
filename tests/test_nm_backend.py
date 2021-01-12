#!/usr/bin/python3
# Blackbox tests of NetworkManager netplan backend. These are run during
# "make check" and don't touch the system configuration at all.
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
import shutil
import ctypes
import ctypes.util
import tempfile

from generator.base import TestBase


lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p


# TODO: refactor into base class (not copy from test_dbus.py), or make use of mockproc package
class MockCmd:
    """MockCmd will mock a given command name and capture all calls to it"""

    def __init__(self, name):
        self._tmp = tempfile.TemporaryDirectory()
        self.name = name
        self.path = os.path.join(self._tmp.name, name)
        self.call_log = os.path.join(self._tmp.name, "call.log")
        with open(self.path, "w") as fp:
            fp.write("""#!/bin/bash
printf "%%s" "$(basename "$0")" >> %(log)s
printf '\\0' >> %(log)s

for arg in "$@"; do
     printf "%%s" "$arg" >> %(log)s
     printf '\\0'  >> %(log)s
done

printf '\\0' >> %(log)s
""" % {'log': self.call_log})
        os.chmod(self.path, 0o755)

    def calls(self):
        """
        calls() returns the calls to the given mock command in the form of
        [ ["cmd", "call1-arg1"], ["cmd", "call2-arg1"], ... ]
        """
        with open(self.call_log) as fp:
            b = fp.read()
        calls = []
        for raw_call in b.rstrip("\0\0").split("\0\0"):
            call = raw_call.rstrip("\0")
            calls.append(call.split("\0"))
        return calls


class TestNetworkManagerBackend(TestBase):
    '''Test libnetplan functionality as used by NetworkManager backend'''

    def setUp(self):
        super().setUp()
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        super().tearDown()

    def test_get_id_from_filename(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
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

    def test_generate(self):
        self.mock_netplan_cmd = MockCmd("netplan")
        os.environ["TEST_NETPLAN_CMD"] = self.mock_netplan_cmd.path
        self.assertTrue(lib.netplan_generate(self.workdir.name.encode()))
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "generate", "--root-dir", self.workdir.name],
        ])
