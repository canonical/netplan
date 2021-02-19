#!/usr/bin/python3
# Blackbox tests of the netplan YAML serializer. These are run during
# "make check" and don't touch the system configuration at all.
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
import ctypes
import ctypes.util

from generator.base import TestBase

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))


class TestNetplanSerialize(TestBase):
    '''Test netplan's YAML serializer'''

    def setUp(self):
        super().setUp()
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        super().tearDown()

    def _template_serialize_yaml(self, yaml_content, netdef_id='myid'):
        FILENAME = os.path.join(self.confdir, 'some-filename.yaml')
        NEWFILE = os.path.join(self.confdir, '10-netplan-{}.yaml'.format(netdef_id))
        with open(FILENAME, 'w') as f:
            f.write(yaml_content)
        # Parse YAML and and re-write the specified netdef ID into a new file
        lib._write_netplan_conf(netdef_id.encode(), FILENAME.encode(), self.workdir.name.encode())
        self.assertTrue(os.path.isfile(NEWFILE))
        with open(FILENAME, 'r') as f:
            with open(NEWFILE, 'r') as new:
                self.assertEquals(f.read(), new.read())

    def test_serialize_yaml_basic(self):
        self._template_serialize_yaml('''network:
  version: 2
  ethernets:
    some-netplan-id:
      renderer: networkd
      match:
        name: "eth42"
''', 'some-netplan-id')

    def test_serialize_yaml_wifi_ap(self):
        self._template_serialize_yaml('''network:
  version: 2
  wifis:
    myid:
      renderer: NetworkManager
      match:
        name: "eth42"
      access-points:
        "SOME-SSID":
          hidden: true
          mode: infrastructure
          networkmanager:
            uuid: some-uuid
            name: "Some NM name with spaces"
            passthrough:
              wifi.mode: "mesh"
''', 'myid')
