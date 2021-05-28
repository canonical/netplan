#
# Blackbox tests of netplan generate that verify that the generated
# configuration files look as expected. These are run during "make check" and
# don't touch the system configuration at all.
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
import ctypes
import ctypes.util

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), 'generate')

# make sure we point to libnetplan properly.
os.environ.update({'LD_LIBRARY_PATH': '.:{}'.format(os.environ.get('LD_LIBRARY_PATH'))})

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))


class TestBase(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.confdir = os.path.join(self.workdir.name, 'etc', 'netplan')
        self.nm_enable_all_conf = os.path.join(
            self.workdir.name, 'run', 'NetworkManager', 'conf.d', '10-globally-managed-devices.conf')
        self.maxDiff = None
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        super().tearDown()

    def generate(self, keyfile, netdef_id=None, expect_fail=False):
        '''Call libnetplan with given keyfile string as configuration'''
        # Autodetect default 'NM-<UUID>' netdef-id
        if not netdef_id:
            for line in keyfile.splitlines():
                if line.startswith('uuid='):
                    netdef_id = 'NM-' + line.split('=')[1]
                    break
        f = os.path.join(self.workdir.name, 'run/NetworkManager/system-connections/netplan-{}.nmconnection'.format(netdef_id))
        os.makedirs(os.path.dirname(f))
        with open(f, 'w') as file:
            file.write(keyfile)
        if expect_fail:
            # TODO: capture and return stderr/stdout
            self.assertFalse(lib.netplan_parse_keyfile(f.encode(), None))
        else:
            self.assertTrue(lib.netplan_parse_keyfile(f.encode(), None))
            lib._write_netplan_conf(netdef_id.encode(), self.workdir.name.encode())
            lib.netplan_clear_netdefs()


    def assert_netplan(self, file_contents_map):
        for uuid in file_contents_map.keys():
            self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(uuid))))
            with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(uuid)), 'r') as f:
                self.assertEqual(f.read(), file_contents_map[uuid])