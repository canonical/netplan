#!/usr/bin/python3
# Dummy devices integration tests.          wokeignore:rule=dummy
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2023 Canonical, Ltd.
# Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_create_single_interface(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dm0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:        # wokeignore:rule=dummy
    dm0: {}
''' % {'r': self.backend})
        self.generate_and_settle(['dm0'])
        self.assert_iface('dm0')

    def test_create_multiple_interfaces(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dm0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dm1'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dm2'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:        # wokeignore:rule=dummy
    dm0: {}
    dm1: {}
    dm2: {}
''' % {'r': self.backend})
        self.generate_and_settle(['dm0', 'dm1', 'dm2'])
        self.assert_iface('dm0')
        self.assert_iface('dm1')
        self.assert_iface('dm2')

    def test_interface_with_ip_addresses(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dm0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:            # wokeignore:rule=dummy
    dm0:
      addresses:
        - 192.168.123.123/24
        - 1234:FFFF::42/64
''' % {'r': self.backend})
        self.generate_and_settle(['dm0'])
        self.assert_iface('dm0', ['inet 192.168.123.123/24', 'inet6 1234:ffff::42/64'])


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
