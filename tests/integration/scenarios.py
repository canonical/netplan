#!/usr/bin/python3
#
# Integration tests for complex networking scenarios
# (ie. mixes of various features, may test real live cases)
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

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_mix_bridge_on_bond(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'bond0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  bridges:
    br0:
      interfaces: [bond0]
      addresses: ['192.168.0.2/24']
  bonds:
    bond0:
      interfaces: [ethb2]
      parameters:
        mode: balance-rr
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e2_client,
                             ['master bond0'],
                             ['inet '])
        self.assert_iface_up('bond0',
                             ['master br0'])
        ipaddr = subprocess.check_output(['ip', 'a', 'show', 'dev', 'br0'],
                                         universal_newlines=True)
        self.assertIn('inet 192.168', ipaddr)
        with open('/sys/class/net/bond0/bonding/slaves') as f:
            result = f.read().strip()
            self.assertIn(self.dev_e2_client, result)

    def test_mix_vlan_on_bridge_on_bond(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'bond0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  vlans:
    vlan1:
      link: 'br0'
      id: 1
      addresses: [ '10.10.10.1/24' ]
  bridges:
    br0:
      interfaces: ['bond0', 'vlan2']
      parameters:
        stp: false
        path-cost:
          bond0: 1000
          vlan2: 2000
  bonds:
    bond0:
      interfaces: ['br1']
      parameters:
        mode: balance-rr
  bridges:
    br1:
      interfaces: ['ethb2']
  vlans:
    vlan2:
      link: ethbn
      id: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up('vlan1', ['vlan1@br0'])
        self.assert_iface_up('vlan2',
                             ['vlan2@' + self.dev_e_client, 'master br0'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master br1'],
                             ['inet '])
        self.assert_iface_up('bond0',
                             ['master br0'])


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
