#!/usr/bin/python3
# Veths integration tests.
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

    def test_create_veth_pair(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'veth0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  virtual-ethernets:
    veth0:
      dhcp4: false
      dhcp6: false
      peer: veth1
    veth1:
      dhcp4: false
      dhcp6: false
      peer: veth0''' % {'r': self.backend})
        # Workaround for NetworkManager on Ubuntu Jammy
        # NM will not change the link state to UP after creating the interfaces and
        # emit an error saying the second interface already exists. It looks like a bug in NM.
        # NM will change the link state to IP after trying to create them again.
        # Running netplan apply twice will workaround the issue.
        subprocess.call(['netplan', 'apply'], stderr=subprocess.DEVNULL)
        self.generate_and_settle(['veth0', 'veth1'])
        self.assert_iface_up('veth0')
        self.assert_iface_up('veth1')

    def test_create_veth_pair_with_ip_address(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'veth0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  virtual-ethernets:
    veth0:
      dhcp4: false
      dhcp6: false
      peer: veth1
      addresses:
        - 192.168.123.123/24
        - 1234:FFFF::42/64
    veth1:
      dhcp4: false
      dhcp6: false
      peer: veth0''' % {'r': self.backend})
        # Workaround for NetworkManager on Ubuntu Jammy
        # NM will not change the link state to UP after creating the interfaces and
        # emit an error saying the second interface already exists. It looks like a bug in NM.
        # NM will change the link state to IP after trying to create them again.
        # Running netplan apply twice will workaround the issue.
        subprocess.call(['netplan', 'apply'], stderr=subprocess.DEVNULL)
        self.generate_and_settle(['veth0', 'veth1'])
        self.assert_iface_up('veth0')
        self.assert_iface_up('veth1')

        expected_ips = {'192.168.123.123', '1234:ffff::42'}
        json = self.iface_json('veth0')
        data = json.get('addr_info', {})
        ips = {ip.get('local') for ip in data}
        self.assertTrue(expected_ips.issubset(ips))


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
