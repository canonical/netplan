#!/usr/bin/python3
#
# Integration tests for complex networking scenarios
# (ie. mixes of various features, may test real live cases)
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018-2021 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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
import sys
import subprocess
import tempfile
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_mix_bridge_on_bond(self):
        self.setup_eth('ra-only')
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'bond0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
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
        self.generate_and_settle([self.dev_e_client, self.dev_e2_client, 'br0', 'bond0'])
        self.assert_iface_up(self.dev_e2_client, ['master bond0'], ['inet '])  # wokeignore:rule=master
        self.assert_iface_up('bond0', ['master br0'])  # wokeignore:rule=master
        self.assert_iface('br0', ['inet 192.168.0.2/24'])
        with open('/sys/class/net/bond0/bonding/slaves') as f:  # wokeignore:rule=slave
            result = f.read().strip()
            self.assertIn(self.dev_e2_client, result)

    def test_mix_vlan_on_bridge_on_bond(self):
        self.setup_eth('ra-only')
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
        self.generate_and_settle([self.dev_e_client, self.dev_e2_client, 'br0', 'br1', 'bond0', 'vlan1', 'vlan2'])
        self.assert_iface_up('vlan1', ['vlan1@br0'])
        self.assert_iface_up('vlan2', ['vlan2@' + self.dev_e_client, 'master br0'])  # wokeignore:rule=master
        self.assert_iface_up(self.dev_e2_client, ['master br1'], ['inet '])  # wokeignore:rule=master
        self.assert_iface_up('bond0', ['master br0'])  # wokeignore:rule=master

    # https://bugs.launchpad.net/netplan/+bug/1943120
    def test_remove_virtual_interfaces(self):
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br54'], stderr=subprocess.DEVNULL)
        confdir = os.path.join(tempdir, 'etc', 'netplan')
        os.makedirs(confdir)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  bridges:
    br54:
      addresses: [1.2.3.4/24]''' % {'r': self.backend})
        self.generate_and_settle(['br54'])
        self.assert_iface('br54', ['inet 1.2.3.4/24'])
        # backup the current YAML state (incl. br54)
        shutil.copytree('/etc/netplan', confdir, dirs_exist_ok=True)
        # drop br54 interface
        subprocess.check_call(['netplan', 'set', 'network.bridges.br54.addresses=null'])
        self.generate_and_settle([], state_dir=tempdir)
        res = subprocess.run(['ip', 'link', 'show', 'dev', 'br54'], capture_output=True, text=True)
        self.assertIn('not exist', res.stderr)


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
