#!/usr/bin/python3
#
# Integration tests for VLAN virtual devices
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

    def test_vlan(self):
        # we create two VLANs on e2c, and run dnsmasq on ID 2002 to test DHCP via VLAN
        self.setup_eth(None, start_dnsmasq=False)
        self.start_dnsmasq(None, self.dev_e2_ap)
        subprocess.check_call(['ip', 'link', 'add', 'link', self.dev_e2_ap,
                               'name', 'nptestsrv', 'type', 'vlan', 'id', '2002'])
        subprocess.check_call(['ip', 'a', 'add', '192.168.5.1/24', 'dev', 'nptestsrv'])
        subprocess.check_call(['ip', 'link', 'set', 'nptestsrv', 'up'])
        self.start_dnsmasq(None, 'nptestsrv')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s: {}
    myether:
      match: {name: %(e2c)s}
      dhcp4: yes
  vlans:
    nptestone:
      id: 1001
      link: myether
      addresses: [10.9.8.7/24]
    nptesttwo:
      id: 2002
      link: myether
      dhcp4: true
      ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()

        self.assert_iface_up('nptestone', ['nptestone@' + self.dev_e2_client, 'inet 10.9.8.7/24'])
        self.assert_iface_up('nptesttwo', ['nptesttwo@' + self.dev_e2_client, 'inet 192.168.5'])
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', 'nptestone']))
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', 'nptesttwo']))

    def test_vlan_mac_address(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'myvlan'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  vlans:
    myvlan:
      id: 101
      link: ethbn
      macaddress: aa:bb:cc:dd:ee:22
        ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up('myvlan', ['myvlan@' + self.dev_e_client])
        with open('/sys/class/net/myvlan/address') as f:
            self.assertEqual(f.read().strip(), 'aa:bb:cc:dd:ee:22')


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
