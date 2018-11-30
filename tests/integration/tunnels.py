#!/usr/bin/python3
# Tunnel integration tests. NM and networkd are started on the generated
# configuration, using emulated ethernets (veth).
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

import sys
import subprocess
import unittest

from base import IntegrationTestsBase


class _CommonTests():

    def test_tunnel_ipip(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: ipip
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up('tun0', ['tun0@NONE'])


class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    @unittest.skip("Not implemented yet")
    def test_tunnel_(self):
        pass


class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'

    @unittest.skip("Not implemented yet")
    def test_tunnel_(self):
        pass


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
